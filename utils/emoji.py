from __future__ import annotations

from html import escape

CUSTOM_EMOJI_IDS = {
    "⏱": "5382194935057372936",
    "🎁": "5203996991054432397",
    "❌": "5210952531676504517",
    "✔️": "5206607081334906820",
    "💎": "5427168083074628963",
    "🔒": "5296369303661067030",
    "⭐️": "5438496463044752972",
    "✅": "5427009714745517609",
    "⚡️": "5456140674028019486",
}


def ce(symbol: str, *, premium: bool = True) -> str:
    """Return safe HTML for a Telegram custom emoji, with a normal emoji fallback."""
    emoji_id = CUSTOM_EMOJI_IDS.get(symbol)
    if premium and emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{escape(symbol)}</tg-emoji>'
    return escape(symbol)


def plain_emoji_text(html_text: str) -> str:
    """Strip only tg-emoji tags, keeping the emoji itself and other HTML markup intact."""
    import re

    return re.sub(r"</?tg-emoji(?:\s+emoji-id=\"\d+\")?>", "", html_text)
