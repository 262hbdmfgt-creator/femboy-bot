from __future__ import annotations

import logging
import random

from aiogram import Bot

from database import connect, now, transaction
from utils import (
    destination_for_user,
    esc,
    send_user_notification,
    safe_int,
)

logger = logging.getLogger("femboy_bot.levels")


LEAGUES = [
    "Деревянная",
    "Каменная",
    "Медная",
    "Железная",
    "Бронзовая",
    "Серебряная",
    "Золотая",
    "Платиновая",
    "Титановая",
    "Ультра фембойская",
]

STAGES = (
    ("Начинающий", 5),
    ("Опытный", 10),
    ("Профессионал", 15),
)


def xp_needed(level: int) -> int:
    """
    Опыт для следующего уровня:
    уровень 1 — 10;
    уровень 2 — 12;
    дальше +4 за уровень.
    """
    level = max(1, level)

    if level == 1:
        return 10

    if level == 2:
        return 12

    return 12 + (level - 2) * 4


def get_rank(
    level: int,
) -> tuple[int, str, int]:
    """
    Считает номер лиги, ступень и номер уровня в ступени.

    Уровни не сбрасываются при переходе между ступенями
    или лигами.
    """
    level = max(1, level)
    position = level - 1

    league_index = min(
        len(LEAGUES) - 1,
        position // 30,
    )
    position_in_league = position % 30

    if position_in_league < 5:
        return (
            league_index,
            "Начинающий",
            position_in_league + 1,
        )

    if position_in_league < 15:
        return (
            league_index,
            "Опытный",
            position_in_league - 5 + 6,
        )

    return (
        league_index,
        "Профессионал",
        position_in_league - 15 + 16,
    )


def stage_reward(
    league_index: int,
    stage: str,
) -> int:
    league_number = league_index + 1

    formulas = {
        "Начинающий": 20 * league_number + 200,
        "Опытный": 30 * league_number + 300,
        "Профессионал": 50 * league_number + 500,
    }

    return formulas[stage]


LEAGUE_REWARDS: dict[int, tuple[int, dict[tuple[str, str], int]]] = {
    # Номер новой лиги: (монеты, {артефакт: количество})
    1: (500, {}),
    2: (600, {("shield", "weak"): 1}),
    3: (
        800,
        {
            ("shield", "weak"): 1,
            ("shield", "reinforced"): 1,
        },
    ),
    4: (
        1000,
        {
            ("blade", ""): 1,
            ("armor", ""): 1,
            ("shield", "reinforced"): 3,
        },
    ),
    5: (
        1500,
        {
            ("blade", ""): 3,
            ("armor", ""): 3,
            ("shield", "femboy"): 2,
            ("shield", "reinforced"): 4,
        },
    ),
    6: (
        2500,
        {
            ("blade", ""): 5,
            ("armor", ""): 5,
            ("shield", "femboy"): 5,
        },
    ),
    7: (5000, {("blade", ""): 15}),
    8: (10000, {("blade", ""): 25}),
    9: (25000, {("blade", ""): 50}),
}


async def _add_artifact(
    db,
    user_id: int,
    artifact_type: str,
    subtype: str,
    amount: int,
) -> None:
    await db.execute(
        """
        INSERT INTO artifacts(
            user_id,
            artifact_type,
            subtype,
            amount,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, artifact_type, subtype)
        DO UPDATE SET amount = amount + excluded.amount
        """,
        (
            user_id,
            artifact_type,
            subtype,
            amount,
            now(),
        ),
    )


async def _notify(
    bot: Bot | None,
    user_id: int,
    text: str,
) -> None:
    if bot is None:
        return

    try:
        await send_user_notification(
            bot,
            user_id,
            text,
        )
    except Exception:
        logger.exception(
            "Не удалось отправить уведомление о повышении: user=%s",
            user_id,
        )


