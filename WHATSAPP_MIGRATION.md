# Shermos WhatsApp Migration — Architect Handoff for Gemini CLI

> Audience: Gemini CLI in coding/agent mode.
> Reviewer: Codex acts as senior architect and reviews each phase before merge.
> Current date of this plan: 2026-04-20.
> Repository: `/Users/mosesvasilenko/shermos-bot`.

## 0. Current Git Reality

- `main` and `feat/whatsapp-migration` both point to commit `f337f5d` (`feat(mini-app): redesign with dark glass-morphism UI`).
- `feat/wa-phase-1-bridge` points to newer commit `467303b` (`feat(wa): Phase 1 - whatsapp-bridge Node.js service`).
- Therefore `feat/wa-phase-1-bridge` is the newest WhatsApp branch. `feat/whatsapp-migration` is currently only an integration branch placeholder and does not contain WhatsApp code.
- Phase 1 bridge was statically checked on 2026-04-20:
  - `cd whatsapp-bridge && pnpm typecheck && pnpm lint` passed.
  - `cd whatsapp-bridge && pnpm build` passed.
- Manual WhatsApp pairing, inbound message forwarding, media download, and outbound sends were not verified in this review.

## 0.1 Current AWS/Ubuntu Reality

Read-only SSH check on `aws-shermos1-frankfurt` on 2026-04-20:

- Host OS: Ubuntu 24.04.3 LTS.
- Running services:
  - `shermos-api.service`
  - `shermos-webhook.service`
  - `shermos-worker.service`
  - `shermos-tunnel.service`
  - Docker
- Installed:
  - Docker
  - Node.js
  - `cloudflared` 2026.3.0
- Not installed:
  - `pnpm`
  - Vercel CLI
- Current tunnel service:
  - `ExecStart=/usr/bin/cloudflared tunnel --url http://localhost:9443 --no-autoupdate`
  - This is a Cloudflare Quick Tunnel, not a named tunnel.
  - Example URL seen in logs: `https://carb-investigation-drive-equations.trycloudflare.com`

Production implication:

- Quick Tunnel gives HTTPS without buying a domain and without opening inbound ports.
- Quick Tunnel URL is not contractual infrastructure. Cloudflare logs explicitly say account-less tunnels have no uptime guarantee and recommend named tunnels for production.
- Because Shermos currently has no purchased HTTPS domain, the migration must support a no-domain path first, but must not hide the reliability tradeoff.

## 1. Non-Negotiable Rules for Gemini CLI

1. Work one phase at a time.
2. Open each phase as a PR into `feat/whatsapp-migration`; do not target `main` until the final migration PR.
3. Do not push to `main`.
4. Do not commit secrets, `.env`, Baileys auth state, Cloudflare credentials, Vercel tokens, or private keys.
5. Do not run production deploy commands without explicit human approval.
6. Preserve Telegram runtime until WhatsApp has passed production soft-launch for at least 3 days.
7. Keep the core business logic stable:
   - pricing
   - render requirements
   - render engine
   - FSM
   - prompt builder
   - action parser
8. If a requested change touches `src/llm/actions_applier.py`, keep it narrowly scoped to notification sender injection or extraction. Do not rewrite pricing/render/scheduling semantics.
9. After Python changes: run `.venv/bin/python -m pytest tests/ -x --tb=short`.
10. After `whatsapp-bridge` changes: run `pnpm typecheck && pnpm lint && pnpm build`.
11. After `mini-app` changes: run its existing typecheck/lint/build commands. If a script is missing, add or document the gap.

## 2. External Documentation Checked

Gemini CLI must re-check current docs before coding any SDK-dependent work.

