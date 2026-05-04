# ENV_REFERENCE — Переменные окружения Shermos Bot

> Автоматически составлено из `src/config.py` + systemd-юнитов на 2026-05-04.
> **Значения секретов не указаны.** Смотри `/etc/shermos/` или EnvironmentFile каждого юнита.

## Какой сервис использует какие переменные

| Переменная | Telegram Worker | API | Webhook | WA Bridge (client) | WA Bridge (manager) |
|---|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✓ | | ✓ | | |
| `TELEGRAM_WEBHOOK_SECRET` | | | ✓ | | |
| `MANAGER_BOT_TOKEN` | ✓ | | ✓ | | |
| `MANAGER_WEBHOOK_SECRET` | | | ✓ | | |
| `MANAGER_CHAT_IDS` | ✓ | | | | |
| `POSTGRES_*` | ✓ | ✓ | ✓ | | |
| `REDIS_URL` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BRIDGE_SHARED_SECRET` | ✓ | ✓ | | ✓ | ✓ |
| `WHATSAPP_BRIDGE_URL` | ✓ | | | | |
| `MANAGER_WHATSAPP_BRIDGE_URL` | ✓ | ✓ | | | |
| `MANAGER_WHATSAPP_NUMBERS` | ✓ | | | | |
| `JWT_SECRET` | | ✓ | | | |
| `CMS_ADMIN_TOKEN` | | ✓ | | | |
| `ASSEMBLYAI_API_KEY` | ✓ | | | | |
| `BRIDGE_PORT` | | | | ✓ | ✓ |
| `BRIDGE_ROLE` | | | | ✓ (=client) | ✓ (=manager) |
| `BAILEYS_AUTH_PREFIX` | | | | ✓ | ✓ |
| `INGRESS_URL` | | | | ✓ | ✓ |

## Полный список переменных

### Telegram

| Имя | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **да** | — | Токен клиентского Telegram-бота |
| `TELEGRAM_WEBHOOK_SECRET` | **да** | — | X-Telegram-Bot-Api-Secret-Token для клиентского вебхука |
| `MANAGER_BOT_TOKEN` | **да** | — | Токен менеджерского Telegram-бота |
| `MANAGER_WEBHOOK_SECRET` | **да** | — | X-Telegram-Bot-Api-Secret-Token для менеджерского вебхука |
| `MANAGER_CHAT_IDS` | нет | `""` | Comma-separated Telegram chat_id менеджеров |
| `WEBHOOK_HOST` | нет | `0.0.0.0` | |
| `WEBHOOK_PORT` | нет | `88` | |
| `WEBHOOK_PUBLIC_URL` | нет | `https://3.79.24.73:88` | Публичный URL для регистрации вебхука |
| `WEBHOOK_PATH_CLIENT` | нет | `/webhook/client` | |
| `WEBHOOK_PATH_MANAGER` | нет | `/webhook/manager` | |
| `SSL_CERT_PATH` | нет | `certs/webhook.pem` | |
| `SSL_KEY_PATH` | нет | `certs/webhook.key` | |

### База данных

| Имя | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `POSTGRES_HOST` | нет | `localhost` | |
| `POSTGRES_PORT` | нет | `5432` | |
| `POSTGRES_DB` | нет | `shermos_bot` | |
| `POSTGRES_USER` | нет | `shermos` | |
| `POSTGRES_PASSWORD` | **да** | `change_me` | Сменить! |
| `REDIS_URL` | нет | `redis://localhost:6379/0` | |

### LLM / Gemini

| Имя | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `GEMINI_MODEL` | нет | `gemini-3-flash-preview` | Название модели |
| `LLM_CLI_COMMAND` | нет | `gemini` | Путь к CLI |
| `LLM_CLI_FLAGS` | нет | `-p` | Флаги CLI |
| `MAX_LLM_CONCURRENCY` | нет | `2` | Макс параллельных запросов к LLM |
| `LLM_TIMEOUT_SECONDS` | нет | `90` | |

### WhatsApp Bridge

| Имя | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `BRIDGE_SHARED_SECRET` | **да** | `""` | Общий секрет между Python и bridge (HMAC) |
| `WHATSAPP_BRIDGE_URL` | нет | `http://localhost:3001` | URL клиентского бриджа |
| `MANAGER_WHATSAPP_BRIDGE_URL` | нет | `""` | URL менеджерского бриджа |
| `MANAGER_WHATSAPP_NUMBERS` | нет | `""` | Comma-separated e164 номера сотрудников (без `+`) |
| `BRIDGE_PORT` | нет | `3001` | Порт самого bridge-процесса |
| `BRIDGE_HOST` | нет | `127.0.0.1` | |
| `BRIDGE_ROLE` | **да** | `client` | `client` или `manager` |
| `BAILEYS_AUTH_PREFIX` | нет | `baileys:auth:` | Redis-префикс для Baileys-сессий |
| `INGRESS_URL` | нет | `http://localhost:9443/internal/whatsapp/inbound` | |
| `BRIDGE_SPOOL_KEY` | нет | `bridge:spool:inbound` | Redis-ключ для спула |
| `MEDIA_DIR` | нет | `/data/incoming` | |

### API / CMS Auth

| Имя | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `JWT_SECRET` | **да** | `change_me_in_production` | Сменить! |
| `JWT_ISSUER` | нет | `shermos-api` | |
| `JWT_TTL_DAYS` | нет | `7` | |
| `JWT_REFRESH_TTL_DAYS` | нет | `30` | |
| `OTP_EXPIRY_MINUTES` | нет | `10` | |
| `OTP_MAX_ATTEMPTS` | нет | `5` | |
| `CMS_ADMIN_TOKEN` | нет | `""` | Статический токен для CMS-admin эндпоинтов |
| `MINI_APP_URL` | нет | `""` | URL Telegram Mini App |

### Остальное

| Имя | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `TIMEZONE` | нет | `Asia/Bishkek` | Временная зона для расписания замеров |
| `BOT_LANGUAGE` | нет | `ru` | |
| `ASSEMBLYAI_API_KEY` | нет | `""` | Если пусто — транскрипция голосовых отключена |
| `TRANSCRIPTION_LANGUAGE` | нет | `ru` | |
| `TRANSCRIPTION_TIMEOUT_SECONDS` | нет | `180` | |
| `LOG_LEVEL` | нет | `INFO` | |
| `LOG_FORMAT` | нет | `json` | |
| `RENDERS_DIR` | нет | `data/renders` | |
| `GALLERY_DIR` | нет | `data/gallery` | |
| `GALLERY_PHOTO_MAX_BYTES` | нет | `8388608` (8 MB) | |

## EnvironmentFile на сервере

| Юнит | EnvironmentFile |
|---|---|
| `shermos-worker` | нет (используется `.env` в CWD через `python-dotenv`) |
| `shermos-webhook` | нет |
| `shermos-api` | нет |
| `shermos-wa-client` | `~/shermos_bot/whatsapp-bridge/.env` |
| `shermos-wa-manager` | `~/shermos_bot/whatsapp-bridge/.env.manager` |

> Дополнительно: все Python-сервисы читают `shermos_bot/.env` через `pydantic-settings` при старте.
