#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WA_DIR="$PROJECT_DIR/whatsapp-bridge"

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
step() { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }

env_val() {
    grep "^$1=" "$WA_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-
}

check_env() {
    if [ ! -f "$WA_DIR/.env" ]; then
        err "whatsapp-bridge/.env not found!"
        exit 1
    fi
}

cmd_wa_bridge_check() {
    step "WhatsApp Bridge Local Check"
    if [ ! -d "$WA_DIR" ]; then
        err "whatsapp-bridge directory not found!"
        exit 1
    fi
    log "whatsapp-bridge directory exists"

    if ! command -v node &>/dev/null; then
        err "node is not installed!"
        exit 1
    fi
    log "node is installed"

    if ! command -v pnpm &>/dev/null; then
        err "pnpm is not installed!"
        exit 1
    fi
    log "pnpm is installed"

    cd "$WA_DIR"
    if [ ! -d "node_modules" ]; then
        warn "node_modules missing, running pnpm install..."
        pnpm install --frozen-lockfile
    fi

    log "Running checks..."
    pnpm typecheck
    pnpm lint
    pnpm build
    pnpm test
    log "All checks passed!"
}

cmd_wa_bridge_dev() {
    step "WhatsApp Bridge Dev Run"
    check_env
    cd "$WA_DIR"
    pnpm dev
}

cmd_wa_bridge_status() {
    step "WhatsApp Bridge Status"
    if curl -s http://localhost:3001/status; then
        echo ""
        log "Bridge is reachable"
    else
        echo ""
        err "Bridge is not running or unreachable at http://localhost:3001/status"
        exit 1
    fi
}

cmd_wa_bridge_pair() {
    step "WhatsApp Bridge Pair Helper"
    if [ -z "${1:-}" ]; then
        err "Usage: ./run.sh wa-bridge-pair <phone_e164_without_plus>"
        exit 1
    fi
    check_env
    SECRET=$(env_val "BRIDGE_SHARED_SECRET")
    if [ -z "$SECRET" ]; then
        err "BRIDGE_SHARED_SECRET not found in .env"
        exit 1
    fi

    PHONE="$1"
    PAYLOAD=$(python3 - "$PHONE" <<'PY'
import json
import sys

print(json.dumps({"phone": sys.argv[1]}))
PY
)

    log "Requesting pairing code for $PHONE..."
    curl -s -X POST http://localhost:3001/pair \
        -H "X-Bridge-Secret: $SECRET" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD"
    echo ""
}

cmd_wa_bridge_send_test() {
    step "WhatsApp Bridge Send Test Helper"
    if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
        err "Usage: ./run.sh wa-bridge-send-test <phone_e164_without_plus> <text>"
        exit 1
    fi
    check_env
    SECRET=$(env_val "BRIDGE_SHARED_SECRET")
    if [ -z "$SECRET" ]; then
        err "BRIDGE_SHARED_SECRET not found in .env"
        exit 1
    fi

    PHONE="$1"
    TEXT="$2"
    UUID=$(python3 -c 'import uuid; print(uuid.uuid4())')
    PAYLOAD=$(python3 - "$PHONE" "$UUID" "$TEXT" <<'PY'
import json
import sys

print(json.dumps({"to": sys.argv[1], "idempotency_key": sys.argv[2], "text": sys.argv[3]}, ensure_ascii=False))
PY
)

    log "Sending test message to $PHONE..."
    curl -s -X POST http://localhost:3001/send \
        -H "X-Bridge-Secret: $SECRET" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD"
    echo ""
}

cmd_wa_bridge_server_preflight() {
    step "WhatsApp Bridge Server Preflight"

    log "OS Info:"
    cat /etc/os-release | grep -E '^(NAME|VERSION)=' || true

    log "Versions:"
    command -v node &>/dev/null && node --version || echo "node not found"
    command -v npm &>/dev/null && npm --version || echo "npm not found"
    command -v pnpm &>/dev/null && pnpm --version || echo "pnpm not found"
    command -v docker &>/dev/null && docker --version || echo "docker not found"
    command -v cloudflared &>/dev/null && cloudflared --version || echo "cloudflared not found"

    log "Port 3001 Check:"
    if command -v netstat &>/dev/null; then
        netstat -tuln | grep 3001 || echo "Port 3001 is free"
    else
        ss -tuln | grep 3001 || echo "Port 3001 is free"
    fi

    log "Shermos Services Status:"
    systemctl list-units 'shermos-*' || true

    log "Tunnel ExecStart:"
    cat /etc/systemd/system/shermos-tunnel.service 2>/dev/null | grep ExecStart || echo "Not found"

    log "Docker Containers (Redis/Postgres):"
    if command -v docker &>/dev/null; then
        docker ps | grep -E 'redis|postgres' || echo "No redis/postgres containers running"
    fi
}

