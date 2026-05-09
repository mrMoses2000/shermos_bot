#!/usr/bin/env bash
# ============================================================
# Shermos Bot — рутинные операционные команды
# ============================================================
# Вызывается из run.sh, когда первый аргумент — одна из:
#   test | service | logs | health | deploy | db | remote | tunnel | cleanup
#
# Сервер vs Mac:
#   • На сервере (Ubuntu, /home/ubuntu/shermos_bot) — всё работает напрямую.
#   • На Mac префиксни любую серверную команду через `remote`:
#       ./run.sh remote service status
#       ./run.sh remote test
#       ./run.sh remote logs worker -n 50
#   • Mac-only:
#       ./run.sh deploy mini    — netlify deploy (требует netlify-cli + auth)
#
# Полный список:    ./run.sh help
# ============================================================

set -euo pipefail

# ── Цветной вывод (одинаков с run.sh / wa_bridge.sh) ─────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1" >&2; }
step() { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }

# ── Константы окружения ──────────────────────────────────────
SERVER_REPO="/home/ubuntu/shermos_bot"
SSH_ALIAS="aws-shermos1-frankfurt"
NETLIFY_SITE_ID="121a8211-34a6-4f70-bc6e-a5fc4e261138"

# Все шермосовские systemd-юниты, которые мы трогаем рутинно.
# shermos-tunnel и shermos-webhook не входят (вспомогательные / decommissioned).
SHERMOS_SERVICES=(shermos-worker shermos-api shermos-wa-client shermos-wa-manager)

is_server() { [ "$PROJECT_DIR" = "$SERVER_REPO" ]; }
is_local()  { ! is_server; }

require_server() {
    if ! is_server; then
        err "Эта команда выполняется на проде. С Mac оборачивай в 'remote':"
        err "  ./run.sh remote $*"
        exit 1
    fi
}

require_local() {
    if ! is_local; then
        err "Эта команда работает только локально (Netlify CLI / SSH out)."
        exit 1
    fi
}

# ────────────────────────────────────────────────────────────
# remote  — re-invoke ./run.sh на сервере через SSH
# ────────────────────────────────────────────────────────────
cmd_remote() {
    require_local
    if [ $# -eq 0 ]; then
        err "Использование: ./run.sh remote <subcmd> [args...]"
        return 1
    fi
    local quoted=""
    for a in "$@"; do
        quoted+=" $(printf '%q' "$a")"
    done
    ssh -t "$SSH_ALIAS" "cd shermos_bot && ./run.sh${quoted}"
}

# ────────────────────────────────────────────────────────────
# test  — Python unit / integration / bridge / mini-app
# ────────────────────────────────────────────────────────────
cmd_test() {
    local kind="${1:-all}"
    case "$kind" in
        py|python|unit)
            step "🧪 Python unit-тесты"
            "$PROJECT_DIR/.venv/bin/python" -m pytest -q
            ;;
        integration|integ)
            step "🧪 Python integration-тесты (реальные Postgres + Redis)"
            require_server
            set -a
            # shellcheck disable=SC1091
            source "$PROJECT_DIR/.env"
            set +a
            INTEGRATION_DB_DSN="postgresql://shermos:${POSTGRES_PASSWORD}@127.0.0.1:5432/shermos_test" \
            INTEGRATION_REDIS_URL="redis://127.0.0.1:6379/15" \
            "$PROJECT_DIR/.venv/bin/python" -m pytest -m integration -q
            ;;
        bridge|wa)
            step "🧪 WhatsApp bridge: typecheck + vitest"
            cd "$PROJECT_DIR/whatsapp-bridge"
            pnpm typecheck
            pnpm test
            cd "$PROJECT_DIR"
            ;;
        mini|frontend)
            step "🧪 Mini-app: vitest"
            cd "$PROJECT_DIR/mini-app"
            npm test
            cd "$PROJECT_DIR"
            ;;
        all)
            cmd_test py
            cmd_test bridge
            if is_server; then
                cmd_test integration
            else
                warn "Integration пропущены — запускаются только на сервере (./run.sh remote test integration)."
            fi
            ;;
        *)
            err "Неизвестный набор: $kind  (доступно: py | integration | bridge | mini | all)"
            return 1
            ;;
    esac
}

