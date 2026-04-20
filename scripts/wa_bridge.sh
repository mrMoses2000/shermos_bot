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
    
    log "Requesting pairing code for $1..."
    curl -s -X POST http://localhost:3001/pair \
        -H "X-Bridge-Secret: $SECRET" \
        -H "Content-Type: application/json" \
        -d "{\"phone\":\"$1\"}"
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

    UUID=$(python3 -c 'import uuid; print(uuid.uuid4())')
    
    log "Sending test message to $1..."
    curl -s -X POST http://localhost:3001/send \
        -H "X-Bridge-Secret: $SECRET" \
        -H "Content-Type: application/json" \
        -d "{\"to\":\"$1\", \"idempotency_key\":\"$UUID\", \"text\":\"$2\"}"
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

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    wa-bridge-check)
        cmd_wa_bridge_check
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
    *)
        err "Unknown command: $COMMAND"
        exit 1
        ;;
esac
