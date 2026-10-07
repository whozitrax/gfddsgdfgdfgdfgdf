from __future__ import annotations

import logging
from datetime import timedelta

from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Database, utcnow
from services.offers import active_markup, build_offer_text, link_preview, miniapp_deep_link
from utils.parser import OfferParseError, parse_offer_command

logger = logging.getLogger(__name__)


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not query:
        return

    if query.chat_type not in (None, "private"):
        await query.answer([], cache_time=0, is_personal=True)
        return

    try:
        parsed = parse_offer_command(query.query, require_buy_prefix=False)
    except OfferParseError:
        await query.answer([], cache_time=0, is_personal=True)
        return

    db: Database = context.application.bot_data["db"]
    settings = context.application.bot_data["settings"]
    user = query.from_user
    await db.upsert_user(user.id, user.username, user.first_name)

    now = utcnow()
    offer = await db.create_offer(
        creator_id=user.id,
        creator_username=user.username,
        business_connection_id=None,
        chat_id=None,
        source_message_id=None,
        source_type="INLINE",
        gift_url=parsed.gift_url,
        gift_slug=parsed.gift_slug,
        gift_name=parsed.gift_name,
        gift_number=parsed.gift_number,
        price=parsed.price,
        currency=parsed.currency,
        created_at=now,
        expires_at=now + timedelta(hours=settings.offer_lifetime_hours),
    )

    bot_username = context.bot.username or (await context.bot.get_me()).username
    app_url = miniapp_deep_link(
        bot_username=bot_username,
        offer_id=offer.id,
    )
    text = build_offer_text(offer, premium=False)
    result = InlineQueryResultArticle(
        id=offer.id,
        title=f"Оффер: {offer.gift_name} #{offer.gift_number}",
        description=f"{offer.price} {offer.currency} · 6 часов",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=link_preview(),
        ),
        reply_markup=active_markup(offer, miniapp_url=app_url),
    )
    await query.answer([result], cache_time=0, is_personal=True)


async def chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chosen = update.chosen_inline_result
    if not chosen or not chosen.inline_message_id:
        return
    db: Database = context.application.bot_data["db"]
    offer = await db.get_offer(chosen.result_id)
    if offer and offer.creator_id == chosen.from_user.id:
        await db.set_message_ids(offer.id, inline_message_id=chosen.inline_message_id)
        logger.info("INLINE OFFER SENT offer_id=%s", offer.id)
