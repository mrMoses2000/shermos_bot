"""asyncpg access layer for all local PostgreSQL data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import asyncpg


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


async def create_pool(settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
        timeout=30,
    )


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()


async def run_migrations(pool: asyncpg.Pool, migrations_dir: str = "migrations/") -> None:
    migrations_path = Path(migrations_dir)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        for sql_file in sorted(migrations_path.glob("*.sql")):
            already = await conn.fetchval(
                "SELECT 1 FROM _migrations WHERE filename=$1",
                sql_file.name,
            )
            if already:
                continue
            async with conn.transaction():
                await conn.execute(sql_file.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO _migrations(filename) VALUES ($1)", sql_file.name)


async def mark_update_received(pool, update_id: int) -> bool:
    row = await pool.fetchrow(
        """
        INSERT INTO processed_updates (telegram_update_id, status)
        VALUES ($1, 'received')
        ON CONFLICT DO NOTHING
        RETURNING telegram_update_id
        """,
        update_id,
    )
    return row is not None


async def mark_update_status(pool, update_id: int, status: str, error: str | None = None) -> None:
    await pool.execute(
        """
        UPDATE processed_updates
        SET status=$2,
            error_message=COALESCE($3, error_message),
            completed_at=CASE WHEN $2 IN ('completed', 'failed') THEN now() ELSE completed_at END
        WHERE telegram_update_id=$1
        """,
        update_id,
        status,
        error,
    )


async def insert_inbound_event(pool, update_id: int, chat_id: int, user_id: int, text: str, raw_update: dict) -> int:
    return await pool.fetchval(
        """
        INSERT INTO inbound_events (telegram_update_id, chat_id, user_id, text, raw_update)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        RETURNING id
        """,
        update_id,
        chat_id,
        user_id,
        text or "",
        _json(raw_update),
    )


async def insert_outbound_event(
    pool,
    chat_id: int,
    reply_text: str,
    reply_markup: dict | None = None,
    inbound_event_id: int | None = None,
    bot_type: str = "client",
) -> int:
    return await pool.fetchval(
        """
        INSERT INTO outbound_events (chat_id, bot_type, reply_text, reply_markup, inbound_event_id)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        RETURNING id
        """,
        chat_id,
        bot_type,
        reply_text or "",
        _json(reply_markup) if reply_markup is not None else None,
        inbound_event_id,
    )


async def mark_outbound_sent(pool, event_id: int, telegram_message_id: int | None = None) -> None:
    await pool.execute(
        """
        UPDATE outbound_events
        SET status='sent',
            sent_at=now(),
            telegram_message_id=$2,
            error_message=NULL
        WHERE id=$1
        """,
        event_id,
        telegram_message_id,
    )


async def mark_outbound_failed(pool, event_id: int, error: str) -> None:
    await pool.execute(
        """
        UPDATE outbound_events
        SET attempts=attempts+1,
            last_attempt_at=now(),
            error_message=$2,
            status=CASE WHEN attempts + 1 >= 5 THEN 'failed' ELSE 'pending' END
        WHERE id=$1
        """,
        event_id,
        error[:2000],
    )


async def get_pending_outbound(pool, limit: int = 20) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT *
        FROM outbound_events
        WHERE status='pending' AND attempts < 5
        ORDER BY created_at
        LIMIT $1
        """,
        limit,
    )
    return _rows_to_dicts(rows)


