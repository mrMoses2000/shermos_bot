# WhatsApp Dual Bot — два номера, две очереди

**Контекст:** Shermos обслуживает два WhatsApp-номера через два независимых инстанса бриджа (`whatsapp-bridge`). Один номер позиционируется как «клиентский», второй — как «менеджерский». Этот документ описывает: какой бридж где, как сообщения маршрутизуются по очередям, что значит allowlist, и что система делает при каждом из 4 базовых сценариев.

## Поток сообщения

```
WhatsApp (Meta)
    │
    │ inbound
    ▼
┌─────────────────────────────┐      ┌──────────────────────────────┐
│  whatsapp-bridge (client)   │      │  whatsapp-bridge (manager)   │
│  systemd: shermos-wa-client │      │  systemd: shermos-wa-manager │
│  port: 3001                 │      │  port: 3002                  │
│  BRIDGE_ROLE=client         │      │  BRIDGE_ROLE=manager         │
│  Redis ns: wa:client:*      │      │  Redis ns: wa:manager:*      │
└──────────────┬──────────────┘      └──────────────┬───────────────┘
               │ POST                                 │ POST
               │ /internal/whatsapp/inbound           │ /internal/whatsapp/inbound
               │ X-Bridge-Secret: <shared>            │
               └──────────────┬───────────────────────┘
                              ▼
                  ┌──────────────────────────────┐
                  │  src/api/routes_whatsapp.py  │
                  │  is_bridge_secret_valid()    │
                  │  -> enqueue_whatsapp_inbound │
                  └──────────────┬───────────────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │  src/bot/whatsapp_ingress.py │
                  │                              │
                  │  bridge_role = payload.role  │
                  │      (manager | client)      │
                  │  sender_is_staff =           │
                  │      phone in MANAGER_       │
                  │      WHATSAPP_NUMBERS        │
                  │                              │
                  │  bot_type =                  │
                  │   "manager" if sender_is_    │
                  │     staff else "client"      │
                  │                              │
                  │  queue = bot_type            │
                  └──────────────┬───────────────┘
                                 ▼
              ┌──────────────────────┴───────────────────────┐
              ▼                                              ▼
   queue:incoming (Redis)                       queue:manager (Redis)
              │                                              │
              ▼                                              ▼
   process_client_job()                          process_manager_job()
              │                                              │
              ▼                                              ▼
   send_and_record() через                       send_and_record() через
   telegram_sender или                           manager_whatsapp_sender
   whatsapp_sender                               (port 3002, role=manager)
```

## Семантика allowlist

`MANAGER_WHATSAPP_NUMBERS` (env, comma-separated, e164 без `+`) — это **список телефонов сотрудников**, не «список разрешённых отправителей».

Ключевая инверсия по сравнению с обычной allowlist-логикой: обычно «не в allowlist → отказ». Здесь **«не в allowlist → клиент, идёт в обычную очередь»**.

## Четыре сценария

| # | Отправитель | Получатель (через какой бридж) | bridge_role | sender_is_staff | bot_type | Очередь | Что происходит |
|---|---|---|---|---|---|---|---|
| 1 | Клиент (не в allowlist) | Клиентский номер | client | false | client | `queue:incoming` | LLM-движок отвечает, обычный клиентский флоу |
| 2 | Клиент (не в allowlist) | Менеджерский номер | manager | false | client | `queue:incoming` | Логируется `whatsapp_client_on_manager_number INFO` (это нормально, не warning), затем как (1) |
| 3 | Сотрудник (в allowlist) | Клиентский номер | client | true | manager | `queue:manager` | Менеджерские команды (`/orders`, `/measurements`, slot proposal, `/meas_confirm:N`) |
| 4 | Сотрудник (в allowlist) | Менеджерский номер | manager | true | manager | `queue:manager` | Как (3) |

### Что НЕ происходит (по дизайну)

