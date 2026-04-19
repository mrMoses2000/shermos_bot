# WhatsApp Migration — Execution Spec for Gemini CLI

> **Audience:** Gemini CLI in agent/coding mode. You will read this spec and implement it.
> **DO NOT confuse with `GEMINI.md`** — that file is the runtime conversational prompt for the bot. Never modify it during this migration.
> **Working directory:** repository root (`/Users/mosesvasilenko/shermos-bot/.claude/worktrees/sleepy-brahmagupta-9b751b` locally; on AWS — wherever the repo is cloned).

---

## STEP 0 — MANDATORY FIRST ACTION: create the integration branch

**Before doing anything else** (before installing tools, before reading the rest of the spec in detail), execute these commands exactly:

```bash
# 1. Make sure your working tree is clean
git status
# If there are uncommitted changes — STOP and ask the human. Do not stash, do not discard.

# 2. Sync with remote main
git fetch origin
git checkout main
git pull --ff-only origin main

# 3. Create the long-lived integration branch for the whole WhatsApp migration
git checkout -b feat/whatsapp-migration
git push -u origin feat/whatsapp-migration
```

> ⚠️ All Phase branches in this spec (`feat/wa-phase-1-bridge`, `feat/wa-phase-2-ingress`, …) MUST branch off `feat/whatsapp-migration`, **not** off `main`.
> Each Phase PR targets `feat/whatsapp-migration` as its base branch (not `main`).
> Only after all 7 Phases are merged into `feat/whatsapp-migration` AND the Phase 7 soft-launch checklist passes, open the **final PR** `feat/whatsapp-migration → main`.

This isolates the whole multi-week migration from `main` so the existing Telegram bot keeps shipping fixes safely on `main` in parallel.

### Branch strategy summary

```
main
 └── feat/whatsapp-migration            ← integration branch (long-lived)
      ├── feat/wa-phase-1-bridge        → PR into feat/whatsapp-migration
      ├── feat/wa-phase-2-ingress       → PR into feat/whatsapp-migration
      ├── feat/wa-phase-3-jwt-auth      → PR into feat/whatsapp-migration
      ├── feat/wa-phase-4-frontend      → PR into feat/whatsapp-migration
      ├── feat/wa-phase-5-tunnel        → PR into feat/whatsapp-migration
      ├── chore/wa-phase-6-remove-tg    → PR into feat/whatsapp-migration
      └── docs/wa-phase-7-runbook       → PR into feat/whatsapp-migration
```

After STEP 0 is done, proceed to Section 0 (project context) and then Phase 1.

---

> **Per-phase branch protocol:** for each Phase, run:
> ```bash
> git checkout feat/whatsapp-migration
> git pull --ff-only origin feat/whatsapp-migration
> git checkout -b feat/wa-phase-N-<short-name>
> # ... do the work ...
> git push -u origin feat/wa-phase-N-<short-name>
> gh pr create --base feat/whatsapp-migration --title "..." --body "..."
> ```
> Open a PR after each Phase passes its acceptance test. Wait for human review before starting the next Phase.

---

## 0. Project context (read before writing any code)

**What exists today:**
- Python FastAPI backend ([src/api/](src/api/)) + aiohttp Telegram webhook ([src/bot/webhook.py](src/bot/webhook.py)) + async worker ([src/queue/worker.py](src/queue/worker.py)) + Gemini CLI subprocess for LLM ([src/llm/executor.py](src/llm/executor.py)) + Trimesh/Pyrender for 3D ([src/render/](src/render/)) + PostgreSQL (asyncpg, [src/db/postgres.py](src/db/postgres.py)) + Redis queue ([src/db/redis_client.py](src/db/redis_client.py)).
- React+Vite Mini App ([mini-app/](mini-app/)) auth via Telegram `initData` ([src/api/auth.py](src/api/auth.py)).
- 18 SQL migrations in [migrations/](migrations/).
- 97 tests, 91.74% coverage in [tests/](tests/).

**What we are building:**
- Replace Telegram client channel with **WhatsApp** via **Baileys** (unofficial WhatsApp Web Multi-Device library, Node.js).
- Replace Telegram-Mini-App auth with **standalone web app on Vercel** (`shermos-master.vercel.app`) using **JWT + WhatsApp OTP**.
- Backend stays on AWS, exposed via **Cloudflare Tunnel** (`api-shermos.cfargotunnel.com`) so Vercel frontend can reach it over HTTPS.
- Worker, FSM, LLM, render, pricing, measurement, gallery — **untouched**.

**Hard constraints — DO NOT violate:**
1. **Do not modify** [GEMINI.md](GEMINI.md), [src/llm/](src/llm/), [src/render/](src/render/), [src/engine/](src/engine/), [migrations/001-018_*.sql](migrations/) (only ADD new migrations 019+).
2. **Do not delete** existing Telegram code in Phases 1–4. Only delete in Phase 6 after end-to-end tests pass.
3. **Do not commit secrets**. Use `.env.example` for templates only.
4. **Do not run `vercel deploy --prod`** without explicit user approval.
5. **Do not run `git push --force`**, do not skip pre-commit hooks.
6. After every file change, run `pytest tests/ -x --tb=short` if Python files changed; run `npm run typecheck && npm run lint` in the changed Node project if TS files changed. Stop and report if anything fails.

