from __future__ import annotations

import asyncio
import logging
import random

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import connect, now, transaction
from utils import (
    answer_callback,
    command_is,
    display_name,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.casino")

BETS = (10, 20, 50, 100)
user_bets: dict[int, int] = {}
casino_locks: dict[int, asyncio.Lock] = {}


def get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in casino_locks:
        casino_locks[user_id] = asyncio.Lock()
    return casino_locks[user_id]


def casino_keyboard(bet: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if bet == value else ''}{value} 🪙",
                    callback_data=f"casino:bet:{value}",
                )
                for value in BETS
            ],
            [
                InlineKeyboardButton(
                    text=f"🎲 Кости — {bet} 🪙",
                    callback_data="casino:play:dice",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔴 Красное ×2 — {bet}",
                    callback_data="casino:play:red",
                ),
                InlineKeyboardButton(
                    text=f"⚫ Чёрное ×2 — {bet}",
                    callback_data="casino:play:black",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🟢 Зеро ×14 — {bet}",
                    callback_data="casino:play:zero",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🎰 Слоты — {bet} 🪙",
                    callback_data="casino:play:slots",
                )
            ],
        ]
    )


def casino_text(bet: int) -> str:
    return (
        "🎰✨ <b>ФЕМБОЙСКОЕ КАЗИНО</b> ✨🎰\n\n"
        f"💰 Текущая ставка: <b>{bet} 🪙</b>\n\n"
        "🎲 Кости: победа — чистая прибыль ставки!\n"
        "🔴 Красное / ⚫ чёрное: множитель ×2!\n"
        "🟢 Зеро: множитель ×14!\n"
        "🎰 Три 7️⃣: множитель ×15!"
    )


@router.message(
    lambda message: command_is(message, "казино", "kaz")
)
async def casino_command(message: Message) -> None:
    bet = user_bets.get(message.from_user.id, 20)

    await message.answer(
        casino_text(bet),
        reply_markup=casino_keyboard(bet),
    )


@router.callback_query(
    F.data.startswith("casino:bet:")
)
async def casino_bet_callback(
    callback: CallbackQuery,
) -> None:
    try:
        bet = int(
            (callback.data or "").rsplit(":", 1)[-1]
        )
    except ValueError:
        await answer_callback(
            callback,
            "Некорректная ставка",
            alert=True,
        )
        return

    if bet not in BETS:
        await answer_callback(
            callback,
            "Такой ставки нет",
            alert=True,
        )
        return

    user_bets[callback.from_user.id] = bet

    try:
        await callback.message.edit_text(
            casino_text(bet),
            reply_markup=casino_keyboard(bet),
        )
    except Exception:
        logger.exception("Ошибка обновления меню казино")

    await answer_callback(
        callback,
        f"Ставка выбрана: {bet} 🪙",
    )


