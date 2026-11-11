from __future__ import annotations

import asyncio
import logging
import re
import secrets
import string
import time
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from config import SUPER_ADMIN_ID
from database import (
    connect,
    ensure_user,
    log_action,
    now,
    transaction,
)
from states import AdminStates
from utils import (
    answer_callback,
    command_is,
    display_name,
    esc,
    find_user_by_username,
    format_date,
    resolve_user_id,
    safe_float,
    safe_int,
    user_is_admin,
)

router = Router()
logger = logging.getLogger("femboy_bot.admin")


RARITIES = [
    "Редкое",
    "Ультра редкое",
    "Мифическое",
    "Легендарное",
    "Фембойский артефакт",
    "Редчайший фем",
]


def rarity_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✨ {rarity}",
                    callback_data=f"admin:rarity:{index}",
                )
            ]
            for index, rarity in enumerate(RARITIES)
        ]
    )


async def admin_target(
    message: Message,
) -> Optional[int]:
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):
        target = message.reply_to_message.from_user

        await ensure_user(
            target.id,
            target.username or target.full_name,
        )
        return target.id

    if not message.text:
        return None

    for token in reversed(message.text.split()):
        if token.startswith("@"):
            return await find_user_by_username(token)

    return None


def admin_arguments(message: Message) -> list[str]:
    if not message.text:
        return []

    parts = message.text.strip().split()

    if parts and parts[0].lower() in {"/бот", "бот"}:
        return parts[1:]

    return parts


# ------------------------------------------------------------
# Добавление карты: /plus_foto
# ------------------------------------------------------------

@router.message(
    lambda message: command_is(message, "plus_foto")
)
async def plus_foto_command(
    message: Message,
    state: FSMContext,
) -> None:
    if not await user_is_admin(message.from_user.id):
        return

    await state.clear()
    await state.set_state(AdminStates.waiting_card_photo)

    await message.answer(
        "📸✨ <b>ДОБАВЛЕНИЕ КАРТЫ</b> ✨📸\n\n"
        "Отправь фотографию карты."
    )


@router.message(
    AdminStates.waiting_card_photo,
    F.photo,
)
async def admin_card_photo(
    message: Message,
    state: FSMContext,
) -> None:
    if not await user_is_admin(message.from_user.id):
        await state.clear()
        return

    await state.update_data(
        file_id=message.photo[-1].file_id
    )
    await state.set_state(
        AdminStates.waiting_card_rarity
    )

    await message.answer(
        "🌈 Выбери редкость:",
        reply_markup=rarity_keyboard(),
    )


