from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import CHANNEL_URL
from database import connect, now, transaction
from keyboards import card_navigation_keyboard
from utils import answer_callback, command_is, esc, safe_float, safe_int

router = Router()
logger = logging.getLogger("femboy_bot.cards")

RARITIES = [
    "Редкое",
    "Ультра редкое",
    "Мифическое",
    "Легендарное",
    "Фембойский артефакт",
    "Редчайший фем",
]

RARITY_INDEX = {
    rarity: index
    for index, rarity in enumerate(RARITIES)
}

BASE_WEIGHTS = {
    "Редкое": 58.0,
    "Ультра редкое": 28.0,
    "Мифическое": 10.0,
    "Легендарное": 0.9,
    "Фембойский артефакт": 0.3,
    "Редчайший фем": 0.1,
}

LUCK_WEIGHTS = {
    "Редкое": 20.0,
    "Ультра редкое": 35.0,
    "Мифическое": 30.0,
    "Легендарное": 10.0,
    "Фембойский артефакт": 3.5,
    "Редчайший фем": 1.5,
}

VIP_WEIGHTS = {
    "Редкое": 52.0,
    "Ультра редкое": 31.0,
    "Мифическое": 13.0,
    "Легендарное": 0.9,
    "Фембойский артефакт": 0.3,
    "Редчайший фем": 0.1,
}

DUPLICATE_COMPENSATION = {
    "Редкое": 5,
    "Ультра редкое": 10,
    "Мифическое": 15,
    "Легендарное": 20,
    "Фембойский артефакт": 25,
    "Редчайший фем": 30,
}

_user_locks: dict[int, asyncio.Lock] = {}


def user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


async def card_keyboard() -> InlineKeyboardMarkup:
    bot_info = await router.bot.get_me()

    rows = [
        [
            InlineKeyboardButton(
                text="🎁 Забрать бонус ✨",
                url=f"https://t.me/{bot_info.username}?start=bonus",
            )
        ]
    ]

    async with connect() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'post_btn_url'"
        ) as cursor:
            row = await cursor.fetchone()

    if row and row["value"]:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💖 Присоединиться / Подробнее",
                    url=str(row["value"]),
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def select_card(
    db,
    weights: dict[str, float],
):
    async with db.execute(
        "SELECT DISTINCT rarity FROM cards"
    ) as cursor:
        available_rows = await cursor.fetchall()

    available = {
        str(row["rarity"])
        for row in available_rows
    }

    rarities = [
        rarity
        for rarity in weights
        if rarity in available
    ]

    if not rarities:
        async with db.execute(
            """
            SELECT id, file_id, rarity, description
            FROM cards
            ORDER BY RANDOM()
            LIMIT 1
            """
        ) as cursor:
            return await cursor.fetchone()

    rarity = random.choices(
        rarities,
        weights=[weights[value] for value in rarities],
        k=1,
    )[0]

    async with db.execute(
        """
        SELECT id, file_id, rarity, description
        FROM cards
        WHERE rarity = ?
        ORDER BY RANDOM()
        LIMIT 1
        """,
        (rarity,),
    ) as cursor:
        card = await cursor.fetchone()

    if card:
        return card

    async with db.execute(
        """
        SELECT id, file_id, rarity, description
        FROM cards
        ORDER BY RANDOM()
        LIMIT 1
        """
    ) as cursor:
        return await cursor.fetchone()


async def add_card_to_inventory(
    db,
    user_id: int,
    card_id: int,
) -> bool:
    async with db.execute(
        """
        SELECT count
        FROM inventory
        WHERE user_id = ? AND card_id = ?
        """,
        (user_id, card_id),
    ) as cursor:
        existing = await cursor.fetchone()

    if existing:
        await db.execute(
            """
            UPDATE inventory
            SET count = count + 1
            WHERE user_id = ? AND card_id = ?
            """,
            (user_id, card_id),
        )
        return True

    await db.execute(
        """
        INSERT INTO inventory(user_id, card_id, count)
        VALUES (?, ?, 1)
        """,
        (user_id, card_id),
    )
    return False


