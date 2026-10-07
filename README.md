# GiftRelayer — clean BotHost/GitHub build

This build is intentionally **Python-only on the server**. The Mini App JavaScript and CSS are embedded inside `web/index.html`, so the repository has no `app.js`, `package.json`, or `node_modules` that could make BotHost mis-detect the project as Node.js.

## Runtime

- Python 3.11
- `python-telegram-bot` 22.8
- `aiohttp`
- `aiosqlite`
- one process runs both Telegram polling and the Mini App HTTP server
- public web port: `PORT` (default `3000`)

## Telegram flow

1. Buyer writes `.buy https://t.me/nft/RareBird-3396 8000 звёзды` in a Business chat.
2. GiftRelayer validates it and creates the offer.
3. A formatted offer appears with only `Отклонить` and `Принять`.
4. `Принять` opens the bot's **Main Mini App** with `?startapp=<offer_id>`; opening the app does not accept the offer.
5. Mini App validates signed `initData` on the backend.
6. Acceptance inside Mini App changes `ACTIVE -> ACCEPTED`.
7. The seller can transfer the gift and request verification.
8. Telegram-owned unique gifts are checked through the official Bot API where available; ambiguous/unavailable checks become `TRANSFER_PENDING` for admin review.

## BotHost deployment

1. Push the repository to GitHub. Do **not** commit `.env`, `node_modules`, `package.json`, or any JS server entrypoint.
2. In BotHost select Python 3.11.
3. Main file: `main.py`.
4. Enable **Use custom Dockerfile** so only this application owns port 3000.
5. Domain web-app port: `3000`.
6. Add `.env` in the project root using `.env.example` as a template.
7. Rebuild/redeploy the container after changing Dockerfile/runtime settings.

Expected startup log:

```text
DATABASE INITIALIZED
BOT STARTED @YourBot | ...
MINI APP SERVER STARTED http://0.0.0.0:3000
TELEGRAM POLLING STARTED
```

Health check:

```text
https://YOUR-DOMAIN.bothost.tech/health
```

Expected response:

```json
{"ok": true, "service": "GiftRelayer"}
```

## BotFather

Configure **Main App** for the same bot and set its URL to the public BotHost HTTPS domain, for example:

```text
https://YOUR-DOMAIN.bothost.tech
```

The offer button uses:

```text
https://t.me/<bot_username>?startapp=<offer_id>
```

This opens the Main Mini App directly. `offer_id` only selects an offer; authorization comes from validated Telegram `initData`.