# ────────────────────────────────────────────────────────────
# service  — systemctl-обёртка (status | start | stop | restart)
# ────────────────────────────────────────────────────────────
_resolve_services() {
    local target="${1:-all}"
    if [ "$target" = "all" ]; then
        printf '%s\n' "${SHERMOS_SERVICES[@]}"
    elif [[ "$target" == shermos-* ]]; then
        echo "$target"
    else
        echo "shermos-$target"
    fi
}

cmd_service() {
    require_server
    local action="${1:-status}"
    local target="${2:-all}"
    local services
    mapfile -t services < <(_resolve_services "$target")

    case "$action" in
        status)
            step "📋 Статус: ${services[*]}"
            for s in "${services[@]}"; do
                local active since
                active=$(systemctl is-active "$s" 2>/dev/null || true)
                since=$(systemctl show "$s" -p ActiveEnterTimestamp --value 2>/dev/null || echo "—")
                printf "  %-22s %-12s  с %s\n" "$s" "$active" "$since"
            done
            ;;
        restart)
            step "🔄 Restart: ${services[*]}"
            sudo systemctl restart "${services[@]}"
            sleep 3
            cmd_service status "$target"
            ;;
        start)
            step "▶️  Start: ${services[*]}"
            sudo systemctl start "${services[@]}"
            sleep 2
            cmd_service status "$target"
            ;;
        stop)
            step "⏹️  Stop: ${services[*]}"
            sudo systemctl stop "${services[@]}"
            cmd_service status "$target"
            ;;
        *)
            err "Неизвестное действие: $action  (доступно: status | restart | start | stop)"
            return 1
            ;;
    esac
}

