from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from contextlib import asynccontextmanager
from uuid import uuid4

import aiosqlite


VALID_STATUSES = {
    "ACTIVE",
    "ACCEPTED",
    "TRANSFER_PENDING",
    "TRANSFER_CONFIRMED",
    "DECLINED",
    "EXPIRED",
    "CANCELLED",
    "TRANSFER_REJECTED",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(slots=True)
class Offer:
    id: str
    creator_id: int
    creator_username: str | None
    seller_id: int | None
    seller_username: str | None
    business_connection_id: str | None
    chat_id: int | None
    source_message_id: int | None
    offer_message_id: int | None
    inline_message_id: str | None
    source_type: str
    gift_url: str
    gift_slug: str
    gift_name: str
    gift_number: int
    price: Decimal
    currency: str
    status: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    transfer_requested_at: datetime | None
    completed_at: datetime | None
    owner_before_json: str | None
    verification_result: str | None
    verification_requested_at: datetime | None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Offer":
        return cls(
            id=row["id"],
            creator_id=row["creator_id"],
            creator_username=row["creator_username"],
            seller_id=row["seller_id"],
            seller_username=row["seller_username"],
            business_connection_id=row["business_connection_id"],
            chat_id=row["chat_id"],
            source_message_id=row["source_message_id"],
            offer_message_id=row["offer_message_id"],
            inline_message_id=row["inline_message_id"],
            source_type=row["source_type"],
            gift_url=row["gift_url"],
            gift_slug=row["gift_slug"],
            gift_name=row["gift_name"],
            gift_number=row["gift_number"],
            price=Decimal(row["price"]),
            currency=row["currency"],
            status=row["status"],
            created_at=parse_dt(row["created_at"]),
            expires_at=parse_dt(row["expires_at"]),
            accepted_at=parse_dt(row["accepted_at"]),
            transfer_requested_at=parse_dt(row["transfer_requested_at"]),
            completed_at=parse_dt(row["completed_at"]),
            owner_before_json=row["owner_before_json"] if "owner_before_json" in row.keys() else None,
            verification_result=row["verification_result"] if "verification_result" in row.keys() else None,
            verification_requested_at=parse_dt(row["verification_requested_at"]) if "verification_requested_at" in row.keys() else None,
        )


class Database:
    def __init__(self, path: Path):
        self.path = path

    @asynccontextmanager
    async def connection(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            await db.close()

    async def initialize(self) -> None:
        async with self.connection() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS business_connections (
                    connection_id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    rights_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS offers (
                    id TEXT PRIMARY KEY,
                    creator_id INTEGER NOT NULL,
                    creator_username TEXT,
                    seller_id INTEGER,
                    seller_username TEXT,
                    business_connection_id TEXT,
                    chat_id INTEGER,
                    source_message_id INTEGER,
                    offer_message_id INTEGER,
                    inline_message_id TEXT,
                    source_type TEXT NOT NULL DEFAULT 'BUSINESS',
                    gift_url TEXT NOT NULL,
                    gift_slug TEXT NOT NULL,
                    gift_name TEXT NOT NULL,
                    gift_number INTEGER NOT NULL,
                    price TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    accepted_at TEXT,
                    transfer_requested_at TEXT,
                    completed_at TEXT,
                    owner_before_json TEXT,
                    verification_result TEXT,
                    verification_requested_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_offers_status_expires
                ON offers(status, expires_at);

                CREATE TABLE IF NOT EXISTS offer_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT NOT NULL,
                    actor_id INTEGER,
                    event_type TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(offer_id) REFERENCES offers(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_offer_events_offer_id
                ON offer_events(offer_id, id);
                """
            )
            # Lightweight migrations for installations created by earlier GiftRelayer builds.
            cur = await db.execute("PRAGMA table_info(offers)")
            columns = {row[1] for row in await cur.fetchall()}
            migrations = {
                "owner_before_json": "ALTER TABLE offers ADD COLUMN owner_before_json TEXT",
                "verification_result": "ALTER TABLE offers ADD COLUMN verification_result TEXT",
                "verification_requested_at": "ALTER TABLE offers ADD COLUMN verification_requested_at TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    await db.execute(statement)
            await db.commit()

    async def upsert_user(self, telegram_id: int, username: str | None, first_name: str | None) -> None:
        now = iso(utcnow())
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO users(telegram_id, username, first_name, created_at, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    updated_at=excluded.updated_at
                """,
                (telegram_id, username, first_name, now, now),
            )
            await db.commit()

    async def upsert_business_connection(
        self,
        connection_id: str,
        owner_user_id: int,
        active: bool,
        rights: dict[str, Any] | None,
    ) -> None:
        now = iso(utcnow())
        rights_json = json.dumps(rights or {}, ensure_ascii=False)
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO business_connections(connection_id, owner_user_id, active, rights_json, created_at, updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    owner_user_id=excluded.owner_user_id,
                    active=excluded.active,
                    rights_json=excluded.rights_json,
                    updated_at=excluded.updated_at
                """,
                (connection_id, owner_user_id, 1 if active else 0, rights_json, now, now),
            )
            await db.commit()

    async def get_business_owner(self, connection_id: str) -> int | None:
        async with self.connection() as db:
            cur = await db.execute(
                "SELECT owner_user_id FROM business_connections WHERE connection_id=? AND active=1",
                (connection_id,),
            )
            row = await cur.fetchone()
            return row["owner_user_id"] if row else None

    async def create_offer(
        self,
        *,
        creator_id: int,
        creator_username: str | None,
        business_connection_id: str | None,
        chat_id: int | None,
        source_message_id: int | None,
        source_type: str,
        gift_url: str,
        gift_slug: str,
        gift_name: str,
        gift_number: int,
        price: Decimal,
        currency: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> Offer:
        offer_id = uuid4().hex
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                INSERT INTO offers(
                    id, creator_id, creator_username, business_connection_id, chat_id,
                    source_message_id, source_type, gift_url, gift_slug, gift_name,
                    gift_number, price, currency, status, created_at, expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?,?)
                """,
                (
                    offer_id,
                    creator_id,
                    creator_username,
                    business_connection_id,
                    chat_id,
                    source_message_id,
                    source_type,
                    gift_url,
                    gift_slug,
                    gift_name,
                    gift_number,
                    str(price),
                    currency,
                    iso(created_at),
                    iso(expires_at),
                ),
            )
            await self._insert_event(
                db,
                offer_id=offer_id,
                actor_id=creator_id,
                event_type="CREATED",
                old_status=None,
                new_status="ACTIVE",
                metadata={"source_type": source_type},
            )
            await db.commit()
        return await self.get_offer(offer_id)

    async def get_offer(self, offer_id: str) -> Offer | None:
        async with self.connection() as db:
            cur = await db.execute("SELECT * FROM offers WHERE id=?", (offer_id,))
            row = await cur.fetchone()
            return Offer.from_row(row) if row else None

    async def set_message_ids(
        self,
        offer_id: str,
        *,
        offer_message_id: int | None = None,
        inline_message_id: str | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if offer_message_id is not None:
            fields.append("offer_message_id=?")
            params.append(offer_message_id)
        if inline_message_id is not None:
            fields.append("inline_message_id=?")
            params.append(inline_message_id)
        if not fields:
            return
        params.append(offer_id)
        async with self.connection() as db:
            await db.execute(f"UPDATE offers SET {', '.join(fields)} WHERE id=?", params)
            await db.commit()

    async def transition(
        self,
        offer_id: str,
        *,
        from_statuses: Iterable[str],
        to_status: str,
        actor_id: int | None,
        event_type: str,
        seller_id: int | None = None,
        seller_username: str | None = None,
        accepted_at: datetime | None = None,
        transfer_requested_at: datetime | None = None,
        completed_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Offer | None:
        statuses = tuple(from_statuses)
        if not statuses:
            raise ValueError("from_statuses can't be empty")
        if to_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {to_status}")

        placeholders = ",".join("?" for _ in statuses)
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT status FROM offers WHERE id=?", (offer_id,))
            before = await cur.fetchone()
            if not before or before["status"] not in statuses:
                await db.rollback()
                return None
            old_status = before["status"]

            update_parts = ["status=?"]
            params: list[Any] = [to_status]
            if seller_id is not None:
                update_parts.append("seller_id=?")
                params.append(seller_id)
            if seller_username is not None:
                update_parts.append("seller_username=?")
                params.append(seller_username)
            if accepted_at is not None:
                update_parts.append("accepted_at=?")
                params.append(iso(accepted_at))
            if transfer_requested_at is not None:
                update_parts.append("transfer_requested_at=?")
                params.append(iso(transfer_requested_at))
            if completed_at is not None:
                update_parts.append("completed_at=?")
                params.append(iso(completed_at))

            params.extend([offer_id, *statuses])
            result = await db.execute(
                f"UPDATE offers SET {', '.join(update_parts)} WHERE id=? AND status IN ({placeholders})",
                params,
            )
            if result.rowcount != 1:
                await db.rollback()
                return None

            await self._insert_event(
                db,
                offer_id=offer_id,
                actor_id=actor_id,
                event_type=event_type,
                old_status=old_status,
                new_status=to_status,
                metadata=metadata,
            )
            await db.commit()
        return await self.get_offer(offer_id)


    async def set_verification_snapshot(
        self,
        offer_id: str,
        *,
        owner_before: dict[str, Any] | None = None,
        verification_result: str | None = None,
        verification_requested_at: datetime | None = None,
    ) -> None:
        parts: list[str] = []
        params: list[Any] = []
        if owner_before is not None:
            parts.append("owner_before_json=?")
            params.append(json.dumps(owner_before, ensure_ascii=False))
        if verification_result is not None:
            parts.append("verification_result=?")
            params.append(verification_result)
        if verification_requested_at is not None:
            parts.append("verification_requested_at=?")
            params.append(iso(verification_requested_at))
        if not parts:
            return
        params.append(offer_id)
        async with self.connection() as db:
            await db.execute(f"UPDATE offers SET {', '.join(parts)} WHERE id=?", params)
            await db.commit()

    async def expire_due_offers(self, now: datetime) -> list[Offer]:
        expired_ids: list[str] = []
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "SELECT id FROM offers WHERE status='ACTIVE' AND expires_at<=?",
                (iso(now),),
            )
            rows = await cur.fetchall()
            for row in rows:
                offer_id = row["id"]
                result = await db.execute(
                    "UPDATE offers SET status='EXPIRED' WHERE id=? AND status='ACTIVE'",
                    (offer_id,),
                )
                if result.rowcount == 1:
                    expired_ids.append(offer_id)
                    await self._insert_event(
                        db,
                        offer_id=offer_id,
                        actor_id=None,
                        event_type="EXPIRED",
                        old_status="ACTIVE",
                        new_status="EXPIRED",
                        metadata=None,
                    )
            await db.commit()

        offers: list[Offer] = []
        for offer_id in expired_ids:
            offer = await self.get_offer(offer_id)
            if offer:
                offers.append(offer)
        return offers

    async def _insert_event(
        self,
        db: aiosqlite.Connection,
        *,
        offer_id: str,
        actor_id: int | None,
        event_type: str,
        old_status: str | None,
        new_status: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        await db.execute(
            """
            INSERT INTO offer_events(offer_id, actor_id, event_type, old_status, new_status, metadata, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                offer_id,
                actor_id,
                event_type,
                old_status,
                new_status,
                json.dumps(metadata or {}, ensure_ascii=False),
                iso(utcnow()),
            ),
        )
