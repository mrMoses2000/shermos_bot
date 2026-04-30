"""Main Redis worker pipeline for client and manager bots."""

from __future__ import annotations

import asyncio
from typing import Any

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.bot.keyboards import gallery_offer_keyboard, manager_measurement_keyboard, open_mini_app_keyboard, rate_render_keyboard
from pathlib import Path
from src.bot.telegram_sender import TelegramSender, telegram_sender
from src.bot.transcribe import TranscriptionError, extract_voice_file_id, transcribe_voice
from src.bot.whatsapp_sender import WhatsAppSender, manager_whatsapp_sender, whatsapp_sender
from src.config import settings
from src.db import postgres
from src.db.redis_client import RedisClient
from src.llm.actions_applier import apply_actions
from src.llm.actions_parser import parse_actions
from src.llm.conversation_memory import refresh_conversation_memory_if_needed
from src.llm.executor import call_llm
from src.llm.health_check import run_gemini_health_check
from src.llm.prompt_builder import build_prompt
from src.models import Job
from src.queue.outbox_dispatcher import run_outbox_dispatcher
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

CLIENT_QUEUE = "queue:incoming"
CLIENT_PROCESSING_QUEUE = "queue:processing:client"
CLIENT_DELAYED_QUEUE = "queue:delayed:incoming"
MANAGER_QUEUE = "queue:manager"
MANAGER_PROCESSING_QUEUE = "queue:processing:manager"
CLIENT_LOCK_TTL_SECONDS = max(360, settings.llm_timeout_seconds + 240)


def _lock_retry_delay(attempt: int) -> int:
    return min(2 ** min(max(attempt, 0), 4), 15)


async def _schedule_locked_client_job(redis_client: RedisClient, job: Job) -> None:
    next_job = job.model_copy(update={"attempt": job.attempt + 1})
    delay = _lock_retry_delay(job.attempt)
    await redis_client.schedule_job(CLIENT_DELAYED_QUEUE, next_job, delay)
    logger.info(
        "client_job_delayed_by_lock",
        extra={
            "chat_id": job.chat_id,
            "update_id": job.update_id,
            "attempt": job.attempt,
            "delay_seconds": delay,
        },
    )


async def _load_available_slots(pg_pool, days_ahead: int = 3) -> dict[str, list[str]]:
    """Load available measurement slots for the next N days."""
    from src.engine.measurement_service import get_available_slots

    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    slots = {}
    for i in range(days_ahead):
        day = today + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        try:
            day_slots = await get_available_slots(pg_pool, date_str, settings.timezone)
            slots[date_str] = day_slots
        except Exception:
            slots[date_str] = []
    return slots


async def _refresh_memory_best_effort(pg_pool, chat_id: int) -> None:
    try:
        await refresh_conversation_memory_if_needed(pg_pool, chat_id)
    except Exception as exc:
        logger.warning("conversation_memory_refresh_failed", extra={"chat_id": chat_id, "error": str(exc)})


async def _get_memory_best_effort(pg_pool, chat_id: int) -> dict[str, Any] | None:
    try:
        return await postgres.get_conversation_memory(pg_pool, chat_id)
    except Exception as exc:
        logger.warning("conversation_memory_load_failed", extra={"chat_id": chat_id, "error": str(exc)})
        return None


CLIENT_COMMANDS = {
    "/start": (
        "Здравствуйте! Я помогу рассчитать стеклянную перегородку Shermos.\n"
        "Опишите форму, размеры, тип стекла и цвет профиля. Например: "
        "прямая перегородка 3 на 2.6 м, черный профиль, прозрачное стекло."
    ),
    "/help": (
        "<b>Что я умею</b>\n"
        "1. Собрать параметры перегородки.\n"
        "2. Сделать 3D-рендер.\n"
        "3. Рассчитать ориентировочную стоимость.\n"
        "4. Записать на замер."
    ),
    "/examples": (
        "Примеры:\n"
        "• Прямая перегородка шириной 3 м, высота 2.7 м.\n"
        "• Г-образная 2.5 на 1.2 м, рифленое стекло.\n"
        "• Хочу замер завтра в 15:30."
    ),
}


