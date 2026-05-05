# Shermos Bot — Deployment & Operations Guide

## Prerequisites

- Server: `ssh aws-shermos1-frankfurt` (Ubuntu 24.04, user `ubuntu`)
- Gemini CLI: authorized via OAuth (`gemini` → complete OAuth → Ctrl+C)
- GitHub SSH key configured on server

> **Telegram removed (2026-05-05):** No port 88 / self-signed cert / webhook registration needed.
> Both client and manager bots run via WhatsApp only. CMS is served by Netlify.

## Environment Variables Reference

Full reference for every env var (tokens, URLs, feature flags) is in:

```
docs/ENV_REFERENCE.md
```

The `.env` file is **gitignored** — copy it from your Mac to the server manually (see step 2 below).

---

## Deploy a New Version

### 1. Clone project on server (first time only)

```bash
ssh aws-shermos1-frankfurt
git clone git@github.com:mrMoses2000/shermos_bot.git ~/shermos-bot
```

### 2. Copy `.env` from Mac

`.env` contains real tokens and is gitignored — it won't appear after clone.
Run this **from your Mac**:

```bash
scp /Users/mosesvasilenko/shermos-bot/.env ubuntu@3.79.24.73:~/shermos-bot/.env
```

Any stale `TELEGRAM_*` / `MANAGER_BOT_TOKEN` / `MANAGER_CHAT_IDS` keys in `.env` are
silently ignored by pydantic-settings (`extra="ignore"`).

### 3. Pull latest and restart services

```bash
ssh aws-shermos1-frankfurt
cd ~/shermos-bot
git pull origin main
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m alembic upgrade head   # if migrations changed
sudo systemctl restart shermos-worker shermos-api
sudo systemctl is-active shermos-worker shermos-api
sudo journalctl -u shermos-worker --since "1 min ago" -p info
```

### 4. Restart sequence (after `git pull`)

Which services to restart depends on what changed:

| Changed files | Restart |
|---|---|
| `src/queue/worker.py`, `src/llm/*`, `src/engine/*` | `shermos-worker` |
| `src/api/*` | `shermos-api` |
| `src/bot/whatsapp_ingress.py` | `shermos-worker` + `shermos-api` |
| `whatsapp-bridge/**` | `shermos-wa-client` + `shermos-wa-manager` |
| `mini-app/**` | push to Netlify (auto-builds on merge to main) |

### 5. Run integration tests (on server)

```bash
cd ~/shermos-bot
TEST_ENV=integration .venv/bin/python -m pytest tests/ -q 2>&1 | tail -10
```

---

## Rollback

### Option A — Roll back to a previous git SHA

```bash
ssh aws-shermos1-frankfurt
cd ~/shermos-bot
git log --oneline -10                 # find the good SHA
git checkout <good-sha>               # detached HEAD — services still run old code
sudo systemctl restart shermos-worker shermos-api
```

### Option B — Roll back to the prod-snapshot tag

```bash
git checkout prod-snapshot-2026-05-04
sudo systemctl restart shermos-worker shermos-api
```

### Option C — Use git reflog (if you force-pushed or lost a commit)

```bash
git reflog | head -20                 # find the lost commit hash
git checkout <reflog-hash>
```

After rollback, verify:
```bash
sudo systemctl is-active shermos-worker shermos-api
curl http://localhost:9443/api/health/bridges
```

To return to a normal branch after detached-HEAD rollback:
```bash
git checkout main
git pull origin main
```

---

## Reading Logs & Metrics

```bash
# Errors only
journalctl -u shermos-worker -p err
journalctl -u shermos-api -p err

# Warning and above
journalctl -u shermos-worker -p warning -f

# All logs, follow
journalctl -u shermos-worker -f

# Prometheus metrics
curl http://localhost:9443/metrics | grep shermos_

# Bridge health
curl http://localhost:9443/api/health/bridges   # both WA bridges status
curl http://localhost:9443/health               # main API
```

---

## Incident Runbooks

### Runbook 1 — Gemini in Downtime

**Symptoms:**
- Worker logs show `TimeoutError: Gemini CLI timed out` or `Gemini CLI failed with code`
- `llm_call_duration_seconds{status="timeout"}` or `{status="error"}` rising in metrics
- Users receive "Запрос занял слишком много времени" replies repeatedly

