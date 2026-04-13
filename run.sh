#!/usr/bin/env bash
# ============================================================
# Shermos Bot — Server Deployment Script
# ============================================================
# Usage:
#   1. Clone repo:  git clone git@github.com:mrMoses2000/shermos_bot.git ~/shermos-bot
#   2. Copy .env:   scp from Mac (see below)
#   3. Run:         cd ~/shermos-bot && chmod +x run.sh && ./run.sh
#
# Copy .env from Mac:
#   scp /Users/mosesvasilenko/shermos-bot/.env ubuntu@3.79.24.73:~/shermos-bot/.env
#
# Re-running is safe (idempotent). Already-completed steps are skipped.
# ============================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
step() { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }

# ── Helper: read .env value ──────────────────────────────────
env_val() {
    grep "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-
}

# ============================================================
# STEP 0: Validate .env
# ============================================================
step "Step 0: Validating .env"

if [ ! -f .env ]; then
    err ".env not found!"
    echo ""
    echo "Copy it from your Mac:"
    echo "  scp /Users/mosesvasilenko/shermos-bot/.env ubuntu@3.79.24.73:$PROJECT_DIR/.env"
    echo ""
    echo "Or create from template:"
    echo "  cp .env.example .env && nano .env"
    exit 1
fi

# Check critical values aren't placeholders
CRITICAL_VARS=(TELEGRAM_BOT_TOKEN MANAGER_BOT_TOKEN)
for var in "${CRITICAL_VARS[@]}"; do
    val=$(env_val "$var")
    if [ -z "$val" ] || [ "$val" = "replace_me" ]; then
        err "$var is not set in .env (still 'replace_me' or empty)"
        echo "Edit .env: nano $PROJECT_DIR/.env"
        exit 1
    fi
done

POSTGRES_PASSWORD=$(env_val "POSTGRES_PASSWORD")
if [ -z "$POSTGRES_PASSWORD" ] || [ "$POSTGRES_PASSWORD" = "change_me" ]; then
    err "POSTGRES_PASSWORD is still 'change_me' — set a real password in .env"
    exit 1
fi

log ".env validated — tokens present, password set"

# ============================================================
# STEP 1: System dependencies
# ============================================================
step "Step 1: System dependencies"

# Docker
if command -v docker &>/dev/null; then
    log "Docker already installed: $(docker --version)"
else
    warn "Installing Docker..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker.io docker-compose-v2
    sudo usermod -aG docker "$USER"
    log "Docker installed. NOTE: You may need to re-login for group changes."
fi

# Python build deps + OpenGL (for pyrender headless)
PYTHON_DEPS="python3-venv python3-dev build-essential libegl1-mesa-dev libgles2-mesa-dev libgl1-mesa-dev libosmesa6-dev freeglut3-dev"
if dpkg -l python3-venv &>/dev/null 2>&1; then
    log "Python system deps already installed"
else
    warn "Installing Python system deps + OpenGL libs..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq $PYTHON_DEPS
    log "System deps installed"
fi

# Gemini CLI check (user must install + OAuth manually)
if command -v gemini &>/dev/null; then
    log "Gemini CLI found: $(which gemini)"
else
    warn "Gemini CLI not found!"
    echo "  Install it and run OAuth interactively:"
    echo "    npm install -g @anthropic-ai/gemini-cli@latest"
    echo "    gemini   # complete OAuth flow, then Ctrl+C"
    echo ""
    echo "  Script will continue, but the worker LLM calls will fail without it."
fi

# ============================================================
# STEP 2: SSL certificate
# ============================================================
step "Step 2: SSL certificate"

if [ -f certs/webhook.pem ] && [ -f certs/webhook.key ]; then
    log "SSL certificate already exists"
else
    mkdir -p certs
    openssl req -newkey rsa:2048 -sha256 -nodes \
        -keyout certs/webhook.key \
        -x509 -days 3650 \
        -out certs/webhook.pem \
        -subj "/CN=3.79.24.73" \
        2>/dev/null
    log "Self-signed SSL certificate generated (valid 10 years)"
fi

# ============================================================
# STEP 3: Docker Compose (PostgreSQL + Redis)
# ============================================================
step "Step 3: Docker Compose (PostgreSQL + Redis)"

