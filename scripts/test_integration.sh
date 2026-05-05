#!/usr/bin/env bash
# Run integration tests on the production server against shermos_test DB
# and Redis db=15. The server's POSTGRES_PASSWORD is read from its env file.
set -euo pipefail

EXTRA_ARGS=("$@")  # forward any extra args (e.g. specific test path)

ssh aws-shermos1-frankfurt bash -c "'
set -euo pipefail
cd ~/shermos_bot
# Source env to get POSTGRES_PASSWORD
set -a
source .env 2>/dev/null || true
set +a

INTEGRATION_DB_DSN=\"postgresql://shermos:\${POSTGRES_PASSWORD}@127.0.0.1:5432/shermos_test\" \
INTEGRATION_REDIS_URL=\"redis://127.0.0.1:6379/15\" \
.venv/bin/python -m pytest -m integration -v ${EXTRA_ARGS[@]}
'"