@router.callback_query(
    F.data.startswith("admin:rarity:")
)
async def admin_card_rarity(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await user_is_admin(callback.from_user.id):
        await answer_callback(
            callback,
            "Нет прав администратора",
            alert=True,
        )
        return

    try:
        index = int(
            (callback.data or "").rsplit(":", 1)[-1]
        )
        rarity = RARITIES[index]
    except (ValueError, IndexError):
        await answer_callback(
            callback,
            "Некорректная редкость",
            alert=True,
        )
        return

    data = await state.get_data()

    if not data.get("file_id"):
        await state.clear()
        await answer_callback(
            callback,
            "Сначала отправь фотографию",
            alert=True,
        )
        return

    await state.update_data(rarity=rarity)
    await state.set_state(
        AdminStates.waiting_card_description
    )

    await callback.message.answer(
        f"🏷 Редкость: <b>{esc(rarity)}</b>\n\n"
        "Теперь отправь описание карты текстом. "
        "Для пустого описания отправь дефис."
    )

    await answer_callback(callback)


@router.message(
    AdminStates.waiting_card_description
)
async def admin_card_description(
    message: Message,
    state: FSMContext,
) -> None:
    if not await user_is_admin(message.from_user.id):
        await state.clear()
        return

    if not message.text:
        await message.answer(
            "❌ Описание нужно отправить текстом."
        )
        return

    data = await state.get_data()
    file_id = data.get("file_id")
    rarity = data.get("rarity")

    if not file_id or rarity not in RARITIES:
        await state.clear()
        await message.answer(
            "❌ Данные добавления карты потерялись. Начни заново."
        )
        return

    description = message.text.strip()

    if description in {"-", "—"}:
        description = ""

    async with transaction() as db:
        cursor = await db.execute(
            """
            INSERT INTO cards(file_id, rarity, description)
            VALUES (?, ?, ?)
            """,
            (file_id, rarity, description),
        )
        card_id = cursor.lastrowid

    await log_action(
        message.from_user.id,
        f"Добавлена карта #{card_id}, {rarity}",
    )

    await state.clear()

    await message.answer(
        "✅🎴 <b>КАРТА ДОБАВЛЕНА!</b>\n\n"
        f"ID: <b>#{card_id}</b>\n"
        f"Редкость: <b>{esc(rarity)}</b>"
    )


@router.message(
    AdminStates.waiting_card_photo
)
async def admin_card_photo_required(
    message: Message,
) -> None:
    await message.answer(
        "📸 Отправь именно фотографию, не файл-документ."
    )


# ------------------------------------------------------------
# Просмотр библиотеки альбомами до 10 фото
# ------------------------------------------------------------

@router.message(
    lambda message: (
        message.text
        and message.text.strip().lower()
        in {"all card", "100 card", "card 100"}
    )
)
async def admin_cards_album(
    message: Message,
) -> None:
    if not await user_is_admin(message.from_user.id):
        return

    limit = (
        100
        if message.text.strip().lower()
        in {"100 card", "card 100"}
        else 500
    )

    async with connect() as db:
        async with db.execute(
            """
            SELECT id, file_id, rarity, description
            FROM cards
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            cards = await cursor.fetchall()

    if not cards:
        await message.answer("🎴 Библиотека пока пуста.")
        return

    await message.answer(
        f"🎴 Отправляю <b>{len(cards)}</b> карт "
        "альбомами по 10 изображений."
    )

    for start in range(0, len(cards), 10):
        chunk = cards[start:start + 10]

        media = [
            InputMediaPhoto(
                media=row["file_id"],
                caption=(
                    f"🎴 #{safe_int(row['id'])} — "
                    f"{esc(row['rarity'])}\n"
                    f"📝 {esc(row['description']) or 'Без описания'}"
                ),
            )
            for row in chunk
        ]

        try:
            await message.answer_media_group(media)
        except Exception:
            logger.exception(
                "Не удалось отправить альбом карт"
            )

        await asyncio.sleep(0.2)


# ------------------------------------------------------------
# Просмотр карты: /card ID или card ID
# ------------------------------------------------------------

@router.message(
    lambda message: (
        message.text
        and re.fullmatch(
            r"/?card\s+\d+",
            message.text.strip(),
            re.IGNORECASE,
        )
        and message.text.strip().lower()
        not in {"card 100", "/card 100"}
    )
)
async def admin_card_info(
    message: Message,
) -> None:
    if not await user_is_admin(message.from_user.id):
        return

    try:
        card_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer(
            "Формат: <code>/card 123</code>"
        )
        return

    async with connect() as db:
        async with db.execute(
            """
            SELECT id, file_id, rarity, description
            FROM cards
            WHERE id = ?
            """,
            (card_id,),
        ) as cursor:
            card = await cursor.fetchone()

        if not card:
            await message.answer("❌ Карта не найдена.")
            return

        async with db.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS owners,
                   COALESCE(SUM(count), 0) AS copies
            FROM inventory
            WHERE card_id = ?
            """,
            (card_id,),
        ) as cursor:
            stats = await cursor.fetchone()

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить карту",
                    callback_data=f"admin:delete_card:{card_id}",
                )
            ]
        ]
    )

    await message.answer_photo(
        card["file_id"],
        caption=(
            f"🎴✨ <b>КАРТА #{card_id}</b> ✨🎴\n\n"
            f"🏷 Редкость: <b>{esc(card['rarity'])}</b>\n"
            f"📝 {esc(card['description']) or 'Без описания'}\n\n"
            f"👥 Владельцев: <b>{safe_int(stats['owners'])}</b>\n"
            f"📦 Всего копий: <b>{safe_int(stats['copies'])}</b>"
        ),
        reply_markup=markup,
    )