**What to check:**
```bash
journalctl -u shermos-worker -p err -n 50
curl http://localhost:9443/metrics | grep llm_call_duration
# Check Gemini OAuth token expiry on server
gemini --version   # should succeed; if not, re-run OAuth
```

**What to do:**
1. Check Gemini API status at https://status.google.com (or Gemini dashboard).
2. If OAuth token expired: `gemini` → complete OAuth dance → Ctrl+C → `sudo systemctl restart shermos-worker`.
3. If Gemini CLI binary is missing: `npm install -g @google/gemini-cli`.
4. While Gemini is down, users get the timeout reply automatically — no further action needed for them.
5. Optionally raise `LLM_TIMEOUT_SECONDS` in `.env` if Gemini is just slow (then `sudo systemctl restart shermos-worker`).
6. Once Gemini recovers: monitor `llm_call_duration_seconds{status="success"}` rising again.

---

### Runbook 2 — Postgres in Downtime

**Symptoms:**
- Worker and API logs: `asyncpg.exceptions.ConnectionFailureError` or `connect call failed`
- All API endpoints return 500
- Outbox dispatcher stalls (no `outbox_send_*` log entries)

**What to check:**
```bash
docker compose ps                         # check postgres container status
docker compose logs postgres --tail 50
journalctl -u shermos-worker -p err -n 20
```

**What to do:**
1. Restart the container: `docker compose restart postgres`.
2. Wait ~10 s for Postgres to accept connections: `docker compose exec postgres pg_isready`.
3. Restart the Python services so they re-establish pools:
   ```bash
   sudo systemctl restart shermos-worker shermos-api
   ```
4. Data integrity check via outbox — any events that were `pending` during the outage will be retried automatically by `run_outbox_dispatcher` on the next tick (idempotent).
5. Verify: `curl http://localhost:9443/health` → `{"ok": true}`.
6. If Postgres volume is corrupted: restore from last snapshot / backup before restarting.

---

### Runbook 3 — Redis in Downtime

**Symptoms:**
- Worker logs: `redis.exceptions.ConnectionError` or `Connection refused`
- No jobs being dequeued (queues stall)
- `shermos_worker_jobs_in_flight` gauge stays at 0 despite incoming messages

**What to check:**
```bash
docker compose ps                          # check redis container status
docker compose logs redis --tail 30
journalctl -u shermos-worker -p err -n 20
```

**What to do:**
1. Restart the container: `docker compose restart redis`.
2. Wait ~5 s, then restart the worker (it reconnects on start):
   ```bash
   sudo systemctl restart shermos-worker
   ```
3. **Jobs lost?** — Redis is used only as a queue buffer; the authoritative state is in Postgres (`inbound_events` table with status `processing`). On worker startup, `recover_stuck_jobs()` automatically re-queues any jobs that were `processing` when Redis died.
4. In-flight protection: the worker uses a `processing` queue — jobs moved there are recovered on restart (see `RedisClient.recover_stuck_jobs`).
5. Delayed jobs (`queue:delayed:incoming`) are ephemeral. If Redis restarts, those jobs are lost — clients may need to resend their messages.
6. Verify recovery: `journalctl -u shermos-worker --since "1 min ago" | grep recovered_stuck_jobs`.

---

### Runbook 4 — WhatsApp Bridge in Downtime

**Symptoms:**
- `curl http://localhost:9443/api/health/bridges` returns `connected: false` for one or both bridges
- Worker logs: `"Connection Terminated"` or `"websocket closed"` entries
- `shermos_outbound_events_total{channel="whatsapp", status="failed"}` rising
- WhatsApp messages not being sent or received

**What to check:**
```bash
journalctl -u shermos-wa-client -p err -n 30
journalctl -u shermos-wa-manager -p err -n 30
curl http://localhost:9443/api/health/bridges
```

**What to do:**
1. Restart the disconnected bridge:
   ```bash
   sudo systemctl restart shermos-wa-client    # client bot bridge
   sudo systemctl restart shermos-wa-manager   # manager bot bridge
   ```
2. Wait ~15 s for reconnect. Check status:
   ```bash
   curl http://localhost:9443/api/health/bridges
   ```
