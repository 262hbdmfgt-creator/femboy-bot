from __future__ import annotations

import random
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from database import connect, now, transaction
from keyboards import quest_keyboard
from utils import answer_callback, command_is, esc, safe_int

router = Router()


QUEST_TEMPLATES = [
    ("daily", "Заберите {n} дейлик", "easy", 1, 15, 5, 0),
    ("fem", "Получите {n} карт", "easy", 2, 15, 5, 0),
    ("profile", "Откройте профиль {n} раз", "easy", 2, 15, 5, 0),
    ("casino", "Сыграйте {n} раз в казино", "easy", 3, 15, 5, 0),
    ("transfer", "Переведите {n} фемкоинов", "easy", 20, 15, 5, 0),
    ("chest", "Откройте {n} сундук", "medium", 1, 25, 10, 0),
    ("craft", "Выполните {n} крафт", "medium", 1, 25, 10, 0),
    ("trade", "Завершите {n} трейд", "medium", 1, 25, 10, 0),
    ("cards", "Соберите {n} разных карты", "medium", 3, 25, 10, 0),
    ("coins", "Заработайте {n} фемкоинов", "medium", 50, 25, 10, 0),
    ("artifact", "Получите {n} артефакт", "medium", 1, 25, 10, 0),
    ("rare_card", "Получите {n} редкую карту", "hard", 1, 50, 25, 3),
    ("blade", "Получите {n} клинок", "hard", 1, 50, 25, 3),
    ("shield_craft", "Скрафтите {n} щит", "hard", 1, 50, 25, 3),
    ("vip_card", "Получите {n} VIP-карту", "hard", 1, 50, 25, 3),
]

DIFFICULTY_ICONS = {
    "easy": "🟢",
    "medium": "🟡",
    "hard": "🔴",
}


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def quest_template(
    quest_type: str,
    target: int,
) -> str:
    for item in QUEST_TEMPLATES:
        if item[0] == quest_type:
            return item[1].format(n=target)

    return f"Выполните задание: {target}"


