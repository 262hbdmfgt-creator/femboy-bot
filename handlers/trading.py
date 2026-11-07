from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Optional

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import connect, ensure_user, now, transaction
from utils import (
    answer_callback,
    command_is,
    display_name,
    edit_message_safely,
    esc,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.trading")

trade_locks: dict[str, asyncio.Lock] = {}


def trade_lock(trade_id: str) -> asyncio.Lock:
    if trade_id not in trade_locks:
        trade_locks[trade_id] = asyncio.Lock()
    return trade_locks[trade_id]


def trade_invite_keyboard(
    trade_id: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤝 Принять обмен",
                    callback_data=f"trade:accept:{trade_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"trade:cancel:{trade_id}",
                ),
            ]
        ]
    )


def trade_keyboard(
    trade_id: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎴 Выбрать карту",
                    callback_data=f"trade:pick:{trade_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"trade:confirm:{trade_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"trade:cancel:{trade_id}",
                )
            ],
        ]
    )


async def get_trade(
    trade_id: str,
) -> Optional[dict]:
    async with connect() as db:
        async with db.execute(
            """
            SELECT *
            FROM trades
            WHERE trade_id = ?
            """,
            (trade_id,),
        ) as cursor:
            row = await cursor.fetchone()

    return dict(row) if row else None


@router.message(
    lambda message: command_is(
        message,
        "трейд",
        "trade",
    )
)
async def trade_start(
    message: Message,
) -> None:
    if not message.reply_to_message:
        await message.answer(
            "🤝 Команду <b>трейд</b> нужно отправить "
            "ответом на сообщение игрока!"
        )
        return

    sender = message.from_user
    target = message.reply_to_message.from_user

    if not target or target.is_bot:
        await message.answer(
            "❌ Нельзя торговать с ботом!"
        )
        return

    if sender.id == target.id:
        await message.answer(
            "❌ Нельзя торговать с собой!"
        )
        return

    await ensure_user(
        sender.id,
        sender.username or sender.full_name,
    )
    await ensure_user(
        target.id,
        target.username or target.full_name,
    )

    trade_id = secrets.token_urlsafe(18)

    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO trades(
                trade_id,
                p1,
                p2,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (
                trade_id,
                sender.id,
                target.id,
                now(),
                now(),
            ),
        )

    await message.answer(
        "🤝✨ <b>ПРЕДЛОЖЕНИЕ ОБМЕНА!</b> ✨🤝\n\n"
        f"👤 От: {display_name(sender)}\n"
        f"🎯 Для: {display_name(target)}\n\n"
        "Каждый игрок выбирает по одному дубликату.\n"
        "🏷 Редкости карт должны совпадать!",
        reply_markup=trade_invite_keyboard(trade_id),
    )


@router.callback_query(
    F.data.startswith("trade:accept:")
)
async def trade_accept(
    callback: CallbackQuery,
) -> None:
    trade_id = callback.data.removeprefix(
        "trade:accept:"
    )

    async with transaction() as db:
        async with db.execute(
            """
            SELECT p1, p2, status
            FROM trades
            WHERE trade_id = ?
            """,
            (trade_id,),
        ) as cursor:
            trade = await cursor.fetchone()

        if not trade:
            await answer_callback(
                callback,
                "Сделка не найдена 💔",
                alert=True,
            )
            return

        if safe_int(trade["p2"]) != callback.from_user.id:
            await answer_callback(
                callback,
                "Это предложение не тебе!",
                alert=True,
            )
            return

        if trade["status"] != "pending":
            await answer_callback(
                callback,
                "Сделка уже закрыта!",
                alert=True,
            )
            return

        await db.execute(
            """
            UPDATE trades
            SET status = 'active',
                updated_at = ?
            WHERE trade_id = ?
              AND status = 'pending'
            """,
            (now(), trade_id),
        )

    await edit_message_safely(
        callback.message,
        "🔄✨ <b>ОБМЕН ОТКРЫТ!</b> ✨🔄\n\n"
        "Оба игрока должны выбрать по одному "
        "дубликату карты.",
        trade_keyboard(trade_id),
    )

    await answer_callback(
        callback,
        "Обмен принят! 🤝",
    )