---

## 1. Tools you must install before starting

Run these once on the AWS server and on local dev machine:

```bash
# Node.js 20 LTS (for whatsapp-bridge)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# pnpm (package manager for bridge)
npm install -g pnpm@9

# cloudflared (Cloudflare Tunnel daemon)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
sudo install -m 755 /tmp/cloudflared /usr/local/bin/cloudflared

# Vercel CLI (for frontend deploy) — version >= 51.7.0
npm install -g vercel@latest

# Python deps (already in requirements.txt; add the ones below in Phase 3)
pip install pyjwt[crypto]==2.10.1 bcrypt==4.2.1 httpx==0.27.2
```

Verify:
```bash
node --version       # v20.x
pnpm --version       # 9.x
cloudflared --version
vercel --version     # >= 51.7.0
```

If any check fails, stop and report which tool is missing.

---

## 2. Architecture target (the whole picture)

```
┌─────────┐  WhatsApp WS  ┌──────────────────┐  HTTP  ┌─────────────────────┐
│ CLIENT  │─────────────► │ whatsapp-bridge  │ ─────► │ FastAPI ingress     │
│ phone   │ ◄───────────  │ (Node, Baileys)  │ ◄───── │ src/bot/whatsapp_*  │
└─────────┘               └──────────────────┘  HTTP  └──────────┬──────────┘
                                  ▲                              │
                                  │ HTTP /send                   ▼
                          ┌───────┴──────────┐         ┌──────────────────┐
                          │ worker (Python,  │ ◄────── │ Redis queues     │
                          │ unchanged logic) │         └──────────────────┘
                          └───────┬──────────┘                  ▲
                                  │ asyncpg                     │
                                  ▼                             │
                          ┌──────────────────┐                  │
                          │ PostgreSQL       │                  │
                          └──────────────────┘                  │
                                                                │
┌─────────┐  HTTPS    ┌──────────────────────┐  HTTPS  ┌────────┴─────────┐
│ MASTER  │ ────────► │ shermos-master       │ ──────► │ Cloudflare Tunnel│
│ browser │           │ .vercel.app (React)  │ ◄────── │ → FastAPI :9443  │
└─────────┘ ◄──────── └──────────────────────┘         └──────────────────┘
                            JWT auth
```

---

## 3. Phase 1 — `whatsapp-bridge` Node.js service

**Goal:** A standalone TypeScript service that owns the Baileys WebSocket connection, forwards inbound WhatsApp messages to Python over HTTP, and exposes an HTTP API for outbound sends.

**Branch:** `feat/wa-phase-1-bridge`

### 3.1 Create directory structure

```bash
mkdir -p whatsapp-bridge/src/{routes,lib}
cd whatsapp-bridge
pnpm init
```

### 3.2 Install dependencies

```bash
cd whatsapp-bridge
pnpm add @whiskeysockets/baileys@^6.7.0 \
         express@^4.21.0 \
         ioredis@^5.4.1 \
         pino@^9.5.0 \
         pino-pretty@^11.3.0 \
         qrcode-terminal@^0.12.0 \
         dotenv@^16.4.5 \
         zod@^3.23.8
pnpm add -D typescript@^5.6.0 \
            @types/node@^22.7.0 \
            @types/express@^5.0.0 \
            tsx@^4.19.0 \
            eslint@^9.13.0 \
            @typescript-eslint/parser@^8.10.0 \
            @typescript-eslint/eslint-plugin@^8.10.0
```

> ⚠️ **Verify Baileys API version with Context7 MCP before writing code.** Run:
> ```
> resolve-library-id "Baileys"
> query-docs /whiskeysockets/baileys "useMultiFileAuthState, sock.sendMessage interactive list/buttons, downloadMediaMessage, requestPairingCode, messages.upsert handling, reconnect on DisconnectReason, save creds with custom auth state in Redis"
> ```
> If any function signature in this spec disagrees with current Baileys docs — **trust the docs, not this file**. Update accordingly and note the diff in the PR description.

### 3.3 Files to create

**`whatsapp-bridge/package.json`** — set `"type": "module"`, scripts:
```json
{
  "scripts": {
    "build": "tsc -p .",
    "start": "node dist/index.js",
    "dev": "tsx watch src/index.ts",
    "typecheck": "tsc --noEmit",
    "lint": "eslint src"
  }
}
```

