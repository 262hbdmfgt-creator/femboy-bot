from __future__ import annotations

import logging
import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import connect, ensure_user, now, transaction
from keyboards import shield_craft_keyboard
from utils import (
    answer_callback,
    command_is,
    display_name,
    edit_message_safely,
    format_duration,
    safe_float,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.artifacts")


SHIELD_LABELS = {
    "weak": "слабый",
    "reinforced": "усиленный",
    "femboy": "фембойский",
}

HIDDEN_COLUMNS = {
    "blade": "blade_hidden",
    "armor": "armor_hidden",
    "shield": "shield_hidden",
}


async def is_vip(user_id: int) -> bool:
    async with connect() as db:
        async with db.execute(
            "SELECT vip_until FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    return bool(row and safe_float(row["vip_until"]) > now())


async def artifact_rows(
    user_id: int,
    artifact_type: str,
):
    async with connect() as db:
        async with db.execute(
            """
            SELECT subtype, amount, blocked_until
            FROM artifacts
            WHERE user_id = ?
              AND artifact_type = ?
              AND amount > 0
            ORDER BY subtype
            """,
            (user_id, artifact_type),
        ) as cursor:
            return await cursor.fetchall()


async def send_artifacts(
    message: Message,
    artifact_type: str,
) -> None:
    user_id = message.from_user.id
    rows = await artifact_rows(user_id, artifact_type)

    titles = {
        "blade": "🗡️✨ ТВОИ КЛИНКИ",
        "armor": "🛡️✨ ТВОЯ БРОНЯ",
        "shield": "🔰✨ ТВОИ ЩИТЫ",
    }

    lines = [
        f"<b>{titles.get(artifact_type, 'АРТЕФАКТЫ')}</b>",
        "",
    ]

    if not rows:
        lines.append("💔 Пока таких предметов нет!")
    else:
        for row in rows:
            subtype = str(row["subtype"] or "")
            amount = safe_int(row["amount"])

            label = (
                f"{SHIELD_LABELS.get(subtype, subtype)} щит"
                if artifact_type == "shield"
                else (
                    "клинок"
                    if artifact_type == "blade"
                    else "броня"
                )
            )

            lines.append(
                f"• {label}: <b>{amount}</b>"
            )

            blocked_until = safe_float(
                row["blocked_until"]
            )

            if blocked_until > now():
                lines.append(
                    "🔒 Заблокировано ещё "
                    f"<b>{format_duration(blocked_until - now())}</b>"
                )

    await message.answer("\n".join(lines))


@router.message(
    lambda message: command_is(message, "мои клинки")
)
async def blades_command(message: Message) -> None:
    await send_artifacts(message, "blade")


@router.message(
    lambda message: command_is(message, "моя броня")
)
async def armor_command(message: Message) -> None:
    await send_artifacts(message, "armor")


@router.message(
    lambda message: command_is(message, "мои щиты")
)
async def shields_command(message: Message) -> None:
    await send_artifacts(message, "shield")


@router.message(
    lambda message: command_is(message, "крафт щитов")
)
async def shield_craft_command(message: Message) -> None:
    await message.answer(
        "⚒️✨ <b>КРАФТ ЩИТОВ</b> ✨⚒️\n\n"
        "🔰 3 слабых → 1 усиленный\n"
        "💎 3 усиленных → 1 фембойский\n"
        "👑 3 фембойских → 1 броня",
        reply_markup=shield_craft_keyboard(),
    )


@router.callback_query(
    F.data.startswith("craft:shield:")
)
async def shield_craft_callback(
    callback: CallbackQuery,
) -> None:
    subtype = (callback.data or "").rsplit(":", 1)[-1]

    recipes = {
        "weak": ("reinforced", "усиленный щит"),
        "reinforced": ("femboy", "фембойский щит"),
        "femboy": ("armor", "броню"),
    }

    recipe = recipes.get(subtype)

    if not recipe:
        await answer_callback(
            callback,
            "Неизвестный рецепт 💔",
            alert=True,
        )
        return

    target, target_label = recipe
    user_id = callback.from_user.id

    async with transaction() as db:
        async with db.execute(
            """
            SELECT amount
            FROM artifacts
            WHERE user_id = ?
              AND artifact_type = 'shield'
              AND subtype = ?
            """,
            (user_id, subtype),
        ) as cursor:
            row = await cursor.fetchone()

        if not row or safe_int(row["amount"]) < 3:
            await answer_callback(
                callback,
                "Нужно 3 щита одного типа 🔰",
                alert=True,
            )
            return

        changed = await db.execute(
            """
            UPDATE artifacts
            SET amount = amount - 3
            WHERE user_id = ?
              AND artifact_type = 'shield'
              AND subtype = ?
              AND amount >= 3
            """,
            (user_id, subtype),
        )

        if changed.rowcount != 1:
            await answer_callback(
                callback,
                "Щитов недостаточно — попробуй ещё раз 💔",
                alert=True,
            )
            return

        if target == "armor":
            await db.execute(
                """
                INSERT INTO artifacts(
                    user_id, artifact_type, subtype, amount, created_at
                )
                VALUES (?, 'armor', '', 1, ?)
                ON CONFLICT(user_id, artifact_type, subtype)
                DO UPDATE SET amount = amount + 1
                """,
                (user_id, now()),
            )
        else:
            await db.execute(
                """
                INSERT INTO artifacts(
                    user_id, artifact_type, subtype, amount, created_at
                )
                VALUES (?, 'shield', ?, 1, ?)
                ON CONFLICT(user_id, artifact_type, subtype)
                DO UPDATE SET amount = amount + 1
                """,
                (user_id, target, now()),
            )

        await db.execute(
            """
            UPDATE users
            SET experience = experience + 2
            WHERE user_id = ?
            """,
            (user_id,),
        )

    await answer_callback(
        callback,
        "Крафт завершён! ✨",
        alert=True,
    )

    await callback.message.answer(
        "🎉💖 <b>КРАФТ УСПЕШЕН!</b>\n\n"
        f"Получена награда: <b>{target_label}</b>\n"
        "💫 Опыт: <b>+2</b>"
    )


@router.message(
    lambda message: (
        message.text
        and message.text.strip().lower()
        in {
            "скрыть клинки",
            "скрыть броню",
            "скрыть щиты",
            "раскрыть клинки",
            "раскрыть броню",
            "раскрыть щиты",
        }
    )
)
async def artifact_visibility_command(
    message: Message,
) -> None:
    if not await is_vip(message.from_user.id):
        await message.answer(
            "👑 Скрытие артефактов доступно только VIP!"
        )
        return

    parts = message.text.strip().lower().split()
    action, target = parts[0], parts[1]

    type_by_word = {
        "клинки": "blade",
        "броню": "armor",
        "щиты": "shield",
    }

    artifact_type = type_by_word.get(target)

    if not artifact_type:
        return

    column = HIDDEN_COLUMNS[artifact_type]
    hidden = 1 if action == "скрыть" else 0

    async with transaction() as db:
        await db.execute(
            f"""
            UPDATE users
            SET {column} = ?
            WHERE user_id = ?
            """,
            (hidden, message.from_user.id),
        )

    text = "скрыты 🙈" if hidden else "снова видны 👀"

    await message.answer(
        f"✨ Артефакты «{target}» {text}!"
    )


@router.callback_query(
    F.data.startswith("profile:artifact:")
)
async def profile_artifact_callback(
    callback: CallbackQuery,
) -> None:
    try:
        _, _, user_raw, artifact_type = (
            callback.data or ""
        ).split(":", 3)
        owner_id = int(user_raw)
    except (ValueError, AttributeError):
        await answer_callback(
            callback,
            "Некорректная кнопка",
            alert=True,
        )
        return

    if callback.from_user.id != owner_id:
        await answer_callback(
            callback,
            "Это не твой профиль 💖",
            alert=True,
        )
        return

    if artifact_type not in HIDDEN_COLUMNS:
        await answer_callback(
            callback,
            "Неизвестный тип предмета",
            alert=True,
        )
        return

    rows = await artifact_rows(
        owner_id,
        artifact_type,
    )

    title = {
        "blade": "🗡️✨ ТВОИ КЛИНКИ",
        "armor": "🛡️✨ ТВОЯ БРОНЯ",
        "shield": "🔰✨ ТВОИ ЩИТЫ",
    }[artifact_type]

    lines = [f"<b>{title}</b>", ""]

    if not rows:
        lines.append("💔 Пока предметов нет!")
    else:
        for row in rows:
            subtype = str(row["subtype"] or "")
            label = (
                f"{SHIELD_LABELS.get(subtype, subtype)} щит"
                if artifact_type == "shield"
                else artifact_type
            )
            lines.append(
                f"• {label}: <b>{safe_int(row['amount'])}</b>"
            )

    await edit_message_safely(
        callback.message,
        "\n".join(lines),
    )
    await answer_callback(callback)


async def consume_one_artifact(
    db,
    user_id: int,
    artifact_type: str,
    subtype: str = "",
) -> bool:
    result = await db.execute(
        """
        UPDATE artifacts
        SET amount = amount - 1
        WHERE user_id = ?
          AND artifact_type = ?
          AND subtype = ?
          AND amount > 0
        """,
        (user_id, artifact_type, subtype),
    )

    return result.rowcount == 1


@router.message(
    lambda message: command_is(message, "клинок")
)
async def blade_attack_command(message: Message) -> None:
    if not message.reply_to_message:
        await message.answer(
            "🗡️ Ответь командой «клинок» на сообщение игрока!"
        )
        return

    attacker = message.from_user
    victim = message.reply_to_message.from_user

    if not victim or victim.is_bot or victim.id == attacker.id:
        await message.answer(
            "❌ Нельзя атаковать себя или бота!"
        )
        return

    await ensure_user(
        attacker.id,
        attacker.username or attacker.full_name,
    )
    await ensure_user(
        victim.id,
        victim.username or victim.full_name,
    )

    attacker_id = attacker.id
    victim_id = victim.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT amount, blocked_until
            FROM artifacts
            WHERE user_id = ?
              AND artifact_type = 'blade'
              AND subtype = ''
            """,
            (attacker_id,),
        ) as cursor:
            blade = await cursor.fetchone()

        if not blade or safe_int(blade["amount"]) <= 0:
            await message.answer(
                "💔 У тебя нет клинка!"
            )
            return

        if safe_float(blade["blocked_until"]) > current_time:
            await message.answer(
                "🔒 Клинок заблокирован ещё "
                f"<b>{format_duration(safe_float(blade['blocked_until']) - current_time)}</b>"
            )
            return

        async with db.execute(
            """
            SELECT femcoins, vip_until
            FROM users
            WHERE user_id = ?
            """,
            (victim_id,),
        ) as cursor:
            victim_row = await cursor.fetchone()

        if not victim_row:
            await message.answer(
                "❌ Игрок не зарегистрирован."
            )
            return

        theft = min(
            random.randint(50, 500),
            safe_int(victim_row["femcoins"]),
        )

        async with db.execute(
            """
            SELECT subtype
            FROM artifacts
            WHERE user_id = ?
              AND artifact_type = 'shield'
              AND amount > 0
            ORDER BY CASE subtype
                WHEN 'femboy' THEN 1
                WHEN 'reinforced' THEN 2
                ELSE 3
            END
            LIMIT 1
            """,
            (victim_id,),
        ) as cursor:
            shield = await cursor.fetchone()

        reflected = False
        result_lines: list[str] = []

        if shield:
            shield_type = str(shield["subtype"])
            await consume_one_artifact(
                db,
                victim_id,
                "shield",
                shield_type,
            )

            if shield_type == "weak":
                reflected = random.random() < 0.50

                if reflected:
                    blocked_until = current_time + 30 * 60
                    result_lines.append(
                        "🔰 Слабый щит отразил атаку! "
                        "Клинок заблокирован на 30 минут."
                    )
                else:
                    result_lines.append(
                        "🔰 Слабый щит сломался, атака прошла!"
                    )

            elif shield_type == "reinforced":
                reflected = random.random() < 0.50

                if reflected:
                    blocked_until = current_time + 90 * 60
                    result_lines.append(
                        "💎 Усиленный щит отразил атаку! "
                        "Клинок заблокирован на 1 ч. 30 мин."
                    )
                else:
                    theft = int(theft * 0.90)
                    result_lines.append(
                        "💎 Усиленный щит сломался и уменьшил "
                        "кражу на 10%."
                    )

            elif shield_type == "femboy":
                reflected = random.random() < 0.60

                if reflected:
                    blocked_until = current_time + 3 * 3600
                    result_lines.append(
                        "🩷 Фембойский щит отразил атаку! "
                        "Клинок заблокирован на 3 часа."
                    )
                else:
                    theft = int(theft * 0.50)
                    result_lines.append(
                        "🩷 Щит пропустил атаку, "
                        "но уменьшил кражу на 50%."
                    )

                    async with db.execute(
                        """
                        SELECT attack_block_until
                        FROM users
                        WHERE user_id = ?
                        """,
                        (victim_id,),
                    ) as cursor:
                        block = await cursor.fetchone()

                    if block:
                        current_block = safe_float(
                            block["attack_block_until"]
                        )
                        if current_block > current_time:
                            await db.execute(
                                """
                                UPDATE users
                                SET attack_block_until = MAX(
                                    ?,
                                    attack_block_until - 3600
                                )
                                WHERE user_id = ?
                                """,
                                (
                                    current_time,
                                    victim_id,
                                ),
                            )

            if reflected:
                # Отражение не расходует клинок, только блокирует его.
                await db.execute(
                    """
                    UPDATE artifacts
                    SET blocked_until = MAX(blocked_until, ?)
                    WHERE user_id = ?
                      AND artifact_type = 'blade'
                      AND subtype = ''
                    """,
                    (
                        blocked_until,
                        attacker_id,
                    ),
                )

                result_lines.append(
                    "🗡️ Клинок не израсходован."
                )

            else:
                await consume_one_artifact(
                    db,
                    attacker_id,
                    "blade",
                    "",
                )

        if not reflected:
            # Броня проверяется только если щит не отразил атаку.
            async with db.execute(
                """
                SELECT amount
                FROM artifacts
                WHERE user_id = ?
                  AND artifact_type = 'armor'
                  AND subtype = ''
                """,
                (victim_id,),
            ) as cursor:
                armor = await cursor.fetchone()

            if armor and safe_int(armor["amount"]) > 0:
                await consume_one_artifact(
                    db,
                    victim_id,
                    "armor",
                    "",
                )

                attacker_vip = False

                async with db.execute(
                    """
                    SELECT vip_until
                    FROM users
                    WHERE user_id = ?
                    """,
                    (attacker_id,),
                ) as cursor:
                    attacker_status = await cursor.fetchone()

                if attacker_status:
                    attacker_vip = (
                        safe_float(attacker_status["vip_until"])
                        > current_time
                    )

                armor_chance = (
                    0.25 if attacker_vip else 0.40
                )

                if random.random() < armor_chance:
                    penalty = random.randint(
                        10 if attacker_vip else 50,
                        60 if attacker_vip else 150,
                    )
                    penalty = min(
                        penalty,
                        safe_int(
                            (
                                await db.execute(
                                    "SELECT femcoins FROM users WHERE user_id = ?",
                                    (attacker_id,),
                                )
                            ).fetchone()
                        )
                        if False
                        else penalty,
                    )

                    # Списываем только имеющийся баланс.
                    async with db.execute(
                        """
                        SELECT femcoins
                        FROM users
                        WHERE user_id = ?
                        """,
                        (attacker_id,),
                    ) as cursor:
                        attacker_balance = await cursor.fetchone()

                    penalty = min(
                        penalty,
                        safe_int(attacker_balance["femcoins"])
                        if attacker_balance
                        else 0,
                    )

                    if penalty:
                        await db.execute(
                            """
                            UPDATE users
                            SET femcoins = femcoins - ?
                            WHERE user_id = ?
                              AND femcoins >= ?
                            """,
                            (
                                penalty,
                                attacker_id,
                                penalty,
                            ),
                        )
                        await db.execute(
                            """
                            UPDATE users
                            SET femcoins = femcoins + ?
                            WHERE user_id = ?
                            """,
                            (
                                penalty,
                                victim_id,
                            ),
                        )

                    result_lines.append(
                        "🛡️ Броня сработала! "
                        f"Атакующий передал жертве {penalty} 🪙."
                    )
                else:
                    result_lines.append(
                        "🛡️ Броня поглотила удар! "
                        "Клинок и броня израсходованы."
                    )

                reflected = True

            if not reflected:
                # Кража и запрет сбора карт.
                await db.execute(
                    """
                    UPDATE users
                    SET femcoins = femcoins - ?
                    WHERE user_id = ?
                      AND femcoins >= ?
                    """,
                    (
                        theft,
                        victim_id,
                        theft,
                    ),
                )

                await db.execute(
                    """
                    UPDATE users
                    SET femcoins = femcoins + ?
                    WHERE user_id = ?
                    """,
                    (
                        theft,
                        attacker_id,
                    ),
                )

                victim_vip = (
                    safe_float(victim_row["vip_until"])
                    > current_time
                )

                if victim_vip:
                    duration_hours = random.choices(
                        [1, 2, 3],
                        weights=[25, 50, 25],
                        k=1,
                    )[0]
                else:
                    duration_hours = random.choices(
                        [3, 6, 9],
                        weights=[60, 30, 10],
                        k=1,
                    )[0]

                await db.execute(
                    """
                    UPDATE users
                    SET attack_block_until = MAX(
                        attack_block_until,
                        ?
                    )
                    WHERE user_id = ?
                    """,
                    (
                        current_time + duration_hours * 3600,
                        victim_id,
                    ),
                )

                result_lines.append(
                    f"💰 Украдено: <b>{theft} 🪙</b>."
                )
                result_lines.append(
                    "🚫 Запрет сбора карт: "
                    f"<b>{duration_hours} ч.</b>."
                )

        await db.execute(
            """
            UPDATE users
            SET experience = experience + 2
            WHERE user_id = ?
            """,
            (attacker_id,),
        )

    await message.answer(
        "🗡️💥 <b>АТАКА КЛИНКОМ!</b>\n\n"
        f"⚔️ Нападающий: {display_name(attacker)}\n"
        f"🎯 Цель: {display_name(victim)}\n\n"
        + "\n".join(result_lines)
    )