@router.callback_query(
    F.data.startswith("admin:delete_card:")
)
async def admin_delete_card(
    callback: CallbackQuery,
) -> None:
    if not await user_is_admin(callback.from_user.id):
        await answer_callback(
            callback,
            "Нет прав",
            alert=True,
        )
        return

    try:
        card_id = int(
            (callback.data or "").rsplit(":", 1)[-1]
        )
    except ValueError:
        await answer_callback(
            callback,
            "Некорректный ID",
            alert=True,
        )
        return

    async with transaction() as db:
        await db.execute(
            "DELETE FROM inventory WHERE card_id = ?",
            (card_id,),
        )
        deleted = await db.execute(
            "DELETE FROM cards WHERE id = ?",
            (card_id,),
        )

        if deleted.rowcount != 1:
            await answer_callback(
                callback,
                "Карта не найдена",
                alert=True,
            )
            return

    await log_action(
        callback.from_user.id,
        f"Удалена карта #{card_id}; остальные ID сохранены",
    )

    try:
        await callback.message.edit_caption(
            caption=f"🗑 Карта #{card_id} удалена. ID других карт не менялись."
        )
    except Exception:
        logger.exception("Не удалось обновить сообщение карты")

    await answer_callback(callback, "Карта удалена")


# ------------------------------------------------------------
# Админы и одноразовые коды
# ------------------------------------------------------------

@router.message(
    lambda message: command_is(message, "admins")
)
async def admins_command(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    async with connect() as db:
        async with db.execute(
            """
            SELECT user_id
            FROM admins
            ORDER BY added_at
            """
        ) as cursor:
            admins = await cursor.fetchall()

    if not admins:
        await message.answer(
            "👑 Дополнительных администраторов нет."
        )
        return

    rows = []

    for row in admins:
        user_id = safe_int(row["user_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"❌ Снять ID {user_id}",
                    callback_data=f"admin:remove:{user_id}",
                )
            ]
        )

    await message.answer(
        "👑✨ <b>АДМИНИСТРАТОРЫ</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ),
    )


@router.callback_query(
    F.data.startswith("admin:remove:")
)
async def remove_admin_callback(
    callback: CallbackQuery,
) -> None:
    if callback.from_user.id != SUPER_ADMIN_ID:
        await answer_callback(
            callback,
            "Только супер-администратор",
            alert=True,
        )
        return

    try:
        user_id = int(
            (callback.data or "").rsplit(":", 1)[-1]
        )
    except ValueError:
        await answer_callback(
            callback,
            "Некорректный ID",
            alert=True,
        )
        return

    async with transaction() as db:
        await db.execute(
            "DELETE FROM admins WHERE user_id = ?",
            (user_id,),
        )

    await log_action(
        callback.from_user.id,
        f"Снят администратор {user_id}",
    )

    await answer_callback(callback, "Администратор снят")