**`whatsapp-bridge/tsconfig.json`**:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "bundler",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*"]
}
```

**`whatsapp-bridge/.env.example`**:
```env
BRIDGE_PORT=3001
BRIDGE_SHARED_SECRET=replace_with_openssl_rand_hex_32
INGRESS_URL=http://localhost:9443/internal/whatsapp/inbound
INGRESS_TIMEOUT_MS=10000
REDIS_URL=redis://localhost:6379/0
BAILEYS_AUTH_PREFIX=baileys:auth:
LOG_LEVEL=info
MEDIA_DIR=/data/incoming
```

**`whatsapp-bridge/src/lib/auth-state-redis.ts`** — implement Baileys `AuthenticationState` backed by Redis (so session survives container restarts):
- Export `useRedisAuthState(redis: Redis, prefix: string)` returning `{ state, saveCreds }`.
- Use `BufferJSON` reviver/replacer from `@whiskeysockets/baileys` for serialization.
- Keys: `${prefix}creds`, `${prefix}keys:${type}-${id}` for signal keys.
- Reference: see Context7 example "Connect WhatsApp via QR / pairing code, multi-device session persistence". Adapt the file-based `useMultiFileAuthState` pattern to Redis HSET/HGET.

**`whatsapp-bridge/src/lib/baileys-client.ts`** — exports `createBaileysClient(opts)`:
- Calls `makeWASocket({ auth: state, printQRInTerminal: false, logger, browser: ['Shermos','Chrome','1.0'] })`.
- Wires `connection.update`: on `close` with status !== `loggedOut`, reconnect with exponential backoff (1s, 2s, 4s, max 30s). On `loggedOut`, log fatal and exit(1) so systemd restarts and admin re-pairs.
- Wires `creds.update` → `saveCreds`.
- Wires `messages.upsert` → only forward when `type === 'notify'`, `!message.key.fromMe`, JID does **not** end with `@g.us` (no groups). Extract text from `message.conversation || message.extendedTextMessage.text || message.imageMessage.caption || message.audioMessage` (for audio set text=""). For media — call `downloadMediaMessage` and write to `${MEDIA_DIR}/<id>.<ext>`. POST to `INGRESS_URL` with header `X-Bridge-Secret: ${BRIDGE_SHARED_SECRET}`. Body shape:
  ```ts
  {
    external_id: string,        // message.key.id — dedup key
    chat_id: number,            // parseInt(jid.split('@')[0])
    user_id: number,            // same as chat_id for 1:1
    text: string,
    msg_type: 'text' | 'voice' | 'image' | 'button_reply' | 'list_reply' | 'document',
    callback_data: string | null,  // populated for button_reply / list_reply
    media_path: string | null,
    media_mime: string | null,
    raw: object,                // full baileys message JSON (for debugging)
    received_at: string         // ISO8601
  }
  ```
- Retry POST up to 3 times with backoff (200ms, 1s, 5s). If still failing — **log error and drop** (the message will be re-delivered by WhatsApp on next reconnect; dedup will handle it).

**`whatsapp-bridge/src/routes/send.ts`** — `POST /send`:
- Auth: header `X-Bridge-Secret` must equal `BRIDGE_SHARED_SECRET` (constant-time compare).
- Body (zod validate):
  ```ts
  {
    to: string,                 // E.164 without + (e.g. "996555111222")
    idempotency_key: string,    // UUID — required
    text?: string,
    interactive?: {
      type: 'buttons' | 'list',
      buttons?: Array<{ id: string, title: string }>,   // max 3, title ≤20 chars
      list?: {
        button_text: string,                            // ≤20 chars
        sections: Array<{ title: string, rows: Array<{ id: string, title: string, description?: string }> }>
      }
    },
    media?: { type: 'image'|'document', path: string, caption?: string }
  }
  ```
- Idempotency: check Redis key `bridge:idem:${idempotency_key}` (TTL 1h). If hit — return cached response.
- Map to Baileys `sock.sendMessage(jid, payload)`. JID: `${to}@s.whatsapp.net`.
- For interactive, use Baileys `buttonsMessage` / `listMessage` shapes — verify exact field names via Context7.
- Response: `{ message_id: string, status: 'sent' | 'queued' }`. Cache in Redis.
- On Baileys send error — return 502 with error detail.

**`whatsapp-bridge/src/routes/pair.ts`** — `POST /pair`:
- Auth: `X-Bridge-Secret` required.
- Body: `{ phone: string }` (E.164 without +).
- If `sock.authState.creds.registered` — return 409 "already paired".
- Else — `const code = await sock.requestPairingCode(phone)` → return `{ code }`.
- Operator enters this 8-character code in WhatsApp on their phone: Settings → Linked Devices → Link with phone number.

**`whatsapp-bridge/src/routes/status.ts`** — `GET /status` (no auth, for healthcheck):
- Returns `{ connection: 'open'|'connecting'|'close', registered: boolean, jid: string|null, last_event_at: string }`.

**`whatsapp-bridge/src/index.ts`** — entry point:
- Load `.env` via `dotenv`.
- Init pino logger (pretty in dev, json in prod via `LOG_LEVEL` and `NODE_ENV`).
- Init Redis client.
- Init Baileys client (start connection loop).
- Init Express, mount routes, listen on `BRIDGE_PORT`.
- Graceful shutdown on SIGTERM: stop accepting new HTTP, close Baileys socket, flush Redis, exit.

**`whatsapp-bridge/Dockerfile`**:
```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY tsconfig.json ./
COPY src ./src
RUN pnpm build

