# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import aiosqlite

from config import DATABASE_PATH


def now() -> float:
    return time.time()


@asynccontextmanager
async def connect():
    db = await aiosqlite.connect(DATABASE_PATH, timeout=30.0)
    db.row_factory = aiosqlite.Row

    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=30000")

    try:
        yield db
    finally:
        await db.close()


@asynccontextmanager
async def transaction():
    async with connect() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise




async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        rows = await cursor.fetchall()
    return {str(row["name"]) for row in rows}


async def _add_columns(
    db: aiosqlite.Connection,
    table: str,
    definitions: dict[str, str],
) -> None:
    existing = await _columns(db, table)
    for name, definition in definitions.items():
        if name in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        except Exception:
            continue


async def init_db() -> None:
    async with connect() as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                femcoins INTEGER NOT NULL DEFAULT 100,
                last_fem_time REAL NOT NULL DEFAULT 0,
                custom_cd_hours REAL NOT NULL DEFAULT 3,
                custom_cd_expires REAL NOT NULL DEFAULT 0,
                daily_streak INTEGER NOT NULL DEFAULT 0,
                last_daily_time REAL NOT NULL DEFAULT 0,
                referred_by INTEGER NOT NULL DEFAULT 0,
                referral_reward_given INTEGER NOT NULL DEFAULT 0,
                vip_until REAL NOT NULL DEFAULT 0,
                luck_expires REAL NOT NULL DEFAULT 0,
                cd_resets_count INTEGER NOT NULL DEFAULT 0,
                cd_reset_expires REAL NOT NULL DEFAULT 0,
                channel_bonus_claimed INTEGER NOT NULL DEFAULT 0,
                last_weekly_bonus REAL NOT NULL DEFAULT 0,
                attack_block_until REAL NOT NULL DEFAULT 0,
                blade_hidden INTEGER NOT NULL DEFAULT 0,
                armor_hidden INTEGER NOT NULL DEFAULT 0,
                shield_hidden INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL DEFAULT 0,
                experience INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                league_index INTEGER NOT NULL DEFAULT 0,
                clan_id INTEGER,
                personal_experience INTEGER NOT NULL DEFAULT 0,
                last_private_activity REAL NOT NULL DEFAULT 0,
                last_group_chat_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                rarity TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                card_id INTEGER NOT NULL,
                count INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                subtype TEXT NOT NULL DEFAULT '',
                amount INTEGER NOT NULL DEFAULT 0,
                hidden_amount INTEGER NOT NULL DEFAULT 0,
                blocked_until REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER NOT NULL DEFAULT 0,
                added_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL DEFAULT '',
                inactivity_interval REAL NOT NULL DEFAULT 3600,
                last_activity REAL NOT NULL DEFAULT 0,
                last_chest_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS group_rewards (
                chat_id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL DEFAULT 0,
                reward_claimed INTEGER NOT NULL DEFAULT 0,
                member_count INTEGER NOT NULL DEFAULT 0,
                rewarded_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS owner_group_counts (
                owner_id INTEGER PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                p_type TEXT NOT NULL,
                reward_type TEXT NOT NULL,
                reward_val INTEGER NOT NULL DEFAULT 0,
                expires_at REAL NOT NULL,
                is_used INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS promo_claims (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                PRIMARY KEY(user_id, code)
            );

            CREATE TABLE IF NOT EXISTS admin_codes (
                code TEXT PRIMARY KEY,
                created_by INTEGER NOT NULL,
                expires_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL DEFAULT 0,
                action TEXT NOT NULL,
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                p1 INTEGER NOT NULL,
                p2 INTEGER NOT NULL,
                p1_card INTEGER,
                p2_card INTEGER,
                p1_confirmed INTEGER NOT NULL DEFAULT 0,
                p2_confirmed INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chests (
                chest_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                chest_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                claimed_by INTEGER,
                claimed_at REAL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clans (
                clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_number INTEGER NOT NULL UNIQUE,
                name TEXT NOT NULL UNIQUE,
                owner_id INTEGER NOT NULL,
                clan_coins INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                experience INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                deleted_at REAL,
                owner_change_locked_until REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS clan_members (
                clan_id INTEGER NOT NULL,
                user_id INTEGER PRIMARY KEY,
                joined_at REAL NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                donated_coins INTEGER NOT NULL DEFAULT 0,
                personal_experience INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS clan_name_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER NOT NULL,
                old_name TEXT NOT NULL,
                new_name TEXT NOT NULL,
                changed_by INTEGER NOT NULL,
                changed_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clan_bans (
                user_id INTEGER PRIMARY KEY,
                expires_at REAL NOT NULL DEFAULT 0,
                changed_by INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS clan_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER NOT NULL,
                old_owner_id INTEGER NOT NULL,
                new_owner_id INTEGER NOT NULL,
                changed_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clan_quests (
                quest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                quest_date TEXT NOT NULL,
                slot INTEGER NOT NULL,
                quest_type TEXT NOT NULL,
                target INTEGER NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                difficulty TEXT NOT NULL,
                clan_reward INTEGER NOT NULL DEFAULT 0,
                fem_reward INTEGER NOT NULL DEFAULT 0,
                xp_reward INTEGER NOT NULL DEFAULT 0,
                claimed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, quest_date, slot)
            );

            CREATE TABLE IF NOT EXISTS clan_shop_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                product TEXT NOT NULL,
                price INTEGER NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                telegram_charge_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_actions (
                user_id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                expires_at REAL NOT NULL
            );
            """
        )

        await _add_columns(
            db,
            "users",
            {
                "shield_hidden": "INTEGER NOT NULL DEFAULT 0",
                "experience": "INTEGER NOT NULL DEFAULT 0",
                "level": "INTEGER NOT NULL DEFAULT 1",
                "league_index": "INTEGER NOT NULL DEFAULT 0",
                "clan_id": "INTEGER",
                "personal_experience": "INTEGER NOT NULL DEFAULT 0",
                "last_private_activity": "REAL NOT NULL DEFAULT 0",
                "last_group_chat_id": "INTEGER",
            },
        )

        await _add_columns(
            db,
            "chats",
            {
                "last_activity": "REAL NOT NULL DEFAULT 0",
                "last_chest_at": "REAL NOT NULL DEFAULT 0",
            },
        )

        await _add_columns(
            db,
            "clans",
            {
                "updated_at": "REAL NOT NULL DEFAULT 0",
                "deleted_at": "REAL",
                "owner_change_locked_until": "REAL NOT NULL DEFAULT 0",
            },
        )

        async with db.execute(
            """
            SELECT user_id, card_id, SUM(count) AS total
            FROM inventory
            GROUP BY user_id, card_id
            HAVING COUNT(*) > 1
            """
        ) as cursor:
            duplicates = await cursor.fetchall()

        for duplicate in duplicates:
            u_id = int(duplicate["user_id"])
            c_id = int(duplicate["card_id"])
            total = int(duplicate["total"])

            async with db.execute(
                "SELECT id FROM inventory WHERE user_id = ? AND card_id = ? ORDER BY id",
                (u_id, c_id),
            ) as c:
                rows = await c.fetchall()

            if rows:
                keep_id = int(rows[0]["id"])
                await db.execute("UPDATE inventory SET count = ? WHERE id = ?", (total, keep_id))
                del_ids = [int(r["id"]) for r in rows[1:]]
                if del_ids:
                    pl = ",".join("?" for _ in del_ids)
                    await db.execute(f"DELETE FROM inventory WHERE id IN ({pl})", del_ids)

        async with db.execute(
            """
            SELECT user_id, artifact_type, subtype, SUM(amount) AS total
            FROM artifacts
            GROUP BY user_id, artifact_type, subtype
            HAVING COUNT(*) > 1
            """
        ) as cursor:
            dup_art = await cursor.fetchall()

        for d in dup_art:
            u_id = int(d["user_id"])
            a_type = str(d["artifact_type"])
            sub = str(d["subtype"] or "")
            total = int(d["total"] or 0)

            async with db.execute(
                """
                SELECT id FROM artifacts
                WHERE user_id = ? AND artifact_type = ? AND subtype = ?
                ORDER BY id
                """,
                (u_id, a_type, sub),
            ) as c:
                rows = await c.fetchall()

            if rows:
                keep_id = int(rows[0]["id"])
                await db.execute("UPDATE artifacts SET amount = ? WHERE id = ?", (total, keep_id))
                del_ids = [int(r["id"]) for r in rows[1:]]
                if del_ids:
                    pl = ",".join("?" for _ in del_ids)
                    await db.execute(f"DELETE FROM artifacts WHERE id IN ({pl})", del_ids)

        await db.execute(
            """
            UPDATE users SET first_seen = ?
            WHERE first_seen IS NULL OR first_seen = 0
            """,
            (now(),),
        )

        await db.execute(
            """
            UPDATE clans SET updated_at = created_at
            WHERE updated_at IS NULL OR updated_at = 0
            """
        )

        await db.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_user_card ON inventory(user_id, card_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_unique ON artifacts(user_id, artifact_type, subtype);
            CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id);
            CREATE INDEX IF NOT EXISTS idx_inventory_card ON inventory(card_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_user ON artifacts(user_id);
            CREATE INDEX IF NOT EXISTS idx_clan_members_clan ON clan_members(clan_id);
            CREATE INDEX IF NOT EXISTS idx_quests_user_date ON clan_quests(user_id, quest_date);
            CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """
        )

        await db.commit()


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    *,
    referred_by: int = 0,
) -> bool:
    username = username or str(user_id)
    if referred_by == user_id:
        referred_by = 0

    async with transaction() as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            existing = await cursor.fetchone()

        if existing:
            await db.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                (username, user_id),
            )
            return False

        await db.execute(
            """
            INSERT INTO users(user_id, username, referred_by, first_seen)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, username, referred_by, now()),
        )
        return True


async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    async with connect() as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()


async def find_user_by_username(username: str) -> Optional[int]:
    username = username.strip().lstrip("@").lower()
    async with connect() as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE LOWER(REPLACE(username, '@', '')) = ? LIMIT 1",
            (username,),
        ) as cursor:
            row = await cursor.fetchone()
    return int(row["user_id"]) if row else None


async def add_coins(user_id: int, amount: int) -> None:
    async with transaction() as db:
        await db.execute(
            "UPDATE users SET femcoins = MAX(0, femcoins + ?) WHERE user_id = ?",
            (amount, user_id),
        )


async def get_setting(key: str) -> Optional[str]:
    async with connect() as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
    return str(row["value"]) if row else None


async def set_setting(key: str, value: str) -> None:
    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


async def log_action(admin_id: int, action: str) -> None:
    async with transaction() as db:
        await db.execute(
            "INSERT INTO logs(admin_id, action, timestamp) VALUES (?, ?, ?)",
            (admin_id, action[:3000], now()),
        )
