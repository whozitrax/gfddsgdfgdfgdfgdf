from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramWebAppUser:
    id: int
    username: str | None
    first_name: str | None


@dataclass(frozen=True)
class ValidatedInitData:
    user: TelegramWebAppUser
    auth_date: int
    start_param: str | None
    raw: dict[str, str]


def validate_init_data(raw_init_data: str, *, bot_token: str, max_age_seconds: int) -> ValidatedInitData:
    if not raw_init_data:
        raise InitDataError("Telegram initData отсутствует.")

    pairs = dict(parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("В initData отсутствует hash.")

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise InitDataError("Подпись Telegram initData недействительна.")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("Некорректный auth_date.") from exc

    now = int(time.time())
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > max_age_seconds:
        raise InitDataError("Telegram initData устарел. Закройте Mini App и откройте оффер снова.")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("Telegram не передал пользователя Mini App.")
    try:
        user_obj = json.loads(user_raw)
        user_id = int(user_obj["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise InitDataError("Некорректные данные пользователя Telegram.") from exc

    user = TelegramWebAppUser(
        id=user_id,
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
    )
    return ValidatedInitData(
        user=user,
        auth_date=auth_date,
        start_param=pairs.get("start_param"),
        raw=pairs,
    )
