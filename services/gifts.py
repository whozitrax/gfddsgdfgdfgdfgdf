from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from telegram import Bot, OwnedGiftUnique
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class GiftPresence(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class PresenceResult:
    status: GiftPresence
    details: str


class TransferCheck(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_TRANSFERRED = "NOT_TRANSFERRED"
    WRONG_OWNER_OR_UNKNOWN = "WRONG_OWNER_OR_UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class TransferVerificationResult:
    status: TransferCheck
    seller_presence: GiftPresence
    buyer_presence: GiftPresence
    details: str


async def gift_presence(bot: Bot, *, user_id: int, gift_slug: str) -> PresenceResult:
    """Check a Telegram-native unique gift on one user via the official Bot API."""
    offset: str | None = None
    try:
        while True:
            page = await bot.get_user_gifts(
                user_id=user_id,
                exclude_unlimited=True,
                exclude_limited_upgradable=True,
                exclude_limited_non_upgradable=True,
                exclude_from_blockchain=True,
                exclude_unique=False,
                offset=offset,
                limit=100,
            )
            for owned in page.gifts:
                if isinstance(owned, OwnedGiftUnique) and owned.gift.name == gift_slug:
                    return PresenceResult(GiftPresence.PRESENT, "Gift найден у пользователя.")
            if not page.next_offset:
                return PresenceResult(GiftPresence.ABSENT, "Gift у пользователя не найден.")
            offset = page.next_offset
    except TelegramError as exc:
        logger.warning("Gift presence unavailable user_id=%s gift=%s: %s", user_id, gift_slug, exc)
        return PresenceResult(GiftPresence.UNAVAILABLE, str(exc))


async def verify_transfer(
    bot: Bot,
    *,
    seller_id: int,
    expected_buyer_id: int,
    gift_slug: str,
) -> TransferVerificationResult:
    seller = await gift_presence(bot, user_id=seller_id, gift_slug=gift_slug)
    buyer = await gift_presence(bot, user_id=expected_buyer_id, gift_slug=gift_slug)

    if buyer.status == GiftPresence.PRESENT and seller.status == GiftPresence.ABSENT:
        return TransferVerificationResult(
            TransferCheck.VERIFIED,
            seller.status,
            buyer.status,
            "Gift исчез у продавца и найден у ожидаемого покупателя.",
        )
    if seller.status == GiftPresence.PRESENT and buyer.status != GiftPresence.PRESENT:
        return TransferVerificationResult(
            TransferCheck.NOT_TRANSFERRED,
            seller.status,
            buyer.status,
            "Gift всё ещё найден у продавца.",
        )
    if GiftPresence.UNAVAILABLE in {seller.status, buyer.status}:
        return TransferVerificationResult(
            TransferCheck.UNAVAILABLE,
            seller.status,
            buyer.status,
            "Bot API не позволил достоверно завершить автоматическую проверку.",
        )
    return TransferVerificationResult(
        TransferCheck.WRONG_OWNER_OR_UNKNOWN,
        seller.status,
        buyer.status,
        "Gift не найден у ожидаемого покупателя; автоматическое подтверждение невозможно.",
    )