- Baileys via Context7: `/whiskeysockets/baileys`, APIs checked for `makeWASocket`, `messages.upsert`, `downloadMediaMessage`, `requestPairingCode`, auth state, and reconnect handling.
- Baileys upstream README currently warns about `7.0.0` breaking changes. Keep `@whiskeysockets/baileys` pinned to the intended major version until the bridge is intentionally upgraded.
- FastAPI via Context7: `/fastapi/fastapi`, checked for `APIRouter` dependencies, `Header`, 401 errors, and CORS.
- Meta WhatsApp Cloud API docs indicate the official production integration is HTTPS Graph API + Webhooks with TLS, message templates, rate limits, and delivery-status webhooks.
- Meta/partner docs indicate 2026 rollout of business-scoped user IDs (BSUID). Do not design new storage that assumes a WhatsApp user is always represented only by a phone number.

## 3. Architecture Boundary

The migration boundary is the messaging channel and manager web access layer.

Keep unchanged:

- PostgreSQL-backed pricing catalog and materials.
- Redis queue reliability hardening.
- Worker concurrency and user locks.
- Gemini CLI execution and prompt-building semantics for customer dialog.
- Render, price calculation, measurements, order drafts, gallery, and analytics behavior.

Replace or generalize:

- Telegram webhook ingress.
- Telegram sender.
- Telegram inline keyboard payloads.
- Telegram Mini App initData authentication.
- Manager access path from Telegram Mini App to standalone web app.

## 4. Target Deployment Units

During migration:

- `api`: existing FastAPI CMS/API service on AWS.
- `webhook`: existing Telegram aiohttp webhook service, retained until cleanup.
- `worker`: existing Python worker, changed to channel-aware messaging.
- `postgres`: existing PostgreSQL.
- `redis`: existing Redis.
- `whatsapp-bridge`: Node.js Baileys service, tactical adapter for WhatsApp Web.
- `mini-app`: existing React/Vite admin UI, later converted to standalone Vercel app.
- `cloudflared`: tunnel from public HTTPS origin to AWS API.

Final production recommendation:

- The tactical Baileys bridge may be used for a fast pilot only.
- For long-lived customer production, prefer official WhatsApp Business Platform Cloud API or a BSP because Baileys is unofficial and has account/policy/runtime risk.
- Keep the Python side provider-neutral so Baileys can be replaced by official Cloud API without rewriting worker business logic.
- If no domain is purchased, use Cloudflare Quick Tunnel only as a pilot/preview transport.
- For reliable production with Vercel frontend, buy a cheap domain and create a named Cloudflare Tunnel, or move API hosting to a platform that provides a stable HTTPS domain.

## 5. Normalized Event Model

Do not let Telegram names leak into new WhatsApp code.

Use these concepts:

- `channel`: `"telegram"` or `"whatsapp"`.
- `external_message_id`: provider message id, text.
- `external_chat_id`: provider chat/user id, text. For Baileys this is the JID or phone-derived id; for Cloud API this may become BSUID.
- `phone_e164`: optional phone string without `+`.
- `legacy_chat_id`: current numeric `chat_id` used by existing Shermos tables.
- `msg_type`: `"text"`, `"voice"`, `"image"`, `"document"`, `"button_reply"`, `"list_reply"`, `"command"`, `"callback_query"`.
- `callback_data`: normalized command payload used by the worker.
- `media_path`: local downloaded media path when bridge has already stored media.
- `raw_update`: full provider payload for debugging.

Short-term compatibility rule:

- Existing tables are keyed by `chat_id BIGINT`.
- For Baileys, derive `legacy_chat_id` from phone digits in Python, not from a JSON number produced by Node.
- The bridge must send phone/JID as strings. Python may cast digit-only E.164 values to `int` for existing code.
- Store `external_chat_id` and `external_message_id` as text in new columns so a future BSUID transition does not require parsing phone numbers out of legacy ids.

## 6. Phase 1 Review: `feat/wa-phase-1-bridge`

Current Phase 1 implementation exists on branch `feat/wa-phase-1-bridge` and creates:

