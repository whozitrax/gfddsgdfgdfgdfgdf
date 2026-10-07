from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import web
from telegram import Bot, OwnedGiftUnique

from config import Settings
from database import Database, Offer, utcnow
from services.admin import send_admin_report
from services.gifts import GiftPresence, TransferCheck, gift_presence, verify_transfer
from services.message_sync import sync_offer_message
from services.offers import CURRENCY_LABELS, display_gift, format_price
from utils.webapp_auth import InitDataError, ValidatedInitData, validate_init_data

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent / "web"


class ApiError(web.HTTPException):
    pass


def _json_error(message: str, *, status: int = 400, code: str = "error") -> web.Response:
    return web.json_response({"ok": False, "error": message, "code": code}, status=status)


def _offer_payload(offer: Offer, *, actor_id: int) -> dict[str, Any]:
    seconds_left = max(0, int((offer.expires_at - utcnow()).total_seconds()))
    creator_link = None
    if offer.creator_username:
        creator_link = f"https://t.me/{offer.creator_username.lstrip('@')}"
    else:
        creator_link = f"tg://user?id={offer.creator_id}"

    return {
        "id": offer.id,
        "status": offer.status,
        "gift": {
            "slug": offer.gift_slug,
            "name": display_gift(offer),
            "url": offer.gift_url,
        },
        "price": {
            "value": format_price(offer.price),
            "currency": CURRENCY_LABELS.get(offer.currency, offer.currency),
        },
        "seconds_left": seconds_left,
        "creator": {
            "username": offer.creator_username,
            "link": creator_link,
        },
        "is_creator": actor_id == offer.creator_id,
    }


def _extract_offer_id(request: web.Request) -> str:
    offer_id = (request.match_info.get("offer_id") or request.query.get("offer_id") or "").strip()
    if not offer_id or len(offer_id) > 80:
        raise web.HTTPBadRequest(text="Invalid offer id")
    return offer_id


def _validate_request(request: web.Request) -> ValidatedInitData:
    settings: Settings = request.app["settings"]
    raw = request.headers.get("X-Telegram-Init-Data", "")
    try:
        return validate_init_data(
            raw,
            bot_token=settings.bot_token,
            max_age_seconds=settings.init_data_max_age_seconds,
        )
    except InitDataError as exc:
        raise web.HTTPUnauthorized(text=str(exc)) from exc


def _seller_allowed(offer: Offer, user_id: int) -> bool:
    if user_id == offer.creator_id:
        return False
    if offer.source_type == "BUSINESS":
        return offer.chat_id == user_id
    if offer.seller_id is not None:
        return offer.seller_id == user_id
    return True


async def _load_authorized_offer(request: web.Request, *, allow_creator: bool = False) -> tuple[ValidatedInitData, Offer]:
    auth = _validate_request(request)
    offer_id = _extract_offer_id(request)
    db: Database = request.app["db"]
    offer = await db.get_offer(offer_id)
    if not offer:
        raise web.HTTPNotFound(text="Оффер не найден.")

    # start_param is an object selector, not an authorization credential. When it is
    # present in signed initData, require it to match the requested offer.
    if auth.start_param and auth.start_param != offer.id:
        raise web.HTTPForbidden(text="Открыт другой оффер.")

    if auth.user.id == offer.creator_id and not allow_creator:
        raise web.HTTPForbidden(text="Нельзя принять собственное предложение.")
    if not allow_creator and not _seller_allowed(offer, auth.user.id):
        raise web.HTTPForbidden(text="Этот оффер предназначен другому пользователю.")
    return auth, offer


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "GiftRelayer"})


async def get_offer_state(request: web.Request) -> web.Response:
    try:
        auth, offer = await _load_authorized_offer(request, allow_creator=True)
    except web.HTTPUnauthorized as exc:
        return _json_error(exc.text, status=401, code="unauthorized")
    except web.HTTPNotFound as exc:
        return _json_error(exc.text, status=404, code="not_found")
    except web.HTTPForbidden as exc:
        return _json_error(exc.text, status=403, code="forbidden")

    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    if offer.status == "ACTIVE" and offer.expires_at <= utcnow():
        changed = await db.transition(
            offer.id,
            from_statuses=("ACTIVE",),
            to_status="EXPIRED",
            actor_id=None,
            event_type="EXPIRED",
        )
        if changed:
            offer = changed
            await sync_offer_message(bot, offer)

    payload = _offer_payload(offer, actor_id=auth.user.id)
    if auth.user.id == offer.creator_id:
        payload["action_blocked"] = "OWN_OFFER"
    elif not _seller_allowed(offer, auth.user.id):
        payload["action_blocked"] = "NOT_RECIPIENT"
    return web.json_response({"ok": True, "offer": payload})


