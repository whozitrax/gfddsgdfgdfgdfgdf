from __future__ import annotations

from html import escape

from telegram import Bot
from telegram.constants import ParseMode

from database import Offer
from services.offers import CURRENCY_LABELS, admin_markup, display_gift, format_price
from utils.emoji import ce, plain_emoji_text


def _user_label(username: str | None, user_id: int | None) -> str:
    if user_id is None:
        return "неизвестно"
    uname = f"@{escape(username)}\n" if username else ""
    return f"{uname}ID: <code>{user_id}</code>"


def build_admin_report(offer: Offer, check_text: str, *, premium: bool = True) -> str:
    price = format_price(offer.price)
    currency = CURRENCY_LABELS.get(offer.currency, offer.currency)
    return (
        f"{ce('💎', premium=premium)} <b>GIFTRELAYER — ОТЧЁТ</b>\n\n"
        f"{ce('🎁', premium=premium)} <b>Подарок:</b> {escape(display_gift(offer))}\n"
        f"🔗 {escape(offer.gift_url)}\n\n"
        f"{ce('⭐️', premium=premium)} <b>Оффер:</b> {escape(price)} {escape(currency)}\n\n"
        f"👤 <b>Кто создал оффер:</b>\n{_user_label(offer.creator_username, offer.creator_id)}\n\n"
        f"👤 <b>Кто принял / передал подарок:</b>\n{_user_label(offer.seller_username, offer.seller_id)}\n\n"
        f"🔎 <b>Проверка:</b> {escape(check_text)}\n\n"
        f"🆔 <b>Offer ID:</b> <code>{escape(offer.id)}</code>\n"
        f"🕐 <b>Создан:</b> {offer.created_at.astimezone().strftime('%d.%m.%Y %H:%M')}"
    )


async def send_admin_report(
    bot: Bot,
    *,
    admin_id: int,
    offer: Offer,
    check_text: str,
    needs_buttons: bool,
) -> None:
    text = build_admin_report(offer, check_text, premium=True)
    kwargs = dict(
        chat_id=admin_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_markup(offer.id) if needs_buttons else None,
    )
    try:
        await bot.send_message(**kwargs)
    except Exception:
        kwargs["text"] = plain_emoji_text(text)
        await bot.send_message(**kwargs)
