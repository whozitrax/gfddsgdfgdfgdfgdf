from __future__ import annotations

import logging

from telegram import Bot, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import BadRequest

from utils.emoji import plain_emoji_text

logger = logging.getLogger(__name__)


async def send_html(
    bot: Bot,
    *,
    chat_id: int,
    text: str,
    business_connection_id: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    link_preview_options: LinkPreviewOptions | None = None,
):
    kwargs = dict(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        link_preview_options=link_preview_options,
    )
    if business_connection_id:
        kwargs["business_connection_id"] = business_connection_id
    try:
        return await bot.send_message(**kwargs)
    except BadRequest as exc:
        # Custom emoji availability depends on Bot API context and bot owner's Premium state.
        # Retry with normal emoji without changing the rest of the message.
        logger.warning("send_html premium-emoji fallback: %s", exc)
        kwargs["text"] = plain_emoji_text(text)
        return await bot.send_message(**kwargs)


async def edit_html(
    bot: Bot,
    *,
    text: str,
    chat_id: int | None = None,
    message_id: int | None = None,
    inline_message_id: str | None = None,
    business_connection_id: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    link_preview_options: LinkPreviewOptions | None = None,
):
    kwargs = dict(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        link_preview_options=link_preview_options,
    )
    if inline_message_id:
        kwargs["inline_message_id"] = inline_message_id
    else:
        kwargs["chat_id"] = chat_id
        kwargs["message_id"] = message_id
        if business_connection_id:
            kwargs["business_connection_id"] = business_connection_id
    try:
        return await bot.edit_message_text(**kwargs)
    except BadRequest as exc:
        logger.warning("edit_html premium-emoji fallback: %s", exc)
        kwargs["text"] = plain_emoji_text(text)
        return await bot.edit_message_text(**kwargs)