# docker-compose.yml reads POSTGRES_* from .env automatically
if docker compose ps --format json 2>/dev/null | grep -q '"running"'; then
    log "Docker services already running"
else
    docker compose up -d
    log "Docker Compose started"
fi

# Wait for Postgres to be ready
echo -n "  Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U "$(env_val POSTGRES_USER)" -d "$(env_val POSTGRES_DB)" &>/dev/null; then
        echo ""
        log "PostgreSQL ready"
        break
    fi
    echo -n "."
    sleep 1
done

# Wait for Redis
echo -n "  Waiting for Redis..."
for i in $(seq 1 15); do
    if docker compose exec -T redis redis-cli ping &>/dev/null; then
        echo ""
        log "Redis ready"
        break
    fi
    echo -n "."
    sleep 1
done

# ============================================================
# STEP 4: Python virtual environment
# ============================================================
step "Step 4: Python virtual environment"

if [ -f .venv/bin/python ]; then
    log "Virtual environment already exists"
else
    python3 -m venv .venv
    log "Virtual environment created"
fi

source .venv/bin/activate
export PYOPENGL_PLATFORM=egl

pip install --upgrade pip -q
pip install -r requirements.txt -q
log "Python dependencies installed"

# ============================================================
# STEP 5: Database migrations
# ============================================================
step "Step 5: Database migrations"

PG_USER=$(env_val "POSTGRES_USER")
PG_DB=$(env_val "POSTGRES_DB")
PG_PASS=$(env_val "POSTGRES_PASSWORD")

# Create DB user if not exists (ignore error if already exists)
docker compose exec -T postgres psql -U postgres -c \
    "DO \$\$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${PG_USER}') THEN
            CREATE ROLE ${PG_USER} WITH LOGIN PASSWORD '${PG_PASS}';
        END IF;
    END \$\$;" 2>/dev/null || true

# Create database if not exists
docker compose exec -T postgres psql -U postgres -c \
    "SELECT 1 FROM pg_database WHERE datname = '${PG_DB}'" 2>/dev/null | grep -q 1 \
    || docker compose exec -T postgres psql -U postgres -c \
        "CREATE DATABASE ${PG_DB} OWNER ${PG_USER};" 2>/dev/null

# Grant privileges
docker compose exec -T postgres psql -U postgres -c \
    "GRANT ALL PRIVILEGES ON DATABASE ${PG_DB} TO ${PG_USER};" 2>/dev/null || true