async def _send_and_record(
    pg_pool,
    sender: TelegramSender | WhatsAppSender,
    token: str,
    chat_id: int | str,
    text: str,
    bot_type: str = "client",
    reply_markup: dict | None = None,
) -> None:
    channel = getattr(sender, "channel", "telegram")
    idempotency_key = str(uuid4()) if channel == "whatsapp" else None
    event_kwargs: dict[str, Any] = {}
    if channel != "telegram":
        event_kwargs = {
            "channel": channel,
            "external_chat_id": str(chat_id),
            "idempotency_key": idempotency_key,
        }

    event_id = await postgres.insert_outbound_event(
        pg_pool,
        chat_id=int(chat_id),
        reply_text=text,
        reply_markup=reply_markup,
        bot_type=bot_type,
        **event_kwargs,
    )
    if channel == "whatsapp":
        msg_id = await sender.send_message(
            token,
            chat_id,
            text,
            reply_markup=reply_markup,
            idempotency_key=idempotency_key,
        )
        await postgres.mark_outbound_sent(
            pg_pool,
            event_id,
            external_message_id=str(msg_id) if msg_id is not None else None,
        )
    else:
        msg_id = await sender.send_message(token, int(chat_id), text, reply_markup=reply_markup)
        await postgres.mark_outbound_sent(pg_pool, event_id, telegram_message_id=msg_id)


def _telegram_user(job: Job) -> tuple[str, str]:
    message = job.raw_update.get("message") or {}
    user = message.get("from") or {}
    return user.get("first_name", ""), user.get("username", "")


async def _handle_client_command(job: Job, pg_pool, sender: TelegramSender) -> bool:
    text = (job.text or "").split()[0].lower()
    if text == "/clear":
        await postgres.clear_chat_messages(pg_pool, job.chat_id)
        try:
            await postgres.delete_conversation_memory(pg_pool, job.chat_id)
        except Exception as exc:
            logger.warning("conversation_memory_delete_failed", extra={"chat_id": job.chat_id, "error": str(exc)})
        await postgres.abandon_current_order_draft(pg_pool, job.chat_id, cancel_order=True)
        await postgres.upsert_conversation_state(pg_pool, job.chat_id, "idle", None, {})
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            "История диалога очищена.",
        )
        return True
    if text in {"/cancel", "/cancel_order"}:
        await postgres.abandon_current_order_draft(pg_pool, job.chat_id, cancel_order=True)
        await postgres.upsert_conversation_state(pg_pool, job.chat_id, "idle", None, {})
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            "Текущий заказ отменён. Можно начать новый расчёт.",
        )
        return True
    if text == "/status":
        orders = await postgres.list_orders(pg_pool, search=str(job.chat_id), limit=5)
        if not orders:
            reply = "У вас пока нет расчетов."
        else:
            lines = ["<b>Последние расчеты:</b>"]
            for order in orders:
                price = order.get("price") or {}
                lines.append(
                    f"• <code>{order['request_id']}</code> — {order['status']}, "
                    f"{price.get('total_price', '—')} {price.get('currency', '')}"
                )
            reply = "\n".join(lines)
        await _send_and_record(pg_pool, sender, settings.telegram_bot_token, job.chat_id, reply)
        return True
    if text in CLIENT_COMMANDS:
        first_name, username = _telegram_user(job)
        await postgres.create_client(pg_pool, job.chat_id, first_name, username)
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            CLIENT_COMMANDS[text],
        )
        return True
    return False