async def get_conversation_state(pool, chat_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow("SELECT * FROM conversation_state WHERE chat_id=$1", chat_id)
    return _row_to_dict(row)


async def upsert_conversation_state(
    pool,
    chat_id: int,
    mode: str,
    step: str | None,
    collected_params: dict | None,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO conversation_state (chat_id, mode, step, collected_params, updated_at)
        VALUES ($1, $2, $3, $4::jsonb, now())
        ON CONFLICT (chat_id) DO UPDATE
        SET mode=EXCLUDED.mode,
            step=EXCLUDED.step,
            collected_params=EXCLUDED.collected_params,
            updated_at=now()
        RETURNING *
        """,
        chat_id,
        mode,
        step,
        _json(collected_params),
    )
    return dict(row)


async def insert_chat_message(pool, chat_id: int, role: str, text: str) -> int:
    return await pool.fetchval(
        "INSERT INTO chat_messages (chat_id, role, text) VALUES ($1, $2, $3) RETURNING id",
        chat_id,
        role,
        text,
    )


async def get_chat_messages(pool, chat_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT *
        FROM (
            SELECT *
            FROM chat_messages
            WHERE chat_id=$1
            ORDER BY created_at DESC
            LIMIT $2
        ) recent
        ORDER BY created_at ASC
        """,
        chat_id,
        limit,
    )
    return _rows_to_dicts(rows)


async def clear_chat_messages(pool, chat_id: int) -> None:
    await pool.execute("DELETE FROM chat_messages WHERE chat_id=$1", chat_id)


async def get_client_by_chat_id(pool, chat_id: int) -> dict[str, Any] | None:
    return _row_to_dict(await pool.fetchrow("SELECT * FROM clients WHERE chat_id=$1", chat_id))


async def create_client(pool, chat_id: int, first_name: str = "", username: str = "") -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO clients (chat_id, first_name, username)
        VALUES ($1, $2, $3)
        ON CONFLICT (chat_id) DO UPDATE
        SET first_name=COALESCE(NULLIF(EXCLUDED.first_name, ''), clients.first_name),
            username=COALESCE(NULLIF(EXCLUDED.username, ''), clients.username),
            updated_at=now()
        RETURNING *
        """,
        chat_id,
        first_name or "",
        username or "",
    )
    return dict(row)


async def update_client(pool, chat_id: int, **fields: Any) -> dict[str, Any]:
    allowed = {"first_name", "username", "name", "phone", "address"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    if not updates:
        existing = await get_client_by_chat_id(pool, chat_id)
        if existing:
            return existing
        return await create_client(pool, chat_id)
    set_sql = ", ".join(f"{key}=${idx}" for idx, key in enumerate(updates, start=2))
    values = list(updates.values())
    row = await pool.fetchrow(
        f"""
        UPDATE clients
        SET {set_sql}, updated_at=now()
        WHERE chat_id=$1
        RETURNING *
        """,
        chat_id,
        *values,
    )
    if row is None:
        await create_client(pool, chat_id)
        return await update_client(pool, chat_id, **fields)
    return dict(row)


async def list_clients(pool, search: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    if search:
        like = f"%{search}%"
        rows = await pool.fetch(
            """
            SELECT *
            FROM clients
            WHERE name ILIKE $1 OR first_name ILIKE $1 OR username ILIKE $1 OR phone ILIKE $1
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            like,
            limit,
            offset,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM clients ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return _rows_to_dicts(rows)


async def get_client_with_orders(pool, chat_id: int) -> dict[str, Any] | None:
    client = await get_client_by_chat_id(pool, chat_id)
    if not client:
        return None
    client["orders"] = await list_orders(pool, limit=100, offset=0, search=str(chat_id))
    return client


async def create_order(
    pool,
    request_id: str,
    chat_id: int,
    details_json: dict,
    render_paths: dict,
    price: dict,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO orders (request_id, chat_id, details_json, render_paths, price)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb)
        RETURNING *
        """,
        request_id,
        chat_id,
        _json(details_json),
        _json(render_paths),
        _json(price),
    )
    return dict(row)


async def get_order(pool, request_id: str) -> dict[str, Any] | None:
    return _row_to_dict(await pool.fetchrow("SELECT * FROM orders WHERE request_id=$1", request_id))


async def list_orders(
    pool,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if status:
        values.append(status)
        clauses.append(f"status=${len(values)}")
    if search:
        values.append(f"%{search}%")
        idx = len(values)
        clauses.append(
            f"(request_id ILIKE ${idx} OR chat_id::text ILIKE ${idx} OR details_json::text ILIKE ${idx})"
        )
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.extend([limit, offset])
    rows = await pool.fetch(
        f"""
        SELECT *
        FROM orders
        {where}
        ORDER BY created_at DESC
        LIMIT ${len(values) - 1} OFFSET ${len(values)}
        """,
        *values,
    )
    return _rows_to_dicts(rows)


async def update_order_status(pool, request_id: str, status: str, note: str = "") -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        UPDATE orders
        SET status=$2, manager_note=$3, updated_at=now()
        WHERE request_id=$1
        RETURNING *
        """,
        request_id,
        status,
        note or "",
    )
    if row is None:
        raise ValueError(f"Order not found: {request_id}")
    return dict(row)


async def count_orders_by_status(pool) -> dict[str, int]:
    rows = await pool.fetch("SELECT status, count(*)::int AS count FROM orders GROUP BY status")
    return {row["status"]: row["count"] for row in rows}