# ────────────────────────────────────────────────────────────
# logs  — журнал systemd для shermos-* сервиса
# ────────────────────────────────────────────────────────────
cmd_logs() {
    require_server
    local service
    service="$(_resolve_services "${1:-worker}" | head -1)"
    shift || true
    if [ $# -eq 0 ]; then
        sudo journalctl -u "$service" -n 50 --no-pager
    else
        sudo journalctl -u "$service" --no-pager "$@"
    fi
}

# ────────────────────────────────────────────────────────────
# health  — единый снимок: сервисы / очереди / outbox / диск
# ────────────────────────────────────────────────────────────
cmd_health() {
    require_server

    step "📋 Сервисы"
    cmd_service status all

    step "📥 Redis-очереди"
    for q in queue:incoming queue:manager bridge:spool:inbound; do
        printf "  %-26s %s\n" "$q" "$(docker exec shermos_bot_redis_1 redis-cli LLEN "$q" 2>/dev/null || echo '?')"
    done

    step "📤 Outbox за последний час"
    docker exec shermos_bot_postgres_1 psql -U shermos -d shermos_bot -t -A -F'|' -c \
        "SELECT bot_type, status, COUNT(*) FROM outbound_events
         WHERE created_at > now() - interval '1 hour' GROUP BY 1,2 ORDER BY 1,2" \
        2>/dev/null | awk -F'|' 'NF>=3 {printf "  %-10s %-10s %s\n",$1,$2,$3}'

    step "📐 Активные замеры"
    docker exec shermos_bot_postgres_1 psql -U shermos -d shermos_bot -t -A -F'|' -c \
        "SELECT id, status, scheduled_time AT TIME ZONE 'Asia/Bishkek', client_name FROM measurements
         WHERE status NOT IN ('completed','cancelled','no_show') ORDER BY scheduled_time" \
        2>/dev/null | awk -F'|' 'NF>=4 {printf "  #%-4s %-12s %s  %s\n",$1,$2,$3,$4}'

    step "📡 WhatsApp-мосты (HTTP /status)"
    for port in 3001 3002; do
        local role code
        role=$( [ "$port" = 3001 ] && echo client || echo manager )
        code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/status" || echo "ERR")
        printf "  %-7s localhost:%s  HTTP %s\n" "$role" "$port" "$code"
    done

    step "💾 Диск / Память / Swap"
    df -h / | tail -1 | awk '{printf "  /  %s used  (%s of %s)\n",$5,$3,$2}'
    free -h | awk '/^Mem:/  {printf "  Mem:  %s used / %s total / %s available\n",$3,$2,$7}
                   /^Swap:/ {printf "  Swap: %s used / %s total\n",$3,$2}'

    step "🌐 Cloudflare-туннель (URL для VITE_API_BASE_URL)"
    local tunnel_url
    tunnel_url=$(journalctl -u shermos-tunnel --no-pager 2>/dev/null \
                 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
    echo "  ${tunnel_url:-(не найден в логах shermos-tunnel)}"
}

# ────────────────────────────────────────────────────────────
# deploy  — server | mini (Netlify) | both
# ────────────────────────────────────────────────────────────
cmd_deploy() {
    local target="${1:-}"
    case "$target" in
        server)
            if is_local; then
                cmd_remote deploy server
                return $?
            fi
            step "📥 git pull main"
            cd "$PROJECT_DIR"
            git fetch origin
            git pull --ff-only origin main

            step "🔨 whatsapp-bridge: pnpm install + build"
            cd "$PROJECT_DIR/whatsapp-bridge"
            pnpm install --frozen-lockfile
            pnpm build
            cd "$PROJECT_DIR"

            step "🐍 Python deps (если изменились)"
            "$PROJECT_DIR/.venv/bin/pip" install -q -r requirements.txt

            step "🔄 Restart всех сервисов"
            sudo systemctl restart "${SHERMOS_SERVICES[@]}"
            sleep 3
            cmd_service status all
            ;;

        mini|netlify|frontend)
            require_local

            if ! command -v netlify >/dev/null 2>&1; then
                err "netlify CLI не найден. Установи: npm install -g netlify-cli"
                return 1
            fi

            step "🌐 Получаю текущий URL Cloudflare-туннеля"
            local api_base="${VITE_API_BASE_URL:-}"
            if [ -z "$api_base" ]; then
                api_base=$(ssh "$SSH_ALIAS" "journalctl -u shermos-tunnel --no-pager 2>/dev/null | grep -oE 'https://[a-z0-9-]+\\.trycloudflare\\.com' | tail -1" || true)
            fi
            if [ -z "$api_base" ]; then
                err "VITE_API_BASE_URL не задан и не нашёлся в логах. Передай явно:"
                err "  VITE_API_BASE_URL=https://... ./run.sh deploy mini"
                return 1
            fi
            log "Backend URL: $api_base"

            step "🔨 Сборка mini-app (npm run build)"
            cd "$PROJECT_DIR/mini-app"
            VITE_API_BASE_URL="$api_base" npm run build
            cd "$PROJECT_DIR"

            step "🚀 netlify deploy --prod"
            netlify deploy --dir=mini-app/dist --site="$NETLIFY_SITE_ID" --no-build --prod
            ;;

        both)
            cmd_deploy server
            cmd_deploy mini
            ;;

        ""|*)
            err "Использование: ./run.sh deploy <server|mini|both>"
            return 1
            ;;
    esac
}

# ────────────────────────────────────────────────────────────
# db  — shell | migrate | backup
# ────────────────────────────────────────────────────────────
cmd_db() {
    require_server
    local action="${1:-}"
    case "$action" in
        shell|psql)
            docker exec -it shermos_bot_postgres_1 psql -U shermos -d shermos_bot
            ;;

        migrate)
            step "🗄️  Применяю незакрытые миграции (run_migrations)"
            cd "$PROJECT_DIR"
            "$PROJECT_DIR/.venv/bin/python" - <<'PYEOF'
import asyncio
from src.config import settings
from src.db import postgres


async def main():
    pool = await postgres.create_pool(settings)
    try:
        await postgres.run_migrations(pool, "migrations/")
        print("Миграции применены.")
    finally:
        await postgres.close_pool(pool)


asyncio.run(main())
PYEOF
            ;;

        backup)
            local ts out
            ts=$(date +%Y%m%d-%H%M%S)
            out="$HOME/shermos_bot_attic/db-backups/shermos_bot-${ts}.sql.gz"
            mkdir -p "$(dirname "$out")"
            step "💾 Дамп shermos_bot → $out"
            docker exec shermos_bot_postgres_1 pg_dump -U shermos shermos_bot | gzip > "$out"
            log "Готово: $(du -h "$out" | cut -f1)  $out"
            ;;

        *)
            err "Использование: ./run.sh db <shell|migrate|backup>"
            return 1
            ;;
    esac
}