- Сообщение никогда не отбрасывается «потому что не в allowlist» — раньше так было (см. лог-флуд `whatsapp_manager_not_allowlisted` до 2026-05-04). Это была семантическая ошибка, исправлена в коммите `83db7c9`.
- Сценарий «оба номера попали в spam Meta» — выходит за рамки allowlist, обрабатывается отдельным healthcheck'ом бриджей (см. `/healthz`).

## Где что в коде

| Файл | Что |
|---|---|
| `whatsapp-bridge/src/index.ts` | HTTP-точка бриджа, `/healthz`, `/send`, `/pair`, `/status` |
| `whatsapp-bridge/src/lib/baileys-client.ts` | Подключение к WhatsApp через Baileys, reconnect-логика |
| `whatsapp-bridge/src/lib/auth-state-redis.ts` | Хранение Baileys-сессии в Redis |
| `src/api/routes_whatsapp.py` | FastAPI endpoint `/internal/whatsapp/inbound`, проверка `X-Bridge-Secret` |
| `src/bot/whatsapp_ingress.py` | Бизнес-логика: bridge_role + sender_is_staff → bot_type + queue |
| `src/bot/whatsapp_sender.py` | Исходящие сообщения через `manager_whatsapp_sender` (port 3002) или `whatsapp_sender` (port 3001) |
| `src/queue/worker.py` | `process_client_job`, `process_manager_job` |

## Конфигурация (env)

См. [`docs/ENV_REFERENCE.md`](ENV_REFERENCE.md) для полного списка. Ключевые:

- `WHATSAPP_BRIDGE_URL` — URL клиентского бриджа (по умолчанию `http://localhost:3001`)
- `MANAGER_WHATSAPP_BRIDGE_URL` — URL менеджерского бриджа (по умолчанию `http://localhost:3002`)
- `BRIDGE_SHARED_SECRET` — общий секрет для аутентификации бридж↔API
- `MANAGER_WHATSAPP_NUMBERS` — список телефонов сотрудников, comma-separated, e164 без `+`
- `MANAGER_CHAT_IDS` — список Telegram chat_id'ов менеджеров (для дублирования уведомлений в Telegram)

## Healthcheck

```
$ curl http://localhost:3001/healthz
{"connected":true,"role":"client","last_message_at":"2026-05-04T17:56:29+0000","reconnect_attempts":0}

$ curl http://localhost:3002/healthz
{"connected":true,"role":"manager","last_message_at":null,"reconnect_attempts":0}
```

Поля:
- `connected` (bool) — открыт ли WebSocket к WhatsApp.
- `role` — какая роль настроена через `BRIDGE_ROLE`.
- `last_message_at` (iso8601 или null) — когда последнее сообщение обработано.
- `reconnect_attempts` (int) — сколько раз подряд бридж пытался переподключиться без успеха.

При интеграции в CMS Status page (см. план Phase 1.5.5) опрашивать оба эндпоинта, показывать оператору в табличном виде.

## Известные ограничения

- **Native WhatsApp buttons (interactive messages)** — бридж их умеет (`whatsapp-bridge/src/routes/send.ts` принимает поле `interactive`), но Python-сторона `_reply_markup_to_payload` пока конвертирует в текст «👉 Подтвердить: /meas_confirm:N». Менеджеру приходится отвечать командой текстом. Включение нативных кнопок — Phase 1.5.4.
- **Outbox для менеджерских уведомлений** — пока `actions_applier.py` отправляет уведомления о новом замере напрямую через `send_and_record`. Если бридж в дауне в момент создания замера — уведомление теряется (хотя ошибка логируется). Перевод на outbox — Phase 1.5.3.
- **Reconnect storm** — Baileys backoff капается на 30 сек без jitter. При длительном даунтайме WhatsApp бридж стучится каждые 30 сек, спамит логи. Тикет: TODO Phase 5+.

## История изменений

- 2026-05-04 — `83db7c9` — Phase 1.2 fix: bridge_role и sender_is_staff разведены. До этого `bot_type=manager` ставился для любого сообщения через менеджерский бридж, что блокировало клиентов.
