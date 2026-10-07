from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from database import Database, Offer, utcnow
from services.message_sync import sync_offer_message

logger = logging.getLogger(__name__)


async def _load_and_bind_inline_id(update: Update, context: ContextTypes.DEFAULT_TYPE, offer_id: str) -> Offer | None:
    db: Database = context.application.bot_data["db"]
    offer = await db.get_offer(offer_id)
    query = update.callback_query
    if offer and query and query.inline_message_id and not offer.inline_message_id:
        await db.set_message_ids(offer.id, inline_message_id=query.inline_message_id)
        offer = await db.get_offer(offer.id)
    return offer


def _can_act_as_seller(offer: Offer, user_id: int) -> bool:
    if offer.source_type == "BUSINESS":
        return offer.chat_id == user_id
    return user_id != offer.creator_id


async def offer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not isinstance(query.data, str):
        return

    action, _, offer_id = query.data.partition(":")
    if action != "od" or not offer_id:
        return

    db: Database = context.application.bot_data["db"]
    offer = await _load_and_bind_inline_id(update, context, offer_id)
    if not offer:
        await query.answer("Оффер не найден.", show_alert=True)
        return

    if offer.status == "ACTIVE" and offer.expires_at <= utcnow():
        expired = await db.transition(
            offer.id,
            from_statuses=("ACTIVE",),
            to_status="EXPIRED",
            actor_id=None,
            event_type="EXPIRED",
        )
        if expired:
            await sync_offer_message(context.bot, expired)
        await query.answer("⏱ Срок действия этого оффера истёк.", show_alert=True)
        return

    actor = query.from_user
    await db.upsert_user(actor.id, actor.username, actor.first_name)

    if offer.status != "ACTIVE":
        await query.answer("Этот оффер уже обработан.", show_alert=True)
        return
    if actor.id == offer.creator_id:
        await query.answer("❌ Нельзя отклонить собственный оффер.", show_alert=True)
        return
    if not _can_act_as_seller(offer, actor.id):
        await query.answer("Эта кнопка предназначена получателю оффера.", show_alert=True)
        return

    changed = await db.transition(
        offer.id,
        from_statuses=("ACTIVE",),
        to_status="DECLINED",
        actor_id=actor.id,
        event_type="DECLINED",
        seller_id=actor.id,
        seller_username=actor.username,
        completed_at=utcnow(),
    )
    if not changed:
        await query.answer("Оффер уже обработан.", show_alert=True)
        return

    logger.info("OFFER DECLINED offer_id=%s seller_id=%s", changed.id, actor.id)
    await query.answer("Предложение отклонено.")
    await sync_offer_message(context.bot, changed)
