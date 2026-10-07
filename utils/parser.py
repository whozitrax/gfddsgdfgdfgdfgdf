from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse


class OfferParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedOffer:
    gift_url: str
    gift_slug: str
    gift_name: str
    gift_number: int
    price: Decimal
    currency: str


_CURRENCY_ALIASES = {
    "звёзды": "STARS",
    "звезды": "STARS",
    "stars": "STARS",
    "star": "STARS",
    "gram": "GRAM",
    "rub": "RUB",
    "руб": "RUB",
    "₽": "RUB",
    "usdt": "USDT",
}

_SLUG_RE = re.compile(r"^(?P<name>[A-Za-z0-9_]+)-(?P<number>[1-9][0-9]*)$")


def parse_gift_url(raw_url: str) -> tuple[str, str, str, int]:
    candidate = raw_url.strip()
    if candidate.startswith("t.me/"):
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    if parsed.scheme.lower() != "https" or parsed.netloc.lower() not in {"t.me", "www.t.me"}:
        raise OfferParseError("Ссылка должна вести на https://t.me/nft/...")

    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) != 2 or parts[0].lower() != "nft":
        raise OfferParseError("Нужна ссылка формата https://t.me/nft/RareBird-3396")

    slug = parts[1]
    match = _SLUG_RE.fullmatch(slug)
    if not match:
        raise OfferParseError("Не удалось разобрать название и номер подарка из ссылки")

    name = match.group("name")
    number = int(match.group("number"))
    normalized = f"https://t.me/nft/{slug}"
    return normalized, slug, name, number


def normalize_currency(raw: str) -> str:
    key = raw.strip().lower()
    value = _CURRENCY_ALIASES.get(key)
    if not value:
        raise OfferParseError("Неизвестная валюта. Доступно: звёзды, Gram, руб, usdt")
    return value


def parse_offer_command(text: str, *, require_buy_prefix: bool) -> ParsedOffer:
    raw = (text or "").strip()
    if not raw:
        raise OfferParseError("Пустая команда")

    parts = raw.split()
    if require_buy_prefix:
        if not parts or parts[0].lower() != ".buy":
            raise OfferParseError("Команда должна начинаться с .buy")
        parts = parts[1:]

    if len(parts) != 3:
        raise OfferParseError("Формат: .buy ссылка цена валюта")

    url_raw, price_raw, currency_raw = parts
    gift_url, gift_slug, gift_name, gift_number = parse_gift_url(url_raw)

    try:
        price = Decimal(price_raw.replace(",", "."))
    except InvalidOperation as exc:
        raise OfferParseError("Цена должна быть числом") from exc

    if not price.is_finite() or price <= 0:
        raise OfferParseError("Цена должна быть больше 0")
    if price > Decimal("1000000000000"):
        raise OfferParseError("Слишком большая цена")
    if price.as_tuple().exponent < -8:
        raise OfferParseError("Слишком много знаков после запятой")

    currency = normalize_currency(currency_raw)
    return ParsedOffer(
        gift_url=gift_url,
        gift_slug=gift_slug,
        gift_name=gift_name,
        gift_number=gift_number,
        price=price,
        currency=currency,
    )
