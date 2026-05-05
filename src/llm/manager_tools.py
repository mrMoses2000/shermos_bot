"""Tool implementations for the manager NL flow.

Each tool takes a pg_pool + args dict and returns a Russian text response
ready to send via outbox to the manager.
"""
from __future__ import annotations

from typing import Any
from src.db import postgres


_STATUS_ICON = {
    "new": "🆕", "scheduled": "📅", "confirmed": "✅",
    "completed": "🎉", "cancelled": "❌",
}


async def list_recent_orders(pg_pool, args: dict[str, Any]) -> str:
    limit = max(1, min(50, int(args.get("limit", 10))))
    status_filter = args.get("status")
    orders = await postgres.list_orders(pg_pool, status=status_filter, limit=limit)
    if not orders:
        return "Заказов пока нет." if not status_filter else f"Заказов со статусом {status_filter} нет."
    lines = ["<b>Последние заказы:</b>", ""]
    for order in orders:
        created = order["created_at"].strftime("%d.%m %H:%M")
        price_obj = order.get("price") or {}
        price = (
            f"{price_obj['total_price']} {price_obj.get('currency','')}".strip()
            if isinstance(price_obj, dict) and price_obj.get("total_price")
            else "—"
        )
        short = str(order["request_id"]).split("-")[0]
        icon = _STATUS_ICON.get(order["status"], "•")
        lines.append(f"{icon} <b>{created}</b> · {order['chat_id']}")
        lines.append(f"   Сумма: {price} · <code>{short}</code>")
        lines.append("")
    return "\n".join(lines).rstrip()


async def list_upcoming_measurements(pg_pool, args: dict[str, Any]) -> str:
    limit = max(1, min(20, int(args.get("limit", 10))))
    rows = await postgres.list_measurements(pg_pool, upcoming_only=True, limit=limit)
    if not rows:
        return "Ближайших замеров нет."
    lines = ["<b>Ближайшие замеры:</b>", ""]
    for m in rows:
        when = m["scheduled_time"].strftime("%d.%m %H:%M")
        name = m.get("client_name") or "—"
        phone = m.get("client_phone") or "—"
        lines.append(f"📅 <b>{when}</b> · #{m['id']}")
        lines.append(f"   {name} · {phone} · {m.get('status','')}")
        lines.append("")
    return "\n".join(lines).rstrip()


async def get_order_details(pg_pool, args: dict[str, Any]) -> str:
    rid_input = str(args.get("request_id") or "").strip()
    if not rid_input:
        return "Не понял id заказа."
    # Allow both full UUID and first-8-char prefix; resolve via list_orders search.
    matched = await postgres.list_orders(pg_pool, search=rid_input, limit=2)
    if not matched:
        return f"Заказ <code>{rid_input}</code> не найден."
    if len(matched) > 1:
        listing = "\n".join(f"• <code>{o['request_id'].split('-')[0]}</code>" for o in matched)
        return f"Найдено несколько, уточни:\n{listing}"
    order = matched[0]
    price = order.get("price") or {}
    price_str = (
        f"{price['total_price']} {price.get('currency','')}".strip()
        if isinstance(price, dict) and price.get("total_price")
        else "—"
    )
    details = order.get("details_json") or {}
    shape = details.get("shape", "—")
    height = details.get("height", "—")
    return (
        f"<b>Заказ <code>{str(order['request_id']).split('-')[0]}</code></b>\n\n"
        f"Статус: {order['status']}\n"
        f"Создан: {order['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
        f"Клиент: <code>{order['chat_id']}</code>\n"
        f"Форма: {shape} · высота {height} м\n"
        f"Сумма: <b>{price_str}</b>"
    )


async def cancel_measurement(pg_pool, args: dict[str, Any]) -> str:
    try:
        mid = int(args.get("measurement_id"))
    except (TypeError, ValueError):
        return "Не понял номер замера."
    from src.engine.measurement_service import update_measurement_status
    try:
        m = await update_measurement_status(pg_pool, mid, "cancelled", reason="Отменён мастером")
    except ValueError as exc:
        return f"Не удалось отменить замер #{mid}: {exc}"
    when = m["scheduled_time"].strftime("%d.%m %H:%M")
    return f"❌ Замер #{mid} ({when}) отменён."


async def propose_reschedule(pg_pool, args: dict[str, Any]) -> str:
    from src.engine.measurement_service import propose_reschedule as _propose
    from src.config import settings

    try:
        mid = int(args.get("measurement_id"))
    except (TypeError, ValueError):
        return "Не понял номер замера."
    new_time = str(args.get("new_time") or "").strip()
    if not new_time:
        return "Не понял новое время — укажи в формате HH:MM."
    new_date = args.get("new_date")
    new_date = str(new_date).strip() if new_date else None
    reason = str(args.get("reason") or "").strip()

    try:
        m = await _propose(
            pg_pool,
            mid,
            new_date=new_date,
            new_time=new_time,
            timezone=settings.timezone,
            reason=reason,
        )
    except ValueError as exc:
        return f"Не получилось: {exc}"

    # Notify the client via outbox
    proposed = m["pending_reschedule_at"]
    proposed_str = proposed.strftime("%d.%m %H:%M")
    old_str = m["scheduled_time"].strftime("%d.%m %H:%M")
    client_chat_id = int(m["client_chat_id"])

    reason_block = f"\n\nПричина: {reason}" if reason else ""
    client_text = (
        f"Здравствуйте! Мастер не сможет приехать в <b>{old_str}</b>.{reason_block}\n\n"
        f"Можно перенести на <b>{proposed_str}</b>?\n"
        "Напишите «да», если подходит, или предложите другое удобное время."
    )

    await postgres.insert_outbound_event(
        pg_pool,
        chat_id=client_chat_id,
        channel="whatsapp",
        external_chat_id=f"{client_chat_id}@s.whatsapp.net",
        reply_text=client_text,
        bot_type="client",
        idempotency_key=f"reschedule_proposal:{mid}:{int(proposed.timestamp())}",
    )

    return (
        f"✅ Клиенту отправлено предложение перенести замер #{mid}\n"
        f"с <b>{old_str}</b> на <b>{proposed_str}</b>.\n"
        "Жду подтверждения от клиента."
    )


TOOLS = {
    "list_recent_orders": list_recent_orders,
    "list_upcoming_measurements": list_upcoming_measurements,
    "get_order_details": get_order_details,
    "cancel_measurement": cancel_measurement,
    "propose_reschedule": propose_reschedule,
}


async def dispatch(pg_pool, tool: str, args: dict[str, Any]) -> str | None:
    """Returns the response text, or None if the tool is unknown."""
    fn = TOOLS.get(tool)
    if not fn:
        return None
    return await fn(pg_pool, args)