async def _send_render_result(job: Job, pg_pool, sender: TelegramSender, action_result: dict[str, Any]) -> None:
    render_paths = action_result.get("render_paths")
    if not render_paths:
        return
    order = action_result.get("order") or {}
    price = action_result.get("price") or {}
    details = price.get("details") or {}
    paths = [render_paths[key] for key in sorted(render_paths.keys())]

    pt_names = {
        "fixed": "Стационарная",
        "sliding_2": "Раздвижная 2 створки",
        "sliding_3": "Раздвижная 3 створки",
        "sliding_4": "Раздвижная 4 створки",
    }
    pt = details.get("partition_type", "sliding_2")

    lines = ["<b>Рендер готов</b>"]
    lines.append(f"Заказ: <code>{order.get('request_id', '')}</code>")
    lines.append("")
    lines.append(f"Тип: {pt_names.get(pt, pt)}")
    lines.append(f"Площадь: {details.get('area_sq_m', '—')} м²")
    lines.append(f"Базовая ставка: {details.get('base_rate_per_sqm', '—')} $/м²")
    lines.append(f"Базовая стоимость: {details.get('base_price', '—')} $")

    matting_price = details.get("matting_price", 0)
    if matting_price:
        matting_names = {
            "matting_solid": "Сплошная матировка",
            "matting_stripes": "Матовые полосы",
            "matting_logo": "Матовый рисунок",
        }
        mat_name = matting_names.get(details.get("matting", ""), "Матировка")
        lines.append(f"{mat_name}: +{matting_price} $")

    pattern_price = details.get("complex_pattern_price", 0)
    if pattern_price:
        lines.append(f"Сложный рисунок: +{pattern_price} $")

    frame_surcharge = details.get("frame_surcharge", 0)
    if frame_surcharge:
        lines.append(f"Наценка за цвет рамки: +{frame_surcharge} $")

    handle_price = details.get("handle_price", 0)
    if handle_price:
        lines.append(f"Дверная ручка: +{handle_price} $")

    discount = details.get("volume_discount", 0)
    if discount:
        lines.append(f"Скидка за объём (>8 м²): -{discount} $")

    lines.append("")
    lines.append(f"<b>Итого: {price.get('total_price')} {price.get('currency', 'USD')}</b>")

    caption = "\n".join(lines)

    if len(paths) == 1:
        await sender.send_photo(settings.telegram_bot_token, job.chat_id, paths[0], caption=caption)
    else:
        await sender.send_media_group(settings.telegram_bot_token, job.chat_id, paths, caption=caption)
    collected = order.get("collected_params") or {}
    if isinstance(collected, str):
        import json as _json
        try:
            collected = _json.loads(collected)
        except Exception:
            collected = {}
    shape = collected.get("shape", "")
    await sender.send_message(
        settings.telegram_bot_token,
        job.chat_id,
        "Показать 3 реальные работы такого же типа? Это поможет представить результат.",
        reply_markup=gallery_offer_keyboard(order.get("request_id", ""), pt, shape),
    )


async def _resolve_voice_text(
    job: Job,
    pg_pool,
    sender: TelegramSender,
) -> bool:
    """Download and transcribe a voice/audio message, mutating job.text in place.

    Returns True when the job is ready to continue into the LLM pipeline,
    False when the message was rejected (user already notified, update marked).
    """
    file_id: str | None = None
    if job.channel == "whatsapp":
        if not job.media_path:
            await _send_and_record(
                pg_pool, sender, settings.telegram_bot_token, job.chat_id,
                "Не удалось получить голосовое сообщение. Отправьте, пожалуйста, текстом.",
            )
            await postgres.mark_update_status(pg_pool, job.update_id, "failed", "voice_no_media_path")
            return False
    else:
        file_id = extract_voice_file_id(job.raw_update)
        if not file_id:
            await _send_and_record(
                pg_pool, sender, settings.telegram_bot_token, job.chat_id,
                "Не удалось распознать голосовое сообщение. Отправьте, пожалуйста, текстом.",
            )
            await postgres.mark_update_status(pg_pool, job.update_id, "failed", "voice_no_file_id")
            return False

    if not settings.assemblyai_api_key:
        await _send_and_record(
            pg_pool, sender, settings.telegram_bot_token, job.chat_id,
            "Распознавание голосовых пока недоступно. Напишите, пожалуйста, текстом.",
        )
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", "assemblyai_not_configured")
        return False

    try:
        await sender.send_chat_action(settings.telegram_bot_token, job.chat_id, action="record_voice")
        if job.channel == "whatsapp":
            audio_bytes = await asyncio.to_thread(Path(job.media_path).read_bytes)
        else:
            file_info = await sender.get_file(settings.telegram_bot_token, file_id)
            audio_bytes = await sender.download_file(settings.telegram_bot_token, file_info["file_path"])
        transcript = await transcribe_voice(audio_bytes)
    except TranscriptionError as exc:
        logger.warning("voice_transcription_failed", extra={"chat_id": job.chat_id, "error": str(exc)})
        await _send_and_record(
            pg_pool, sender, settings.telegram_bot_token, job.chat_id,
            "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.",
        )
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", f"transcription: {exc}")
        return False
    except Exception as exc:
        logger.exception(
            "voice_download_failed", extra={"chat_id": job.chat_id, "error": str(exc)},
        )
        await _send_and_record(
            pg_pool, sender, settings.telegram_bot_token, job.chat_id,
            "Не удалось получить голосовое сообщение. Попробуйте ещё раз.",
        )
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", f"voice_download: {exc}")
        return False

    if not transcript:
        await _send_and_record(
            pg_pool, sender, settings.telegram_bot_token, job.chat_id,
            "Голосовое сообщение не распознано (тишина?). Попробуйте ещё раз.",
        )
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", "empty_transcript")
        return False

    # Replace the job text: Pydantic models are frozen-ish, so update attr via __dict__.
    job.text = transcript
    job.msg_type = "text"
    return True