async def award_experience(
    db,
    user_id: int,
    amount: int,
) -> list[dict[str, object]]:
    """
    Добавляет опыт в уже открытую SQLite-транзакцию.

    Возвращает список повышений для последующего уведомления.
    Важно: передаваемый db должен принадлежать активной транзакции.
    """
    if amount <= 0:
        return []

    async with db.execute(
        """
        SELECT experience,
               level,
               femcoins
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ) as cursor:
        user = await cursor.fetchone()

    if not user:
        return []

    experience = max(
        0,
        safe_int(user["experience"]),
    )
    level = max(
        1,
        safe_int(user["level"], 1),
    )
    old_level = level

    experience += amount
    notifications: list[dict[str, object]] = []

    while experience >= xp_needed(level):
        experience -= xp_needed(level)
        level += 1

        old_league, old_stage, _ = get_rank(level - 1)
        new_league, new_stage, _ = get_rank(level)

        level_coins = 5 + 2 * level
        milestone_bonus = 0

        if level % 5 == 0:
            milestone_bonus = 10 + 3 * level

        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + ?
            WHERE user_id = ?
            """,
            (
                level_coins + milestone_bonus,
                user_id,
            ),
        )

        notification: dict[str, object] = {
            "kind": "level",
            "level": level,
            "coins": level_coins + milestone_bonus,
            "milestone": level % 5 == 0,
        }

        if (
            new_league != old_league
            or new_stage != old_stage
        ):
            coins = stage_reward(
                new_league,
                new_stage,
            )

            await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins + ?
                WHERE user_id = ?
                """,
                (coins, user_id),
            )

            artifact = random.choices(
                [
                    ("blade", ""),
                    ("shield", "reinforced"),
                    ("armor", ""),
                ],
                weights=[10, 50, 40],
                k=1,
            )[0]

            await _add_artifact(
                db,
                user_id,
                artifact[0],
                artifact[1],
                1,
            )

            notification.update(
                {
                    "kind": "stage",
                    "league": LEAGUES[new_league],
                    "stage": new_stage,
                    "stage_coins": coins,
                    "stage_artifact": artifact,
                }
            )

        if new_league > old_league:
            league_number = new_league + 1
            league_reward = LEAGUE_REWARDS.get(
                league_number
            )

            if league_reward:
                league_coins, artifacts = league_reward

                await db.execute(
                    """
                    UPDATE users
                    SET femcoins = femcoins + ?
                    WHERE user_id = ?
                    """,
                    (league_coins, user_id),
                )

                for (artifact_type, subtype), count in artifacts.items():
                    await _add_artifact(
                        db,
                        user_id,
                        artifact_type,
                        subtype,
                        count,
                    )

                notification.update(
                    {
                        "kind": "league",
                        "league": LEAGUES[new_league],
                        "league_coins": league_coins,
                        "league_artifacts": artifacts,
                    }
                )

        notifications.append(notification)

    await db.execute(
        """
        UPDATE users
        SET experience = ?,
            level = ?,
            league_index = ?
        WHERE user_id = ?
        """,
        (
            experience,
            level,
            min(len(LEAGUES) - 1, (level - 1) // 30),
            user_id,
        ),
    )

    if level < old_level:
        logger.error(
            "Некорректное снижение уровня user=%s old=%s new=%s",
            user_id,
            old_level,
            level,
        )

    return notifications


def format_promotion(
    username: str,
    item: dict[str, object],
) -> str:
    level = safe_int(item.get("level"))
    coins = safe_int(item.get("coins"))

    if item.get("kind") == "league":
        artifacts = item.get("league_artifacts", {})
        artifacts_text = []

        if isinstance(artifacts, dict):
            for key, count in artifacts.items():
                artifact_type, subtype = key
                label = {
                    ("blade", ""): "🗡 клинок",
                    ("armor", ""): "🛡 броня",
                    ("shield", "weak"): "🔰 слабый щит",
                    ("shield", "reinforced"): "💎 усиленный щит",
                    ("shield", "femboy"): "🩷 фембойский щит",
                }.get((artifact_type, subtype), artifact_type)

                artifacts_text.append(
                    f"{label} ×{safe_int(count)}"
                )

        details = (
            ", ".join(artifacts_text)
            if artifacts_text
            else "без артефактов"
        )

        return (
            "👑🏆✨ <b>НОВАЯ ЛИГА!</b> ✨🏆👑\n\n"
            f"🎉 Поздравляем {username}!\n"
            f"🛡 Лига: <b>{esc(item.get('league', ''))}</b>\n"
            f"💰 Награда: <b>+{safe_int(item.get('league_coins'))} 🪙</b>\n"
            f"🎁 Артефакты: <b>{esc(details)}</b>\n"
            f"📈 Уровень: <b>{level}</b>"
        )

    if item.get("kind") == "stage":
        artifact_type, subtype = item.get(
            "stage_artifact",
            ("", ""),
        )

        label = {
            ("blade", ""): "🗡 клинок",
            ("shield", "reinforced"): "💎 усиленный щит",
            ("armor", ""): "🛡 броня",
        }.get((artifact_type, subtype), "🎁 артефакт")

        return (
            "🌟✨ <b>НОВАЯ СТУПЕНЬ!</b> ✨🌟\n\n"
            f"🎉 Поздравляем {username}!\n"
            f"🏆 Лига: <b>{esc(item.get('league', ''))}</b>\n"
            f"📊 Ступень: <b>{esc(item.get('stage', ''))}</b>\n"
            f"💰 Награда: <b>+{safe_int(item.get('stage_coins'))} 🪙</b>\n"
            f"🎁 Артефакт: <b>{esc(label)}</b>\n"
            f"📈 Уровень: <b>{level}</b>"
        )

    milestone = bool(item.get("milestone"))

    if milestone:
        title = "🎊💖 <b>ЮБИЛЕЙНЫЙ УРОВЕНЬ!</b> 💖🎊"
        extra = "\n✨ Дополнительная награда за уровень, кратный 5!"
    else:
        title = "✨📈 <b>НОВЫЙ УРОВЕНЬ!</b> 📈✨"
        extra = ""

    return (
        f"{title}\n\n"
        f"🎉 Поздравляем {username}!\n"
        f"🏅 Новый уровень: <b>{level}</b>\n"
        f"💰 Награда: <b>+{coins} 🪙</b>"
        f"{extra}"
    )


async def announce_promotions(
    bot: Bot,
    user_id: int,
    username: str,
    promotions: list[dict[str, object]],
) -> None:
    for promotion in promotions:
        await _notify(
            bot,
            user_id,
            format_promotion(username, promotion),
        )


async def add_experience_and_notify(
    bot: Bot,
    user_id: int,
    username: str,
    amount: int,
) -> None:
    async with transaction() as db:
        promotions = await award_experience(
            db,
            user_id,
            amount,
        )

    if promotions:
        await announce_promotions(
            bot,
            user_id,
            username,
            promotions,
        )