# ────────────────────────────────────────────────────────────
# tunnel  — текущий публичный URL Cloudflare-туннеля
# ────────────────────────────────────────────────────────────
cmd_tunnel() {
    if is_local; then
        cmd_remote tunnel "$@"
        return $?
    fi
    journalctl -u shermos-tunnel --no-pager 2>/dev/null \
        | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
}

# ────────────────────────────────────────────────────────────
# cleanup  — освобождение диска / архивация секретов
# ────────────────────────────────────────────────────────────
cmd_cleanup() {
    require_server
    local target="${1:-all}"
    case "$target" in
        docker|images)
            step "🧹 Docker image prune (только неиспользуемые)"
            df -h / | tail -1
            sudo docker image prune -a -f
            df -h / | tail -1
            ;;
        env-bak)
            step "📦 Архивирую .env.bak.* в ~/shermos_bot_attic/"
            local archive_dir="$HOME/shermos_bot_attic/env_backups_$(date +%Y-%m-%d)"
            mkdir -p "$archive_dir"
            mv "$PROJECT_DIR"/.env.bak.* "$archive_dir/" 2>/dev/null || warn "В репо нет .env.bak.* файлов"
            ls -la "$archive_dir/" 2>/dev/null | tail -5
            ;;
        all)
            cmd_cleanup docker
            cmd_cleanup env-bak
            ;;
        *)
            err "Использование: ./run.sh cleanup <docker|env-bak|all>"
            return 1
            ;;
    esac
}

# ────────────────────────────────────────────────────────────
# help
# ────────────────────────────────────────────────────────────
cmd_help() {
    cat <<'HELP'
Shermos Bot — операционные команды
==================================

Серверные (запускать на проде, либо на Mac через `remote`):

  test [py|integration|bridge|mini|all]
                        Тесты. all = py + bridge.
  service <action> [name]
                        action: status | restart | start | stop
                        name:   worker | api | wa-client | wa-manager | all
  logs [service] [args journalctl]
                        По умолчанию last 50 lines.
                          ./run.sh logs worker -n 100
                          ./run.sh logs wa-client -f
                          ./run.sh logs api --since "10 min ago"
  health                Снимок: сервисы / очереди / outbox / диск / туннель.
  db <shell|migrate|backup>
                        psql / применить миграции / дамп.
  deploy server         git pull + bridge build + restart всех сервисов.
  tunnel                Текущий URL Cloudflare-туннеля (для VITE_API_BASE_URL).
  cleanup <docker|env-bak|all>
                        Освободить диск / архивировать .env-бэкапы.

Локальные (Mac):

  remote <subcmd>       SSH на сервер и выполнить там `./run.sh <subcmd>`.
                          ./run.sh remote service status
                          ./run.sh remote test
                          ./run.sh remote logs worker -n 50
                          ./run.sh remote health
  deploy mini           npm run build с VITE_API_BASE_URL из туннеля,
                        потом `netlify deploy --prod` (Netlify CLI).
  deploy both           server + mini одной командой.
  test [py|bridge|mini|all]
                        Локальные виды тестов.

Bootstrap (без аргументов): ./run.sh
                        Полная первичная установка на сервере.

Примеры:
  # На сервере: рестартонуть worker и проверить
  ./run.sh service restart worker
  ./run.sh health

  # С Mac: один заход — код + фронт
  ./run.sh deploy both

  # С Mac: подсмотреть логи воркера без ручного SSH
  ./run.sh remote logs worker -n 30
HELP
}

# ────────────────────────────────────────────────────────────
# Диспетчер
# ────────────────────────────────────────────────────────────
COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    test)     cmd_test "$@" ;;
    service)  cmd_service "$@" ;;
    logs)     cmd_logs "$@" ;;
    health)   cmd_health "$@" ;;
    deploy)   cmd_deploy "$@" ;;
    db)       cmd_db "$@" ;;
    remote)   cmd_remote "$@" ;;
    tunnel)   cmd_tunnel "$@" ;;
    cleanup)  cmd_cleanup "$@" ;;
    help|-h|--help) cmd_help ;;
    *)
        err "Неизвестная команда: $COMMAND"
        cmd_help
        exit 1
        ;;
esac