FROM node:20-alpine
WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
ENV NODE_ENV=production
EXPOSE 3001
CMD ["node", "dist/index.js"]
```

**`whatsapp-bridge/.gitignore`**:
```
node_modules/
dist/
.env
*.log
```

### 3.4 Acceptance test for Phase 1

Run on a dev machine with Redis on `localhost:6379`:

```bash
cd whatsapp-bridge
cp .env.example .env
# Set BRIDGE_SHARED_SECRET to a real random hex
# Start a dummy ingress:
python3 -c "
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length','0'))
        body = self.rfile.read(n)
        print('GOT:', body.decode())
        self.send_response(200); self.end_headers()
HTTPServer(('localhost', 9443), H).serve_forever()
" &

pnpm install
pnpm dev
# In another terminal:
curl -X POST http://localhost:3001/pair \
  -H "X-Bridge-Secret: <your_secret>" \
  -H "Content-Type: application/json" \
  -d '{"phone":"<your test number>"}'
# → returns 8-char code, enter in WhatsApp Linked Devices on the test phone
```

After pairing:
- Send a text message from another phone to the paired number → dummy ingress prints the JSON payload with `external_id`, `chat_id`, `text`.
- `curl http://localhost:3001/status` returns `{"connection":"open","registered":true,...}`.
- `curl -X POST http://localhost:3001/send -H "X-Bridge-Secret: ..." -H "Content-Type: application/json" -d '{"to":"<other phone>","idempotency_key":"test-1","text":"hello from bridge"}'` → message arrives in WhatsApp.
- Restart bridge (`Ctrl+C`, `pnpm dev` again) → no re-pairing required (Redis-backed auth state works).
- Send same `idempotency_key` twice → second call returns cached response, **no duplicate WhatsApp message**.

**Stop here. Open PR. Wait for review.**

---

## 4. Phase 2 — Python ingress + sender + worker rewire

**Goal:** FastAPI receives normalized payloads from bridge, enqueues to Redis, worker uses new sender to reply via bridge. Telegram code remains untouched (parallel paths).

**Branch:** `feat/wa-phase-2-ingress`

### 4.1 New migration

Create **`migrations/019_external_messaging.sql`**:
```sql
-- Add channel column to events tables (default 'whatsapp' for new rows)
ALTER TABLE inbound_events ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS outbound_events_idem_key_uq
  ON outbound_events (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Track external update IDs across channels.
-- For backward-compat: keep telegram_update_id; add external_update_id as text superset.
ALTER TABLE processed_updates ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE processed_updates ADD COLUMN IF NOT EXISTS external_update_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS processed_updates_channel_extid_uq
  ON processed_updates (channel, external_update_id) WHERE external_update_id IS NOT NULL;

-- Client channel + phone
ALTER TABLE clients ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS phone_e164 TEXT;
```

> Do **not** rename `telegram_update_id` — keep it for rollback safety. New WhatsApp rows use `external_update_id` + `channel='whatsapp'`.

### 4.2 New Python modules

**`src/bot/messaging.py`** — channel-agnostic facade:
```python
"""Unified messaging facade. Worker calls this; impl picks channel."""
from typing import Protocol
class MessageSender(Protocol):
    async def send_text(self, chat_id: int, text: str, *, idempotency_key: str) -> str: ...
    async def send_interactive(self, chat_id: int, payload: dict, *, idempotency_key: str) -> str: ...
    async def send_image(self, chat_id: int, image_path: str, caption: str, *, idempotency_key: str) -> str: ...
```
Plus a factory `get_sender(channel: str) -> MessageSender` that returns `WhatsAppSender` or the existing Telegram sender (kept as a fallback).

**`src/bot/whatsapp_sender.py`**:
- `class WhatsAppSender` implementing `MessageSender`.
- Uses `httpx.AsyncClient` (singleton) with `base_url=settings.wa_bridge_url`, default headers `{"X-Bridge-Secret": settings.wa_bridge_shared_secret}`, timeout 15s.
- `send_text`: POST `/send` with `{to, idempotency_key, text}`; on 4xx — log + raise `MessageSendError`; on 5xx — retry once after 1s.
- `send_interactive`: validates payload shape, POSTs.
- Returns `message_id` from bridge response.

**`src/bot/wa_interactive.py`** — translation layer Telegram-keyboard → WhatsApp interactive:
- `def to_wa_buttons(items: list[tuple[str,str]]) -> dict` — for ≤3 quick replies (raise if >3).
- `def to_wa_list(title: str, items: list[tuple[str,str]]) -> dict` — for >3 options.
- Used by callers that previously built `InlineKeyboardMarkup`. Look at [src/bot/keyboards.py](src/bot/keyboards.py) — provide a 1:1 translation for each builder there.

