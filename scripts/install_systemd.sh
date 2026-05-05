#!/usr/bin/env bash
# install_systemd.sh — Phase 7 systemd unit installer
# Copies all unit files in scripts/systemd/ to /etc/systemd/system/,
# reloads daemon, and prints next-steps.
#
# Idempotent. Run as user with sudo. DO NOT auto-restart services
# (operator decides when to roll forward).
set -euo pipefail

DIR="$(cd "$(dirname "$0")/systemd" && pwd)"

if [ ! -d "${DIR}" ]; then
    echo "ERROR: ${DIR} not found"; exit 1
fi

count=0
for f in "${DIR}"/*.service; do
    [ -e "$f" ] || continue
    name="$(basename "$f")"
    echo "Installing ${name}..."
    sudo cp "$f" "/etc/systemd/system/${name}"
    count=$((count+1))
done

if [ $count -eq 0 ]; then
    echo "WARNING: no .service files found in ${DIR}"
    exit 0
fi

sudo systemctl daemon-reload
echo
echo "Installed $count units. systemd daemon reloaded."
echo
echo "Next steps (run manually):"
echo "  pip install systemd-python>=235 in venv (worker only)"
echo "  sudo systemctl restart shermos-worker shermos-api shermos-wa-client shermos-wa-manager"
echo "  systemctl status shermos-worker | head -20  # confirm WatchdogSec is honored"
