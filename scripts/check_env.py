#!/usr/bin/env python3
"""Check that all required environment variables are set before starting a service.

Usage:
    python scripts/check_env.py worker
    python scripts/check_env.py api
    python scripts/check_env.py webhook
"""

from __future__ import annotations

import os
import sys

REQUIRED: dict[str, list[str]] = {
    "worker": [
        "TELEGRAM_BOT_TOKEN",
        "MANAGER_BOT_TOKEN",
        "POSTGRES_PASSWORD",
        "BRIDGE_SHARED_SECRET",
    ],
    "api": [
        "TELEGRAM_BOT_TOKEN",
        "POSTGRES_PASSWORD",
        "JWT_SECRET",
        "BRIDGE_SHARED_SECRET",
    ],
    "webhook": [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "MANAGER_BOT_TOKEN",
        "MANAGER_WEBHOOK_SECRET",
        "POSTGRES_PASSWORD",
    ],
}

INSECURE_DEFAULTS = {
    "POSTGRES_PASSWORD": "change_me",
    "JWT_SECRET": "change_me_in_production",
}


def check(role: str) -> int:
    required = REQUIRED.get(role)
    if required is None:
        print(f"Unknown role '{role}'. Valid: {', '.join(REQUIRED)}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for var in required:
        value = os.environ.get(var, "")
        if not value:
            errors.append(f"  MISSING: {var}")
        elif var in INSECURE_DEFAULTS and value == INSECURE_DEFAULTS[var]:
            errors.append(f"  INSECURE DEFAULT: {var} — change before production use")

    if errors:
        print(f"[check_env] Role '{role}' — environment problems:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    print(f"[check_env] Role '{role}' — all required vars present.")
    return 0


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "worker"
    sys.exit(check(role))