async def _send_gallery_works(job: Job, pg_pool, sender: TelegramSender, order_id: str, partition_type: str, shape: str = "") -> None:
    works = await postgres.pick_random_gallery_works(pg_pool, partition_type, shape=shape or None, limit=3)
    if not works:
        await sender.send_message(
            settings.telegram_bot_token, job.chat_id,
            "Скоро пополним базу реальными фотографиями этого типа.",
        )
    else:
        for work in works:
            photos = work.get("photos") or []
            paths = [str(Path(settings.gallery_dir) / p["file_path"]) for p in photos]
            caption = work.get("title") or "Реальная работа"
            if len(paths) >= 2:
                await sender.send_media_group(settings.telegram_bot_token, job.chat_id, paths, caption=caption)
            elif len(paths) == 1:
                await sender.send_photo(settings.telegram_bot_token, job.chat_id, paths[0], caption=caption)
    
    await sender.send_message(
        settings.telegram_bot_token, job.chat_id,
        "Оцените, пожалуйста, рендер:",
        reply_markup=rate_render_keyboard(order_id),
    )

async def _handle_client_callback(job: Job, pg_pool, sender: TelegramSender) -> bool:
    if not job.callback_data:
        return False
        
    parts = job.callback_data.split(":")
    action = parts[0]
    
    if action == "rate_render":
        order_id = parts[1]
        score = parts[2]
        await postgres.insert_chat_message(pg_pool, job.chat_id, "user", f"Оценка рендера {order_id}: {score}")
        return True
        
    if action == "gallery_show":
        order_id = parts[1]
        partition_type = parts[2] if len(parts) > 2 else "sliding_2"
        shape = parts[3] if len(parts) > 3 else ""
        allowed_types = {"fixed", "sliding_2", "sliding_3", "sliding_4"}
        pt = partition_type if partition_type in allowed_types else "sliding_2"
        await _send_gallery_works(job, pg_pool, sender, order_id, pt, shape)
        return True
        
    if action == "gallery_skip":
        order_id = parts[1]
        await sender.send_message(
            settings.telegram_bot_token, job.chat_id,
            "Оцените, пожалуйста, рендер:",
            reply_markup=rate_render_keyboard(order_id),
        )
        return True
        
    return False

