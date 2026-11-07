from __future__ import annotations

import logging
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import SUPER_ADMIN_ID
from database import connect, ensure_user, now, transaction
from states import UserStates
from utils import (
    answer_callback,
    command_is,
    display_name,
    esc,
    find_user_by_username,
    safe_float,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.clans")

CLAN_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z0-9(),;:!?/\-]{3,32}$")


def create_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏳️ Ввести название", callback_data="clan:create")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="clan:create_cancel")],
        ]
    )


def join_keyboard(number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💖 Вступить в клан", callback_data=f"clan:join:{number}")]
        ]
    )


async def find_clan_by_number(number: int):
    async with connect() as db:
        async with db.execute(
            "SELECT * FROM clans WHERE clan_number = ? AND deleted_at IS NULL",
            (number,),
        ) as cursor:
            return await cursor.fetchone()


async def user_clan(user_id: int):
    async with connect() as db:
        async with db.execute(
            """
            SELECT c.*
            FROM users u
            JOIN clans c ON c.clan_id = u.clan_id
            WHERE u.user_id = ?
              AND c.deleted_at IS NULL
            """,
            (user_id,),
        ) as cursor:
            return await cursor.fetchone()


async def member_count(clan_id: int) -> int:
    async with connect() as db:
        async with db.execute(
            "SELECT COUNT(*) AS n FROM clan_members WHERE clan_id = ?",
            (clan_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return safe_int(row["n"] if row else 0)


async def clan_details(clan) -> str:
    clan_id = safe_int(clan["clan_id"])

    async with connect() as db:
        async with db.execute(
            """
            SELECT u.user_id, u.username, cm.role,
                   COALESCE(SUM(i.count), 0) AS cards
            FROM clan_members cm
            JOIN users u ON u.user_id = cm.user_id
            LEFT JOIN inventory i ON i.user_id = u.user_id
            WHERE cm.clan_id = ?
            GROUP BY u.user_id
            ORDER BY CASE WHEN cm.role = 'owner' THEN 0 ELSE 1 END,
                     cards DESC, cm.joined_at
            """,
            (clan_id,),
        ) as cursor:
            members = await cursor.fetchall()

        async with db.execute(
            """
            SELECT old_name, new_name, changed_at
            FROM clan_name_history
            WHERE clan_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (clan_id,),
        ) as cursor:
            history = await cursor.fetchall()

    created = safe_float(clan["created_at"])
    lines = [
        "🏳️✨ <b>ИНФОРМАЦИЯ О КЛАНЕ</b> ✨🏳️",
        "",
        f"🔢 Номер: <b>#{safe_int(clan['clan_number'])}</b>",
        f"🏷 Название: <b>{esc(clan['name'])}</b>",
        f"👑 Владелец ID: <code>{safe_int(clan['owner_id'])}</code>",
        f"👥 Участников: <b>{len(members)}</b>",
        f"💰 Кланкоинов: <b>{safe_int(clan['clan_coins'])}</b>",
        f"🏰 Уровень: <b>{safe_int(clan['level'])}</b>",
        f"📅 Создан: <b>{datetime.fromtimestamp(created).strftime('%d.%m.%Y %H:%M')}</b>",
        "",
        "👥 <b>Участники:</b>",
    ]

    if members:
        for index, member in enumerate(members, 1):
            username = str(member["username"] or "Игрок").lstrip("@").split()[0]
            role = "👑 владелец" if member["role"] == "owner" else "участник"
            lines.append(
                f"{index}. {esc(username)} — {role}, "
                f"{safe_int(member['cards'])} 🎴"
            )
    else:
        lines.append("Пока участников нет.")

    if history:
        lines.extend(["", "📝 <b>Недавние переименования:</b>"])
        for row in history:
            date = datetime.fromtimestamp(
                safe_float(row["changed_at"])
            ).strftime("%d.%m.%Y")
            lines.append(
                f"• {esc(row['old_name'])} → "
                f"{esc(row['new_name'])} ({date})"
            )

    return "\n".join(lines)


async def transfer_clan_membership(
    message: Message,
    target_clan,
) -> None:
    user_id = message.from_user.id
    new_clan_id = safe_int(target_clan["clan_id"])

    current = await user_clan(user_id)

    if current and safe_int(current["clan_id"]) == new_clan_id:
        await message.answer("💖 Ты уже состоишь в этом клане!")
        return

    if current and safe_int(current["owner_id"]) == user_id:
        await message.answer(
            "👑 Владелец не может перейти в другой клан, "
            "пока не передаст владение или не удалит свой клан."
        )
        return

    if current:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да, перейти",
                        callback_data=f"clan:confirm_join:{safe_int(target_clan['clan_number'])}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Остаться",
                        callback_data="clan:cancel_join",
                    )
                ],
            ]
        )
        await message.answer(
            "⚠️ <b>Подтверди переход</b>\n\n"
            f"Ты покинешь клан <b>{esc(current['name'])}</b> "
            f"№{safe_int(current['clan_number'])} и вступишь в "
            f"<b>{esc(target_clan['name'])}</b> "
            f"№{safe_int(target_clan['clan_number'])}.\n\n"
            "Продолжить?",
            reply_markup=keyboard,
        )
        return

    await join_clan(message, target_clan)


async def join_clan(message: Message, clan) -> None:
    user = message.from_user
    clan_id = safe_int(clan["clan_id"])

    async with transaction() as db:
        async with db.execute(
            "SELECT clan_id FROM users WHERE user_id = ?",
            (user.id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row and row["clan_id"]:
            raise ValueError("already_in_clan")

        await db.execute(
            "UPDATE users SET clan_id = ? WHERE user_id = ?",
            (clan_id, user.id),
        )
        await db.execute(
            """
            INSERT OR REPLACE INTO clan_members(
                clan_id, user_id, joined_at, role
            )
            VALUES (?, ?, ?, 'member')
            """,
            (clan_id, user.id, now()),
        )

    await message.answer(
        "🎉🏳️ <b>ДОБРО ПОЖАЛОВАТЬ В КЛАН!</b>\n\n"
        f"👤 Игрок: {display_name(user)}\n"
        f"🏷 Клан: <b>{esc(clan['name'])}</b>\n"
        f"🔢 Номер: <b>#{safe_int(clan['clan_number'])}</b>"
    )


@router.message(
    lambda message: command_is(message, "создать клан")
)
async def create_clan_command(message: Message) -> None:
    current = await user_clan(message.from_user.id)
    if current:
        await message.answer("💔 Ты уже состоишь в клане!")
        return

    async with connect() as db:
        async with db.execute(
            "SELECT femcoins FROM users WHERE user_id = ?",
            (message.from_user.id,),
        ) as cursor:
            user = await cursor.fetchone()

        async with db.execute(
            "SELECT expires_at FROM clan_bans WHERE user_id = ?",
            (message.from_user.id,),
        ) as cursor:
            ban = await cursor.fetchone()

    if ban and safe_float(ban["expires_at"]) > now():
        await message.answer(
            "🚫 Создание кланов запрещено ещё "
            f"<b>{int((safe_float(ban['expires_at']) - now()) / 3600)} ч.</b>"
        )
        return

    if not user or safe_int(user["femcoins"]) < 50:
        await message.answer("💔 Для создания клана нужно 50 🪙!")
        return

    await message.answer(
        "🏳️✨ <b>СОЗДАТЬ КЛАН?</b> ✨🏳️\n\n"
        "Стоимость: <b>50 фемкоинов</b>.\n"
        "После подтверждения оплата не возвращается.",
        reply_markup=create_keyboard(),
    )


@router.callback_query(F.data == "clan:create")
async def clan_create_callback(
    callback: CallbackQuery,
    state,
) -> None:
    user_id = callback.from_user.id

    async with transaction() as db:
        async with db.execute(
            "SELECT femcoins, clan_id FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user or user["clan_id"]:
            await answer_callback(callback, "Ты уже в клане 💔", alert=True)
            return

        if safe_int(user["femcoins"]) < 50:
            await answer_callback(callback, "Не хватает 50 🪙", alert=True)
            return

        async with db.execute(
            "SELECT expires_at FROM clan_bans WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            ban = await cursor.fetchone()

        if ban and safe_float(ban["expires_at"]) > now():
            await answer_callback(callback, "Создание клана запрещено 🚫", alert=True)
            return

        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 50
            WHERE user_id = ? AND femcoins >= 50
            """,
            (user_id,),
        )

    await state.set_state(UserStates.waiting_clan_name)
    await answer_callback(callback)
    await callback.message.answer(
        "📝 Отправь название клана отдельным сообщением.\n"
        "Разрешены буквы, цифры и символы <code>(),;:!?/-</code>.\n"
        "Длина — 3–32 символа. Оплата уже списана."
    )


@router.callback_query(F.data == "clan:create_cancel")
async def clan_create_cancel_callback(
    callback: CallbackQuery,
    state,
) -> None:
    await state.clear()
    await answer_callback(callback, "Создание отменено.")
    await callback.message.edit_text("❌ Создание клана отменено.")


@router.message(UserStates.waiting_clan_name)
async def clan_name_handler(
    message: Message,
    state,
) -> None:
    if not message.text:
        await message.answer("❌ Название нужно отправить текстом.")
        return

    name = message.text.strip()

    if not CLAN_NAME_RE.fullmatch(name):
        await message.answer(
            "❌ Название не подходит. Используй 3–32 символа: "
            "русские/английские буквы, цифры и <code>(),;:!?/-</code>."
        )
        return

    user_id = message.from_user.id

    try:
        async with transaction() as db:
            async with db.execute(
                "SELECT 1 FROM clans WHERE LOWER(name) = LOWER(?) AND deleted_at IS NULL",
                (name,),
            ) as cursor:
                if await cursor.fetchone():
                    await message.answer("💔 Такое название уже занято.")
                    return

            async with db.execute(
                "SELECT clan_number FROM clans WHERE deleted_at IS NULL ORDER BY clan_number",
            ) as cursor:
                used = {
                    safe_int(row["clan_number"])
                    for row in await cursor.fetchall()
                }

            number = 1
            while number in used:
                number += 1

            created = now()
            cursor = await db.execute(
                """
                INSERT INTO clans(
                    clan_number, name, owner_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (number, name, user_id, created, created),
            )
            clan_id = cursor.lastrowid

            await db.execute(
                "UPDATE users SET clan_id = ? WHERE user_id = ?",
                (clan_id, user_id),
            )
            await db.execute(
                """
                INSERT INTO clan_members(
                    clan_id, user_id, joined_at, role
                )
                VALUES (?, ?, ?, 'owner')
                """,
                (clan_id, user_id, created),
            )

        await state.clear()
        await message.answer(
            "🎉🏳️ <b>КЛАН СОЗДАН!</b>\n"
            f"🏷 <b>{esc(name)}</b>\n"
            f"🔢 Номер: <b>#{number}</b>\n"
            "👑 Ты владелец клана!"
        )
    except Exception:
        logger.exception("Ошибка создания клана")
        await message.answer(
            "❌ Не удалось создать клан. "
            "Обратись к администратору."
        )


@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"вступить в клан\s+\d+",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def join_clan_command(message: Message) -> None:
    number = safe_int(message.text.split()[-1])
    clan = await find_clan_by_number(number)

    if not clan:
        await message.answer("💔 Клан не найден!")
        return

    await transfer_clan_membership(message, clan)


@router.callback_query(F.data.startswith("clan:join:"))
async def clan_join_callback(callback: CallbackQuery) -> None:
    number = safe_int(callback.data.rsplit(":", 1)[-1])
    clan = await find_clan_by_number(number)

    if not clan:
        await answer_callback(callback, "Клан не найден", alert=True)
        return

    try:
        await transfer_clan_membership(callback.message, clan)
    except Exception:
        logger.exception("Ошибка вступления в клан")
        await answer_callback(callback, "Не удалось вступить", alert=True)
        return

    await answer_callback(callback)


@router.callback_query(F.data.startswith("clan:confirm_join:"))
async def confirm_clan_join_callback(
    callback: CallbackQuery,
) -> None:
    number = safe_int(callback.data.rsplit(":", 1)[-1])
    clan = await find_clan_by_number(number)

    if not clan:
        await answer_callback(callback, "Клан не найден", alert=True)
        return

    user_id = callback.from_user.id
    current = await user_clan(user_id)

    if current and safe_int(current["owner_id"]) == user_id:
        await answer_callback(
            callback,
            "Сначала передай владение или удали свой клан",
            alert=True,
        )
        return

    async with transaction() as db:
        if current:
            await db.execute(
                "DELETE FROM clan_members WHERE user_id = ?",
                (user_id,),
            )

        await db.execute(
            "UPDATE users SET clan_id = ? WHERE user_id = ?",
            (safe_int(clan["clan_id"]), user_id),
        )

        await db.execute(
            """
            INSERT OR REPLACE INTO clan_members(
                clan_id, user_id, joined_at, role
            )
            VALUES (?, ?, ?, 'member')
            """,
            (safe_int(clan["clan_id"]), user_id, now()),
        )

    await callback.message.edit_text(
        "🎉🏳️ <b>ТЫ ВСТУПИЛ В КЛАН!</b>\n"
        f"👤 {display_name(callback.from_user)}\n"
        f"🏷 {esc(clan['name'])}\n"
        f"🔢 №{safe_int(clan['clan_number'])}"
    )
    await answer_callback(callback)


@router.callback_query(F.data == "clan:cancel_join")
async def cancel_clan_join_callback(callback: CallbackQuery) -> None:
    await callback.message.edit_text("💖 Ты остался в своём клане.")
    await answer_callback(callback)


@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"клан\s+\d+",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def clan_info_command(message: Message) -> None:
    number = safe_int(message.text.split()[-1])
    clan = await find_clan_by_number(number)

    if not clan:
        await message.answer("💔 Клан не найден.")
        return

    await message.answer(
        await clan_details(clan),
        reply_markup=join_keyboard(number),
    )


@router.message(
    lambda message: command_is(message, "кланы", "clans")
)
async def clan_list_command(message: Message) -> None:
    async with connect() as db:
        async with db.execute(
            """
            SELECT clan_number, name, clan_coins, level
            FROM clans
            WHERE deleted_at IS NULL
            ORDER BY clan_coins DESC, level DESC, clan_number ASC
            LIMIT 10
            """
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("🏳️ Кланов пока нет. Создай первый!")
        return

    text = ["🏳️✨ <b>ТОП-10 КЛАНОВ</b> ✨🏳️", ""]

    for index, row in enumerate(rows, 1):
        text.append(
            f"{index}. №{safe_int(row['clan_number'])} "
            f"<b>{esc(row['name'])}</b> — "
            f"🏰 ур. {safe_int(row['level'])}, "
            f"💰 {safe_int(row['clan_coins'])}"
        )

    await message.answer("\n".join(text))


@router.message(
    lambda message: command_is(message, "мой клан")
)
async def my_clan_command(message: Message) -> None:
    clan = await user_clan(message.from_user.id)

    if not clan:
        await message.answer(
            "💔 Ты пока не состоишь в клане!"
        )
        return

    buttons = []

    if safe_int(clan["owner_id"]) != message.from_user.id:
        buttons.append(
            [InlineKeyboardButton(text="💔 Покинуть клан", callback_data="clan:leave")]
        )

    await message.answer(
        await clan_details(clan),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.message(
    lambda message: command_is(message, "покинуть клан")
)
async def leave_clan_command(message: Message) -> None:
    user_id = message.from_user.id
    clan = await user_clan(user_id)

    if not clan:
        await message.answer("💔 Ты не состоишь в клане.")
        return

    if safe_int(clan["owner_id"]) == user_id:
        await message.answer(
            "👑 Владелец не может покинуть клан. "
            "Передай владение или удали клан."
        )
        return

    async with transaction() as db:
        await db.execute(
            "DELETE FROM clan_members WHERE user_id = ?",
            (user_id,),
        )
        await db.execute(
            "UPDATE users SET clan_id = NULL WHERE user_id = ?",
            (user_id,),
        )

    await message.answer("💔 Ты покинул клан.")


@router.callback_query(F.data == "clan:leave")
async def leave_clan_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    clan = await user_clan(user_id)

    if not clan:
        await answer_callback(callback, "Ты не в клане", alert=True)
        return

    if safe_int(clan["owner_id"]) == user_id:
        await answer_callback(
            callback,
            "Владелец должен передать владение или удалить клан",
            alert=True,
        )
        return

    async with transaction() as db:
        await db.execute(
            "DELETE FROM clan_members WHERE user_id = ?",
            (user_id,),
        )
        await db.execute(
            "UPDATE users SET clan_id = NULL WHERE user_id = ?",
            (user_id,),
        )

    await callback.message.edit_text("💔 Ты покинул клан.")
    await answer_callback(callback)


@router.message(
    lambda message: command_is(message, "все кланы")
)
async def all_clans_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    async with connect() as db:
        async with db.execute(
            """
            SELECT clan_number, name, owner_id, clan_coins, level
            FROM clans
            WHERE deleted_at IS NULL
            ORDER BY clan_number
            """
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Кланов нет.")
        return

    lines = ["🛠 <b>ВСЕ КЛАНЫ</b>", ""]

    for row in rows:
        lines.append(
            f"№{safe_int(row['clan_number'])} "
            f"<b>{esc(row['name'])}</b> | "
            f"👑 <code>{safe_int(row['owner_id'])}</code> | "
            f"💰 {safe_int(row['clan_coins'])} | "
            f"ур. {safe_int(row['level'])}"
        )

    await message.answer("\n".join(lines))


@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"инфо\s+\d+",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_clan_info_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    number = safe_int(message.text.split()[-1])
    clan = await find_clan_by_number(number)

    if not clan:
        await message.answer("Клан не найден.")
        return

    await message.answer(await clan_details(clan))


@router.message(
    lambda message: (
        message.text
        and message.text.lower().startswith(
            ("передать владельца клана", "/передать владельца клана")
        )
    )
)
async def transfer_clan_owner_command(message: Message) -> None:
    clan = await user_clan(message.from_user.id)

    if not clan or safe_int(clan["owner_id"]) != message.from_user.id:
        await message.answer("👑 Передать владение может только владелец клана.")
        return

    if safe_float(clan["owner_change_locked_until"]) > now():
        await message.answer(
            "🔒 Передача владельца временно запрещена."
        )
        return

    target_id = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif message.text:
        match = re.search(r"@([A-Za-z0-9_]+)", message.text)
        if match:
            target_id = await find_user_by_username(match.group(0))

    if not target_id:
        await message.answer(
            "Укажи нового владельца через @username "
            "или ответь на его сообщение."
        )
        return

    async with connect() as db:
        async with db.execute(
            """
            SELECT clan_id
            FROM users
            WHERE user_id = ?
            """,
            (target_id,),
        ) as cursor:
            target = await cursor.fetchone()

    if not target or safe_int(target["clan_id"], -1) != safe_int(clan["clan_id"]):
        await message.answer(
            "❌ Новый владелец должен состоять именно в твоём клане."
        )
        return

    async with transaction() as db:
        await db.execute(
            "UPDATE clans SET owner_id = ?, updated_at = ? WHERE clan_id = ?",
            (target_id, now(), safe_int(clan["clan_id"])),
        )
        await db.execute(
            "UPDATE clan_members SET role = 'member' WHERE clan_id = ?",
            (safe_int(clan["clan_id"]),),
        )
        await db.execute(
            """
            UPDATE clan_members
            SET role = 'owner'
            WHERE clan_id = ? AND user_id = ?
            """,
            (safe_int(clan["clan_id"]), target_id),
        )
        await db.execute(
            """
            INSERT INTO clan_transfers(
                clan_id, old_owner_id, new_owner_id, changed_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                safe_int(clan["clan_id"]),
                message.from_user.id,
                target_id,
                now(),
            ),
        )

    await message.answer(
        f"👑 Владение кланом передано игроку "
        f"<code>{target_id}</code>."
    )


@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"/?бот\s+ред\s+клан\s+\d+\s+-?\d+",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_lock_clan_rename_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()

    try:
        clan_number = int(parts[3])
        hours = float(parts[4])
    except (IndexError, ValueError):
        await message.answer("Формат: /бот ред клан 3 100")
        return

    clan = await find_clan_by_number(clan_number)

    if not clan:
        await message.answer("Клан не найден.")
        return

    lock_until = -1 if hours == -1 else now() + hours * 3600

    async with transaction() as db:
        await db.execute(
            """
            UPDATE clans
            SET owner_change_locked_until = ?,
                updated_at = ?
            WHERE clan_id = ?
            """,
            (lock_until, now(), safe_int(clan["clan_id"])),
        )

    await message.answer(
        f"🔒 Смена владельца для клана №{clan_number}: "
        f"{'навсегда' if hours == -1 else f'{hours:g} часов'}."
    )


@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"/?бот\s+-клан\s+\d+",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_delete_clan_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    number = safe_int(message.text.split()[-1])
    clan = await find_clan_by_number(number)

    if not clan:
        await message.answer("Клан не найден.")
        return

    clan_id = safe_int(clan["clan_id"])

    async with transaction() as db:
        await db.execute(
            "UPDATE users SET clan_id = NULL WHERE clan_id = ?",
            (clan_id,),
        )
        await db.execute(
            "DELETE FROM clan_members WHERE clan_id = ?",
            (clan_id,),
        )
        await db.execute(
            "DELETE FROM clans WHERE clan_id = ?",
            (clan_id,),
        )

    await message.answer(
        f"🗑 Клан №{number} «{esc(clan['name'])}» удалён."
    )


@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"/?бот\s+[+-]кзапрет\s+-?\d+(\.\d+)?\s+.+",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_clan_ban_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()

    try:
        operation = parts[1].lower()
        days = float(parts[2])
    except (IndexError, ValueError):
        await message.answer("Формат: /бот +кзапрет 20 @username")
        return

    target_id = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        for token in reversed(parts):
            if token.startswith("@"):
                target_id = await find_user_by_username(token)
                break

    if not target_id or days <= 0:
        await message.answer("Пользователь не найден или срок неверен.")
        return

    async with transaction() as db:
        async with db.execute(
            "SELECT expires_at FROM clan_bans WHERE user_id = ?",
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()

        existing = safe_float(row["expires_at"]) if row else 0

        if operation == "+кзапрет":
            new_expiry = now() + days * 86400
        else:
            new_expiry = max(
                0,
                existing - days * 86400,
            )

        if new_expiry <= now():
            await db.execute(
                "DELETE FROM clan_bans WHERE user_id = ?",
                (target_id,),
            )
        else:
            await db.execute(
                """
                INSERT INTO clan_bans(
                    user_id, expires_at, changed_by, reason
                )
                VALUES (?, ?, ?, 'admin')
                ON CONFLICT(user_id)
                DO UPDATE SET
                    expires_at = excluded.expires_at,
                    changed_by = excluded.changed_by
                """,
                (
                    target_id,
                    new_expiry,
                    message.from_user.id,
                ),
            )

    await message.answer(
        f"✅ Запрет создания кланов обновлён для "
        f"<code>{target_id}</code>."
    )