async def decline_offer(request: web.Request) -> web.Response:
    try:
        auth, offer = await _load_authorized_offer(request)
    except web.HTTPException as exc:
        return _json_error(exc.text, status=exc.status, code="forbidden" if exc.status == 403 else "error")

    if offer.status != "ACTIVE":
        return _json_error("Предложение уже обработано.", status=409, code="state_changed")
    if offer.expires_at <= utcnow():
        return _json_error("Срок предложения истёк.", status=409, code="expired")

    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    await db.upsert_user(auth.user.id, auth.user.username, auth.user.first_name)
    changed = await db.transition(
        offer.id,
        from_statuses=("ACTIVE",),
        to_status="DECLINED",
        actor_id=auth.user.id,
        event_type="DECLINED",
        seller_id=auth.user.id,
        seller_username=auth.user.username,
        completed_at=utcnow(),
    )
    if not changed:
        return _json_error("Предложение уже обработано.", status=409, code="state_changed")
    await sync_offer_message(bot, changed)
    return web.json_response({"ok": True, "offer": _offer_payload(changed, actor_id=auth.user.id)})


async def accept_offer(request: web.Request) -> web.Response:
    try:
        auth, offer = await _load_authorized_offer(request)
    except web.HTTPException as exc:
        code = "own_offer" if exc.status == 403 and "собственное" in exc.text else "forbidden"
        return _json_error(exc.text, status=exc.status, code=code)

    if offer.status != "ACTIVE":
        return _json_error("Предложение уже обработано.", status=409, code="state_changed")
    if offer.expires_at <= utcnow():
        return _json_error("Срок предложения истёк.", status=409, code="expired")

    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    await db.upsert_user(auth.user.id, auth.user.username, auth.user.first_name)

    seller_presence = await gift_presence(bot, user_id=auth.user.id, gift_slug=offer.gift_slug)
    buyer_presence = await gift_presence(bot, user_id=offer.creator_id, gift_slug=offer.gift_slug)
    await db.set_verification_snapshot(
        offer.id,
        owner_before={
            "seller_id": auth.user.id,
            "seller_presence": seller_presence.status.value,
            "buyer_id": offer.creator_id,
            "buyer_presence": buyer_presence.status.value,
            "checked_at": utcnow().isoformat(),
        },
    )

    changed = await db.transition(
        offer.id,
        from_statuses=("ACTIVE",),
        to_status="ACCEPTED",
        actor_id=auth.user.id,
        event_type="ACCEPTED",
        seller_id=auth.user.id,
        seller_username=auth.user.username,
        accepted_at=utcnow(),
        metadata={
            "seller_presence_before": seller_presence.status.value,
            "buyer_presence_before": buyer_presence.status.value,
        },
    )
    if not changed:
        return _json_error("Предложение уже обработано.", status=409, code="state_changed")

    logger.info("OFFER ACCEPTED VIA MINIAPP offer_id=%s seller_id=%s", changed.id, auth.user.id)
    await sync_offer_message(bot, changed)
    return web.json_response({"ok": True, "offer": _offer_payload(changed, actor_id=auth.user.id)})