@router.message(
    lambda message: command_is(message, "now_admin_cod")
)
async def create_admin_code(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    alphabet = string.ascii_uppercase + string.digits
    code = "".join(
        secrets.choice(alphabet)
        for _ in range(10)
    )
    expires_at = now() + 3 * 3600

    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO admin_codes(
                code, created_by, expires_at, used
            )
            VALUES (?, ?, ?, 0)
            """,
            (code, message.from_user.id, expires_at),
        )

    await message.answer(
        "🔐✨ <b>ОДНОРАЗОВЫЙ КОД АДМИНА</b>\n\n"
        f"<code>{code}</code>\n"
        "⏳ Действует 3 часа."
    )


@router.message(
    lambda message: command_is(message, "I_am_admin")
)
async def request_admin_code(
    message: Message,
    state: FSMContext,
) -> None:
    await state.set_state(
        AdminStates.waiting_admin_code
    )
    await message.answer(
        "🔐 Отправь одноразовый код следующим сообщением."
    )


@router.message(
    AdminStates.waiting_admin_code
)
async def redeem_admin_code(
    message: Message,
    state: FSMContext,
) -> None:
    if not message.text:
        await message.answer("Код нужно отправить текстом.")
        return

    code = message.text.strip().upper()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT created_by, expires_at, used
            FROM admin_codes
            WHERE code = ?
            """,
            (code,),
        ) as cursor:
            row = await cursor.fetchone()

        if (
            not row
            or safe_int(row["used"])
            or safe_float(row["expires_at"]) <= now()
        ):
            await state.clear()
            await message.answer("❌ Код неверный или уже истёк.")
            return

        await db.execute(
            "UPDATE admin_codes SET used = 1 WHERE code = ?",
            (code,),
        )
        await db.execute(
            """
            INSERT OR IGNORE INTO admins(user_id, added_by, added_at)
            VALUES (?, ?, ?)
            """,
            (
                message.from_user.id,
                safe_int(row["created_by"]),
                now(),
            ),
        )

    await state.clear()
    await log_action(
        message.from_user.id,
        "Пользователь получил права администратора по коду",
    )
    await message.answer("🎉👑 Права администратора выданы!")


# ------------------------------------------------------------
# Админские действия с балансом, картами и артефактами
# ------------------------------------------------------------