async def draw_card(
    user_id: int,
    *,
    vip: bool,
    lucky: bool,
    force_duplicate: bool = False,
) -> Optional[dict[str, Any]]:
    weights = (
        VIP_WEIGHTS
        if vip and not force_duplicate
        else LUCK_WEIGHTS
        if lucky
        else BASE_WEIGHTS
    )

    async with transaction() as db:
        card = None

        if force_duplicate:
            async with db.execute(
                """
                SELECT c.id, c.file_id, c.rarity, c.description
                FROM inventory i
                JOIN cards c ON c.id = i.card_id
                WHERE i.user_id = ?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (user_id,),
            ) as cursor:
                card = await cursor.fetchone()

        if not card:
            card = await select_card(db, weights)

        if not card:
            return None

        card_id = safe_int(card["id"])
        rarity = str(card["rarity"])
        duplicate = await add_card_to_inventory(
            db,
            user_id,
            card_id,
        )

        compensation = (
            DUPLICATE_COMPENSATION.get(rarity, 5)
            if duplicate and vip
            else 0
        )

        if compensation:
            await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins + ?
                WHERE user_id = ?
                """,
                (compensation, user_id),
            )

        # Квесты подключаются отдельно; импортируем внутри функции,
        # чтобы не создавать циклический импорт при старте.
        try:
            from handlers.quests import update_quest_progress

            await update_quest_progress(
                user_id,
                "fem",
                1,
            )

            if rarity in {
                "Легендарное",
                "Фембойский артефакт",
                "Редчайший фем",
            }:
                await update_quest_progress(
                    user_id,
                    "rare_card",
                    1,
                )

            if vip and force_duplicate:
                await update_quest_progress(
                    user_id,
                    "vip_card",
                    1,
                )
        except Exception:
            logger.exception("Не удалось обновить квест за карту")

        # Опыт начисляется здесь атомарно с картой.
        try:
            from handlers.quests import award_experience

            await award_experience(
                db,
                user_id,
                2,
            )
        except ImportError:
            await db.execute(
                """
                UPDATE users
                SET experience = experience + 2
                WHERE user_id = ?
                """,
                (user_id,),
            )
        except Exception:
            logger.exception("Не удалось начислить опыт за карту")

        return {
            "id": card_id,
            "file_id": card["file_id"],
            "rarity": rarity,
            "description": str(card["description"] or ""),
            "duplicate": duplicate,
            "compensation": compensation,
        }


def card_caption(
    card: dict[str, Any],
    *,
    second: bool = False,
) -> str:
    title = (
        "👑💖 <b>VIP-БОНУС: ВТОРАЯ КАРТА!</b> 💖👑"
        if second
        else "✨🎴 <b>ТЕБЕ ВЫПАЛА КАРТА!</b> 🎴✨"
    )

    lines = [
        title,
        "",
        f"🎴 Номер: <b>#{safe_int(card['id'])}</b>",
        f"🏷 Редкость: <b>{esc(card['rarity'])}</b>",
        f"📝 Описание: <b>{esc(card['description']) or 'Без описания'}</b>",
    ]

    if card["duplicate"]:
        lines.append(
            "\n🔁 <i>Дубликат! Его можно использовать "
            "для крафта или обмена.</i>"
        )
    else:
        lines.append(
            "\n🆕 <i>Новая карта в твоей коллекции!</i>"
        )

    if card["compensation"]:
        lines.append(
            f"💰 VIP-компенсация: "
            f"<b>+{safe_int(card['compensation'])} 🪙</b>"
        )

    lines.append("💫 Опыт: <b>+2</b>")

    return "\n".join(lines)


