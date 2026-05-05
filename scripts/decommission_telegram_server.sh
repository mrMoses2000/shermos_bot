#!/usr/bin/env bash
# decommission_telegram_server.sh — Phase 10 server-side cleanup
#
# Run ONCE on the production server after deploying Phase 10.A code.
# This script:
#   1. Stops and disables the shermos-webhook.service
#   2. Removes the webhook systemd unit file
#   3. Deletes the Telegram SSL certificate (port 88 no longer needed)
#   4. Closes port 88 in ufw (if ufw is active)
#   5. Removes the AWS Security Group rule for port 88 (manual reminder)
#   6. Marks any stale Telegram outbound_events as dead in Postgres
#
# PREREQUISITES:
#   - Phase 10.A code is deployed and shermos-worker is running
#   - POSTGRES_* env vars are available in the current shell (source .env first)
#   - The script must be run as a user with sudo access
#
# USAGE (on the server):
#   source ~/shermos-bot/.env
#   bash ~/shermos-bot/scripts/decommission_telegram_server.sh
#
# DO NOT RUN this script in development or CI.

set -euo pipefail

UNIT_FILE="/etc/systemd/system/shermos-webhook.service"
SSL_CERT="certs/webhook.pem"
SSL_KEY="certs/webhook.key"
REPO_DIR="${HOME}/shermos-bot"

echo "=== Phase 10 — Telegram decommission ==="
echo "Started at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

# ─── 1. Stop and disable shermos-webhook.service ─────────────────────────────

if systemctl is-active --quiet shermos-webhook 2>/dev/null; then
    echo "[1/6] Stopping shermos-webhook.service..."
    sudo systemctl stop shermos-webhook
else
    echo "[1/6] shermos-webhook.service is not running — skipping stop."
fi

if systemctl is-enabled --quiet shermos-webhook 2>/dev/null; then
    echo "      Disabling shermos-webhook.service..."
    sudo systemctl disable shermos-webhook
else
    echo "      shermos-webhook.service already disabled."
fi

# ─── 2. Remove the webhook systemd unit file ─────────────────────────────────

if [ -f "${UNIT_FILE}" ]; then
    echo "[2/6] Removing ${UNIT_FILE}..."
    sudo rm -f "${UNIT_FILE}"
    sudo systemctl daemon-reload
    echo "      systemd daemon reloaded."
else
    echo "[2/6] ${UNIT_FILE} not found — already removed."
fi

# ─── 3. Delete Telegram SSL certificate (port 88 self-signed cert) ───────────

echo "[3/6] Removing SSL cert/key used for Telegram webhook (port 88)..."
cd "${REPO_DIR}"
if [ -f "${SSL_CERT}" ]; then
    rm -f "${SSL_CERT}"
    echo "      Removed ${SSL_CERT}"
else
    echo "      ${SSL_CERT} not found — already removed."
fi
if [ -f "${SSL_KEY}" ]; then
    rm -f "${SSL_KEY}"
    echo "      Removed ${SSL_KEY}"
else
    echo "      ${SSL_KEY} not found — already removed."
fi

# ─── 4. Close port 88 in ufw (if ufw is active) ──────────────────────────────

echo "[4/6] Closing port 88 in ufw (if active)..."
if sudo ufw status | grep -q "Status: active"; then
    if sudo ufw status | grep -q "88/tcp"; then
        sudo ufw delete allow 88/tcp
        echo "      Port 88/tcp rule deleted."
    else
        echo "      Port 88/tcp rule not found in ufw — already removed."
    fi
else
    echo "      ufw is not active — skipping."
fi

# ─── 5. AWS Security Group reminder (manual action required) ──────────────────

echo "[5/6] MANUAL ACTION REQUIRED:"
echo "      Remove inbound rule for port 88 (TCP) from the AWS Security Group."
echo "      Go to: AWS Console → EC2 → Security Groups → edit inbound rules."
echo "      The Python services no longer listen on port 88."
echo

# ─── 6. Mark stale Telegram outbound_events as dead ──────────────────────────

echo "[6/6] Marking stale Telegram outbound_events as dead in Postgres..."

PSQL_CMD="psql -h ${POSTGRES_HOST:-localhost} -p ${POSTGRES_PORT:-5432} \
    -U ${POSTGRES_USER:-shermos} -d ${POSTGRES_DB:-shermos_bot} \
    --no-password -t -c"

PGPASSWORD="${POSTGRES_PASSWORD:-change_me}" ${PSQL_CMD} "
UPDATE outbound_events
SET status = 'dead',
    error   = 'telegram_decommissioned',
    updated_at = NOW()
WHERE channel = 'telegram'
  AND status  = 'pending';
" && echo "      Telegram pending events marked dead (if any)."

# ─── Done ─────────────────────────────────────────────────────────────────────

echo
echo "=== Decommission complete ==="
echo "Finished at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo
echo "Verify with:"
echo "  sudo systemctl status shermos-webhook  # should say 'not found'"
echo "  sudo systemctl is-active shermos-worker shermos-api  # should say 'active'"
echo "  curl http://localhost:9443/api/health/bridges"