**`src/api/routes_internal.py`** — new FastAPI router mounted at `/internal`:
```python
@router.post("/whatsapp/inbound")
async def whatsapp_inbound(
    payload: WhatsAppInboundEvent,
    x_bridge_secret: str = Header(...),
):
    if not hmac.compare_digest(x_bridge_secret, settings.wa_bridge_shared_secret):
        raise HTTPException(401)
    # 1) dedup check via processed_updates(channel='whatsapp', external_update_id=payload.external_id)
    # 2) insert inbound_events(channel='whatsapp', ...)
    # 3) build Job (msg_type mapping), LPUSH redis queue:incoming
    # 4) return {"status":"queued"}
```
Pydantic model `WhatsAppInboundEvent` mirrors the bridge payload shape from §3.3.

Mount in [src/api/app.py](src/api/app.py) alongside existing routers.

### 4.3 Worker rewire

In [src/queue/worker.py](src/queue/worker.py):
- At the top, replace direct import of `telegram_sender` with `from src.bot.messaging import get_sender`.
- In the function that sends replies, look up channel from the `Job` (added field — see below) and call `sender = get_sender(job.channel)`.
- Generate `idempotency_key = f"{job.update_id}:{step_index}"` and pass to sender.

In `src/models.py`:
- Add `channel: Literal["telegram","whatsapp"] = "telegram"` to `Job`. Default keeps Telegram path safe.

In [src/db/postgres.py](src/db/postgres.py):
- Add `mark_external_update_received(pool, channel: str, external_id: str) -> bool` — returns `True` if newly inserted, `False` if duplicate. Use `INSERT … ON CONFLICT DO NOTHING RETURNING 1`.
- Update `insert_outbound_event` to accept optional `idempotency_key` and `channel`.

### 4.4 Voice handling

In the worker path that handles `msg_type='voice'`:
- Today: download via Telegram `getFile`. New: media is **already on disk** at `payload.media_path` — pass that path directly to AssemblyAI uploader (read bytes from local file).
- No change to AssemblyAI logic.

### 4.5 Config additions

In [src/config.py](src/config.py) (Pydantic Settings), add:
```python
wa_bridge_url: str = "http://localhost:3001"
wa_bridge_shared_secret: str = ""
wa_bot_phone: str = ""                # for logging
manager_phones: list[str] = []        # comma-sep in env, parsed
```
In [.env.example](.env.example), append:
```env
# --- WhatsApp Bridge (Phase 2) ---
WA_BRIDGE_URL=http://localhost:3001
WA_BRIDGE_SHARED_SECRET=replace_with_openssl_rand_hex_32
WA_BOT_PHONE=996555000000
MANAGER_PHONES=996555111222,996555333444
```

### 4.6 Tests to add

- `tests/test_whatsapp_inbound.py`: POST a sample bridge payload to `/internal/whatsapp/inbound` with valid + invalid secrets, assert dedup works on second identical post.
- `tests/test_whatsapp_sender.py`: mock bridge HTTP (use `respx`), assert correct payload shape and idempotency key passed through.
- `tests/test_wa_interactive.py`: assert error when >3 buttons; correct list message shape.

Run full suite: `pytest tests/ -x --tb=short` — must pass.

### 4.7 Acceptance test for Phase 2

Local manual:
1. Run bridge from Phase 1 pointed at this Python ingress.
2. Run Python: `python run_api.py` and `python run_worker.py`.
3. From a real phone, message the bot in WhatsApp: "Привет".
4. Observe logs:
   - bridge: incoming WS event, POST to ingress.
   - api: insert inbound_events, LPUSH queue:incoming.
   - worker: BRPOP, lock acquired, Gemini called, reply sent via WhatsAppSender, message arrives back in WhatsApp within ~8s.
5. Send the same WhatsApp message twice quickly (or simulate by replaying the bridge POST) → second is dropped at dedup, no duplicate reply.
6. Telegram bot still works (unchanged code path) — verify with the existing Telegram test bot.

**Stop. Open PR. Wait for review.**

---

## 5. Phase 3 — JWT auth + WhatsApp OTP for master site

**Goal:** Replace `require_telegram_auth` with `require_jwt_auth` everywhere. Add OTP-based login that delivers code over WhatsApp via the bridge.

**Branch:** `feat/wa-phase-3-jwt-auth`

### 5.1 New migration

**`migrations/020_master_auth.sql`**:
```sql
CREATE TABLE IF NOT EXISTS managers (
  phone_e164 TEXT PRIMARY KEY,
  name       TEXT,
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_otps (
  phone_e164 TEXT PRIMARY KEY,
  code_hash  TEXT NOT NULL,
  attempts   INT NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_otp_rate_limit (
  phone_e164    TEXT PRIMARY KEY,
  last_sent_at  TIMESTAMPTZ NOT NULL,
  send_count_1h INT NOT NULL DEFAULT 0
);
```

