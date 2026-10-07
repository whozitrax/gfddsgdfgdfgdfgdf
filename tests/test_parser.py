from decimal import Decimal

import pytest

from utils.parser import OfferParseError, parse_offer_command


def test_buy_command():
    p = parse_offer_command(
        ".buy https://t.me/nft/RareBird-3396 8000 звёзды",
        require_buy_prefix=True,
    )
    assert p.gift_slug == "RareBird-3396"
    assert p.gift_name == "RareBird"
    assert p.gift_number == 3396
    assert p.price == Decimal("8000")
    assert p.currency == "STARS"


def test_inline_command():
    p = parse_offer_command(
        "https://t.me/nft/RareBird-3396 12.5 USDT",
        require_buy_prefix=False,
    )
    assert p.price == Decimal("12.5")
    assert p.currency == "USDT"


@pytest.mark.parametrize(
    "text",
    [
        ".buy https://evil.example/nft/RareBird-3396 1 stars",
        ".buy https://t.me/nft/RareBird-3396 0 stars",
        ".buy https://t.me/nft/RareBird-3396 abc stars",
        ".buy https://t.me/nft/RareBird 10 stars",
        ".buy https://t.me/nft/RareBird-3396 10 btc",
    ],
)
def test_invalid(text):
    with pytest.raises(OfferParseError):
        parse_offer_command(text, require_buy_prefix=True)