@router.callback_query(
    F.data.startswith("trade:pick:")
)
async def trade_pick(
    callback: CallbackQuery,
) -> None:
    trade_id = callback.data.removeprefix(
        "trade:pick:"
    )

    trade = await get_trade(trade_id)

    if not trade or trade["status"] != "active":
        await answer_callback(
            callback,
            "Сделка закрыта 💔",
            alert=True,
        )
        return

    user_id = callback.from_user.id

    if user_id not in {
        safe_int(trade["p1"]),
        safe_int(trade["p2"]),
    }:
        await answer_callback(
            callback,
            "Ты не участник сделки!",
            alert=True,
        )
        return

    async with connect() as db:
        async with db.execute(
            """
            SELECT c.id,
                   c.rarity,
                   i.count
            FROM inventory i
            JOIN cards c ON c.id = i.card_id
            WHERE i.user_id = ?
              AND i.count >= 2
            ORDER BY c.id
            """,
            (user_id,),
        ) as cursor:
            cards = await cursor.fetchall()

    if not cards:
        await answer_callback(
            callback,
            "У тебя нет свободных дубликатов!",
            alert=True,
        )
        return

    buttons = []

    for card in cards:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"🎴 #{safe_int(card['id'])} "
                        f"{esc(card['rarity'])} "
                        f"×{safe_int(card['count'])}"
                    ),
                    callback_data=(
                        f"trade:set:{trade_id}:"
                        f"{safe_int(card['id'])}"
                    ),
                )
            ]
        )

    await callback.message.answer(
        "🎴✨ <b>ВЫБЕРИ ДУБЛИКАТ:</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
    )

    await answer_callback(callback)


@router.callback_query(
    F.data.startswith("trade:set:")
)
async def trade_set(
    callback: CallbackQuery,
) -> None:
    payload = callback.data.removeprefix(
        "trade:set:"
    )

    try:
        trade_id, card_id_raw = payload.rsplit(":", 1)
        card_id = int(card_id_raw)
    except (ValueError, AttributeError):
        await answer_callback(
            callback,
            "Некорректные данные",
            alert=True,
        )
        return

    user_id = callback.from_user.id

    async with transaction() as db:
        async with db.execute(
            """
            SELECT p1, p2, status
            FROM trades
            WHERE trade_id = ?
            """,
            (trade_id,),
        ) as cursor:
            trade = await cursor.fetchone()

        if not trade or trade["status"] != "active":
            await answer_callback(
                callback,
                "Сделка закрыта 💔",
                alert=True,
            )
            return

        if user_id not in {
            safe_int(trade["p1"]),
            safe_int(trade["p2"]),
        }:
            await answer_callback(
                callback,
                "Ты не участник сделки!",
                alert=True,
            )
            return

        async with db.execute(
            """
            SELECT count
            FROM inventory
            WHERE user_id = ?
              AND card_id = ?
            """,
            (user_id, card_id),
        ) as cursor:
            inventory = await cursor.fetchone()

        if not inventory or safe_int(
            inventory["count"]
        ) < 2:
            await answer_callback(
                callback,
                "Карта больше не является дубликатом!",
                alert=True,
            )
            return

        if user_id == safe_int(trade["p1"]):
            await db.execute(
                """
                UPDATE trades
                SET p1_card = ?,
                    p1_confirmed = 0,
                    p2_confirmed = 0,
                    updated_at = ?
                WHERE trade_id = ?
                """,
                (card_id, now(), trade_id),
            )
        else:
            await db.execute(
                """
                UPDATE trades
                SET p2_card = ?,
                    p1_confirmed = 0,
                    p2_confirmed = 0,
                    updated_at = ?
                WHERE trade_id = ?
                """,
                (card_id, now(), trade_id),
            )

    await answer_callback(
        callback,
        "Карта выбрана! Подтверждения сброшены 🔄",
        alert=True,
    )


