# Test database setup (server-only)

Integration tests defined under `@pytest.mark.integration` require a separate Postgres database and a dedicated Redis namespace on the production server. They run via `bash scripts/test_integration.sh`.

## One-time setup

```bash
ssh aws-shermos1-frankfurt
docker exec -it shermos_bot_postgres_1 psql -U shermos -c "CREATE DATABASE shermos_test"
```

Migrations are applied automatically by the test fixture on first run.

## Redis isolation

Tests use Redis db=15 with key prefix `test:`. The fixture wipes all `test:*` keys at session teardown. Production data on db=0 is never touched.

## Running

From your macbook:

```bash
bash scripts/test_integration.sh                                  # all integration tests
bash scripts/test_integration.sh tests/test_integration_smoke.py  # specific file
```

## Locally (will skip)

```bash
.venv/bin/python -m pytest -m integration -v
```

Without `INTEGRATION_DB_DSN` and `INTEGRATION_REDIS_URL` env vars, all tests in this set print `SKIPPED [reason: integration tests run on server only]`.