### 5.2 Code changes

**`src/api/auth.py`** — add (do not delete existing `require_telegram_auth` until Phase 6):
- `def issue_jwt(phone: str) -> str` — HS256, claims `{sub: phone, iat, exp, iss}`. TTL from settings.
- `def verify_jwt(token: str) -> dict` — raises `ValueError` on invalid/expired.
- `async def require_jwt_auth(authorization: str = Header(...)) -> dict` — parses `Bearer <token>`, verifies, returns claims. 401 on failure.
- Helper `def hash_otp(code: str) -> str` using bcrypt; `def verify_otp_hash(code, hash) -> bool`.

**`src/api/routes_auth.py`** — new router mounted at `/api/auth`:
- `POST /request-otp` body `{phone: str}`:
  - Validate phone is in `managers` table and `is_active`.
  - Rate-limit: max 1 send per 60s per phone, max 5 per hour. Use `auth_otp_rate_limit` table.
  - Generate 6-digit numeric code, bcrypt-hash, UPSERT `auth_otps` with `expires_at = now() + 5min`, `attempts=0`.
  - Send via `WhatsAppSender.send_text(phone, f"Shermos: код входа {code}. Действует 5 минут.")` with idempotency key `f"otp:{phone}:{int(now)}"`.
  - Response: `{status:"sent", expires_in_seconds:300}` (never reveal whether phone exists).
- `POST /verify-otp` body `{phone, code}`:
  - Load `auth_otps` row. If missing/expired → 401.
  - If `attempts >= 5` → 429.
  - Increment attempts. If hash mismatch → 401.
  - On success: delete OTP row, issue JWT, set refresh token cookie (httpOnly, Secure, SameSite=None for cross-site Vercel→tunnel).
  - Response: `{access_token: str, expires_at: ISO}`.
- `POST /refresh` — rotates JWT from refresh cookie.
- `POST /logout` — clears cookie.

**`src/api/app.py`** — register new router. Update CORS:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.master_frontend_origin],   # https://shermos-master.vercel.app
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Switch all existing protected routes** to use `require_jwt_auth`:
- [src/api/routes_orders.py](src/api/routes_orders.py)
- [src/api/routes_clients.py](src/api/routes_clients.py)
- [src/api/routes_measurements.py](src/api/routes_measurements.py)
- [src/api/routes_pricing.py](src/api/routes_pricing.py)
- [src/api/routes_gallery.py](src/api/routes_gallery.py)
- [src/api/routes_analytics.py](src/api/routes_analytics.py)
- [src/api/routes_settings.py](src/api/routes_settings.py)

In each: change `Depends(require_telegram_auth)` → `Depends(require_jwt_auth)`. Keep the parameter name `auth` so route bodies don't need rewrites.

### 5.3 Config additions

In [src/config.py](src/config.py):
```python
jwt_secret: str
jwt_issuer: str = "shermos-master"
jwt_ttl_days: int = 30
master_frontend_origin: str = "https://shermos-master.vercel.app"
```
In [.env.example](.env.example):
```env
# --- Master Auth (Phase 3) ---
JWT_SECRET=replace_with_openssl_rand_hex_64
JWT_ISSUER=shermos-master
JWT_TTL_DAYS=30
MASTER_FRONTEND_ORIGIN=https://shermos-master.vercel.app
```

### 5.4 Bootstrap

Add a one-time SQL helper in [run.sh](run.sh) (or a separate `scripts/seed_managers.py`) to insert manager phones from `MANAGER_PHONES` env into `managers` table.

### 5.5 Tests

- `tests/test_jwt_auth.py`: issue + verify + expired + tampered token.
- `tests/test_auth_routes.py`: full OTP flow with mocked WhatsApp sender, rate-limit enforcement, brute-force lockout.
- Update existing route tests to mint a JWT instead of building Telegram initData.

### 5.6 Acceptance test for Phase 3

```bash
# With bridge + ingress + worker running:
curl -X POST http://localhost:9443/api/auth/request-otp \
  -H "Content-Type: application/json" \
  -d '{"phone":"996555111222"}'
# → {"status":"sent","expires_in_seconds":300}
# WhatsApp message arrives on 996555111222 within ~5s
curl -X POST http://localhost:9443/api/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"phone":"996555111222","code":"123456"}'
# → {"access_token":"eyJ...","expires_at":"..."}
curl http://localhost:9443/api/orders -H "Authorization: Bearer eyJ..."
# → 200 with orders list
curl http://localhost:9443/api/orders     # no auth
# → 401
```

**Stop. Open PR.**

---

## 6. Phase 4 — Frontend on Vercel

**Goal:** Adapt [mini-app/](mini-app/) to standalone web app, deploy to Vercel.

**Branch:** `feat/wa-phase-4-frontend`

### 6.1 Restructure (in-place, no monorepo split)

