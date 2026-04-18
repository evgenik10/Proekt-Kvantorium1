import logging
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_STT_MODEL = os.getenv("GEMINI_STT_MODEL", "gemini-2.0-flash")
GEMINI_SUMMARY_MODEL = os.getenv("GEMINI_SUMMARY_MODEL", "gemini-2.0-flash")
SUMMARY_STYLE = os.getenv(
    "SUMMARY_STYLE",
    "Сделай конспект: главные тезисы, выводы и список задач.",
)

GEMINI_FILE_WAIT_TIMEOUT_SEC = int(os.getenv("GEMINI_FILE_WAIT_TIMEOUT_SEC", "60"))
GEMINI_FILE_POLL_INTERVAL_SEC = float(os.getenv("GEMINI_FILE_POLL_INTERVAL_SEC", "1.5"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в .env")
if not GEMINI_API_KEY:
    raise RuntimeError("Не задан GEMINI_API_KEY в .env")

client = genai.Client(api_key=GEMINI_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Привет! Отправь голосовое или аудио, и я пришлю расшифровку + конспект."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Поддерживаемые типы: voice, audio, document(audio). Просто отправь файл."
    )


def _extract_response_text(response) -> str:
    text = getattr(response, "text", None)
    if text:
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    parts: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)

    return "\n".join(parts).strip()


def _state_name(file_obj) -> str:
    state = getattr(file_obj, "state", None)
    if state is None:
        return "UNKNOWN"
    return getattr(state, "name", str(state))


def wait_until_file_ready(file_obj):
    deadline = time.time() + GEMINI_FILE_WAIT_TIMEOUT_SEC
    current = file_obj

    while time.time() < deadline:
        current = client.files.get(name=current.name)
        state = _state_name(current)

        if state == "ACTIVE":
            return current
        if state == "FAILED":
            raise RuntimeError("Gemini не смог обработать аудиофайл (state=FAILED)")

        time.sleep(GEMINI_FILE_POLL_INTERVAL_SEC)

    raise TimeoutError(
        f"Gemini слишком долго обрабатывает файл (>{GEMINI_FILE_WAIT_TIMEOUT_SEC}с)"
    )


def summarize_text(transcript: str) -> str:
    response = client.models.generate_content(
        model=GEMINI_SUMMARY_MODEL,
        contents=(
            "Ты помощник, делающий краткие и точные конспекты на русском языке.\n"
            f"Инструкция: {SUMMARY_STYLE}\n\n"
            f"Сделай конспект этого текста:\n{transcript}"
        ),
    )
    summary = _extract_response_text(response)
    if not summary:
        raise RuntimeError("Gemini не вернул текст конспекта")
    return summary


def transcribe_audio(file_path: Path) -> str:
    uploaded = client.files.upload(file=file_path)
    ready_file = wait_until_file_ready(uploaded)

    response = client.models.generate_content(
        model=GEMINI_STT_MODEL,
        contents=[
            "Сделай дословную расшифровку этого аудио на исходном языке."
            " Верни только текст без пояснений.",
            ready_file,
        ],
    )
    transcript = _extract_response_text(response)
    if not transcript:
        raise RuntimeError("Gemini не вернул текст расшифровки")
    return transcript


async def process_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        return

    tg_file = None
    suffix = ".ogg"

    if message.voice:
        tg_file = await message.voice.get_file()
        suffix = ".ogg"
    elif message.audio:
        tg_file = await message.audio.get_file()
        suffix = Path(message.audio.file_name or "audio.mp3").suffix or ".mp3"
    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("audio/")
    ):
        tg_file = await message.document.get_file()
        suffix = Path(message.document.file_name or "audio.bin").suffix or ".bin"

    if not tg_file:
        await message.reply_text("Не вижу аудио. Отправь voice/audio файл.")
        return

    await message.reply_text("⏳ Обрабатываю аудио, это может занять до минуты...")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = Path(tmp.name)

        await tg_file.download_to_drive(custom_path=str(temp_path))

        transcript = transcribe_audio(temp_path)
        summary = summarize_text(transcript)

        await message.reply_text(f"📝 Полный текст:\n\n{transcript}")
        await message.reply_text(f"📌 Конспект:\n\n{summary}")
    except Exception as exc:
        logger.exception("Ошибка при обработке аудио: %s", exc)
        await message.reply_text("Произошла ошибка при обработке. Попробуй еще раз.")
    finally:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(
            filters.VOICE
            | filters.AUDIO
            | (filters.Document.ALL & filters.Document.MimeType("audio/")),
            process_audio,
        )
    )

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
