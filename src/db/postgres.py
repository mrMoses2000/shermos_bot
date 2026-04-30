"""asyncpg access layer for all local PostgreSQL data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import asyncpg

from src.utils.json_tools import ensure_json_array, ensure_json_object


def _json(value: Any) -> Any:
    return value if value is not None else {}


def _normalize_json_fields(
    data: dict[str, Any],
    *,
    object_fields: Iterable[str] = (),
    array_fields: Iterable[str] = (),
) -> dict[str, Any]:
    for field in object_fields:
        if field in data and data[field] is not None:
            data[field] = ensure_json_object(data[field])
    for field in array_fields:
        if field in data and data[field] is not None:
            data[field] = ensure_json_array(data[field])
    return data


def _row_to_dict(
    row: Any,
    *,
    object_fields: Iterable[str] = (),
    array_fields: Iterable[str] = (),
) -> dict[str, Any] | None:
    if row is None:
        return None
    return _normalize_json_fields(dict(row), object_fields=object_fields, array_fields=array_fields)


def _rows_to_dicts(
    rows: Iterable[Any],
    *,
    object_fields: Iterable[str] = (),
    array_fields: Iterable[str] = (),
) -> list[dict[str, Any]]:
    return [
        _normalize_json_fields(dict(row), object_fields=object_fields, array_fields=array_fields)
        for row in rows
    ]


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so metadata comes back as dict, not str."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool(settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
        timeout=30,
        init=_init_connection,
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
                await conn.execute(
                    "INSERT INTO _migrations(filename) VALUES ($1) ON CONFLICT DO NOTHING",
                    sql_file.name,
                )


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


async def mark_external_update_received(
    pool,
    channel: str,
    external_update_id: str,
    synthetic_update_id: int,
) -> bool:
    row = await pool.fetchrow(
        """
        INSERT INTO processed_updates (telegram_update_id, channel, external_update_id, status)
        VALUES ($1, $2, $3, 'received')
        ON CONFLICT DO NOTHING
        RETURNING telegram_update_id
        """,
        synthetic_update_id,
        channel,
        external_update_id,
    )
    return row is not None


async def get_update_status(pool, update_id: int) -> str | None:
    row = await pool.fetchrow(
        "SELECT status FROM processed_updates WHERE telegram_update_id=$1",
        update_id,
    )
    return row["status"] if row else None


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


async def insert_inbound_event(
    pool,
    update_id: int,
    chat_id: int,
    user_id: int,
    text: str,
    raw_update: dict,
    *,
    channel: str = "telegram",
    external_message_id: str | None = None,
    external_chat_id: str | None = None,
    phone_e164: str | None = None,
    media_path: str | None = None,
    media_mime: str | None = None,
) -> int:
    return await pool.fetchval(
        """
        INSERT INTO inbound_events (
            telegram_update_id,
            chat_id,
            user_id,
            text,
            raw_update,
            channel,
            external_message_id,
            external_chat_id,
            phone_e164,
            media_path,
            media_mime
        )
        VALUES ($1, $2, $3, $4, $11::jsonb, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        update_id,
        chat_id,
        user_id,
        text or "",
        channel,
        external_message_id,
        external_chat_id,
        phone_e164,
        media_path,
        media_mime,
        _json(raw_update),
    )


async def get_last_inbound_event(pool, chat_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT * FROM inbound_events
        WHERE chat_id=$1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        chat_id,
    )
    return _row_to_dict(row) if row else None


async def insert_outbound_event(
    pool,
    chat_id: int,
    reply_text: str,
    reply_markup: dict | None = None,
    inbound_event_id: int | None = None,
    bot_type: str = "client",
    channel: str = "telegram",
    external_chat_id: str | None = None,
    idempotency_key: str | None = None,
) -> int:
    return await pool.fetchval(
        """
        INSERT INTO outbound_events (
            chat_id,
            bot_type,
            reply_text,
            reply_markup,
            inbound_event_id,
            channel,
            external_chat_id,
            idempotency_key
        )
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)
        RETURNING id
        """,
        chat_id,
        bot_type,
        reply_text or "",
        _json(reply_markup) if reply_markup is not None else None,
        inbound_event_id,
        channel,
        external_chat_id,
        idempotency_key,
    )