- `WHATSAPP_MIGRATION.md`
- `whatsapp-bridge/package.json`
- `whatsapp-bridge/pnpm-lock.yaml`
- `whatsapp-bridge/Dockerfile`
- `whatsapp-bridge/src/index.ts`
- `whatsapp-bridge/src/lib/auth-state-redis.ts`
- `whatsapp-bridge/src/lib/baileys-client.ts`
- `whatsapp-bridge/src/routes/send.ts`
- `whatsapp-bridge/src/routes/pair.ts`
- `whatsapp-bridge/src/routes/status.ts`

Before merging Phase 1, Gemini CLI must fix or explicitly justify:

1. Secret comparison must be constant-time.
   - Current route code uses direct string comparison.
   - Use `crypto.timingSafeEqual` with safe length handling.
2. `/send` and `/pair` must return `503` if Baileys socket is not initialized or not connected.
3. Bridge payload must not send phone/chat ids as JSON numbers.
   - Send `external_chat_id`, `jid`, and `phone_e164` as strings.
   - Keep `chat_id` only if Python requires a temporary legacy field, and prefer string form.
4. Inbound forward failure must not drop messages after 3 HTTP retries.
   - Add a Redis-backed local retry list or durable spool for bridge-to-Python ingress failures.
   - A Baileys in-process event is not equivalent to an official webhook retry contract.
5. `received_at` extraction must handle Baileys timestamp shapes robustly.
   - It may be number-like, string-like, or object-like depending on protobuf representation.
6. `/status` should avoid exposing full JID publicly unless deployment keeps the endpoint private.
7. Outbound media should verify file existence and restrict paths to allowed media/render directories.
8. Interactive messages must be verified against the pinned Baileys major version.
   - If buttons/lists are unstable, implement text fallback first.
9. Add bridge tests with mocked Baileys socket and mocked fetch/Redis.
10. Add an operator runbook for pairing, re-pairing, Redis auth backup, and account logout handling.

Phase 1 acceptance before PR approval:

- `pnpm typecheck && pnpm lint && pnpm build` pass.
- Pairing code can be generated on a test device.
- Text inbound reaches a dummy ingress.
- `/send` sends one text message to a test recipient.
- Same idempotency key does not send a duplicate.
- Restart does not require re-pairing when Redis auth state is present.

## 7. Phase 2: Provider-Neutral Python Ingress and Sender

Goal: receive normalized WhatsApp events and send replies through a channel-aware sender while Telegram remains live.

Create migration `019_external_messaging.sql`:

```sql
ALTER TABLE processed_updates ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE processed_updates ADD COLUMN IF NOT EXISTS external_update_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS processed_updates_channel_extid_uq
  ON processed_updates(channel, external_update_id)
  WHERE external_update_id IS NOT NULL;

ALTER TABLE inbound_events ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE inbound_events ADD COLUMN IF NOT EXISTS external_message_id TEXT;
ALTER TABLE inbound_events ADD COLUMN IF NOT EXISTS external_chat_id TEXT;
ALTER TABLE inbound_events ADD COLUMN IF NOT EXISTS media_path TEXT;
ALTER TABLE inbound_events ADD COLUMN IF NOT EXISTS media_mime TEXT;

ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS external_message_id TEXT;
ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS external_chat_id TEXT;
ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS outbound_events_idempotency_channel_uq
  ON outbound_events(channel, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

ALTER TABLE clients ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';
ALTER TABLE clients ADD COLUMN IF NOT EXISTS external_chat_id TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS phone_e164 TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS clients_channel_external_chat_uq
  ON clients(channel, external_chat_id)
  WHERE external_chat_id IS NOT NULL;
```

Add or update models:

- `Job.channel: Literal["telegram", "whatsapp"] = "telegram"`.
- `Job.external_message_id: str | None = None`.
- `Job.external_chat_id: str | None = None`.
- `Job.phone_e164: str | None = None`.
- `Job.media_path: str | None = None`.
- `Job.media_mime: str | None = None`.

Add `src/api/routes_internal.py`:

- `POST /internal/whatsapp/inbound`.
- Header `X-Bridge-Secret`, checked with `hmac.compare_digest`.
- Validate payload with Pydantic.
- Dedup by `(channel='whatsapp', external_update_id=payload.external_id)`.
- Insert `inbound_events`.
- Create `Job(channel='whatsapp', ...)`.
- Enqueue to `queue:incoming`.

Add `src/bot/messaging.py`:

- Define a channel-neutral sender protocol.
- Provide `TelegramMessageSender` adapter wrapping existing `TelegramSender`.
- Provide `WhatsAppSender` adapter posting to `whatsapp-bridge`.
- Worker should call a facade, not `TelegramSender` directly, for customer-facing sends.

Add `src/bot/whatsapp_sender.py`:

- Use `httpx.AsyncClient`.
- Header `X-Bridge-Secret`.
- Timeout 15s.
- Retry once on 5xx/network error.
- Return provider `message_id`.

Add `src/bot/wa_interactive.py`:

- Translate existing callback payloads to WhatsApp-compatible interactive payloads.
- For more than 3 options, use list or text fallback.

Critical refactor:

- `src/llm/actions_applier.py` currently sends manager notifications directly via `telegram_sender`.
- Do not leave this as Telegram-only.
- Best option: remove direct sends from `apply_actions`; return `manager_notifications` in `action_result`, and let worker send them through the channel-aware facade.
- Acceptable short-term option: inject a `message_sender` or `notify_managers` callback into `apply_actions` without changing render/pricing/scheduling semantics.

Tests:

- `tests/test_whatsapp_inbound.py`
- `tests/test_whatsapp_sender.py`
- `tests/test_wa_interactive.py`
- Worker tests proving WhatsApp jobs send through `WhatsAppSender`.
- Actions applier test proving manager notifications are not hardwired to Telegram after Phase 2.

Acceptance:

- Telegram path still passes existing tests.
- WhatsApp inbound event enqueues exactly once.
- Duplicate WhatsApp event is deduped.
- Worker replies through bridge with idempotency key.
- Voice message with `media_path` reaches existing transcription path.

## 8. Phase 3: Manager Auth With JWT and WhatsApp OTP

Goal: standalone manager web app auth, no Telegram initData requirement.

Add migration `020_master_auth.sql`:

```sql
CREATE TABLE IF NOT EXISTS managers (
  phone_e164 TEXT PRIMARY KEY,
  name TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_otps (
  phone_e164 TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL,
  attempts INT NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_otp_rate_limit (
  phone_e164 TEXT PRIMARY KEY,
  last_sent_at TIMESTAMPTZ NOT NULL,
  send_count_1h INT NOT NULL DEFAULT 0
);
```

Backend:

- Add JWT issue/verify helpers.
- Add OTP request/verify/refresh/logout routes.
- Send OTP through the channel-aware sender.
- Return generic response from request-OTP so unknown manager phones are not disclosed.
- Use httpOnly refresh cookie with `Secure` and `SameSite=None` for Vercel-to-API cross-site usage.
- Change protected API routes from `require_telegram_auth` to `require_jwt_auth`.
- Keep `require_telegram_auth` until final cleanup.

Config:

- `jwt_secret`
- `jwt_issuer`
- `jwt_ttl_days`
- `master_frontend_origin`
- `wa_bridge_url`
- `wa_bridge_shared_secret`
- `manager_phones`

Tests:

- JWT valid/expired/tampered.
- OTP request/verify/rate limit/brute-force lockout.
- Existing API route auth tests updated to JWT.

## 9. Phase 4: Standalone Manager Frontend

Goal: convert `mini-app` from Telegram Mini App to a normal authenticated web app.

Frontend changes:

- Add login page: phone -> OTP.
- Add auth API client.
- Add `useAuth`.
- Store access token in memory or localStorage; use refresh cookie for session recovery.
- Replace `X-Telegram-Init-Data` with `Authorization: Bearer <token>`.
- Remove Telegram WebApp hard dependency.
- Keep current CMS UI and pages intact.

