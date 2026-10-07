from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Database, utcnow
from services.offers import active_markup, build_offer_text, link_preview, miniapp_deep_link
from utils.parser import OfferParseError, parse_offer_command
from utils.telegram_io import send_html

logger = logging.getLogger(__name__)


def _rights_to_dict(rights) -> dict:
    if rights is None:
        return {}
    if hasattr(rights, "to_dict"):
        return rights.to_dict()
    return {}


async def business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    connection = update.business_connection
    if not connection:
        return
    db: Database = context.application.bot_data["db"]
    await db.upsert_user(connection.user.id, connection.user.username, connection.user.first_name)
    await db.upsert_business_connection(
        connection_id=connection.id,
        owner_user_id=connection.user.id,
        active=connection.is_enabled,
        rights=_rights_to_dict(connection.rights),
    )
    logger.info(
        "%s connection_id=%s owner_id=%s",
        "BUSINESS CONNECTED" if connection.is_enabled else "BUSINESS DISCONNECTED",
        connection.id,
        connection.user.id,
    )


async def business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.business_message
    if not message or not message.text or not message.text.lstrip().lower().startswith(".buy"):
        return

    db: Database = context.application.bot_data["db"]
    settings = context.application.bot_data["settings"]
    connection_id = message.business_connection_id
    if not connection_id:
        return

    logger.info("BUY COMMAND RECEIVED chat_id=%s message_id=%s", message.chat_id, message.message_id)

    try:
        parsed = parse_offer_command(message.text, require_buy_prefix=True)
    except OfferParseError as exc:
        await send_html(
            context.bot,
            chat_id=message.chat_id,
            business_connection_id=connection_id,
            text=(
                f"❌ <b>{str(exc)}</b>\n\n"
                "Пример: <code>.buy https://t.me/nft/RareBird-3396 8000 звёзды</code>"
            ),
        )
        return

    owner_id = await db.get_business_owner(connection_id)
    if owner_id is None:
        try:
            connection = await context.bot.get_business_connection(connection_id)
            await db.upsert_user(connection.user.id, connection.user.username, connection.user.first_name)
            await db.upsert_business_connection(
                connection_id=connection.id,
                owner_user_id=connection.user.id,
                active=connection.is_enabled,
                rights=_rights_to_dict(connection.rights),
            )
            owner_id = connection.user.id if connection.is_enabled else None
        except Exception as exc:
            logger.exception("TELEGRAM API ERROR get_business_connection: %s", exc)

    if owner_id is None:
        await send_html(
            context.bot,
            chat_id=message.chat_id,
            business_connection_id=connection_id,
            text="❌ Business Connection неактивен. Переподключите бота в Telegram Business.",
        )
        return

    if message.from_user and message.from_user.id != owner_id:
        return

    logger.info("BUY COMMAND VALIDATED chat_id=%s", message.chat_id)
    now = utcnow()
    offer = await db.create_offer(
        creator_id=owner_id,
        creator_username=(message.from_user.username if message.from_user else None),
        business_connection_id=connection_id,
        chat_id=message.chat_id,
        source_message_id=message.message_id,
        source_type="BUSINESS",
        gift_url=parsed.gift_url,
        gift_slug=parsed.gift_slug,
        gift_name=parsed.gift_name,
        gift_number=parsed.gift_number,
        price=parsed.price,
        currency=parsed.currency,
        created_at=now,
        expires_at=now + timedelta(hours=settings.offer_lifetime_hours),
    )
    logger.info("OFFER CREATED offer_id=%s", offer.id)

    try:
        bot_username = context.bot.username or (await context.bot.get_me()).username
        app_url = miniapp_deep_link(
            bot_username=bot_username,
            offer_id=offer.id,
        )
        sent = await send_html(
            context.bot,
            chat_id=message.chat_id,
            business_connection_id=connection_id,
            text=build_offer_text(offer, premium=True),
            reply_markup=active_markup(offer, miniapp_url=app_url),
            link_preview_options=link_preview(),
        )
        await db.set_message_ids(offer.id, offer_message_id=sent.message_id)
        logger.info("OFFER MESSAGE SENT offer_id=%s message_id=%s", offer.id, sent.message_id)
    except Exception as exc:
        logger.exception("TELEGRAM API ERROR sending offer offer_id=%s: %s", offer.id, exc)
        await db.transition(
            offer.id,
            from_statuses=("ACTIVE",),
            to_status="CANCELLED",
            actor_id=owner_id,
            event_type="CANCELLED",
            metadata={"reason": "offer_send_failed"},
        )
        return

    try:
        await context.bot.delete_business_messages(
            business_connection_id=connection_id,
            message_ids=[message.message_id],
        )
        logger.info("SOURCE BUY MESSAGE DELETED offer_id=%s", offer.id)
    except Exception as exc:
        logger.warning("SOURCE MESSAGE DELETE FAILED offer_id=%s error=%s", offer.id, exc)
        try:
            await context.bot.send_message(
                chat_id=message.chat_id,
                business_connection_id=connection_id,
                text="⚠️ Оффер создан, но Telegram не разрешил удалить исходную команду.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def edited_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.edited_business_message
    if message and message.text and message.text.lstrip().lower().startswith(".buy"):
        logger.info("EDITED BUSINESS .buy ignored message_id=%s", message.message_id)


async def deleted_business_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deleted = update.deleted_business_messages
    if deleted:
        logger.info(
            "BUSINESS MESSAGES DELETED connection_id=%s chat_id=%s count=%s",
            deleted.business_connection_id,
            deleted.chat.id,
            len(deleted.message_ids),
        )