async def process_client_job(
    job: Job,
    pg_pool,
    redis_client: RedisClient,
    sender: TelegramSender = telegram_sender,
) -> None:
    if job.channel == "whatsapp":
        sender = whatsapp_sender

    locked = await redis_client.acquire_user_lock(job.chat_id, ttl=CLIENT_LOCK_TTL_SECONDS)
    if not locked:
        await _schedule_locked_client_job(redis_client, job)
        return

    try:
        existing_status = await postgres.get_update_status(pg_pool, job.update_id)
        if existing_status in ("completed", "failed"):
            logger.info("skipping_already_processed", extra={"update_id": job.update_id, "status": existing_status})
            return
        await postgres.mark_update_status(pg_pool, job.update_id, "processing")
        if settings.send_typing_indicator:
            await sender.send_chat_action(settings.telegram_bot_token, job.chat_id)

        if job.msg_type == "callback_query" and await _handle_client_callback(job, pg_pool, sender):
            await postgres.mark_update_status(pg_pool, job.update_id, "completed")
            return

        if job.msg_type == "command" and await _handle_client_command(job, pg_pool, sender):
            await postgres.mark_update_status(pg_pool, job.update_id, "completed")
            return

        if job.msg_type == "voice":
            ok = await _resolve_voice_text(job, pg_pool, sender)
            if not ok:
                return

        first_name, username = _telegram_user(job)
        client = await postgres.get_client_by_chat_id(pg_pool, job.chat_id)
        if not client:
            client = await postgres.create_client(pg_pool, job.chat_id, first_name, username)
        state = await postgres.get_conversation_state(pg_pool, job.chat_id)
        history = await postgres.get_chat_messages(pg_pool, job.chat_id, settings.max_context_messages)
        memory = await _get_memory_best_effort(pg_pool, job.chat_id)

        # Load available measurement slots for the next 3 days
        available_slots = await _load_available_slots(pg_pool)

        prompt = build_prompt(
            job.text,
            client,
            state,
            history,
            available_slots=available_slots,
            conversation_memory=memory,
        )
        raw_llm = await call_llm(prompt)
        parsed = parse_actions(raw_llm)
        action_result = await apply_actions(parsed, job.chat_id, client, state, pg_pool, redis_client, settings)

        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            parsed.reply_text,
        )
        await _send_render_result(job, pg_pool, sender, action_result)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "user", job.text)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "assistant", parsed.reply_text)
        await _refresh_memory_best_effort(pg_pool, job.chat_id)
        await postgres.mark_update_status(pg_pool, job.update_id, "completed")
    except ValueError as exc:
        logger.info("client_job_validation_failed", extra={"update_id": job.update_id, "error": str(exc)})
        await _send_and_record(
            pg_pool,
            sender,
            settings.telegram_bot_token,
            job.chat_id,
            str(exc),
        )
        await postgres.insert_chat_message(pg_pool, job.chat_id, "user", job.text)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "assistant", str(exc))
        await _refresh_memory_best_effort(pg_pool, job.chat_id)
        await postgres.mark_update_status(pg_pool, job.update_id, "completed")
    except TimeoutError as exc:
        timeout_reply = (
            "Запрос занял слишком много времени. Я сохранил ваше сообщение. "
            "Напишите «продолжи», и я продолжу с него."
        )
        await _send_and_record(pg_pool, sender, settings.telegram_bot_token, job.chat_id, timeout_reply)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "user", job.text)
        await postgres.insert_chat_message(pg_pool, job.chat_id, "assistant", timeout_reply)
        await _refresh_memory_best_effort(pg_pool, job.chat_id)
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", str(exc))
    except Exception as exc:
        logger.exception("client_job_failed", extra={"update_id": job.update_id, "error": str(exc)})
        try:
            await _send_and_record(
                pg_pool,
                sender,
                settings.telegram_bot_token,
                job.chat_id,
                "Произошла ошибка. Попробуйте еще раз или напишите менеджеру.",
            )
        finally:
            await postgres.mark_update_status(pg_pool, job.update_id, "failed", str(exc))
    finally:
        await redis_client.release_user_lock(job.chat_id)


async def pool_fetchrow_safe(pg_pool, measurement_id: int) -> dict | None:
    row = await pg_pool.fetchrow("SELECT * FROM measurements WHERE id=$1", measurement_id)
    return dict(row) if row else None