@router.message(
    lambda message: (
        message.text
        and re.match(
            r"^/?бот\s+[+-](коины|карта|клинок|щит|броня)\b",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_grant_command(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.strip().split()

    if len(parts) < 3:
        await message.answer(
            "Пример: <code>/бот +коины 100 @username</code>\n"
            "<code>/бот +карта 12 @username</code>\n"
            "<code>/бот +щит reinforced 2 @username</code>"
        )
        return

    operation = parts[1].lower()
    is_add = operation.startswith("+")
    kind = operation[1:]

    target_id = await resolve_user_id(message)

    if not target_id:
        await message.answer(
            "❌ Пользователь не найден. Укажи @username "
            "или ответь на его сообщение."
        )
        return

    numeric = [
        int(token)
        for token in parts[2:]
        if token.lstrip("-").isdigit()
    ]

    if not numeric:
        await message.answer("❌ Укажи количество или ID карты.")
        return

    amount_or_card = numeric[0]

    try:
        async with transaction() as db:
            if kind == "коины":
                amount = amount_or_card

                if amount <= 0:
                    raise ValueError

                if is_add:
                    await db.execute(
                        """
                        UPDATE users
                        SET femcoins = femcoins + ?
                        WHERE user_id = ?
                        """,
                        (amount, target_id),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE users
                        SET femcoins = MAX(0, femcoins - ?)
                        WHERE user_id = ?
                        """,
                        (amount, target_id),
                    )

            elif kind == "карта":
                card_id = amount_or_card

                async with db.execute(
                    "SELECT id FROM cards WHERE id = ?",
                    (card_id,),
                ) as cursor:
                    card = await cursor.fetchone()

                if not card:
                    await message.answer("❌ Карта не найдена.")
                    return

                if is_add:
                    await db.execute(
                        """
                        INSERT INTO inventory(user_id, card_id, count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(user_id, card_id)
                        DO UPDATE SET count = count + 1
                        """,
                        (target_id, card_id),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE inventory
                        SET count = count - 1
                        WHERE user_id = ?
                          AND card_id = ?
                          AND count > 1
                        """,
                        (target_id, card_id),
                    )
                    await db.execute(
                        """
                        DELETE FROM inventory
                        WHERE user_id = ?
                          AND card_id = ?
                          AND count <= 1
                        """,
                        (target_id, card_id),
                    )

            else:
                if kind == "клинок":
                    artifact_type = "blade"
                    subtype = ""
                elif kind == "броня":
                    artifact_type = "armor"
                    subtype = ""
                else:
                    artifact_type = "shield"
                    subtype = "weak"

                    for token in parts[2:]:
                        if token.lower() in {
                            "weak",
                            "reinforced",
                            "femboy",
                        }:
                            subtype = token.lower()
                            break

                amount = amount_or_card

                if amount <= 0:
                    raise ValueError

                if is_add:
                    await db.execute(
                        """
                        INSERT INTO artifacts(
                            user_id, artifact_type, subtype,
                            amount, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, artifact_type, subtype)
                        DO UPDATE SET amount = amount + excluded.amount
                        """,
                        (
                            target_id,
                            artifact_type,
                            subtype,
                            amount,
                            now(),
                        ),
                    )
                else:
                    changed = await db.execute(
                        """
                        UPDATE artifacts
                        SET amount = amount - ?
                        WHERE user_id = ?
                          AND artifact_type = ?
                          AND subtype = ?
                          AND amount >= ?
                        """,
                        (
                            amount,
                            target_id,
                            artifact_type,
                            subtype,
                            amount,
                        ),
                    )

                    if changed.rowcount != 1:
                        await message.answer(
                            "❌ Недостаточно предметов."
                        )
                        return

    except ValueError:
        await message.answer(
            "❌ Количество должно быть положительным числом."
        )
        return

    await log_action(
        message.from_user.id,
        f"{operation} {amount_or_card} для пользователя {target_id}",
    )

    await message.answer(
        "✅✨ <b>АДМИНСКАЯ ОПЕРАЦИЯ ВЫПОЛНЕНА!</b>\n"
        f"👤 Пользователь: <code>{target_id}</code>"
    )


# ------------------------------------------------------------
# Админский VIP и кулдаун
# ------------------------------------------------------------

@router.message(
    lambda message: (
        message.text
        and re.match(
            r"^/?бот\s+[+-]вип\s+\d+\b",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_vip_command(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()

    try:
        operation = parts[1].lower()
        hours = int(parts[2])
    except (IndexError, ValueError):
        await message.answer(
            "Формат: <code>/бот +вип 12 @username</code>"
        )
        return

    target_id = await admin_target(message)

    if not target_id:
        await message.answer(
            "Укажи @username или ответь на сообщение."
        )
        return

    if hours <= 0:
        await message.answer("Часы должны быть больше нуля.")
        return

    async with transaction() as db:
        async with db.execute(
            "SELECT vip_until FROM users WHERE user_id = ?",
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            await message.answer(
                "Пользователь ещё не зарегистрирован."
            )
            return

        old_until = safe_float(row["vip_until"])

        if operation == "+вип":
            new_until = max(now(), old_until) + hours * 3600
        else:
            new_until = max(0, old_until - hours * 3600)

        await db.execute(
            "UPDATE users SET vip_until = ? WHERE user_id = ?",
            (new_until, target_id),
        )

    await log_action(
        message.from_user.id,
        f"{operation} {hours}ч для пользователя {target_id}",
    )

    await message.answer(
        f"✅ VIP обновлён для <code>{target_id}</code>.\n"
        f"Дата окончания: "
        f"<b>{format_date(new_until) if new_until > now() else 'VIP не активен'}</b>"
    )


@router.message(
    lambda message: (
        message.text
        and re.match(
            r"^/?бот\s+кд\s+\S+\s+-?\d+(\.\d+)?",
            message.text.strip(),
            re.IGNORECASE,
        )
    )
)
async def admin_cooldown_command(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()

    try:
        cooldown_hours = float(parts[2])
        duration_hours = float(parts[3])
    except (IndexError, ValueError):
        await message.answer(
            "Формат: <code>/бот кд 1 24 @username</code>\n"
            "Срок <code>-1</code> означает бессрочно."
        )
        return

    target_id = await admin_target(message)

    if not target_id:
        await message.answer(
            "Укажи @username или ответь на сообщение."
        )
        return

    if cooldown_hours < 0 or duration_hours == 0:
        await message.answer("❌ Некорректные значения.")
        return

    expires = (
        -1
        if duration_hours == -1
        else now() + duration_hours * 3600
    )

    async with transaction() as db:
        await db.execute(
            """
            UPDATE users
            SET custom_cd_hours = ?,
                custom_cd_expires = ?
            WHERE user_id = ?
            """,
            (cooldown_hours, expires, target_id),
        )

    await log_action(
        message.from_user.id,
        f"КД {cooldown_hours}ч для пользователя {target_id}",
    )

    await message.answer(
        f"✅ КД установлен для <code>{target_id}</code>."
    )


# ------------------------------------------------------------
# «Твой профиль» для супер-админа
# ------------------------------------------------------------

@router.message(
    lambda message: (
        message.text
        and message.text.lower().startswith("твой профиль")
    )
)
async def admin_view_profile(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    target_id = await admin_target(message)

    if not target_id:
        await message.answer(
            "Ответь на сообщение пользователя "
            "или укажи <code>твой профиль @username</code>."
        )
        return

    from handlers.common import build_profile_text
    from keyboards import profile_keyboard

    text = await build_profile_text(target_id)

    try:
        photos = await message.bot.get_user_profile_photos(
            user_id=target_id,
            limit=1,
        )
    except Exception:
        logger.exception("Не удалось получить фото профиля")
        photos = None

    if photos and photos.total_count:
        await message.answer_photo(
            photos.photos[0][-1].file_id,
            caption=text,
            reply_markup=profile_keyboard(target_id),
        )
    else:
        await message.answer(
            text,
            reply_markup=profile_keyboard(target_id),
        )


# ------------------------------------------------------------
# Логи
# ------------------------------------------------------------

@router.message(
    lambda message: command_is(message, "log")
)
async def admin_logs(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    async with connect() as db:
        async with db.execute(
            """
            SELECT admin_id, action, timestamp
            FROM logs
            ORDER BY id DESC
            LIMIT 25
            """
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("📋 Логи пока пусты.")
        return

    lines = [
        "📋✨ <b>ПОСЛЕДНИЕ 25 ДЕЙСТВИЙ</b> ✨📋",
        "",
    ]

    for row in rows:
        lines.append(
            f"🕒 {format_date(safe_float(row['timestamp']))}\n"
            f"👤 <code>{safe_int(row['admin_id'])}</code>\n"
            f"📝 {esc(row['action'])}\n"
        )

    await message.answer("\n".join(lines))


# ------------------------------------------------------------
# Информация об администраторе
# ------------------------------------------------------------

@router.message(
    lambda message: command_is(
        message,
        "set_adm_text",
    )
)
async def set_admin_text(
    message: Message,
    state: FSMContext,
) -> None:
    if not await user_is_admin(message.from_user.id):
        return

    await state.set_state(
        AdminStates.waiting_admin_text
    )
    await message.answer(
        "📝 Отправь текст для команды «кто админ»."
    )


@router.message(
    AdminStates.waiting_admin_text
)
async def save_admin_text(
    message: Message,
    state: FSMContext,
) -> None:
    if not await user_is_admin(message.from_user.id):
        await state.clear()
        return

    if not message.text:
        await message.answer("Нужен текст.")
        return

    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO settings(key, value)
            VALUES ('admin_info', ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (message.text[:3500],),
        )

    await state.clear()
    await log_action(
        message.from_user.id,
        "Изменён текст информации об администраторе",
    )
    await message.answer("✅ Текст сохранён!")


@router.message(
    lambda message: command_is(
        message,
        "кто админ",
        "admin",
    )
)
async def admin_info(
    message: Message,
) -> None:
    async with connect() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'admin_info'"
        ) as cursor:
            row = await cursor.fetchone()

    text = (
        str(row["value"])
        if row and row["value"]
        else "Информация об администраторе не задана."
    )

    await message.answer(
        f"👑✨ <b>ИНФОРМАЦИЯ</b> ✨👑\n\n{text}"
    )


# ------------------------------------------------------------
# Рассылка
# ------------------------------------------------------------

_broadcast_messages: dict[int, list[Message]] = {}


@router.message(
    lambda message: command_is(message, "add")
)
async def broadcast_start(
    message: Message,
    state: FSMContext,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    _broadcast_messages[message.from_user.id] = []
    await state.set_state(
        AdminStates.waiting_broadcast
    )

    await message.answer(
        "📣✨ <b>РЕЖИМ РАССЫЛКИ</b>\n\n"
        "Отправляй сообщения для рассылки.\n"
        "Завершить: <code>/save</code>\n"
        "Отменить: <code>/cancel</code>"
    )


@router.message(
    AdminStates.waiting_broadcast
)
async def broadcast_collect(
    message: Message,
    state: FSMContext,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        await state.clear()
        return

    if message.text and command_is(message, "cancel"):
        _broadcast_messages.pop(
            message.from_user.id,
            None,
        )
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return

    if message.text and command_is(message, "save"):
        items = _broadcast_messages.pop(
            message.from_user.id,
            [],
        )
        await state.clear()

        if not items:
            await message.answer("Нет сообщений для рассылки.")
            return

        async with connect() as db:
            async with db.execute(
                "SELECT user_id FROM users"
            ) as cursor:
                users = await cursor.fetchall()

            async with db.execute(
                """
                SELECT chat_id
                FROM chats
                WHERE chat_type IN ('group', 'supergroup')
                """
            ) as cursor:
                chats = await cursor.fetchall()

        destinations = {
            safe_int(row["user_id"])
            for row in users
        }
        destinations.update(
            safe_int(row["chat_id"])
            for row in chats
        )

        sent = 0
        failed = 0

        for destination in destinations:
            try:
                for item in items:
                    await message.bot.copy_message(
                        chat_id=destination,
                        from_chat_id=item.chat.id,
                        message_id=item.message_id,
                    )
                sent += 1
            except Exception:
                failed += 1
                logger.warning(
                    "Рассылка не доставлена в %s",
                    destination,
                    exc_info=True,
                )

            await asyncio.sleep(0.05)

        await message.answer(
            "📣✨ <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n"
            f"✅ Получателей: <b>{sent}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>"
        )
        return

    _broadcast_messages.setdefault(
        message.from_user.id,
        [],
    ).append(message)

    await message.answer(
        "✅ Сообщение добавлено в рассылку."
    )

# --- Новые команды управления прогрессом ---

@router.message(lambda m: m.text and m.text.startswith("/бот") and any(x in m.text for x in ["опыт", "уровень", "ступень", "лига", "дейлик"]))
async def superadmin_progress_manage(message: Message):
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()
    # Формат: /бот +-опыт 100 @user
    if len(parts) < 3: return

    cmd = parts[1].lower()
    try:
        val = int(re.sub(r"[^\d-]", "", parts[2]))
    except: return

    target_id = await resolve_user_id(message)
    if not target_id:
        await message.answer("❌ Пользователь не найден")
        return

    async with transaction() as db:
        if "опыт" in cmd:
            op = "+" if "+" in cmd else "-"
            await db.execute(f"UPDATE users SET experience = MAX(0, experience {op} ?) WHERE user_id = ?", (val, target_id))
            msg = f"✨ Опыт изменен на {val}"
        
        elif "уровень" in cmd:
            op = "+" if "+" in cmd else "-"
            await db.execute(f"UPDATE users SET level = MAX(1, level {op} ?) WHERE user_id = ?", (val, target_id))
            msg = f"📈 Уровень изменен на {val}"

        elif "ступень" in cmd:
            # 1 ступень = 10 уровней (упрощенно для прыжка)
            op = "+" if "+" in cmd else "-"
            await db.execute(f"UPDATE users SET level = MAX(1, level {op} ?) WHERE user_id = ?", (val * 10, target_id))
            msg = f"📊 Ступени изменены на {val} (через уровни)"

        elif "лига" in cmd:
            # 1 лига = 30 уровней
            op = "+" if "+" in cmd else "-"
            await db.execute(f"UPDATE users SET level = MAX(1, level {op} ?) WHERE user_id = ?", (val * 30, target_id))
            msg = f"🏆 Лиги изменены на {val} (через уровни)"

        elif "дейлик" in cmd:
            await db.execute("UPDATE users SET daily_streak = ? WHERE user_id = ?", (val, target_id))
            msg = f"📅 Серия дейлика установлена на {val}"

    await message.answer(f"✅ {msg} для ID {target_id}")