async def cooldown_seconds(
    db,
    user_id: int,
    timestamp: float,
) -> float:
    async with db.execute(
        """
        SELECT custom_cd_hours,
               custom_cd_expires,
               vip_until
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ) as cursor:
        user = await cursor.fetchone()

    if not user:
        return 3 * 3600

    custom_expiry = safe_float(
        user["custom_cd_expires"]
    )

    if (
        custom_expiry == -1
        or custom_expiry > timestamp
    ):
        return max(
            0,
            safe_float(user["custom_cd_hours"], 3) * 3600,
        )

    if safe_float(user["vip_until"]) > timestamp:
        return 2 * 3600

    return 3 * 3600


@router.message(
    lambda message: command_is(
        message,
        "фем",
        "fem",
        "foto",
    )
)
async def fem_command(message: Message) -> None:
    user_id = message.from_user.id

    async with user_lock(user_id):
        timestamp = now()

        async with transaction() as db:
            async with db.execute(
                """
                SELECT last_fem_time,
                       cd_resets_count,
                       cd_reset_expires,
                       luck_expires,
                       vip_until,
                       attack_block_until
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            if not user:
                await message.answer("💔 Сначала запусти бота через /start.")
                return

            attack_block = safe_float(
                user["attack_block_until"]
            )

            if attack_block > timestamp:
                await message.answer(
                    "🚫💔 <b>Сбор карт временно запрещён!</b>\n"
                    f"Осталось: <b>{int(attack_block - timestamp)} сек.</b>"
                )
                return

            cooldown = await cooldown_seconds(
                db,
                user_id,
                timestamp,
            )

            last_fem = safe_float(
                user["last_fem_time"]
            )
            elapsed = timestamp - last_fem

            skips = safe_int(
                user["cd_resets_count"]
            )
            skip_expiry = safe_float(
                user["cd_reset_expires"]
            )

            if skip_expiry <= timestamp:
                skips = 0

            if elapsed < cooldown:
                if skips <= 0:
                    remaining = int(cooldown - elapsed)
                    await message.answer(
                        "⏳💖 <b>Ещё рано!</b>\n"
                        f"До следующей карты: <b>{remaining} сек.</b>"
                    )
                    return

                skips -= 1
                await db.execute(
                    """
                    UPDATE users
                    SET cd_resets_count = ?,
                        cd_reset_expires = ?
                    WHERE user_id = ?
                    """,
                    (
                        skips,
                        skip_expiry if skips else 0,
                        user_id,
                    ),
                )

            await db.execute(
                """
                UPDATE users
                SET last_fem_time = ?
                WHERE user_id = ?
                """,
                (timestamp, user_id),
            )

            vip = safe_float(user["vip_until"]) > timestamp
            lucky = safe_float(user["luck_expires"]) > timestamp

        first = await draw_card(
            user_id,
            vip=vip,
            lucky=lucky,
        )

        if not first:
            await message.answer(
                "😿🎴 В библиотеке пока нет карт."
            )
            return

        markup = await card_keyboard()

        await message.answer_photo(
            photo=first["file_id"],
            caption=card_caption(first),
            reply_markup=markup,
        )

        if vip and random.random() < 0.20:
            second = await draw_card(
                user_id,
                vip=True,
                lucky=lucky,
                force_duplicate=True,
            )

            if second:
                await asyncio.sleep(0.2)
                await message.answer_photo(
                    photo=second["file_id"],
                    caption=card_caption(second, second=True),
                    reply_markup=markup,
                )

        # Сундук появляется только после успешного получения карты.
        try:
            from handlers.chests import maybe_spawn_after_fem

            await maybe_spawn_after_fem(message)
        except Exception:
            logger.exception("Ошибка появления сундука после фема")


@router.message(
    lambda message: command_is(
        message,
        "крафт",
        "craft",
    )
)
async def card_craft_command(
    message: Message,
) -> None:
    async with connect() as db:
        async with db.execute(
            """
            SELECT c.rarity,
                   SUM(i.count - 1) AS duplicates
            FROM inventory i
            JOIN cards c ON c.id = i.card_id
            WHERE i.user_id = ?
              AND i.count > 1
            GROUP BY c.rarity
            HAVING duplicates >= 3
            """,
            (message.from_user.id,),
        ) as cursor:
            rows = await cursor.fetchall()

    rarities = [
        str(row["rarity"])
        for row in rows
        if str(row["rarity"]) in RARITY_INDEX
        and RARITY_INDEX[str(row["rarity"])] < len(RARITIES) - 1
    ]

    if not rarities:
        await message.answer(
            "💔 Для крафта нужны 3 свободных дубликата "
            "одной редкости. Основная копия не тратится!"
        )
        return

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        f"⚒️ {rarity} → "
                        f"{RARITIES[RARITY_INDEX[rarity] + 1]}"
                    ),
                    callback_data=f"craft:card:{RARITY_INDEX[rarity]}",
                )
            ]
            for rarity in rarities
        ]
    )

    await message.answer(
        "⚒️✨ <b>КРАФТ КАРТ</b> ✨⚒️\n"
        "Выбери редкость. Основные копии сохраняются.",
        reply_markup=markup,
    )