@router.callback_query(
    F.data.startswith("casino:play:")
)
async def casino_play_callback(
    callback: CallbackQuery,
) -> None:
    action = (callback.data or "").rsplit(":", 1)[-1]

    if action not in {
        "dice",
        "red",
        "black",
        "zero",
        "slots",
    }:
        await answer_callback(
            callback,
            "Неизвестная игра",
            alert=True,
        )
        return

    user_id = callback.from_user.id
    bet = user_bets.get(user_id, 20)

    async with get_lock(user_id):
        async with transaction() as db:
            async with db.execute(
                """
                SELECT femcoins
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            if not user or safe_int(user["femcoins"]) < bet:
                await answer_callback(
                    callback,
                    "Недостаточно фемкоинов 🪙",
                    alert=True,
                )
                return

            if action in {"red", "black", "zero"} and bet < 20:
                await answer_callback(
                    callback,
                    "Для рулетки нужна ставка минимум 20 🪙",
                    alert=True,
                )
                return

            # Ставка списывается ровно один раз.
            changed = await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins - ?
                WHERE user_id = ?
                  AND femcoins >= ?
                """,
                (bet, user_id, bet),
            )

            if changed.rowcount != 1:
                await answer_callback(
                    callback,
                    "Баланс изменился. Повтори игру.",
                    alert=True,
                )
                return

            player = display_name(callback.from_user)

            if action == "dice":
                player_roll = random.randint(1, 6)
                bot_roll = random.randint(1, 6)

                if player_roll > bot_roll:
                    await db.execute(
                        """
                        UPDATE users
                        SET femcoins = femcoins + ?
                        WHERE user_id = ?
                        """,
                        (bet * 2, user_id),
                    )
                    result = (
                        "🎲✨ <b>ПОБЕДА!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 {player_roll} против {bot_roll}\n"
                        f"💰 Прибыль: <b>+{bet} 🪙</b>"
                    )

                elif player_roll == bot_roll:
                    await db.execute(
                        """
                        UPDATE users
                        SET femcoins = femcoins + ?
                        WHERE user_id = ?
                        """,
                        (bet, user_id),
                    )
                    result = (
                        "🎲🤝 <b>НИЧЬЯ!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 {player_roll} и {bot_roll}\n"
                        "💰 Ставка возвращена!"
                    )

                else:
                    result = (
                        "🎲💔 <b>ПОРАЖЕНИЕ!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 {player_roll} против {bot_roll}\n"
                        f"💸 Потеря: <b>-{bet} 🪙</b>"
                    )

            elif action in {"red", "black", "zero"}:
                number = random.randint(0, 36)

                if number == 0:
                    color = "zero"
                    color_text = "🟢 зеро"
                elif number % 2:
                    color = "red"
                    color_text = "🔴 красное"
                else:
                    color = "black"
                    color_text = "⚫ чёрное"

                if color == action:
                    multiplier = 14 if action == "zero" else 2
                    total_return = bet * multiplier

                    await db.execute(
                        """
                        UPDATE users
                        SET femcoins = femcoins + ?
                        WHERE user_id = ?
                        """,
                        (total_return, user_id),
                    )

                    result = (
                        "🎡✨ <b>РУЛЕТКА — ПОБЕДА!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 Выпало: <b>{number}</b> ({color_text})\n"
                        f"💰 Прибыль: "
                        f"<b>+{total_return - bet} 🪙</b>"
                    )
                else:
                    result = (
                        "🎡💔 <b>РУЛЕТКА — ПОРАЖЕНИЕ!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 Выпало: <b>{number}</b> ({color_text})\n"
                        f"💸 Потеря: <b>-{bet} 🪙</b>"
                    )

            else:
                symbols = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
                slots = random.choices(symbols, k=3)

                if slots == ["7️⃣", "7️⃣", "7️⃣"]:
                    multiplier = 15
                elif slots[0] == slots[1] == slots[2]:
                    multiplier = 4
                else:
                    multiplier = 0

                if multiplier:
                    total_return = bet * multiplier

                    await db.execute(
                        """
                        UPDATE users
                        SET femcoins = femcoins + ?
                        WHERE user_id = ?
                        """,
                        (total_return, user_id),
                    )

                    result = (
                        "🎰✨ <b>СЛОТЫ — ПОБЕДА!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 {' | '.join(slots)}\n"
                        f"💰 Прибыль: "
                        f"<b>+{total_return - bet} 🪙</b>"
                    )
                else:
                    result = (
                        "🎰💔 <b>СЛОТЫ — ПРОИГРЫШ!</b>\n"
                        f"👤 Игрок: {player}\n"
                        f"🎯 {' | '.join(slots)}\n"
                        f"💸 Потеря: <b>-{bet} 🪙</b>"
                    )

            await db.execute(
                """
                UPDATE users
                SET experience = experience + 1
                WHERE user_id = ?
                """,
                (user_id,),
            )

        # Результат отправляется ответом на меню казино.
        try:
            await callback.message.reply(result)
        except Exception:
            logger.exception(
                "Ошибка отправки результата казино"
            )

    await answer_callback(callback)
