from __future__ import annotations

import logging

from telegram import Bot

from database import Offer
from services.offers import build_terminal_text
from utils.telegram_io import edit_html

logger = logging.getLogger(__name__)


async def sync_offer_message(bot: Bot, offer: Offer, status: str | None = None) -> None:
    target_status = status or offer.status
    try:
        if offer.inline_message_id:
            await edit_html(
                bot,
                inline_message_id=offer.inline_message_id,
                text=build_terminal_text(offer, target_status),
                reply_markup=None,
            )
        elif offer.chat_id is not None and offer.offer_message_id is not None:
            await edit_html(
                bot,
                chat_id=offer.chat_id,
                message_id=offer.offer_message_id,
                business_connection_id=offer.business_connection_id,
                text=build_terminal_text(offer, target_status),
                reply_markup=None,
            )
    except Exception as exc:
        logger.warning("Could not sync Telegram offer message offer_id=%s status=%s: %s", offer.id, target_status, exc)
