from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from database import Database, Offer, utcnow
from services.offers import build_terminal_text
from utils.telegram_io import edit_html

logger = logging.getLogger(__name__)


async def _edit_original(context: ContextTypes.DEFAULT_TYPE, offer: Offer, status: str) -> None:
    try:
        if offer.inline_message_id:
            await edit_html(
                context.bot,
                inline_message_id=offer.inline_message_id,
                text=build_terminal_text(offer, status),
                reply_markup=None,
            )
        elif offer.chat_id is not None and offer.offer_message_id is not None:
            await edit_html(
                context.bot,
                chat_id=offer.chat_id,
                message_id=offer.offer_message_id,
                business_connection_id=offer.business_connection_id,
                text=build_terminal_text(offer, status),
                reply_markup=None,
            )
    except Exception as exc:
        logger.warning("Admin result could not edit original offer_id=%s: %s", offer.id, exc)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not isinstance(query.data, str):
        return

    action, _, offer_id = query.data.partition(":")
    if action not in {"ac", "ar"} or not offer_id:
        return

    settings = context.application.bot_data["settings"]
    if query.from_user.id != settings.admin_id:
        await query.answer("Нет доступа.", show_alert=True)
        return

    await query.answer()
    db: Database = context.application.bot_data["db"]
    offer = await db.get_offer(offer_id)
    if not offer:
        await query.answer("Оффер не найден.", show_alert=True)
        return

    if offer.status != "TRANSFER_PENDING":
        await query.answer("Эта проверка уже обработана.", show_alert=True)
        return

    now = utcnow()
    if action == "ac":
        changed = await db.transition(
            offer.id,
            from_statuses=("TRANSFER_PENDING",),
            to_status="TRANSFER_CONFIRMED",
            actor_id=query.from_user.id,
            event_type="TRANSFER_CONFIRMED",
            completed_at=now,
            metadata={"verification": "admin_manual"},
        )
        status = "TRANSFER_CONFIRMED"
        label = "✅ Передача подтверждена администратором."
    else:
        changed = await db.transition(
            offer.id,
            from_statuses=("TRANSFER_PENDING",),
            to_status="TRANSFER_REJECTED",
            actor_id=query.from_user.id,
            event_type="TRANSFER_REJECTED",
            completed_at=now,
            metadata={"verification": "admin_manual"},
        )
        status = "TRANSFER_REJECTED"
        label = "❌ Передача отклонена администратором."

    if not changed:
        await query.answer("Состояние уже изменилось.", show_alert=True)
        return

    logger.info("ADMIN %s offer_id=%s", status, changed.id)
    await query.edit_message_text(query.message.text_html + "\n\n" + label, parse_mode="HTML", reply_markup=None)
    await _edit_original(context, changed, status)
