import logging
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError, RateLimitError
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NEUROAPI_API_KEY = os.getenv("NEUROAPI_API_KEY")
NEUROAPI_BASE_URL = os.getenv("NEUROAPI_BASE_URL", "https://neuroapi.host/v1")
NEUROAPI_STT_MODEL = os.getenv("NEUROAPI_STT_MODEL", "whisper-1")
NEUROAPI_SUMMARY_MODEL = os.getenv("NEUROAPI_SUMMARY_MODEL", "gpt-3.5-turbo")
SUMMARY_STYLE = os.getenv(
    "SUMMARY_STYLE",
    "Сделай конспект: главные тезисы, выводы и список задач.",
)
NEUROAPI_MAX_RETRIES = int(os.getenv("NEUROAPI_MAX_RETRIES", "3"))
NEUROAPI_RETRY_DELAY_SEC = float(os.getenv("NEUROAPI_RETRY_DELAY_SEC", "10"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в .env")
if not NEUROAPI_API_KEY:
    raise RuntimeError("Не задан NEUROAPI_API_KEY в .env")

client = OpenAI(api_key=NEUROAPI_API_KEY, base_url=NEUROAPI_BASE_URL)


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


def with_retry(callable_fn, operation_name: str):
    for attempt in range(1, NEUROAPI_MAX_RETRIES + 1):
        try:
            return callable_fn()
        except RateLimitError as exc:
            if attempt == NEUROAPI_MAX_RETRIES:
                raise
            delay = NEUROAPI_RETRY_DELAY_SEC * attempt
            logger.warning(
                "%s: rate-limit, retry %s/%s через %.1f сек. Ошибка: %s",
                operation_name,
                attempt,
                NEUROAPI_MAX_RETRIES,
                delay,
                exc,
            )
            time.sleep(delay)


def summarize_text(transcript: str) -> str:
    response = with_retry(
        lambda: client.chat.completions.create(
            model=NEUROAPI_SUMMARY_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Ты помощник, делающий краткие и точные конспекты на русском языке.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Инструкция: {SUMMARY_STYLE}\n\n"
                        f"Сделай конспект этого текста:\n{transcript}"
                    ),
                },
            ],
            temperature=0.2,
        ),
        "summary",
    )

    result = (response.choices[0].message.content or "").strip()
    if not result:
        raise RuntimeError("NeuroAPI не вернул текст конспекта")
    return result


def transcribe_audio(file_path: Path) -> str:
    def _call():
        with file_path.open("rb") as audio_file:
            return client.audio.transcriptions.create(
                model=NEUROAPI_STT_MODEL,
                file=audio_file,
            )

    transcript = with_retry(_call, "transcription")

    text = getattr(transcript, "text", "")
    if not text:
        raise RuntimeError("NeuroAPI не вернул текст расшифровки")
    return text.strip()


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
    except RateLimitError:
        await message.reply_text(
            "Лимит запросов исчерпан. Подожди немного и попробуй снова."
        )
    except OpenAIError as exc:
        logger.exception("Ошибка NeuroAPI/OpenAI-совместимого запроса: %s", exc)
        await message.reply_text("Ошибка запроса к NeuroAPI. Проверь модель/ключ и попробуй еще раз.")
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