async def create_measurement(
    pool,
    client_chat_id: int,
    scheduled_time,
    address: str,
    notes: str = "",
    calendar_event_id: str | None = None,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO measurements (client_chat_id, scheduled_time, address, notes, calendar_event_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        client_chat_id,
        scheduled_time,
        address or "",
        notes or "",
        calendar_event_id,
    )
    return dict(row)


async def list_measurements(
    pool,
    upcoming_only: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if upcoming_only:
        rows = await pool.fetch(
            """
            SELECT *
            FROM measurements
            WHERE scheduled_time >= now()
            ORDER BY scheduled_time ASC
            LIMIT $1
            """,
            limit,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM measurements ORDER BY scheduled_time DESC LIMIT $1",
            limit,
        )
    return _rows_to_dicts(rows)


async def confirm_measurement(pool, measurement_id: int) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        UPDATE measurements
        SET status='confirmed', updated_at=now()
        WHERE id=$1
        RETURNING *
        """,
        measurement_id,
    )
    if row is None:
        raise ValueError(f"Measurement not found: {measurement_id}")
    return dict(row)


async def get_measurements_for_client(pool, chat_id: int) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT * FROM measurements WHERE client_chat_id=$1 ORDER BY scheduled_time DESC",
        chat_id,
    )
    return _rows_to_dicts(rows)


async def get_prices(pool) -> list[dict[str, Any]]:
    return _rows_to_dicts(await pool.fetch("SELECT * FROM prices ORDER BY category, id"))


async def update_price(pool, price_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {"name", "category", "amount", "currency", "metadata"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    if not updates:
        row = await pool.fetchrow("SELECT * FROM prices WHERE id=$1", price_id)
        if row is None:
            raise ValueError(f"Price not found: {price_id}")
        return dict(row)
    values: list[Any] = []
    fragments: list[str] = []
    for key, value in updates.items():
        values.append(_json(value) if key == "metadata" else value)
        cast = "::jsonb" if key == "metadata" else ""
        fragments.append(f"{key}=${len(values) + 1}{cast}")
    row = await pool.fetchrow(
        f"UPDATE prices SET {', '.join(fragments)}, updated_at=now() WHERE id=$1 RETURNING *",
        price_id,
        *values,
    )
    if row is None:
        raise ValueError(f"Price not found: {price_id}")
    return dict(row)


async def seed_default_prices(pool) -> None:
    defaults = [
        ("base_sqm", "Base square meter", "base", 180, "USD", {"unit": "sqm"}),
        ("handle", "Door handle", "addon", 80, "USD", {"unit": "piece"}),
    ]
    for item in defaults:
        await pool.execute(
            """
            INSERT INTO prices (id, name, category, amount, currency, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT DO NOTHING
            """,
            item[0],
            item[1],
            item[2],
            item[3],
            item[4],
            _json(item[5]),
        )


async def get_materials(pool) -> list[dict[str, Any]]:
    return _rows_to_dicts(await pool.fetch("SELECT * FROM materials ORDER BY kind, id"))


async def update_material(pool, material_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {"kind", "name", "color", "roughness", "metadata"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    values: list[Any] = []
    fragments: list[str] = []
    for key, value in updates.items():
        values.append(_json(value) if key in {"color", "metadata"} else value)
        cast = "::jsonb" if key in {"color", "metadata"} else ""
        fragments.append(f"{key}=${len(values) + 1}{cast}")
    if not fragments:
        row = await pool.fetchrow("SELECT * FROM materials WHERE id=$1", material_id)
    else:
        row = await pool.fetchrow(
            f"UPDATE materials SET {', '.join(fragments)}, updated_at=now() WHERE id=$1 RETURNING *",
            material_id,
            *values,
        )
    if row is None:
        raise ValueError(f"Material not found: {material_id}")
    return dict(row)


async def seed_default_materials(pool) -> None:
    from src.utils.config_manager import config

    for kind, db_kind in (("frame_colors", "frame"), ("glass_types", "glass")):
        for material_id, data in config.get_all_materials(kind).items():
            await pool.execute(
                """
                INSERT INTO materials (id, kind, name, color, roughness, metadata)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
                ON CONFLICT DO NOTHING
                """,
                f"{db_kind}_{material_id}",
                db_kind,
                data.get("name", material_id),
                _json(data.get("color")),
                data.get("roughness"),
                _json({"source_id": material_id}),
            )


async def get_dashboard_stats(pool, days: int = 30) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        SELECT
            count(*)::int AS total_orders,
            COALESCE(sum((price->>'total_price')::numeric), 0)::float AS total_revenue,
            count(*) FILTER (WHERE created_at::date = current_date)::int AS orders_today
        FROM orders
        WHERE created_at >= now() - ($1::text || ' days')::interval
        """,
        days,
    )
    pending_measurements = await pool.fetchval(
        "SELECT count(*)::int FROM measurements WHERE status IN ('scheduled', 'confirmed')"
    )
    stats = dict(row) if row else {"total_orders": 0, "total_revenue": 0.0, "orders_today": 0}
    stats["pending_measurements"] = pending_measurements or 0
    return stats