async def confirm_transfer(request: web.Request) -> web.Response:
    try:
        auth, offer = await _load_authorized_offer(request)
    except web.HTTPException as exc:
        return _json_error(exc.text, status=exc.status, code="forbidden")

    if offer.status not in {"ACCEPTED", "TRANSFER_PENDING"}:
        return _json_error("Сделка сейчас не ожидает передачу.", status=409, code="state_changed")
    if offer.seller_id != auth.user.id:
        return _json_error("Подтвердить передачу может только продавец.", status=403, code="forbidden")
    if offer.status == "TRANSFER_PENDING":
        return web.json_response({"ok": True, "result": "PENDING", "offer": _offer_payload(offer, actor_id=auth.user.id)})

    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    settings: Settings = request.app["settings"]
    checked_at = utcnow()
    await db.set_verification_snapshot(offer.id, verification_requested_at=checked_at)

    result = await verify_transfer(
        bot,
        seller_id=offer.seller_id,
        expected_buyer_id=offer.creator_id,
        gift_slug=offer.gift_slug,
    )
    await db.set_verification_snapshot(offer.id, verification_result=result.status.value)

    if result.status == TransferCheck.VERIFIED:
        changed = await db.transition(
            offer.id,
            from_statuses=("ACCEPTED",),
            to_status="TRANSFER_CONFIRMED",
            actor_id=auth.user.id,
            event_type="TRANSFER_CONFIRMED",
            transfer_requested_at=checked_at,
            completed_at=utcnow(),
            metadata={
                "verification": "bot_api_get_user_gifts",
                "seller_presence": result.seller_presence.value,
                "buyer_presence": result.buyer_presence.value,
            },
        )
        if not changed:
            return _json_error("Состояние сделки уже изменилось.", status=409, code="state_changed")
        await sync_offer_message(bot, changed)
        await send_admin_report(
            bot,
            admin_id=settings.admin_id,
            offer=changed,
            check_text="Передача подтверждена автоматически",
            needs_buttons=False,
        )
        return web.json_response({"ok": True, "result": "VERIFIED", "offer": _offer_payload(changed, actor_id=auth.user.id)})

    if result.status == TransferCheck.NOT_TRANSFERRED:
        return web.json_response({
            "ok": True,
            "result": "NOT_TRANSFERRED",
            "message": "Подарок всё ещё находится у продавца.",
            "offer": _offer_payload(offer, actor_id=auth.user.id),
        })

    changed = await db.transition(
        offer.id,
        from_statuses=("ACCEPTED",),
        to_status="TRANSFER_PENDING",
        actor_id=auth.user.id,
        event_type="TRANSFER_REQUESTED",
        transfer_requested_at=checked_at,
        metadata={
            "verification": "manual_required",
            "reason": result.status.value,
            "seller_presence": result.seller_presence.value,
            "buyer_presence": result.buyer_presence.value,
        },
    )
    if not changed:
        current = await db.get_offer(offer.id)
        if current and current.status == "TRANSFER_PENDING":
            changed = current
        else:
            return _json_error("Состояние сделки уже изменилось.", status=409, code="state_changed")

    await sync_offer_message(bot, changed)
    await send_admin_report(
        bot,
        admin_id=settings.admin_id,
        offer=changed,
        check_text="Требуется ручная проверка",
        needs_buttons=True,
    )
    return web.json_response({"ok": True, "result": "PENDING", "offer": _offer_payload(changed, actor_id=auth.user.id)})


async def gift_image(request: web.Request) -> web.Response:
    try:
        auth, offer = await _load_authorized_offer(request, allow_creator=True)
    except web.HTTPException as exc:
        return _json_error(exc.text, status=exc.status)

    bot: Bot = request.app["bot"]
    candidate_ids: list[int] = []
    if offer.seller_id:
        candidate_ids.append(offer.seller_id)
    if offer.source_type == "BUSINESS" and offer.chat_id and offer.chat_id not in candidate_ids:
        candidate_ids.append(offer.chat_id)
    if auth.user.id not in candidate_ids:
        candidate_ids.append(auth.user.id)
    if offer.creator_id not in candidate_ids:
        candidate_ids.append(offer.creator_id)

    for uid in candidate_ids:
        try:
            offset: str | None = None
            while True:
                page = await bot.get_user_gifts(
                    user_id=uid,
                    exclude_unlimited=True,
                    exclude_limited_upgradable=True,
                    exclude_limited_non_upgradable=True,
                    exclude_from_blockchain=True,
                    exclude_unique=False,
                    offset=offset,
                    limit=100,
                )
                for owned in page.gifts:
                    if isinstance(owned, OwnedGiftUnique) and owned.gift.name == offer.gift_slug:
                        sticker = getattr(getattr(owned.gift, "model", None), "sticker", None)
                        thumbnail = getattr(sticker, "thumbnail", None)
                        file_id = getattr(thumbnail, "file_id", None) or getattr(sticker, "file_id", None)
                        if not file_id:
                            continue
                        tg_file = await bot.get_file(file_id)
                        data = bytes(await tg_file.download_as_bytearray())
                        return web.Response(body=data, content_type="image/webp", headers={"Cache-Control": "private, max-age=300"})
                if not page.next_offset:
                    break
                offset = page.next_offset
        except Exception as exc:
            logger.debug("Gift image unavailable user=%s gift=%s: %s", uid, offer.gift_slug, exc)

    return _json_error("Изображение подарка недоступно через Bot API.", status=404, code="image_unavailable")


def create_web_app(*, bot: Bot, db: Database, settings: Settings) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    app["bot"] = bot
    app["db"] = db
    app["settings"] = settings

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/offers/{offer_id}", get_offer_state)
    app.router.add_get("/api/offers/{offer_id}/gift-image", gift_image)
    app.router.add_post("/api/offers/{offer_id}/accept", accept_offer)
    app.router.add_post("/api/offers/{offer_id}/decline", decline_offer)
    app.router.add_post("/api/offers/{offer_id}/confirm-transfer", confirm_transfer)
    return app


async def start_web_server(*, bot: Bot, db: Database, settings: Settings) -> web.AppRunner:
    app = create_web_app(bot=bot, db=db, settings=settings)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.web_host, port=settings.web_port)
    await site.start()
    logger.info("MINI APP SERVER STARTED http://%s:%s", settings.web_host, settings.web_port)
    return runner