@router.callback_query(
    F.data.startswith("trade:confirm:")
)
async def trade_confirm(
    callback: CallbackQuery,
) -> None:
    trade_id = callback.data.removeprefix(
        "trade:confirm:"
    )

    lock = trade_lock(trade_id)

    async with lock:
        async with transaction() as db:
            async with db.execute(
                """
                SELECT p1,
                       p2,
                       p1_card,
                       p2_card,
                       p1_confirmed,
                       p2_confirmed,
                       status
                FROM trades
                WHERE trade_id = ?
                """,
                (trade_id,),
            ) as cursor:
                trade = await cursor.fetchone()

            if not trade or trade["status"] != "active":
                await answer_callback(
                    callback,
                    "Сделка закрыта 💔",
                    alert=True,
                )
                return

            p1 = safe_int(trade["p1"])
            p2 = safe_int(trade["p2"])
            user_id = callback.from_user.id

            if user_id not in {p1, p2}:
                await answer_callback(
                    callback,
                    "Ты не участник сделки!",
                    alert=True,
                )
                return

            if not trade["p1_card"] or not trade["p2_card"]:
                await answer_callback(
                    callback,
                    "Оба игрока должны выбрать карты!",
                    alert=True,
                )
                return

            if user_id == p1:
                await db.execute(
                    """
                    UPDATE trades
                    SET p1_confirmed = 1,
                        updated_at = ?
                    WHERE trade_id = ?
                    """,
                    (now(), trade_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE trades
                    SET p2_confirmed = 1,
                        updated_at = ?
                    WHERE trade_id = ?
                    """,
                    (now(), trade_id),
                )

            async with db.execute(
                """
                SELECT p1,
                       p2,
                       p1_card,
                       p2_card,
                       p1_confirmed,
                       p2_confirmed
                FROM trades
                WHERE trade_id = ?
                """,
                (trade_id,),
            ) as cursor:
                updated = await cursor.fetchone()

            if not (
                safe_int(updated["p1_confirmed"])
                and safe_int(updated["p2_confirmed"])
            ):
                await answer_callback(
                    callback,
                    "Ожидаем второго игрока ⏳",
                )
                return

            card_one = safe_int(updated["p1_card"])
            card_two = safe_int(updated["p2_card"])

            async with db.execute(
                """
                SELECT id, rarity
                FROM cards
                WHERE id IN (?, ?)
                """,
                (card_one, card_two),
            ) as cursor:
                card_rows = await cursor.fetchall()

            rarity_map = {
                safe_int(row["id"]): str(row["rarity"])
                for row in card_rows
            }

            if (
                card_one not in rarity_map
                or card_two not in rarity_map
                or rarity_map[card_one] != rarity_map[card_two]
            ):
                await answer_callback(
                    callback,
                    "Редкости карт не совпадают!",
                    alert=True,
                )
                return

            async with db.execute(
                """
                SELECT user_id, card_id, count
                FROM inventory
                WHERE (user_id = ? AND card_id = ?)
                   OR (user_id = ? AND card_id = ?)
                """,
                (p1, card_one, p2, card_two),
            ) as cursor:
                rows = await cursor.fetchall()

            inventory = {
                (
                    safe_int(row["user_id"]),
                    safe_int(row["card_id"]),
                ): safe_int(row["count"])
                for row in rows
            }

            if (
                inventory.get((p1, card_one), 0) < 2
                or inventory.get((p2, card_two), 0) < 2
            ):
                await answer_callback(
                    callback,
                    "Недостаточно дубликатов!",
                    alert=True,
                )
                return

            await db.execute(
                """
                UPDATE inventory
                SET count = count - 1
                WHERE user_id = ?
                  AND card_id = ?
                  AND count >= 2
                """,
                (p1, card_one),
            )

            await db.execute(
                """
                UPDATE inventory
                SET count = count - 1
                WHERE user_id = ?
                  AND card_id = ?
                  AND count >= 2
                """,
                (p2, card_two),
            )

            await db.execute(
                """
                INSERT INTO inventory(user_id, card_id, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = count + 1
                """,
                (p1, card_two),
            )

            await db.execute(
                """
                INSERT INTO inventory(user_id, card_id, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = count + 1
                """,
                (p2, card_one),
            )

            await db.execute(
                """
                UPDATE trades
                SET status = 'completed',
                    updated_at = ?
                WHERE trade_id = ?
                """,
                (now(), trade_id),
            )

    await edit_message_safely(
        callback.message,
        "🎉💖 <b>ОБМЕН УСПЕШНО ЗАВЕРШЁН!</b>\n\n"
        "Карты атомарно переданы!",
    )

    await answer_callback(
        callback,
        "Обмен завершён! 🤝",
    )


@router.callback_query(
    F.data.startswith("trade:cancel:")
)
async def trade_cancel(
    callback: CallbackQuery,
) -> None:
    trade_id = callback.data.removeprefix(
        "trade:cancel:"
    )
    trade = await get_trade(trade_id)

    if not trade:
        await answer_callback(
            callback,
            "Сделка уже удалена",
            alert=True,
        )
        return

    if callback.from_user.id not in {
        safe_int(trade["p1"]),
        safe_int(trade["p2"]),
    }:
        await answer_callback(
            callback,
            "Ты не участник сделки!",
            alert=True,
        )
        return

    async with transaction() as db:
        await db.execute(
            """
            UPDATE trades
            SET status = 'cancelled',
                updated_at = ?
            WHERE trade_id = ?
              AND status NOT IN ('completed', 'cancelled')
            """,
            (now(), trade_id),
        )

    await edit_message_safely(
        callback.message,
        "❌💔 <b>ОБМЕН ОТМЕНЁН!</b>",
    )

    await answer_callback(callback)