3. **If QR re-scan is needed** (session expired or new device):
   - Watch bridge logs for QR code output:
     ```bash
     journalctl -u shermos-wa-client -f
     ```
   - Scan the QR code with the WhatsApp app on the linked phone.
   - Session is stored in `whatsapp-bridge/session/` — if lost, re-scan is mandatory.
4. **If bridge binary is missing or crashed hard:**
   ```bash
   cd ~/shermos-bot/whatsapp-bridge
   npm install
   npm run build
   sudo systemctl restart shermos-wa-client shermos-wa-manager
   ```
5. After recovery, pending outbound WhatsApp events will be retried automatically by the outbox dispatcher on the next 15-second tick.
6. Verify: `shermos_outbound_events_total{channel="whatsapp", status="sent"}` should start incrementing again.

---

## Useful Commands

```bash
# Logs
sudo journalctl -u shermos-worker -f
sudo journalctl -u shermos-api -f
docker compose logs -f

# Restart services
sudo systemctl restart shermos-worker shermos-api

# Status
sudo systemctl status shermos-worker shermos-api
curl http://localhost:9443/health
curl http://localhost:9443/metrics | grep shermos_
curl http://localhost:9443/api/health/bridges
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `.env not found` | `scp` from Mac (see step 2) |
| Gemini CLI not found | `npm install -g @google/gemini-cli` then `gemini` for OAuth |
| PostgreSQL connection refused | `docker compose ps` — check if postgres is running |
| Permission denied (Docker) | Re-login after `sudo usermod -aG docker ubuntu` |
| journalctl -p err returns nothing | Ensure `LOG_SYSLOG_PRIORITY=1` in `.env` (default: on) |
| /metrics returns 404 | Check `shermos-api` is running; route is at `GET /metrics` (no auth) |
| WA bridge not connecting | See Runbook 4 above |

---

## Phase 7 — Watchdog: Deploying systemd Unit Files

All five service unit files live under `scripts/systemd/`. The worker unit has
`Type=notify` / `WatchdogSec=60` so systemd restarts it if the Python process
stops sending heartbeats (sd_notify watchdog pings every 30 s). The API, tunnel,
and WA bridge units use `Type=simple` / `Restart=on-failure` only.

### Install / update unit files on the server

```bash
ssh aws-shermos1-frankfurt
cd ~/shermos_bot
git pull origin main
bash scripts/install_systemd.sh   # idempotent; reloads daemon; does NOT restart services
```

The script copies every `scripts/systemd/*.service` to `/etc/systemd/system/`
and runs `sudo systemctl daemon-reload`. It is safe to run repeatedly.

### Install systemd-python for watchdog heartbeats (worker only)

```bash
# On the server — one-time setup (requires libsystemd-dev):
sudo apt install -y libsystemd-dev
.venv/bin/pip install 'systemd-python>=235'
```

`src/utils/watchdog.py` gracefully no-ops if `systemd-python` is absent, so
the worker starts even without it — but the WatchdogSec kill won't fire.

### Roll services forward after unit file update

```bash
sudo systemctl restart shermos-worker shermos-api shermos-wa-client shermos-wa-manager
sudo systemctl status shermos-worker | head -20   # confirm Type=notify + WatchdogSec=60
```

### Verify watchdog is active (Step 7.4 — orchestrator checklist)

Run these on the server after install and restart:

```bash
# 1. Confirm sd_notify handshake succeeded (READY=1 appears within ~5 s of start):
journalctl -u shermos-worker -n 20 | grep -E "READY=1|WATCHDOG"

# 2. Confirm systemd sees WatchdogSec:
systemctl show shermos-worker | grep -E "WatchdogUSec|Type"

# 3. Smoke-test watchdog kill (DESTRUCTIVE — use in staging only):
#    Find the worker PID:
systemctl show -p MainPID shermos-worker
#    Pause the process so it stops sending heartbeats:
kill -STOP <MainPID>
#    Wait ~70 s (WatchdogSec=60 + grace), then confirm auto-restart:
sleep 70 && systemctl is-active shermos-worker   # should print "active"
journalctl -u shermos-worker -n 5               # should show a fresh start
```
