# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import secrets

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
)

from database import connect, now, transaction
from utils import answer_callback, safe_int

router = Router()
logger = logging.getLogger("femboy_bot.clan_shop")


async def get_owner_clan(user_id: int):
    async with connect() as db:
        async with db.execute(
            """
            SELECT c.clan_id,
                   c.clan_number,
                   c.name,
                   c.owner_id,
                   c.clan_coins,
                   c.level
            FROM clans AS c
            JOIN clan_members AS cm ON cm.clan_id = c.clan_id
            WHERE cm.user_id = ?
              AND c.owner_id = ?
              AND c.deleted_at IS NULL
            """,
            (user_id, user_id),
        ) as cursor:
            return await cursor.fetchone()


async def get_member_count(clan_id: int) -> int:
    async with connect() as db:
        async with db.execute(
            "SELECT COUNT(*) AS total FROM clan_members WHERE clan_id = ?",
            (clan_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return safe_int(row["total"] if row else 0)


def product_prices(members: int) -> dict[str, int]:
    if members <= 5:
        luck = 100
    elif members <= 15:
        luck = 300
    elif members <= 30:
        luck = 500
    elif members <= 100:
        luck = 999
    else:
        luck = 1000 + members - 100

    if members <= 50:
        blades = 250 + max(0, members - 1) * 200
    else:
        blades = 10050 + (members - 51) * 250

    if members <= 25:
        xp_price = 1000
        xp_amount = 10
    elif members <= 50:
        xp_price = 3000
        xp_amount = 25
    else:
        xp_price = 8500
        xp_amount = 50

    return {
        "luck": luck,
        "blade": blades,
        "xp": xp_price,
        "xp_amount": xp_amount,
    }


async def purchase_clan_product(user_id: int, product: str) -> str:
    async with transaction() as db:
        async with db.execute(
            """
            SELECT c.clan_id, c.clan_coins, c.level
            FROM clans AS c
            JOIN clan_members AS cm ON cm.clan_id = c.clan_id
            WHERE cm.user_id = ?
              AND cm.role = 'owner'
              AND c.owner_id = ?
              AND c.deleted_at IS NULL
            """,
            (user_id, user_id),
        ) as cursor:
            clan = await cursor.fetchone()

        if not clan:
            return "not_owner"

        clan_id = safe_int(clan["clan_id"])

        async with db.execute(
            "SELECT COUNT(*) AS total FROM clan_members WHERE clan_id = ?",
            (clan_id,),
        ) as cursor:
            count_row = await cursor.fetchone()

        members = max(1, safe_int(count_row["total"]))
        prices = product_prices(members)

        if product == "level":
            price = 100 * (2 ** max(0, safe_int(clan["level"]) - 1))
        else:
            price = prices.get(product, 0)

        if price <= 0:
            return "unknown_product"

        if safe_int(clan["clan_coins"]) < price:
            return "not_enough_coins"

        changed = await db.execute(
            """
            UPDATE clans
            SET clan_coins = clan_coins - ?
            WHERE clan_id = ? AND clan_coins >= ?
            """,
            (price, clan_id, price),
        )

        if changed.rowcount != 1:
            return "not_enough_coins"

        if product == "luck":
            await db.execute(
                """
                UPDATE users
                SET luck_expires = MAX(luck_expires, ?)
                WHERE clan_id = ?
                """,
                (now() + 3 * 3600, clan_id),
            )

        elif product == "blade":
            await db.execute(
                """
                INSERT INTO artifacts(user_id, artifact_type, subtype, amount, created_at)
                SELECT user_id, 'blade', '', 1, ?
                FROM clan_members
                WHERE clan_id = ?
                ON CONFLICT(user_id, artifact_type, subtype)
                DO UPDATE SET amount = amount + 1
                """,
                (now(), clan_id),
            )

        elif product == "xp":
            await db.execute(
                """
                UPDATE users
                SET personal_experience = personal_experience + ?
                WHERE user_id = ?
                """,
                (prices["xp_amount"], user_id),
            )

        elif product == "level":
            await db.execute(
                "UPDATE clans SET level = level + 1, updated_at = ? WHERE clan_id = ?",
                (now(), clan_id),
            )

        else:
            return "unknown_product"

        await db.execute(
            """
            INSERT INTO clan_shop_purchases(clan_id, user_id, product, price, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clan_id, user_id, product, price, now()),
        )

    return "ok"


@router.callback_query(F.data.startswith("clanshop:"))
async def clan_shop_callback(callback: CallbackQuery) -> None:
    product = (callback.data or "").removeprefix("clanshop:")

    if product == "readonly":
        await answer_callback(callback, "Only for clan owner ð", alert=True)
        return

    if product == "stars":
        clan = await get_owner_clan(callback.from_user.id)
        if not clan:
            await answer_callback(callback, "Only for clan owner ð", alert=True)
            return

        clan_id = safe_int(clan["clan_id"])
        order_id = secrets.token_urlsafe(8)
        payload = f"clancoins:{clan_id}:150:{order_id}"

        try:
            await callback.bot.send_invoice(
                chat_id=callback.from_user.id,
                title="150 Clan Coins",
                description="Refill clan balance via Telegram Stars",
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice(label="150 Clan Coins", amount=50)],
                provider_token="",
            )
            await answer_callback(callback, "Invoice sent to PM â­")
        except Exception:
            logger.exception("Failed to send Stars invoice for clan coins")
            await answer_callback(callback, "Open PM with bot first!", alert=True)
        return

    if product not in {"luck", "blade", "xp", "level"}:
        await answer_callback(callback, "Unknown item", alert=True)
        return

    result = await purchase_clan_product(callback.from_user.id, product)

    responses = {
        "not_owner": "Only for clan owner ð",
        "not_enough_coins": "Not enough clan coins ð°",
        "unknown_product": "Item not found ð",
        "ok": "Purchase successful! ð",
    }

    await answer_callback(
        callback,
        responses.get(result, "Purchase failed"),
        alert=True,
    )