async def _handle_measurement_callback(
    text: str,
    job: Job,
    pg_pool,
    sender: TelegramSender,
) -> None:
    """Handle meas_confirm:{id} and meas_reject:{id} callbacks from manager."""
    from src.engine.measurement_service import update_measurement_status

    parts = text.split(":")
    action = parts[0]  # meas_confirm or meas_reject
    meas_id = int(parts[1])
    new_status = "confirmed" if action == "meas_confirm" else "rejected"

    try:
        measurement = await update_measurement_status(
            pg_pool, meas_id, new_status, manager_chat_id=job.chat_id
        )
    except ValueError as exc:
        if action == "meas_reject":
            current = await pool_fetchrow_safe(pg_pool, meas_id)
            if current and current.get("status") == "confirmed":
                try:
                    measurement = await update_measurement_status(
                        pg_pool,
                        meas_id,
                        "cancelled",
                        manager_chat_id=job.chat_id,
                        reason="Мастер отменил ранее подтверждённый замер",
                    )
                    new_status = "cancelled"
                except ValueError as cancel_exc:
                    await _send_and_record(
                        pg_pool, sender, settings.manager_bot_token, job.chat_id,
                        f"Ошибка: {cancel_exc}", bot_type="manager",
                    )
                    return
            else:
                await _send_and_record(
                    pg_pool, sender, settings.manager_bot_token, job.chat_id,
                    f"Ошибка: {exc}", bot_type="manager",
                )
                return
        else:
            await _send_and_record(
                pg_pool, sender, settings.manager_bot_token, job.chat_id,
                f"Ошибка: {exc}", bot_type="manager",
            )
            return

    m_time = measurement["scheduled_time"].strftime("%d.%m.%Y %H:%M")
    status_text = {
        "confirmed": "подтверждён",
        "rejected": "отклонён",
        "cancelled": "отменён",
    }.get(new_status, new_status)

    # Notify manager
    manager_text = f"Замер #{meas_id} ({m_time}) — <b>{status_text}</b>."
    if new_status in {"rejected", "cancelled"}:
        await postgres.upsert_conversation_state(
            pg_pool,
            job.chat_id,
            "scheduling",
            f"measurement_alt:{meas_id}",
            {"measurement_id": meas_id},
        )
        manager_text += (
            "\n\nНапишите удобный день и время, например: <b>завтра 11:00</b>. "
            "Я сохраню это как открытый слот для замеров."
        )

    await _send_and_record(
        pg_pool, sender, settings.manager_bot_token, job.chat_id,
        manager_text,
        bot_type="manager",
    )

    # Notify CLIENT about the decision
    client_chat_id = measurement["client_chat_id"]
    if new_status == "confirmed":
        client_msg = (
            f"<b>Ваш замер подтверждён!</b>\n\n"
            f"Дата: <b>{m_time}</b>\n"
            f"Адрес: {measurement.get('address', '—')}\n\n"
            f"Мастер приедет в указанное время. "
            f"Если нужно перенести — напишите нам."
        )
    else:
        client_msg = (
            f"К сожалению, замер на <b>{m_time}</b> не может быть проведён.\n\n"
            f"Пожалуйста, выберите другое время для записи."
        )

    await _send_and_record(
        pg_pool, sender, settings.telegram_bot_token, client_chat_id,
        client_msg, bot_type="client",
    )


async def _handle_manager_slot_proposal(
    text: str,
    job: Job,
    pg_pool,
    sender: TelegramSender,
) -> bool:
    """Handle manager free-text alternative slot after rejecting/cancelling a measurement."""
    from src.engine.measurement_service import parse_slot_proposal, upsert_measurement_slot

    parsed = parse_slot_proposal(text, settings.timezone)
    if not parsed:
        return False

    state = await postgres.get_conversation_state(pg_pool, job.chat_id)
    if not state or state.get("mode") != "scheduling" or not str(state.get("step") or "").startswith("measurement_alt:"):
        return False

    date, time = parsed
    try:
        slot = await upsert_measurement_slot(
            pg_pool,
            date,
            time,
            settings.timezone,
            manager_chat_id=job.chat_id,
        )
    except ValueError as exc:
        await _send_and_record(
            pg_pool, sender, settings.manager_bot_token, job.chat_id,
            f"Не могу сохранить слот: {exc}",
            bot_type="manager",
        )
        return True

    await postgres.upsert_conversation_state(pg_pool, job.chat_id, "idle", None, {})
    slot_time = slot["slot_start"].strftime("%d.%m.%Y %H:%M")
    await _send_and_record(
        pg_pool, sender, settings.manager_bot_token, job.chat_id,
        f"Открытый слот сохранён: <b>{slot_time}</b>.",
        bot_type="manager",
    )
    return True


