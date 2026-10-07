from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from utils.emoji import ce, plain_emoji_text


def help_text(*, premium: bool = True) -> str:
    return (
        f"{ce('💎', premium=premium)} <b>GIFTRELAYER</b>\n"
        f"{ce('🎁', premium=premium)} Оффер на подарок\n\n"
        "✍️ <b>В чате:</b>\n"
        "<code>.buy https://t.me/nft/RareBird-3396 8000 звёзды</code>\n\n"
        f"{ce('⚡️', premium=premium)} <b>Или инлайн в любом личном чате:</b>\n"
        "<code>@ваш_бот https://t.me/nft/RareBird-3396 8000 звёзды</code>\n\n"
        f"{ce('⭐️', premium=premium)} Валюта: звёзды, Gram, руб, usdt\n"
        f"{ce('⏱', premium=premium)} Оффер живёт 6 часов\n"
        f"{ce('✔️', premium=premium)} Принять · {ce('❌', premium=premium)} Отклонить"
    )


async def _send(update: Update, context: ContextTypes.DEFAULT_TYPE, prefix: str | None = None) -> None:
    if not update.effective_message:
        return
    text = (prefix + "\n\n" if prefix else "") + help_text(premium=True)
    try:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        await update.effective_message.reply_text(plain_emoji_text(text), parse_mode=ParseMode.HTML)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, context)


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, context, "Формат: <code>.buy ссылка цена валюта</code>")