@router.callback_query(
    F.data.startswith("craft:card:")
)
async def card_craft_callback(
    callback: CallbackQuery,
) -> None:
    try:
        rarity_index = int(
            (callback.data or "").rsplit(":", 1)[-1]
        )
        rarity = RARITIES[rarity_index]
        target_rarity = RARITIES[rarity_index + 1]
    except (ValueError, IndexError):
        await answer_callback(
            callback,
            "Некорректная редкость",
            alert=True,
        )
        return

    user_id = callback.from_user.id

    async with user_lock(user_id):
        async with transaction() as db:
            async with db.execute(
                """
                SELECT i.id, i.count
                FROM inventory i
                JOIN cards c ON c.id = i.card_id
                WHERE i.user_id = ?
                  AND c.rarity = ?
                  AND i.count > 1
                """,
                (user_id, rarity),
            ) as cursor:
                rows = await cursor.fetchall()

            if sum(max(0, safe_int(row["count"]) - 1) for row in rows) < 3:
                await answer_callback(
                    callback,
                    "Дубликатов уже недостаточно",
                    alert=True,
                )
                return

            async with db.execute(
                """
                SELECT id, file_id, description
                FROM cards
                WHERE rarity = ?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (target_rarity,),
            ) as cursor:
                target = await cursor.fetchone()

            if not target:
                await answer_callback(
                    callback,
                    f"Карт «{target_rarity}» пока нет",
                    alert=True,
                )
                return

            remaining = 3

            for row in rows:
                free = max(0, safe_int(row["count"]) - 1)
                take = min(free, remaining)

                if take:
                    await db.execute(
                        """
                        UPDATE inventory
                        SET count = count - ?
                        WHERE id = ?
                          AND count >= ?
                        """,
                        (
                            take,
                            safe_int(row["id"]),
                            take + 1,
                        ),
                    )

                remaining -= take

                if remaining == 0:
                    break

            gamble = rarity_index >= RARITY_INDEX["Легендарное"]
            success = (
                random.random() < 0.35
                if gamble
                else True
            )

            if not success:
                coins = random.choices(
                    [50, 100, 150, 200, 350],
                    weights=[40, 25, 18, 12, 5],
                    k=1,
                )[0]

                await db.execute(
                    """
                    UPDATE users
                    SET femcoins = femcoins + ?,
                        experience = experience + 2
                    WHERE user_id = ?
                    """,
                    (coins, user_id),
                )

                text = (
                    "💥💔 <b>КРАФТ НЕ УДАЛСЯ!</b>\n\n"
                    f"💰 Компенсация: <b>+{coins} 🪙</b>\n"
                    "💫 Опыт: <b>+2</b>"
                )
                card_file_id = None
            else:
                await db.execute(
                    """
                    INSERT INTO inventory(user_id, card_id, count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(user_id, card_id)
                    DO UPDATE SET count = count + 1
                    """,
                    (user_id, safe_int(target["id"])),
                )

                await db.execute(
                    """
                    UPDATE users
                    SET experience = experience + 2
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )

                text = (
                    "🎉💖 <b>КРАФТ УСПЕШЕН!</b>\n\n"
                    f"🎴 Карта #{safe_int(target['id'])}\n"
                    f"🏷 Редкость: <b>{esc(target_rarity)}</b>\n"
                    f"📝 {esc(target['description']) or 'Без описания'}\n"
                    "💫 Опыт: <b>+2</b>"
                )
                card_file_id = target["file_id"]

    if card_file_id:
        await callback.message.answer_photo(
            photo=card_file_id,
            caption=text,
        )
    else:
        await callback.message.answer(text)

    await answer_callback(callback)