async def mark_outbound_sent(
    pool,
    event_id: int,
    telegram_message_id: int | None = None,
    external_message_id: str | None = None,
) -> None:
    await pool.execute(
        """
        UPDATE outbound_events
        SET status='sent',
            sent_at=now(),
            telegram_message_id=$2,
            external_message_id=COALESCE($3, external_message_id),
            error_message=NULL
        WHERE id=$1
        """,
        event_id,
        telegram_message_id,
        external_message_id,
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
    return _rows_to_dicts(rows, object_fields=("reply_markup",))


async def get_conversation_state(pool, chat_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow("SELECT * FROM conversation_state WHERE chat_id=$1", chat_id)
    return _row_to_dict(row, object_fields=("collected_params",))


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
        ensure_json_object(collected_params),
    )
    return _row_to_dict(row, object_fields=("collected_params",)) or {}


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


async def get_conversation_memory(pool, chat_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow("SELECT * FROM conversation_memory WHERE chat_id=$1", chat_id)
    return _row_to_dict(row, object_fields=("facts_json",))


async def upsert_conversation_memory(
    pool,
    chat_id: int,
    summary_text: str,
    facts_json: dict | None,
    summarized_until_message_id: int,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO conversation_memory (
            chat_id,
            summary_text,
            facts_json,
            summarized_until_message_id,
            updated_at
        )
        VALUES ($1, $2, $3::jsonb, $4, now())
        ON CONFLICT (chat_id) DO UPDATE
        SET summary_text=EXCLUDED.summary_text,
            facts_json=EXCLUDED.facts_json,
            summarized_until_message_id=GREATEST(
                conversation_memory.summarized_until_message_id,
                EXCLUDED.summarized_until_message_id
            ),
            updated_at=now()
        RETURNING *
        """,
        chat_id,
        summary_text or "",
        ensure_json_object(facts_json),
        summarized_until_message_id,
    )
    return _row_to_dict(row, object_fields=("facts_json",)) or {}


async def delete_conversation_memory(pool, chat_id: int) -> None:
    await pool.execute("DELETE FROM conversation_memory WHERE chat_id=$1", chat_id)


async def get_chat_messages_after(
    pool,
    chat_id: int,
    after_message_id: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT *
        FROM chat_messages
        WHERE chat_id=$1 AND id > $2
        ORDER BY id ASC
        LIMIT $3
        """,
        chat_id,
        after_message_id,
        limit,
    )
    return _rows_to_dicts(rows)


async def get_active_order_draft(pool, chat_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT *
        FROM order_drafts
        WHERE chat_id=$1 AND status IN ('collecting', 'confirming', 'rendering')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        chat_id,
    )
    return _row_to_dict(row, object_fields=("collected_params",))


async def get_rendered_order_draft(pool, chat_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT
            d.*,
            o.status AS order_status,
            o.details_json,
            o.render_paths,
            o.price
        FROM order_drafts d
        JOIN orders o ON o.request_id = d.rendered_order_id
        WHERE d.chat_id=$1
          AND d.status='rendered'
          AND d.rendered_order_id IS NOT NULL
          AND o.status NOT IN ('cancelled', 'completed')
        ORDER BY d.updated_at DESC
        LIMIT 1
        """,
        chat_id,
    )
    return _row_to_dict(
        row,
        object_fields=("collected_params", "details_json", "render_paths", "price"),
    )


async def upsert_order_draft(
    pool,
    chat_id: int,
    collected_params: dict | None,
    status: str = "collecting",
    request_id: str | None = None,
) -> dict[str, Any]:
    status = status if status in {"collecting", "confirming", "rendering"} else "collecting"
    row = await pool.fetchrow(
        """
        WITH current AS (
            SELECT request_id
            FROM order_drafts
            WHERE chat_id=$1 AND status IN ('collecting', 'confirming', 'rendering')
            ORDER BY updated_at DESC
            LIMIT 1
        ),
        updated AS (
            UPDATE order_drafts
            SET status=$2,
                collected_params=$3::jsonb,
                updated_at=now()
            WHERE request_id = (SELECT request_id FROM current)
            RETURNING *
        ),
        inserted AS (
            INSERT INTO order_drafts (request_id, chat_id, status, collected_params)
            SELECT $4, $1, $2, $3::jsonb
            WHERE NOT EXISTS (SELECT 1 FROM updated)
            RETURNING *
        )
        SELECT * FROM updated
        UNION ALL
        SELECT * FROM inserted
        LIMIT 1
        """,
        chat_id,
        status,
        ensure_json_object(collected_params),
        request_id or str(uuid4()),
    )
    return _row_to_dict(row, object_fields=("collected_params",)) or {}


async def abandon_current_order_draft(pool, chat_id: int, cancel_order: bool = True) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        """
        SELECT request_id, rendered_order_id
        FROM order_drafts
        WHERE chat_id=$1
          AND status IN ('collecting', 'confirming', 'rendering', 'rendered')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        chat_id,
    )
    if row is None:
        return None
    draft = dict(row)
    await pool.execute(
        """
        UPDATE order_drafts
        SET status='abandoned',
            updated_at=now()
        WHERE request_id=$1
        """,
        draft["request_id"],
    )
    if cancel_order and draft.get("rendered_order_id"):
        await pool.execute(
            """
            UPDATE orders
            SET status='cancelled',
                updated_at=now()
            WHERE request_id=$1
              AND status NOT IN ('cancelled', 'completed')
            """,
            draft["rendered_order_id"],
        )
    return draft


async def mark_active_order_draft_rendered(pool, chat_id: int, order_request_id: str) -> None:
    await pool.execute(
        """
        UPDATE order_drafts
        SET status='rendered',
            rendered_order_id=$2,
            updated_at=now()
        WHERE request_id = (
            SELECT request_id
            FROM order_drafts
            WHERE chat_id=$1 AND status IN ('collecting', 'confirming', 'rendering')
            ORDER BY updated_at DESC
            LIMIT 1
        )
        """,
        chat_id,
        order_request_id,
    )


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
        ensure_json_object(details_json),
        ensure_json_object(render_paths),
        ensure_json_object(price),
    )
    return _row_to_dict(row, object_fields=("details_json", "render_paths", "price")) or {}


async def get_order(pool, request_id: str) -> dict[str, Any] | None:
    return _row_to_dict(
        await pool.fetchrow("SELECT * FROM orders WHERE request_id=$1", request_id),
        object_fields=("details_json", "render_paths", "price"),
    )


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
    return _rows_to_dicts(rows, object_fields=("details_json", "render_paths", "price"))


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
    return _row_to_dict(row, object_fields=("details_json", "render_paths", "price")) or {}


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
    return _rows_to_dicts(
        await pool.fetch("SELECT * FROM prices ORDER BY category, id"),
        object_fields=("metadata",),
    )


async def update_price(pool, price_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {"name", "category", "amount", "currency", "metadata"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    if not updates:
        row = await pool.fetchrow("SELECT * FROM prices WHERE id=$1", price_id)
        if row is None:
            raise ValueError(f"Price not found: {price_id}")
        return _row_to_dict(row, object_fields=("metadata",)) or {}
    values: list[Any] = []
    fragments: list[str] = []
    for key, value in updates.items():
        values.append(ensure_json_object(value) if key == "metadata" else value)
        cast = "::jsonb" if key == "metadata" else ""
        fragments.append(f"{key}=${len(values) + 1}{cast}")
    row = await pool.fetchrow(
        f"UPDATE prices SET {', '.join(fragments)}, updated_at=now() WHERE id=$1 RETURNING *",
        price_id,
        *values,
    )
    if row is None:
        raise ValueError(f"Price not found: {price_id}")
    return _row_to_dict(row, object_fields=("metadata",)) or {}


async def seed_default_prices(pool) -> None:
    from src.engine.pricing_cache import DEFAULT_PRICES

    for item in DEFAULT_PRICES.values():
        await pool.execute(
            """
            INSERT INTO prices (id, name, category, amount, currency, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT DO NOTHING
            """,
            item["id"],
            item["name"],
            item["category"],
            item["amount"],
            item["currency"],
            _json(item.get("metadata")),
        )


async def get_materials(pool) -> list[dict[str, Any]]:
    return _rows_to_dicts(
        await pool.fetch("SELECT * FROM materials ORDER BY kind, id"),
        object_fields=("metadata",),
        array_fields=("color",),
    )


async def update_material(pool, material_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {"kind", "name", "color", "roughness", "metadata", "price_modifier"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    values: list[Any] = []
    fragments: list[str] = []
    for key, value in updates.items():
        if key == "metadata":
            values.append(ensure_json_object(value))
        elif key == "color":
            values.append(ensure_json_array(value))
        else:
            values.append(value)
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
    return _row_to_dict(row, object_fields=("metadata",), array_fields=("color",)) or {}


async def seed_default_materials(pool) -> None:
    from src.utils.config_manager import config

    for kind, db_kind in (("frame_colors", "frame"), ("glass_types", "glass")):
        for material_id, data in config.get_all_materials(kind).items():
            price_modifier = 1.0
            if db_kind == "frame" and str(material_id) not in {"1", "3"}:
                price_modifier = 1.04
            await pool.execute(
                """
                INSERT INTO materials (id, kind, name, color, roughness, metadata, price_modifier)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7)
                ON CONFLICT DO NOTHING
                """,
                f"{db_kind}_{material_id}",
                db_kind,
                data.get("name", material_id),
                _json(data.get("color")),
                data.get("roughness"),
                _json({"source_id": material_id}),
                price_modifier,
            )


async def get_dashboard_stats(pool, days: int = 30) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        SELECT
            count(*)::int AS total_orders,
            COALESCE(sum((price->>'total_price')::numeric), 0)::float AS total_revenue,
            count(*) FILTER (WHERE created_at::date = current_date)::int AS orders_today
        FROM orders
        WHERE created_at >= now() - ($1 * interval '1 day')
        """,
        days,
    )
    pending_measurements = await pool.fetchval(
        "SELECT count(*)::int FROM measurements WHERE status IN ('scheduled', 'confirmed')"
    )
    stats = dict(row) if row else {"total_orders": 0, "total_revenue": 0.0, "orders_today": 0}
    stats["pending_measurements"] = pending_measurements or 0
    return stats

async def create_gallery_work(
    pool,
    partition_type: str,
    glass_type: str | None,
    matting: str | None,
    title: str,
    notes: str,
    created_by_chat_id: int | None,
    shape: str | None = None,
) -> dict[str, Any]:
    work_id = uuid4().hex
    row = await pool.fetchrow(
        """
        INSERT INTO gallery_works (id, partition_type, glass_type, matting, title, notes, created_by_chat_id, shape)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        work_id,
        partition_type,
        glass_type,
        matting,
        title,
        notes,
        created_by_chat_id,
        shape,
    )
    return dict(row)

async def list_gallery_works(
    pool,
    partition_type: str | None = None,
    shape: str | None = None,
    published_only: bool = False,
) -> list[dict[str, Any]]:
    where_clauses = []
    args = []
    if partition_type:
        args.append(partition_type)
        where_clauses.append(f"w.partition_type = ${len(args)}")
    if shape:
        args.append(shape)
        where_clauses.append(f"w.shape = ${len(args)}")
    if published_only:
        where_clauses.append("w.is_published = true")
    
    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
    
    query = f"""
        SELECT w.*,
               count(p.id)::int as photo_count
        FROM gallery_works w
        LEFT JOIN gallery_photos p ON p.work_id = w.id
        {where_sql}
        GROUP BY w.id
        ORDER BY w.created_at DESC
    """
    rows = await pool.fetch(query, *args)
    return [dict(row) for row in rows]

async def get_gallery_work(pool, work_id: str) -> dict[str, Any] | None:
    work_row = await pool.fetchrow("SELECT * FROM gallery_works WHERE id=$1", work_id)
    if not work_row:
        return None
    work = dict(work_row)
    photo_rows = await pool.fetch(
        "SELECT * FROM gallery_photos WHERE work_id=$1 ORDER BY sort_order, id", work_id
    )
    work["photos"] = [dict(row) for row in photo_rows]
    return work

async def update_gallery_work(pool, work_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {"title", "notes", "partition_type", "shape", "glass_type", "matting", "is_published"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        existing = await pool.fetchrow("SELECT * FROM gallery_works WHERE id=$1", work_id)
        if not existing:
            raise ValueError(f"Gallery work not found: {work_id}")
        return dict(existing)
    
    set_sql = ", ".join(f"{key}=${idx}" for idx, key in enumerate(updates, start=2))
    values = list(updates.values())
    row = await pool.fetchrow(
        f"""
        UPDATE gallery_works
        SET {set_sql}, updated_at=now()
        WHERE id=$1
        RETURNING *
        """,
        work_id,
        *values,
    )
    if not row:
        raise ValueError(f"Gallery work not found: {work_id}")
    return dict(row)

async def delete_gallery_work(pool, work_id: str) -> list[dict[str, Any]]:
    # fetch photos to return so caller can unlink files
    photos = await list_photos_for_work(pool, work_id)
    row = await pool.fetchrow("DELETE FROM gallery_works WHERE id=$1 RETURNING id", work_id)
    if not row:
        raise ValueError(f"Gallery work not found: {work_id}")
    return photos

async def add_gallery_photo(
    pool,
    work_id: str,
    file_path: str,
    sort_order: int,
    width: int | None,
    height: int | None,
    size_bytes: int | None,
) -> dict[str, Any]:
    photo_id = uuid4().hex
    row = await pool.fetchrow(
        """
        INSERT INTO gallery_photos (id, work_id, file_path, sort_order, width, height, size_bytes)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        photo_id,
        work_id,
        file_path,
        sort_order,
        width,
        height,
        size_bytes,
    )
    return dict(row)

async def list_photos_for_work(pool, work_id: str) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT * FROM gallery_photos WHERE work_id=$1 ORDER BY sort_order, id", work_id
    )
    return [dict(row) for row in rows]

async def delete_gallery_photo(pool, photo_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow("DELETE FROM gallery_photos WHERE id=$1 RETURNING *", photo_id)
    return dict(row) if row else None

async def pick_random_gallery_works(
    pool,
    partition_type: str,
    shape: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    extra_where = ""
    args: list[Any] = [partition_type, limit]
    if shape:
        args.insert(1, shape)
        args[2] = limit
        extra_where = " AND w.shape = $2"
        limit_param = "$3"
    else:
        limit_param = "$2"
    query = f"""
        SELECT w.*
        FROM gallery_works w
        WHERE w.partition_type = $1{extra_where}
          AND w.is_published = true
          AND EXISTS (SELECT 1 FROM gallery_photos p WHERE p.work_id = w.id)
        ORDER BY random()
        LIMIT {limit_param}
    """
    rows = await pool.fetch(query, *args)
    works = [dict(row) for row in rows]
    if not works:
        return works
    
    work_ids = [w["id"] for w in works]
    photos_query = "SELECT * FROM gallery_photos WHERE work_id = ANY($1) ORDER BY sort_order, id"
    photo_rows = await pool.fetch(photos_query, work_ids)
    
    photos_by_work = {work_id: [] for work_id in work_ids}
    for pr in photo_rows:
        photos_by_work[pr["work_id"]].append(dict(pr))
        
    for w in works:
        w["photos"] = photos_by_work[w["id"]]
        
    return works