In [mini-app/](mini-app/):
- Add a new page `src/pages/Login.tsx` with two steps: phone input → OTP input.
- Add `src/api/auth.ts` — wrapper for `/api/auth/request-otp`, `/api/auth/verify-otp`, `/api/auth/refresh`, `/api/auth/logout`. Stores `access_token` in `localStorage` under `shermos_jwt`.
- Add `src/hooks/useAuth.ts` returning `{ token, login(phone, code), logout(), isAuthenticated }`.
- Modify `src/api/client.ts` (the http wrapper) — replace `X-Telegram-Init-Data` header with `Authorization: Bearer ${token}`. On 401 → call `/refresh`; if that fails → redirect to `/login`.
- Modify `src/App.tsx` — wrap routes in `<RequireAuth>` that redirects to `/login` if no token.
- Remove `useTelegram` hook usage. Telegram WebApp SDK calls (`window.Telegram.WebApp.*`) → replace with stubs or remove.

### 6.2 Vite config

Set `VITE_API_BASE_URL` env. In [mini-app/vite.config.ts](mini-app/vite.config.ts) — no changes needed, it'll pick up `VITE_*` vars.

Add `mini-app/.env.example`:
```
VITE_API_BASE_URL=https://api-shermos.cfargotunnel.com
```

### 6.3 Vercel project config

Create `mini-app/vercel.json`:
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "rewrites": [
    { "source": "/(.*)", "destination": "/" }
  ]
}
```
> SPA fallback so deep links work.

### 6.4 Deploy

```bash
cd mini-app
vercel link                                     # interactive — pick scope, project name "shermos-master"
vercel env add VITE_API_BASE_URL production     # paste tunnel URL when prompted
vercel deploy                                   # preview
# After verifying preview:
vercel deploy --prod                            # PRODUCTION — only with explicit user approval
```

### 6.5 Acceptance test for Phase 4

Open the Vercel preview URL → `/login` page renders → enter master phone → OTP arrives in WhatsApp → enter code → dashboard loads with real orders/clients/gallery → all CRUD works → logout returns to login.

**Stop. Open PR.**

---

## 7. Phase 5 — Cloudflare Tunnel for backend API

**Goal:** Backend exposed at `https://api-shermos.cfargotunnel.com` so Vercel frontend can reach it.

**Branch:** `feat/wa-phase-5-tunnel`

### 7.1 Setup on AWS server

```bash
cloudflared tunnel login                                       # opens browser → Cloudflare account
cloudflared tunnel create shermos-api                          # outputs tunnel UUID + saves credentials JSON
cloudflared tunnel route dns shermos-api api-shermos           # if you have a CF zone; otherwise use the cfargotunnel.com URL
```

Create `/etc/cloudflared/config.yml`:
```yaml
tunnel: shermos-api
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json
ingress:
  - hostname: api-shermos.cfargotunnel.com
    service: http://localhost:9443
  - service: http_status:404
```

