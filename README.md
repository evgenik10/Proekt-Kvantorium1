# AI-диктофон → Telegram бот (NeuroAPI)

Бот принимает голосовые/аудио сообщения в Telegram,
делает:
1) полный текст (STT),
2) краткий конспект.

Сделано через OpenAI-совместимый endpoint NeuroAPI: `https://neuroapi.host/v1`.

## Что умеет
- Принимает `voice`, `audio` и `document` (аудио).
- Скачивает файл через Telegram API.
- Отправляет аудио в `audio/transcriptions` (модель из `NEUROAPI_STT_MODEL`).
- Делает конспект через `chat/completions` (модель из `NEUROAPI_SUMMARY_MODEL`).
- Возвращает пользователю `📝 Полный текст` и `📌 Конспект`.

## Быстрый запуск

1. Установи Python 3.10+
2. Установи зависимости:
   ```bash
   pip install -r requirements.txt
   ```
3. Создай `.env` на основе примера:
   - Linux/macOS/Git Bash:
     ```bash
     cp .env.example .env
     ```
   - Windows PowerShell:
     ```powershell
     Copy-Item .env.example .env
     ```
   - Windows CMD:
     ```cmd
     copy .env.example .env
     ```
4. Заполни `.env`:
   - `TELEGRAM_BOT_TOKEN` — токен от @BotFather
   - `NEUROAPI_API_KEY` — токен с https://neuroapi.host
5. Запусти:
   ```bash
   python bot.py
   ```

## Переменные окружения
- `NEUROAPI_BASE_URL` — по умолчанию `https://neuroapi.host/v1`
- `NEUROAPI_STT_MODEL` — модель для транскрипции (по умолчанию `whisper-1`)
- `NEUROAPI_SUMMARY_MODEL` — модель для конспекта (по умолчанию `gpt-3.5-turbo`)
- `NEUROAPI_SUMMARY_MODEL_FALLBACKS` — список резервных моделей через запятую (используются, если основная недоступна на тарифе)
- `NEUROAPI_MAX_RETRIES` / `NEUROAPI_RETRY_DELAY_SEC` — ретраи при rate limit.

## Важно
Если получаешь 429/rate limit, бот автоматически ретраит запросы. Если ошибка постоянная — проверь лимиты/доступность модели в NeuroAPI.

## Если ошибка `telegram.error.Conflict`
Это означает, что уже запущен второй экземпляр бота с тем же токеном (два процесса `python bot.py` или polling + webhook). Оставь только один процесс.

## Полезные ссылки NeuroAPI
- Getting started: https://neuroapi.host/docs/getting-started
- API endpoint: https://neuroapi.gitbook.io/en/fundamentals/api-endpoint
- Developer example (OpenAI-compatible): https://neuroapi.gitbook.io/en/use-cases/for-developers