async def _notify_auto_confirmed_measurements(pg_pool, sender: TelegramSender, measurements: list[dict]) -> None:
    for measurement in measurements:
        m_time = measurement["scheduled_time"].strftime("%d.%m.%Y %H:%M")
        
        client_chat_id = measurement["client_chat_id"]
        last_event = await postgres.get_last_inbound_event(pg_pool, client_chat_id)
        is_whatsapp = last_event and last_event.get("channel") == "whatsapp"
        client_sender = whatsapp_sender if is_whatsapp else sender
        external_chat_id = last_event.get("external_chat_id") if is_whatsapp else client_chat_id

        try:
            await _send_and_record(
                pg_pool,
                client_sender,
                settings.telegram_bot_token if not is_whatsapp else "",
                external_chat_id,
                (
                    "<b>Ваш замер автоматически подтверждён.</b>\n\n"
                    f"Дата: <b>{m_time}</b>\n"
                    f"Адрес: {measurement.get('address', '—')}\n\n"
                    "Мастер не отклонил запись в течение 15 минут, поэтому время закреплено."
                ),
                bot_type="client",
            )
        except Exception as exc:
            logger.warning("auto_confirm_client_notify_failed", extra={"chat_id": client_chat_id, "error": str(exc)})

        for manager_chat_id in settings.manager_chat_ids_list:
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                manager_chat_id,
                f"Замер #{measurement['id']} на <b>{m_time}</b> автоматически подтверждён.",
                bot_type="manager",
                reply_markup=manager_measurement_keyboard(int(measurement["id"])),
            )
        for manager_phone in settings.manager_whatsapp_numbers_list:
            try:
                await _send_and_record(
                    pg_pool,
                    manager_whatsapp_sender,
                    "",
                    manager_phone,
                    f"Замер #{measurement['id']} на <b>{m_time}</b> автоматически подтверждён.",
                    bot_type="manager",
                    reply_markup=manager_measurement_keyboard(int(measurement["id"])),
                )
            except Exception as exc:
                logger.warning(
                    "manager_whatsapp_auto_confirm_notify_failed",
                    extra={"phone": manager_phone, "error": str(exc)},
                )


async def _measurement_auto_confirm_loop(pg_pool, sender: TelegramSender, interval_seconds: int = 60) -> None:
    from src.engine.measurement_service import auto_confirm_due_measurements

    while True:
        try:
            measurements = await auto_confirm_due_measurements(pg_pool)
            if measurements:
                await _notify_auto_confirmed_measurements(pg_pool, sender, measurements)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("measurement_auto_confirm_error", extra={"error": str(exc)})
        await asyncio.sleep(interval_seconds)


async def process_manager_job(
    job: Job,
    pg_pool,
    redis_client: RedisClient,
    sender: TelegramSender = telegram_sender,
) -> None:
    if job.channel == "whatsapp":
        sender = manager_whatsapp_sender

    try:
        existing_status = await postgres.get_update_status(pg_pool, job.update_id)
        if existing_status in ("completed", "failed"):
            logger.info("skipping_already_processed", extra={"update_id": job.update_id, "status": existing_status})
            return
        await postgres.mark_update_status(pg_pool, job.update_id, "processing")
        text = (job.text or job.callback_data or "").strip()
        if text.startswith("/start") or text.startswith("/health"):
            reply_markup = open_mini_app_keyboard(settings.mini_app_url) if settings.mini_app_url else None
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                "Shermos manager bot работает.",
                bot_type="manager",
                reply_markup=reply_markup,
            )
        elif text.startswith("/orders"):
            orders = await postgres.list_orders(pg_pool, limit=10)
            lines = ["<b>Последние заказы:</b>"]
            for order in orders:
                lines.append(f"• <code>{order['request_id']}</code> — {order['status']}")
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                "\n".join(lines) if orders else "Заказов пока нет.",
                bot_type="manager",
            )
        elif text.startswith("order_status:"):
            _prefix, order_id, status = text.split(":", 2)
            await postgres.update_order_status(pg_pool, order_id, status)
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                f"Статус заказа <code>{order_id}</code> обновлен: {status}",
                bot_type="manager",
            )
        elif text.startswith("meas_confirm:") or text.startswith("meas_reject:"):
            await _handle_measurement_callback(text, job, pg_pool, sender)
        elif text.startswith("meas_call:"):
            meas_id = int(text.split(":")[1])
            meas = await pool_fetchrow_safe(pg_pool, meas_id)
            phone = meas.get("client_phone", "") if meas else ""
            reply = f"Телефон клиента: {phone}" if phone else "Телефон не указан."
            await _send_and_record(pg_pool, sender, settings.manager_bot_token, job.chat_id, reply, bot_type="manager")
        elif text.startswith("/measurements"):
            measurements = await postgres.list_measurements(pg_pool, upcoming_only=True, limit=10)
            lines = ["<b>Ближайшие замеры:</b>"]
            for m in measurements:
                t = m["scheduled_time"].strftime("%d.%m %H:%M")
                lines.append(f"• #{m['id']} {t} — {m.get('client_name', '—')} ({m['status']})")
            await _send_and_record(
                pg_pool, sender, settings.manager_bot_token, job.chat_id,
                "\n".join(lines) if measurements else "Замеров пока нет.",
                bot_type="manager",
            )
        elif await _handle_manager_slot_proposal(text, job, pg_pool, sender):
            pass
        else:
            await _send_and_record(
                pg_pool,
                sender,
                settings.manager_bot_token,
                job.chat_id,
                "Команды: /orders, /health",
                bot_type="manager",
            )
        await postgres.mark_update_status(pg_pool, job.update_id, "completed")
    except Exception as exc:
        logger.exception("manager_job_failed", extra={"update_id": job.update_id, "error": str(exc)})
        await postgres.mark_update_status(pg_pool, job.update_id, "failed", str(exc))