Install as systemd service:
```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

### 7.2 Verify

```bash
curl https://api-shermos.cfargotunnel.com/api/health
# → 200 OK
```

Update Vercel env `VITE_API_BASE_URL` to this URL if not already, redeploy frontend.

### 7.3 Lock down direct access

Edit AWS Security Group: remove inbound rule for port 9443 from public — only allow `127.0.0.1` (cloudflared connects locally). Keep port 22 (SSH) and remove 88 (old Telegram webhook) once Phase 6 is done.

### 7.4 Acceptance

End-to-end: open Vercel URL → login → all data flows. Browser network tab shows requests going to `api-shermos.cfargotunnel.com`, all returning 200.

**Stop. Open PR.**

---

## 8. Phase 6 — Cleanup of Telegram code

**Only execute after Phases 1–5 are merged AND running in production for ≥3 days with zero incidents.**

**Branch:** `chore/wa-phase-6-remove-telegram`

### 8.1 Delete

- `src/bot/webhook.py` (aiohttp Telegram webhook)
- `src/bot/telegram_sender.py`
- `src/bot/keyboards.py` (all callers should now use `wa_interactive.py`)
- `run_webhook.py`
- `certs/` directory (self-signed SSL no longer needed)
- `src/api/auth.py` → remove `require_telegram_auth` and `validate_init_data` functions; keep file for `require_jwt_auth`.

### 8.2 Update

- [.env.example](.env.example): remove `TELEGRAM_BOT_TOKEN`, `MANAGER_BOT_TOKEN`, `*_WEBHOOK_SECRET`, `WEBHOOK_*`, `SSL_*` entries.
- [src/config.py](src/config.py): remove corresponding fields.
- [docker-compose.prod.yml](docker-compose.prod.yml): remove `webhook` service, add `whatsapp-bridge` and `cloudflared` services.
- [run.sh](run.sh): remove Telegram webhook registration steps; add bridge pairing instruction.
- [DEPLOY.md](DEPLOY.md): rewrite for new flow.
- [AGENTS.md](AGENTS.md): append a "WhatsApp migration" section summarizing the new architecture; do **not** rewrite history — just append.

### 8.3 Tests

- Delete all `tests/test_telegram_*.py` and `tests/test_webhook_*.py` files.
- Run `pytest tests/ -x --tb=short` — must pass clean.
- Coverage target: maintain ≥85% (was 91.74%).

### 8.4 Acceptance

Full end-to-end smoke test. Tag release `v2.0.0-whatsapp`.

---

## 9. Phase 7 — Soft launch checklist

Before announcing to real customers:
- [ ] Bridge running under systemd with `Restart=always`, verified by killing process and watching it respawn.
- [ ] Cloudflare Tunnel running under systemd, restart verified.
- [ ] Vercel production deploy URL works, login works, all CRUD works.
- [ ] Send 10 manual WA messages from a test phone, verify replies in <10s p95.
- [ ] Send a voice message → transcription → reply with relevant content.
- [ ] Send an interactive list reply → callback handled correctly.
- [ ] Manager OTP login works on mobile and desktop browsers.
- [ ] Stress test: 20 concurrent WA conversations (use a script). No deadlocks, no >30s replies.
- [ ] Backup verified: dump `baileys:auth:*` keys from Redis → store off-site (loss = re-pair required).
- [ ] Monitoring: bridge `/status`, `/api/health`, Postgres `pg_isready`, Redis `PING` — wire to UptimeRobot or healthchecks.io.
- [ ] Document operator runbook in `docs/runbook.md`: how to re-pair, how to rotate JWT secret, how to add a manager phone.

---

## 10. Verification protocol after each Phase

After you finish writing code for a Phase, before you say "done":

1. **Static checks**:
   - Python: `ruff check src/ tests/` → 0 errors. `mypy src/` → 0 errors.
   - Node (bridge): `pnpm typecheck && pnpm lint` → 0 errors.
   - TS frontend: `npm run typecheck && npm run lint` → 0 errors.
2. **Tests**:
   - Python: `pytest tests/ -x --tb=short` → all pass.
3. **Manual acceptance**:
   - Run the Phase's acceptance section end-to-end.
   - Capture logs of the happy path; paste relevant excerpts in the PR description.
4. **PR**:
   - Title: `feat(wa): Phase N — <short description>`.
   - Body: bullet list of files changed with one-line purpose, paste acceptance log, list known limitations / TODOs for next Phase.
   - Self-review the diff: any `print(`, `console.log(`, `TODO`, `XXX`, hardcoded secret, hardcoded localhost URL? Fix or justify.

5. **DO NOT proceed to next Phase** until I (the human reviewer) approve the PR.

---

## 11. Failure & rollback

If a Phase blows up in production:

- **Phase 1–2 broken**: stop the `whatsapp-bridge` systemd unit. Telegram code is still present (until Phase 6) — re-enable Telegram webhook by starting `run_webhook.py`. No data loss; Postgres/Redis untouched.
- **Phase 3 broken**: revert to previous commit on `main`. The route auth dependency change is the only risky bit; reverting is safe because `require_telegram_auth` is still in code.
- **Phase 4 broken**: redeploy previous Vercel build (`vercel rollback`).
- **Phase 5 broken**: stop `cloudflared`, the API stays available on the AWS server's public IP if security group allows.
- **Phase 6 broken**: this is the irreversible one — that's why we wait 3 days. If something surfaces post-cleanup, restore from git tag `v1.x-telegram-final` and forward-port any new fixes.

---

## 12. What you (Gemini CLI) must NOT do

- ❌ Modify [GEMINI.md](GEMINI.md) (it's the bot's runtime prompt).
- ❌ Modify any file under [src/llm/](src/llm/), [src/render/](src/render/), [src/engine/](src/engine/) (only ADD if a new use-case requires it; ASK first).
- ❌ Modify migrations 001–018. Only ADD new migrations starting from 019.
- ❌ Push to `main`. Always work on a feature branch and open a PR.
- ❌ Run `vercel deploy --prod` without explicit human approval.
- ❌ Skip tests or hooks (`--no-verify`, `--no-edit`).
- ❌ Commit `.env`, Baileys auth state, Cloudflare credentials JSON, or any private key.
- ❌ Use Telegram-style markdown in code comments / docs (use plain text or HTML where appropriate).
- ❌ Combine multiple Phases in a single PR.

---

## 13. When in doubt

- For Baileys API questions → Context7 MCP `query-docs /whiskeysockets/baileys "<question>"`.
- For FastAPI / asyncpg / pytest patterns → look at existing code in [src/api/](src/api/) and [tests/](tests/) — match the prevailing style.
- For Vercel CLI questions → Vercel docs at https://vercel.com/docs/cli (and `vercel <cmd> --help`).
- For Cloudflare Tunnel questions → https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/.
- If a spec instruction in this file conflicts with current upstream library API → trust the library, document the deviation in your PR.
- If you're stuck for >30 minutes on a single problem → stop, write a `BLOCKER.md` describing what you tried, and request human input.

---

**End of spec. Begin with Phase 1. Work strictly sequentially. Open one PR per Phase.**