Vercel:

- `mini-app/vercel.json` with SPA fallback.
- `VITE_API_BASE_URL` must point to the current HTTPS API origin.
- With no purchased domain, use the current Quick Tunnel URL from `journalctl -u shermos-tunnel.service`.
- Do not hardcode `api-shermos.cfargotunnel.com` unless a stable named tunnel/domain has actually been created.
- Preview deploy first.
- Production deploy only after human approval.

Acceptance:

- `/login` works on preview URL.
- OTP arrives in WhatsApp.
- Dashboard, orders, clients, measurements, pricing, gallery, and settings load with JWT.
- Logout clears session.

## 10. Phase 5: HTTPS API Origin Without a Purchased Domain

Goal: public HTTPS API origin for Vercel frontend without exposing raw AWS API port.

There are two supported modes.

Mode A - no purchased domain, fastest pilot:

- Keep `shermos-tunnel.service` as Cloudflare Quick Tunnel.
- Extract the generated URL from `journalctl -u shermos-tunnel.service`.
- Set Vercel `VITE_API_BASE_URL` to that URL.
- Document that the URL may change after service recreation and has no uptime guarantee.
- Add a health check automation that alerts if the Quick Tunnel URL stops serving `/health`.

Mode B - recommended production:

- Buy a cheap domain and put it on Cloudflare DNS.
- Create a named Cloudflare Tunnel.
- Route a stable hostname, for example `api.<domain>`, to `http://localhost:9443`.
- Use that stable hostname in Vercel.
- Keep bridge control endpoints internal; expose only the FastAPI API needed by the frontend.

Tasks:

- Configure `cloudflared` tunnel to FastAPI port using either Mode A or Mode B.
- Restrict API CORS to `settings.master_frontend_origin`.
- Keep bridge internal; do not expose bridge control endpoints publicly.
- Update Vercel env.
- Verify `/health`, auth flow, and CMS routes through tunnel.

Acceptance:

- Vercel app talks only to the selected HTTPS API origin.
- Browser CORS succeeds.
- Direct unwanted public access to raw API port is closed or documented as still open with reason.

## 11. Phase 6: Cleanup Telegram

Execute only after WhatsApp has been running in production for at least 3 days with zero incidents.

Remove or retire:

- Telegram webhook service.
- Telegram sender direct dependencies.
- Telegram auth dependency.
- Telegram Mini App wording in frontend and docs.
- Self-signed webhook certificate deployment.

Keep historical migrations. Never rewrite migrations `001` through current.

Acceptance:

- Full tests pass.
- WhatsApp end-to-end smoke passes.
- Rollback tag exists before deletion commit.

## 12. Failure Modes Gemini Must Handle

- Bridge disconnected: `/send` returns 503; worker/outbox retries.
- Python ingress down: bridge stores inbound event for retry, not only logs and drops.
- Duplicate inbound event: database dedup prevents duplicate worker job.
- Worker crash: existing Redis processing-list recovery still works.
- Send succeeds but DB write fails: outbound idempotency key prevents duplicate send.
- User lock expires during long render: existing render timeout remains required.
- Baileys session invalid: bridge exits non-zero or reports unhealthy; operator re-pairs.
- JWT secret rotation: invalidate old tokens deliberately; document operator steps.
- OTP abuse: enforce per-phone rate limits and attempt caps.
- BSUID rollout: external identifiers stay text; phone is optional metadata, not primary identity.

## 13. PR Template for Gemini CLI

Each PR body must include:

- Phase number and goal.
- Files changed with one-line purpose.
- External docs checked and any API deviations.
- Tests run, exact commands, and results.
- Manual acceptance evidence or explicit reason it could not be run.
- Known limitations.
- Rollback notes.

Do not mark a phase complete without passing tests or stating the exact blocking gap.