# Run migrations (all are idempotent with IF NOT EXISTS)
for f in migrations/*.sql; do
    fname=$(basename "$f")
    docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" < "$f" >/dev/null 2>&1
    log "Migration: $fname"
done

# ============================================================
# STEP 6: Seed default data
# ============================================================
step "Step 6: Seed default data"

.venv/bin/python -c "
import asyncio
from src.config import settings
from src.db import postgres

async def seed():
    pool = await postgres.create_pool(settings)
    await postgres.seed_default_prices(pool)
    await postgres.seed_default_materials(pool)
    await postgres.close_pool(pool)
    print('Done')

asyncio.run(seed())
" 2>/dev/null && log "Default prices & materials seeded" || warn "Seeding skipped (may already exist)"

# ============================================================
# STEP 7: Register Telegram webhooks
# ============================================================
step "Step 7: Register Telegram webhooks"

CLIENT_TOKEN=$(env_val "TELEGRAM_BOT_TOKEN")
CLIENT_SECRET=$(env_val "TELEGRAM_WEBHOOK_SECRET")
MANAGER_TOKEN=$(env_val "MANAGER_BOT_TOKEN")
MANAGER_SECRET=$(env_val "MANAGER_WEBHOOK_SECRET")

# Client bot
echo -n "  Registering client bot webhook... "
RESULT=$(curl -s -F "url=https://3.79.24.73:88/webhook/client" \
     -F "certificate=@certs/webhook.pem" \
     -F "secret_token=$CLIENT_SECRET" \
     -F "allowed_updates=[\"message\",\"callback_query\",\"edited_message\"]" \
     "https://api.telegram.org/bot${CLIENT_TOKEN}/setWebhook")

if echo "$RESULT" | grep -q '"ok":true'; then
    log "Client bot webhook registered"
else
    err "Client webhook failed: $RESULT"
fi

# Manager bot
echo -n "  Registering manager bot webhook... "
RESULT=$(curl -s -F "url=https://3.79.24.73:88/webhook/manager" \
     -F "certificate=@certs/webhook.pem" \
     -F "secret_token=$MANAGER_SECRET" \
     -F "allowed_updates=[\"message\",\"callback_query\"]" \
     "https://api.telegram.org/bot${MANAGER_TOKEN}/setWebhook")

if echo "$RESULT" | grep -q '"ok":true'; then
    log "Manager bot webhook registered"
else
    err "Manager webhook failed: $RESULT"
fi

# ============================================================
# STEP 8: Create systemd services
# ============================================================
step "Step 8: Systemd services"

# Webhook service
sudo tee /etc/systemd/system/shermos-webhook.service >/dev/null << EOF
[Unit]
Description=Shermos Webhook Server
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=${PROJECT_DIR}
Environment=PYOPENGL_PLATFORM=egl
ExecStart=${PROJECT_DIR}/.venv/bin/python run_webhook.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
log "shermos-webhook.service created"

# Worker service
sudo tee /etc/systemd/system/shermos-worker.service >/dev/null << EOF
[Unit]
Description=Shermos Queue Worker
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=${PROJECT_DIR}
Environment=PYOPENGL_PLATFORM=egl
ExecStart=${PROJECT_DIR}/.venv/bin/python run_worker.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
log "shermos-worker.service created"

sudo systemctl daemon-reload
sudo systemctl enable shermos-webhook shermos-worker >/dev/null 2>&1

# ============================================================
# STEP 9: Start / restart services
# ============================================================
step "Step 9: Starting services"

sudo systemctl restart shermos-webhook
sudo systemctl restart shermos-worker
sleep 2

# Check they're running
if sudo systemctl is-active --quiet shermos-webhook; then
    log "shermos-webhook is running"
else
    err "shermos-webhook failed to start!"
    echo "  Check logs: sudo journalctl -u shermos-webhook -n 30"
fi

if sudo systemctl is-active --quiet shermos-worker; then
    log "shermos-worker is running"
else
    err "shermos-worker failed to start!"
    echo "  Check logs: sudo journalctl -u shermos-worker -n 30"
fi

# ============================================================
# STEP 10: Health check
# ============================================================
step "Step 10: Health check"

sleep 1
HEALTH=$(curl -sk https://localhost:88/health 2>/dev/null || echo "FAIL")
if echo "$HEALTH" | grep -q '"ok"'; then
    log "Webhook health check: OK"
else
    warn "Webhook health check failed (may need a few seconds to start)"
    echo "  Retry: curl -k https://localhost:88/health"
fi

# Verify webhook info from Telegram
echo ""
echo -n "  Telegram webhook status: "
INFO=$(curl -s "https://api.telegram.org/bot${CLIENT_TOKEN}/getWebhookInfo")
PENDING=$(echo "$INFO" | grep -o '"pending_update_count":[0-9]*' | cut -d: -f2)
HAS_ERROR=$(echo "$INFO" | grep -o '"last_error_message":"[^"]*"' | cut -d'"' -f4)

if [ -n "$HAS_ERROR" ] && [ "$HAS_ERROR" != "" ]; then
    warn "Telegram reports error: $HAS_ERROR"
else
    log "Telegram webhook OK (pending updates: ${PENDING:-0})"
fi

# ============================================================
# DONE
# ============================================================
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Shermos Bot deployed successfully!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo "  Send /start to your bot in Telegram to test."
echo ""
echo "  Useful commands:"
echo "    sudo journalctl -u shermos-webhook -f    # webhook logs"
echo "    sudo journalctl -u shermos-worker -f     # worker logs"
echo "    sudo systemctl restart shermos-webhook   # restart webhook"
echo "    sudo systemctl restart shermos-worker    # restart worker"
echo "    docker compose logs -f                   # DB logs"
echo ""
echo "  Update deployment:"
echo "    cd $PROJECT_DIR && git pull && ./run.sh"
echo ""