async def ensure_quests(
    user_id: int,
) -> None:
    date = today()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT COUNT(*) AS total
            FROM clan_quests
            WHERE user_id = ?
              AND quest_date = ?
            """,
            (user_id, date),
        ) as cursor:
            row = await cursor.fetchone()

        if safe_int(row["total"]) >= 3:
            return

        # Не допускаем два или три сложных задания.
        easy = [
            item for item in QUEST_TEMPLATES
            if item[2] == "easy"
        ]
        medium = [
            item for item in QUEST_TEMPLATES
            if item[2] == "medium"
        ]
        hard = [
            item for item in QUEST_TEMPLATES
            if item[2] == "hard"
        ]

        selected = [
            random.choice(easy),
            random.choice(medium),
        ]

        if random.random() < 0.35:
            selected.append(random.choice(hard))
        else:
            selected.append(
                random.choice(easy + medium)
            )

        random.shuffle(selected)

        for slot, item in enumerate(selected, 1):
            (
                quest_type,
                _,
                difficulty,
                default_target,
                fem_reward,
                clan_reward,
                xp_reward,
            ) = item

            if difficulty == "easy":
                target = random.randint(
                    max(1, default_target // 2),
                    default_target,
                )
            elif difficulty == "medium":
                target = random.randint(
                    max(1, default_target // 2),
                    default_target,
                )
            else:
                target = default_target

            await db.execute(
                """
                INSERT OR IGNORE INTO clan_quests(
                    user_id,
                    quest_date,
                    slot,
                    quest_type,
                    target,
                    progress,
                    difficulty,
                    clan_reward,
                    fem_reward,
                    xp_reward,
                    claimed
                )
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 0)
                """,
                (
                    user_id,
                    date,
                    slot,
                    quest_type,
                    target,
                    difficulty,
                    clan_reward,
                    fem_reward,
                    xp_reward,
                ),
            )


async def update_quest_progress(
    user_id: int,
    quest_type: str,
    amount: int = 1,
) -> None:
    if amount <= 0:
        return

    await ensure_quests(user_id)

    async with transaction() as db:
        await db.execute(
            """
            UPDATE clan_quests
            SET progress = MIN(target, progress + ?)
            WHERE user_id = ?
              AND quest_date = ?
              AND quest_type = ?
              AND claimed = 0
            """,
            (
                amount,
                user_id,
                today(),
                quest_type,
            ),
        )


async def get_user_quests(
    user_id: int,
):
    await ensure_quests(user_id)

    async with connect() as db:
        async with db.execute(
            """
            SELECT *
            FROM clan_quests
            WHERE user_id = ?
              AND quest_date = ?
            ORDER BY slot
            """,
            (user_id, today()),
        ) as cursor:
            return await cursor.fetchall()


def quest_text(row) -> str:
    progress = min(
        safe_int(row["progress"]),
        safe_int(row["target"]),
    )

    difficulty = str(row["difficulty"])
    icon = DIFFICULTY_ICONS.get(
        difficulty,
        "✨",
    )

    status = (
        "✅ Награда получена"
        if safe_int(row["claimed"])
        else (
            "🎁 Можно забрать"
            if progress >= safe_int(row["target"])
            else "⏳ В процессе"
        )
    )

    text = (
        f"{icon} <b>{safe_int(row['slot'])}.</b> "
        f"{esc(quest_template(row['quest_type'], row['target']))}\n"
        f"   📊 Прогресс: "
        f"<b>{progress}/{safe_int(row['target'])}</b>\n"
        f"   💰 +{safe_int(row['fem_reward'])} 🪙"
        f" | 🏳️ +{safe_int(row['clan_reward'])} кланкоинов\n"
        f"   {status}"
    )

    if safe_int(row["xp_reward"]):
        text += (
            f"\n   💫 +{safe_int(row['xp_reward'])} опыта"
        )

    return text


@router.message(
    lambda message: command_is(
        message,
        "квесты",
        "quests",
    )
)
async def quests_command(
    message: Message,
) -> None:
    rows = await get_user_quests(
        message.from_user.id
    )

    if not rows:
        await message.answer(
            "🧩 Квесты пока не созданы."
        )
        return

    lines = [
        "🧩✨ <b>ТВОИ КВЕСТЫ НА СЕГОДНЯ</b> ✨🧩",
        "",
    ]

    ready_buttons = []
    all_completed = True

    for row in rows:
        lines.append(quest_text(row))
        lines.append("")

        ready = (
            safe_int(row["progress"])
            >= safe_int(row["target"])
            and not safe_int(row["claimed"])
        )

        if ready:
            ready_buttons.append(
                (
                    safe_int(row["slot"]),
                    True,
                )
            )

        if (
            safe_int(row["progress"])
            < safe_int(row["target"])
        ):
            all_completed = False

    markup = quest_keyboard(
        ready_buttons,
        all_completed,
    )

    await message.answer(
        "\n".join(lines),
        reply_markup=markup,
    )


async def claim_one(
    user_id: int,
    slot: int,
) -> str:
    async with transaction() as db:
        async with db.execute(
            """
            SELECT *
            FROM clan_quests
            WHERE user_id = ?
              AND quest_date = ?
              AND slot = ?
            """,
            (user_id, today(), slot),
        ) as cursor:
            quest = await cursor.fetchone()

        if not quest:
            return "not_found"

        if safe_int(quest["claimed"]):
            return "claimed"

        if (
            safe_int(quest["progress"])
            < safe_int(quest["target"])
        ):
            return "not_ready"

        updated = await db.execute(
            """
            UPDATE clan_quests
            SET claimed = 1
            WHERE user_id = ?
              AND quest_date = ?
              AND slot = ?
              AND claimed = 0
            """,
            (user_id, today(), slot),
        )

        if updated.rowcount != 1:
            return "claimed"

        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + ?
            WHERE user_id = ?
            """,
            (
                safe_int(quest["fem_reward"]),
                user_id,
            ),
        )

        async with db.execute(
            """
            SELECT clan_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if user and user["clan_id"]:
            await db.execute(
                """
                UPDATE clans
                SET clan_coins = clan_coins + ?
                WHERE clan_id = ?
                """,
                (
                    safe_int(quest["clan_reward"]),
                    safe_int(user["clan_id"]),
                ),
            )

        return "ok"


@router.callback_query(
    F.data.startswith("quest:claim:")
)
async def claim_quest_callback(
    callback: CallbackQuery,
) -> None:
    raw = callback.data.removeprefix(
        "quest:claim:"
    )

    try:
        slot = int(raw)
    except ValueError:
        await answer_callback(
            callback,
            "Некорректный квест",
            alert=True,
        )
        return

    result = await claim_one(
        callback.from_user.id,
        slot,
    )

    if result == "ok":
        await answer_callback(
            callback,
            "Награда получена! 🎁",
            alert=True,
        )
        await quests_command(callback.message)
    elif result == "claimed":
        await answer_callback(
            callback,
            "Награда уже получена",
            alert=True,
        )
    elif result == "not_ready":
        await answer_callback(
            callback,
            "Квест ещё не выполнен",
            alert=True,
        )
    else:
        await answer_callback(
            callback,
            "Квест не найден",
            alert=True,
        )


@router.callback_query(
    F.data == "quest:claim_all"
)
async def claim_all_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id
    rows = await get_user_quests(user_id)

    if not rows or any(
        safe_int(row["progress"])
        < safe_int(row["target"])
        for row in rows
    ):
        await answer_callback(
            callback,
            "Сначала выполни все три квеста!",
            alert=True,
        )
        return

    claimed = 0

    for row in rows:
        result = await claim_one(
            user_id,
            safe_int(row["slot"]),
        )

        if result == "ok":
            claimed += 1

    # Общая награда за все 3 задания.
    async with transaction() as db:
        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + 10,
                experience = experience + 10
            WHERE user_id = ?
            """,
            (user_id,),
        )

        async with db.execute(
            """
            SELECT clan_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if user and user["clan_id"]:
            await db.execute(
                """
                UPDATE clans
                SET clan_coins = clan_coins + 10
                WHERE clan_id = ?
                """,
                (safe_int(user["clan_id"]),),
            )

    await answer_callback(
        callback,
        "Все награды получены! ✨",
        alert=True,
    )

    await callback.message.answer(
        "🎉✨ <b>ВСЕ КВЕСТЫ ЗАКРЫТЫ!</b> ✨🎉\n\n"
        f"🎁 Забрано заданий: <b>{claimed}</b>\n"
        "💰 Бонус: <b>+10 🪙</b>\n"
        "🏳️ Бонус: <b>+10 кланкоинов</b>\n"
        "💫 Опыт: <b>+10</b>"
    )