cmd_wa_bridge_reset_auth() {
    step "WhatsApp Bridge Reset Auth"
    check_env
    PREFIX=$(env_val "BAILEYS_AUTH_PREFIX")
    if [ -z "$PREFIX" ]; then
        PREFIX="baileys:auth:"
    fi
    REDIS_URL=$(env_val "REDIS_URL")
    if [ -z "$REDIS_URL" ]; then
        REDIS_URL="redis://localhost:6379/0"
    fi

    log "Resetting auth keys in Redis with prefix: $PREFIX"
    cd "$WA_DIR"
    REDIS_URL="$REDIS_URL" BAILEYS_AUTH_PREFIX="$PREFIX" node <<'NODE'
const Redis = require('ioredis');
const redis = new Redis(process.env.REDIS_URL);
const prefix = process.env.BAILEYS_AUTH_PREFIX || 'baileys:auth:';
let deleted = 0;
const stream = redis.scanStream({ match: `${prefix}*`, count: 100 });

stream.on('data', async (keys) => {
  stream.pause();
  try {
    if (keys.length) {
      deleted += await redis.del(...keys);
    }
  } finally {
    stream.resume();
  }
});

stream.on('end', async () => {
  console.log(`Deleted ${deleted} keys`);
  await redis.quit();
});

stream.on('error', async (err) => {
  console.error(err);
  await redis.quit();
  process.exit(1);
});
NODE
    log "Auth state reset successfully."
}

cmd_wa_bridge_stop() {
    step "WhatsApp Bridge Stop"
    if pgrep -f "node dist/index.js|tsx.*/src/index.ts" >/dev/null; then
        pkill -f "node dist/index.js|tsx.*/src/index.ts" || true
        sleep 1
    fi
    if pgrep -f "node dist/index.js|tsx.*/src/index.ts" >/dev/null; then
        pkill -9 -f "node dist/index.js|tsx.*/src/index.ts" || true
    fi
    log "Bridge processes stopped if they were running."
}

cmd_wa_bridge_start() {
    step "WhatsApp Bridge Start (Production)"
    check_env
    cd "$WA_DIR"
    pnpm build
    log "Starting bridge..."
    NODE_ENV=production pnpm start
}

cmd_wa_bridge_start_qr() {
    step "WhatsApp Bridge Start With QR (Production)"
    check_env
    cd "$WA_DIR"
    pnpm build
    warn "Use this only for initial linking. Scan the QR from WhatsApp > Linked devices."
    WA_PRINT_QR=1 NODE_ENV=production pnpm start
}

cmd_wa_bridge_pair_smoke() {
    step "WhatsApp Bridge Pair Smoke Test"
    cd "$WA_DIR"
    PHONE=${1:-77064264520}
    log "Running pair smoke test for $PHONE..."
    pnpm exec tsx scripts/smoke-test.ts pair "$PHONE"
}

cmd_wa_bridge_qr_smoke() {
    step "WhatsApp Bridge QR Smoke Test"
    cd "$WA_DIR"
    log "Running QR smoke test..."
    pnpm exec tsx scripts/smoke-test.ts qr
}

cmd_wa_bridge_deploy() {
    step "WhatsApp Bridge Deploy Services"
    
    if [ ! -d "$PROJECT_DIR/scripts/systemd" ]; then
        err "systemd directory not found in scripts!"
        exit 1
    fi
    
    log "Copying systemd services..."
    sudo cp "$PROJECT_DIR/scripts/systemd/shermos-wa-client.service" /etc/systemd/system/
    sudo cp "$PROJECT_DIR/scripts/systemd/shermos-wa-manager.service" /etc/systemd/system/
    
    log "Reloading systemd daemon..."
    sudo systemctl daemon-reload
    
    log "Enabling and starting services..."
    sudo systemctl enable shermos-wa-client shermos-wa-manager
    sudo systemctl restart shermos-wa-client shermos-wa-manager
    
    sleep 2
    local has_error=0

    if sudo systemctl is-active --quiet shermos-wa-client; then
        log "shermos-wa-client is running"
    else
        err "shermos-wa-client failed to start! Recent logs:"
        sudo journalctl -u shermos-wa-client -n 50 --no-pager
        has_error=1
    fi

    if sudo systemctl is-active --quiet shermos-wa-manager; then
        log "shermos-wa-manager is running"
    else
        err "shermos-wa-manager failed to start! Recent logs:"
        sudo journalctl -u shermos-wa-manager -n 50 --no-pager
        has_error=1
    fi

    if [ "$has_error" -eq 1 ]; then
        err "Deployment failed because one or more services did not start."
        exit 1
    fi
}

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    wa-bridge-check)
        cmd_wa_bridge_check
        ;;
    wa-bridge-deploy)
        cmd_wa_bridge_deploy
        ;;
    wa-bridge-dev)
        cmd_wa_bridge_dev
        ;;
    wa-bridge-status)
        cmd_wa_bridge_status
        ;;
    wa-bridge-pair)
        cmd_wa_bridge_pair "$@"
        ;;
    wa-bridge-send-test)
        cmd_wa_bridge_send_test "$@"
        ;;
    wa-bridge-server-preflight)
        cmd_wa_bridge_server_preflight
        ;;
    wa-bridge-reset-auth)
        cmd_wa_bridge_reset_auth
        ;;
    wa-bridge-stop)
        cmd_wa_bridge_stop
        ;;
    wa-bridge-start)
        cmd_wa_bridge_start
        ;;
    wa-bridge-start-qr)
        cmd_wa_bridge_start_qr
        ;;
    wa-bridge-pair-smoke)
        cmd_wa_bridge_pair_smoke "$@"
        ;;
    wa-bridge-qr-smoke)
        cmd_wa_bridge_qr_smoke
        ;;
    *)
        err "Unknown command: $COMMAND"
        exit 1
        ;;
esac