async def _client_loop(pg_pool, redis_client: RedisClient, sender: TelegramSender) -> None:
    while True:
        try:
            moved = await redis_client.move_due_jobs(CLIENT_DELAYED_QUEUE, CLIENT_QUEUE, limit=100)
            if moved:
                logger.info("client_delayed_jobs_requeued", extra={"count": moved})
            job = await redis_client.dequeue_job_safe(CLIENT_QUEUE, CLIENT_PROCESSING_QUEUE, timeout=5)
            if job is not None:
                try:
                    await process_client_job(job, pg_pool, redis_client, sender)
                finally:
                    await redis_client.ack_job(CLIENT_PROCESSING_QUEUE, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("client_loop_error", extra={"error": str(exc)})
            await asyncio.sleep(5)


async def _manager_loop(pg_pool, redis_client: RedisClient, sender: TelegramSender) -> None:
    while True:
        try:
            job = await redis_client.dequeue_job_safe(MANAGER_QUEUE, MANAGER_PROCESSING_QUEUE, timeout=5)
            if job is not None:
                try:
                    await process_manager_job(job, pg_pool, redis_client, sender)
                finally:
                    await redis_client.ack_job(MANAGER_PROCESSING_QUEUE, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("manager_loop_error", extra={"error": str(exc)})
            await asyncio.sleep(5)


async def run_worker() -> None:
    pg_pool = await postgres.create_pool(settings)
    await postgres.run_migrations(pg_pool)
    await postgres.seed_default_prices(pg_pool)
    await postgres.seed_default_materials(pg_pool)
    redis_client = RedisClient(settings.redis_url)
    await redis_client.connect()
    await telegram_sender.start()
    await whatsapp_sender.start()
    await manager_whatsapp_sender.start()
    recovered = await redis_client.recover_stuck_jobs(CLIENT_PROCESSING_QUEUE, CLIENT_QUEUE)
    if recovered:
        logger.info("recovered_stuck_jobs", extra={"count": recovered, "queue": "client"})
    recovered_mgr = await redis_client.recover_stuck_jobs(MANAGER_PROCESSING_QUEUE, MANAGER_QUEUE)
    if recovered_mgr:
        logger.info("recovered_stuck_jobs", extra={"count": recovered_mgr, "queue": "manager"})
    tasks = [
        asyncio.create_task(_client_loop(pg_pool, redis_client, telegram_sender)),
        asyncio.create_task(_manager_loop(pg_pool, redis_client, telegram_sender)),
        asyncio.create_task(run_outbox_dispatcher(pg_pool, telegram_sender)),
        asyncio.create_task(run_gemini_health_check()),
        asyncio.create_task(_measurement_auto_confirm_loop(pg_pool, telegram_sender)),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await redis_client.close()
        await telegram_sender.close()
        await whatsapp_sender.close()
        await manager_whatsapp_sender.close()
        await postgres.close_pool(pg_pool)
