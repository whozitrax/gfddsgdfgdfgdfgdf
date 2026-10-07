from __future__ import annotations

from decimal import Decimal
from html import escape
import re
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from database import Offer
from utils.emoji import ce


CURRENCY_LABELS = {
    "STARS": "звёзд",
    "GRAM": "Gram",
    "RUB": "руб",
    "USDT": "USDT",
}


def format_price(value: Decimal) -> str:
    if value == value.to_integral():
        return f"{int(value):,}".replace(",", " ")
    normalized = format(value.normalize(), "f")
    whole, dot, frac = normalized.partition(".")
    whole = f"{int(whole):,}".replace(",", " ")
    return whole + (dot + frac if frac else "")


def re_spaced_name(value: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).replace("_", " ")


def display_gift(offer: Offer) -> str:
    return f"{re_spaced_name(offer.gift_name)} #{offer.gift_number}"


def miniapp_deep_link(*, bot_username: str, offer_id: str) -> str:
    username = bot_username.lstrip("@")
    # Main Mini App link. startapp only selects an offer; authorization still
    # comes exclusively from Telegram-signed initData validated by the backend.
    return f"https://t.me/{quote(username)}?startapp={quote(offer_id)}"


def active_markup(offer: Offer, *, miniapp_url: str) -> InlineKeyboardMarkup:
    # A web_app InlineKeyboardButton is not supported for messages sent on behalf of
    # a business account. A Telegram Mini App direct-link URL is supported and still
    # launches the app inside Telegram with signed initData.
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("❌ Отклонить", callback_data=f"od:{offer.id}", style="danger"),
            InlineKeyboardButton("✅ Принять", url=miniapp_url, style="success"),
        ]]
    )


def admin_markup(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("❌ Отклонить", callback_data=f"ar:{offer_id}", style="danger"),
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"ac:{offer_id}", style="success"),
        ]]
    )


def link_preview() -> LinkPreviewOptions:
    return LinkPreviewOptions(is_disabled=False, prefer_large_media=True, show_above_text=True)


def build_offer_text(offer: Offer, *, premium: bool = True) -> str:
    gift = escape(display_gift(offer))
    price = escape(format_price(offer.price))
    currency = escape(CURRENCY_LABELS.get(offer.currency, offer.currency))
    url = escape(offer.gift_url, quote=True)

    return (
        f"{ce('🎁', premium=premium)} <b>Вам предложили купить ваш подарок</b>\n\n"
        f"<a href=\"{url}\"><b>{gift}</b></a>\n"
        f"{ce('⭐️', premium=premium)} <b>Предложение: {price} {currency}</b>\n\n"
        f"{ce('⏱', premium=premium)} Оффер действует <b>6 часов</b>."
    )


def build_terminal_text(offer: Offer, status: str, *, premium: bool = True) -> str:
    gift = escape(display_gift(offer))
    url = escape(offer.gift_url, quote=True)

    mapping = {
        "ACCEPTED": ("✅", "Предложение принято", "Сделка продолжается в GiftRelayer Mini App."),
        "DECLINED": ("❌", "Предложение отклонено", "Получатель отказался от предложения."),
        "EXPIRED": ("⏱", "Срок предложения истёк", "Этот оффер больше недоступен."),
        "TRANSFER_PENDING": ("⏱", "Передача ожидает проверки", "Информация отправлена на проверку."),
        "TRANSFER_CONFIRMED": ("✅", "Подарок передан", "Передача успешно подтверждена."),
        "TRANSFER_REJECTED": ("❌", "Передача не подтверждена", "Проверка передачи была отклонена."),
        "CANCELLED": ("🔒", "Оффер отменён", "Сделка закрыта."),
    }
    icon, title, subtitle = mapping.get(status, ("🔒", "Оффер завершён", "Сделка закрыта."))
    return (
        f"{ce(icon, premium=premium)} <b>{escape(title)}</b>\n\n"
        f"{ce('🎁', premium=premium)} <a href=\"{url}\"><b>{gift}</b></a>\n"
        f"{escape(subtitle)}"
    )
