# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import secrets
import string
import time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import CHANNEL_URL, CHANNEL_USERNAME, SUPER_ADMIN_ID
from database import connect, ensure_user, now, transaction
from keyboards import (
    artifact_shop_keyboard,
    coins_stars_keyboard,
    shop_keyboard,
    top_keyboard,
    vip_coins_keyboard,
    vip_payment_keyboard,
    vip_stars_keyboard,
)
from states import UserStates
from utils import (
    answer_callback,
    command_is,
    display_name,
    edit_message_safely,
    esc,
    find_user_by_username,
    format_date,
    format_duration,
    resolve_user_id,
    safe_float,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.economy")

# All Russian strings encoded in Unicode Escape to avoid any encoding corruption
STR_VIP_INFO = (
    "\U0001f451\u2728 <b>FEMBOY VIP</b> \u2728\U0001f451\n\n"
    "\U0001f3b4 20% \u0448\u0430\u043d\u0441 \u043d\u0430 \u0432\u0442\u043e\u0440\u0443\u044e \u043a\u0430\u0440\u0442\u0443\n"
    "\u23f3 \u041f\u0435\u0440\u0435\u0437\u0430\u0440\u044f\u0434\u043a\u0430 \u0444\u0435\u043c\u0430 \u2014 2 \u0447\u0430\u0441\u0430\n"
    "\U0001f4b0 \u041a\u043e\u043c\u043f\u0435\u043d\u0441\u0430\u0446\u0438\u044f \u0437\u0430 \u0434\u0443\u0431\u043b\u0438\u043a\u0430\u0442\u044b\n"
    "\U0001f340 \u0423\u043b\u0443\u0447\u0448\u0435\u043d\u043d\u044b\u0435 \u0432\u0435\u0441\u0430 \u0440\u0435\u0434\u043a\u0438\u0445 \u043a\u0430\u0440\u0442\n"
    "\U0001f4b8 \u041a\u043e\u043c\u0438\u0441\u0441\u0438\u044f \u043f\u0435\u0440\u0435\u0432\u043e\u0434\u043e\u0432 \u2014 \u0432\u0441\u0435\u0433\u043e 5%\n"
    "\U0001f4c5 \u0414\u0435\u0439\u043b\u0438\u043a \u043a\u0430\u0436\u0434\u044b\u0435 22 \u0447\u0430\u0441\u0430\n"
    "\U0001f496 +5 \U0001fa99 \u043a \u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e\u043c\u0443 \u0431\u043e\u043d\u0443\u0441\u0443"
)

VIP_COIN_PRICES = {1: 1500, 7: 4500, 30: 10000}
VIP_STAR_PRICES = {1: 250, 7: 800, 30: 2000}
COIN_STAR_PRICES = {100: 15, 500: 70, 1000: 135}


def make_promo_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ============================================================
# ÐÐÐ ÐÐÐÐ Ð¤ÐÐÐÐÐÐÐÐ (/Ð¿ÐµÑÐµÐ²Ð¾Ð´, /Ð¿ÐµÑÐµÐ´Ð°ÑÑ)
# ============================================================

@router.message(
    lambda message: (
        message.text
        and message.text.strip().lower().startswith(
            (
                "\u043f\u0435\u0440\u0435\u0432\u043e\u0434",
                "\u043f\u0435\u0440\u0435\u0432\u0435\u0441\u0442\u0438",
                "\u043f\u0435\u0440\u0435\u0434\u0430\u0442\u044c",
                "\u043e\u0442\u0434\u0430\u0442\u044c",
                "pay",
                "transfer",
            )
        )
    )
)
async def transfer_command(message: Message) -> None:
    sender = message.from_user
    await ensure_user(sender.id, sender.username or sender.full_name)

    parts = message.text.strip().split()
    amount = None

    for part in parts[1:]:
        if part.isdigit():
            amount = int(part)
            break

    if not amount or amount <= 0:
        await message.answer(
            "\U0001f4b8 \u0423\u043a\u0430\u0436\u0438 \u0441\u0443\u043c\u043c\u0443 \u043f\u0435\u0440\u0435\u0432\u043e\u0434\u043e\u0432 \u0447\u0438\u0441\u043b\u043e\u043c \u0431\u043e\u043b\u044c\u0448\u0435 0!\n"
            "\u041f\u0440\u0438\u043c\u0435\u0440: <code>\u043f\u0435\u0440\u0435\u0434\u0430\u0442\u044c 50 @username</code> \u0438\u043b\u0438 \u043e\u0442\u0432\u0435\u0442\u043e\u043c \u043d\u0430 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435."
        )
        return

    target_id = await resolve_user_id(message)

    if not target_id:
        await message.answer("\u274c \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u0423\u043a\u0430\u0436\u0438 @username \u0438\u043b\u0438 \u043e\u0442\u0432\u0435\u0442\u044c \u043d\u0430 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435!")
        return

    if target_id == sender.id:
        await message.answer("\u274c \u041d\u0435\u043b\u044c\u0437\u044f \u043f\u0435\u0440\u0435\u0432\u043e\u0434\u0438\u0442\u044c \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u044b \u0441\u0430\u043c\u043e\u043c\u0443 \u0441\u0435\u0431\u0435!")
        return

    current_time = now()

    async with transaction() as db:
        async with db.execute(
            "SELECT femcoins, vip_until FROM users WHERE user_id = ?",
            (sender.id,),
        ) as cursor:
            sender_row = await cursor.fetchone()

        if not sender_row or safe_int(sender_row["femcoins"]) < amount:
            await message.answer("\U0001f494 \u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432 \u0434\u043b\u044f \u043f\u0435\u0440\u0435\u0432\u043e\u0434\u0430!")
            return

        is_vip = safe_float(sender_row["vip_until"]) > current_time
        fee_percent = 5 if is_vip else 10
        fee = max(1, amount * fee_percent // 100)
        received = amount - fee

        updated = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - ?
            WHERE user_id = ? AND femcoins >= ?
            """,
            (amount, sender.id, amount),
        )

        if updated.rowcount != 1:
            await message.answer("\U0001f494 \u041e\u0448\u0438\u0431\u043a\u0430 \u0431\u0430\u043b\u0430\u043d\u0441\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437.")
            return

        await db.execute(
            "UPDATE users SET femcoins = femcoins + ? WHERE user_id = ?",
            (received, target_id),
        )

    try:
        from handlers.quests import update_quest_progress
        await update_quest_progress(sender.id, "transfer", amount)
    except Exception:
        pass

    await message.answer(
        "\U0001f4b8\u2728 <b>\u041f\u0415\u0420\u0415\u0412\u041e\u0414 \u0423\u0421\u041f\u0415\u0428\u0415\u041d!</b> \u2728\U0001f4b8\n\n"
        f"\U0001f464 \u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u0435\u043b\u044c: {display_name(sender)}\n"
        f"\U0001f4b0 \u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e: <b>{amount} \U0001fa99</b>\n"
        f"\U0001f3f7 \u041a\u043e\u043c\u0438\u0441\u0441\u0438\u044f ({fee_percent}%): <b>{fee} \U0001fa99</b>\n"
        f"\U0001f381 \u041f\u043e\u043b\u0443\u0447\u0435\u043d\u043e: <b>{received} \U0001fa99</b>"
    )


# ============================================================
# ÐÐÐÐÐÐÐÐÐ«Ð ÐÐÐÐ£Ð¡ (ÐÐÐÐÐÐ)
# ============================================================

@router.message(lambda message: command_is(message, "\u0434\u0435\u0439\u043b\u0438\u043a", "daily"))
async def daily_command(message: Message) -> None:
    user_id = message.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            "SELECT femcoins, daily_streak, last_daily_time, vip_until FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            await message.answer("\U0001f494 \u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0437\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440\u0443\u0439\u0441\u044f \u0447\u0435\u0440\u0435\u0437 /start!")
            return

        is_vip = safe_float(user["vip_until"]) > current_time
        cooldown = 22 * 3600 if is_vip else 24 * 3600
        last_daily = safe_float(user["last_daily_time"])
        elapsed = current_time - last_daily

        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            await message.answer(
                "\u23f3\u2728 <b>\u0415\u0429\u0401 \u0420\u0410\u041d\u041e!</b> \u2728\u23f3\n\n"
                f"\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0431\u043e\u043d\u0443\u0441 \u043c\u043e\u0436\u043d\u043e \u0437\u0430\u0431\u0440\u0430\u0442\u044c \u0447\u0435\u0440\u0435\u0437: <b>{format_duration(remaining)}</b>"
            )
            return

        streak = safe_int(user["daily_streak"])
        if elapsed > cooldown + 24 * 3600:
            streak = 1
        else:
            streak += 1

        reward = min(100, 10 + (streak - 1) * 2)
        if is_vip:
            reward += 5

        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + ?,
                daily_streak = ?,
                last_daily_time = ?
            WHERE user_id = ?
            """,
            (reward, streak, current_time, user_id),
        )

    try:
        from handlers.quests import update_quest_progress
        await update_quest_progress(user_id, "daily", 1)
    except Exception:
        pass

    vip_note = "\n\U0001f451 <i>VIP-\u0431\u043e\u043d\u0443\u0441 +5 \U0001fa99 \u0432\u043a\u043b\u044e\u0447\u0451\u043d!</i>" if is_vip else ""

    await message.answer(
        "\U0001f4c5\u2728 <b>\u0415\u0416\u0415\u0414\u041d\u0415\u0412\u041d\u042b\u0419 \u0411\u041e\u041d\u0423\u0421!</b> \u2728\U0001f4c5\n\n"
        f"\U0001f525 \u0421\u0435\u0440\u0438\u044f \u0434\u043d\u0435\u0439: <b>{streak}</b>\n"
        f"\U0001f4b0 \u041f\u043e\u043b\u0443\u0447\u0435\u043d\u043e: <b>+{reward} \U0001fa99</b>{vip_note}"
    )


# ============================================================
# ÐÐÐÐÐÐÐÐÐ¬ÐÐ«Ð ÐÐÐÐ£Ð¡
# ============================================================

@router.message(lambda message: command_is(message, "\u043d\u0435\u0434\u0435\u043b\u044c\u043a\u0430"))
async def weekly_bonus_command(message: Message) -> None:
    user_id = message.from_user.id
    current_time = now()

    channel = CHANNEL_USERNAME.strip()
    if not channel.startswith("@") and not channel.startswith("-100"):
        channel = f"@{channel}"

    try:
        member = await message.bot.get_chat_member(chat_id=channel, user_id=user_id)
        status = str(getattr(member.status, "value", member.status)).lower()
        if status not in {"creator", "administrator", "member", "restricted"}:
            await message.answer(f"\U0001f4e3 \u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043f\u043e\u0434\u043f\u0438\u0448\u0438\u0441\u044c \u043d\u0430 \u043a\u0430\u043d\u0430\u043b {channel}!")
            return
    except Exception:
        await message.answer(f"\u274c \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443 \u043d\u0430 \u043a\u0430\u043d\u0430\u043b {channel}.")
        return

    async with transaction() as db:
        async with db.execute(
            "SELECT last_weekly_bonus FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        last_weekly = safe_float(user["last_weekly_bonus"] if user else 0)
        cooldown = 7 * 86400

        if current_time - last_weekly < cooldown:
            remaining = int(cooldown - (current_time - last_weekly))
            await message.answer(
                "\u23f3 \u041d\u0435\u0434\u0435\u043b\u044c\u043a\u0443 \u043c\u043e\u0436\u043d\u043e \u0437\u0430\u0431\u0438\u0440\u0430\u0442\u044c \u0440\u0430\u0437 \u0432 7 \u0434\u043d\u0435\u0439!\n"
                f"\u041e\u0441\u0442\u0430\u043b\u043e\u0441\u044c \u0436\u0434\u0430\u0442\u044c: <b>{format_duration(remaining)}</b>"
            )
            return

        reward = 150
        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + ?,
                last_weekly_bonus = ?
            WHERE user_id = ?
            """,
            (reward, current_time, user_id),
        )

    await message.answer(
        "\U0001f389\U0001f381 <b>\u0415\u0416\u0415\u041d\u0415\u0414\u0415\u041b\u042c\u041d\u042b\u0419 \u0411\u041e\u041d\u0423\u0421 \u0417\u0410 \u041f\u041e\u0414\u041f\u0418\u0421\u041a\u0423!</b> \U0001f381\U0001f389\n\n"
        f"\U0001f4b0 \u041d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e: <b>+{reward} \U0001fa99</b>"
    )


# ============================================================
# ÐÐÐÐ£Ð¡ ÐÐ ÐÐ Ð£ÐÐÐ£
# ============================================================

@router.message(lambda message: command_is(message, "\u0431\u043e\u043d\u0443\u0441 \u0437\u0430 \u0433\u0440\u0443\u043f\u043f\u0443", "\u0433\u0440\u0443\u043f\u043f\u0430"))
async def group_reward_command(message: Message) -> None:
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.answer("\U0001f465 \u042d\u0442\u0443 \u043a\u043e\u043c\u0430\u043d\u0434\u0443 \u043d\u0443\u0436\u043d\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c \u0432 \u0432\u0430\u0448\u0435\u0439 \u0433\u0440\u0443\u043f\u043f\u0435!")
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        member = await message.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if member.status not in {"creator", "administrator"}:
            await message.answer("\u274c \u0411\u043e\u043d\u0443\u0441 \u0437\u0430 \u0433\u0440\u0443\u043f\u043f\u0443 \u043c\u043e\u0436\u0435\u0442 \u0437\u0430\u0431\u0440\u0430\u0442\u044c \u0442\u043e\u043b\u044c\u043a\u043e \u0441\u043e\u0437\u0434\u0430\u0442\u0435\u043b\u044c \u0438\u043b\u0438 \u0430\u0434\u043c\u0438\u043d \u0433\u0440\u0443\u043f\u043f\u044b!")
            return

        count = await message.bot.get_chat_member_count(chat_id=chat_id)
    except Exception:
        await message.answer("\u274c \u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 \u0441\u0442\u0430\u0442\u0443\u0441\u0430 \u0432 \u0433\u0440\u0443\u043f\u043f\u0435.")
        return

    if count < 30:
        await message.answer(f"\U0001f465 \u0412 \u0433\u0440\u0443\u043f\u043f\u0435 \u0434\u043e\u043b\u0436\u043d\u043e \u0431\u044b\u0442\u044c \u043c\u0438\u043d\u0438\u043c\u0443\u043c 30 \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432! \u0421\u0435\u0439\u0447\u0430\u0441: <b>{count}</b>.")
        return

    async with transaction() as db:
        async with db.execute(
            "SELECT reward_claimed FROM group_rewards WHERE chat_id = ?",
            (chat_id,),
        ) as cursor:
            reward = await cursor.fetchone()

        if reward and safe_int(reward["reward_claimed"]):
            await message.answer("\u274c \u0411\u043e\u043d\u0443\u0441 \u0437\u0430 \u044d\u0442\u0443 \u0433\u0440\u0443\u043f\u043f\u0443 \u0443\u0436\u0435 \u0431\u044b\u043b \u043f\u043e\u043b\u0443\u0447\u0435\u043d \u0440\u0430\u043d\u0435\u0435!")
            return

        bonus = 500
        await db.execute(
            """
            INSERT INTO group_rewards(chat_id, owner_id, reward_claimed, member_count, rewarded_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET reward_claimed = 1
            """,
            (chat_id, user_id, count, now()),
        )

        await db.execute(
            "UPDATE users SET femcoins = femcoins + ? WHERE user_id = ?",
            (bonus, user_id),
        )

    await message.answer(
        "\U0001f389\U0001f3f0 <b>\u0411\u041e\u041d\u0423\u0421 \u0417\u0410 \u0413\u0420\u0423\u041f\u041f\u0423 \u041f\u041e\u041b\u0423\u0427\u0415\u041d!</b>\n\n"
        f"\U0001f465 \u0423\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432: <b>{count}</b>\n"
        f"\U0001f4b0 \u041d\u0430\u0433\u0440\u0430\u0434\u0430 \u0441\u043e\u0437\u0434\u0430\u0442\u0435\u043b\u044e: <b>+{bonus} \U0001fa99</b>"
    )


# ============================================================
# Ð¢ÐÐ ÐÐÐ ÐÐÐÐ
# ============================================================

@router.message(lambda message: command_is(message, "\u0442\u043e\u043f", "top"))
async def top_command(message: Message) -> None:
    async with connect() as db:
        async with db.execute(
            """
            SELECT u.user_id, u.username, u.femcoins, COALESCE(SUM(i.count), 0) AS total_cards
            FROM users u
            LEFT JOIN inventory i ON i.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY total_cards DESC, u.femcoins DESC
            LIMIT 10
            """
        ) as cursor:
            rows = await cursor.fetchall()

    lines = ["\U0001f3c6\u2728 <b>\u0422\u041e\u041f-10 \u0418\u0413\u0420\u041e\u041a\u041e\u0412 \u041f\u041e \u041a\u0410\u0420\u0422\u0410\u041c</b> \u2728\U0001f3c6", ""]
    for idx, row in enumerate(rows, 1):
        name = str(row["username"] or f"\u0418\u0433\u0440\u043e\u043a {row['user_id']}").lstrip("@")
        lines.append(f"{idx}. <b>{esc(name)}</b> \u2014 <b>{safe_int(row['total_cards'])}</b> \U0001f3b4 ({safe_int(row['femcoins'])} \U0001fa99)")

    await message.answer("\n".join(lines), reply_markup=top_keyboard())


@router.callback_query(F.data == "top:100")
async def top_100_callback(callback: CallbackQuery) -> None:
    async with connect() as db:
        async with db.execute(
            """
            SELECT u.user_id, u.username, u.femcoins, COALESCE(SUM(i.count), 0) AS total_cards
            FROM users u
            LEFT JOIN inventory i ON i.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY total_cards DESC, u.femcoins DESC
            LIMIT 100
            """
        ) as cursor:
            rows = await cursor.fetchall()

    lines = ["\U0001f3c6\u2728 <b>\u0422\u041e\u041f-100 \u0418\u0413\u0420\u041e\u041a\u041e\u0412</b> \u2728\U0001f3c6", ""]
    for idx, row in enumerate(rows, 1):
        name = str(row["username"] or f"ID {row['user_id']}").lstrip("@")
        lines.append(f"{idx}. {esc(name)} \u2014 {safe_int(row['total_cards'])} \U0001f3b4 | {safe_int(row['femcoins'])} \U0001fa99")

    text = "\n".join(lines)
    try:
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await callback.bot.send_message(chat_id=callback.from_user.id, text=text[i:i+4000])
        else:
            await callback.bot.send_message(chat_id=callback.from_user.id, text=text)
        await answer_callback(callback, "\u0422\u043e\u043f-100 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d \u0432 \u041b\u0421! \U0001f4e9")
    except Exception:
        await answer_callback(callback, "\u041e\u0442\u043a\u0440\u043e\u0439 \u0434\u0438\u0430\u043b\u043e\u0433 \u0441 \u0431\u043e\u0442\u043e\u043c \u0432 \u041b\u0421, \u0447\u0442\u043e\u0431\u044b \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0422\u041e\u041f!", alert=True)


# ============================================================
# ÐÐÐÐÐÐÐ Ð ÐÐÐÐ£ÐÐÐ
# ============================================================

async def show_shop(message: Message) -> None:
    user_id = message.from_user.id

    async with connect() as db:
        async with db.execute(
            "SELECT femcoins FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

    balance = safe_int(user["femcoins"] if user else 0)

    await message.answer(
        "\U0001f3ec\u2728 <b>\u041c\u0410\u0413\u0410\u0417\u0418\u041d \u0424\u0415\u041c\u0411\u041e\u0415\u0412</b> \u2728\U0001f3ec\n\n"
        f"\U0001f4b0 \u0422\u0432\u043e\u0439 \u0431\u0430\u043b\u0430\u043d\u0441: <b>{balance} \U0001fa99</b>\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438 \u0440\u0430\u0437\u0434\u0435\u043b \u0438\u043b\u0438 \u043f\u0440\u0435\u0434\u043c\u0435\u0442! \U0001f496",
        reply_markup=shop_keyboard(),
    )


@router.message(lambda message: command_is(message, "\u043c\u0430\u0433\u0430\u0437\u0438\u043d", "shop"))
async def shop_command(message: Message) -> None:
    await ensure_user(
        message.from_user.id,
        message.from_user.username or message.from_user.full_name,
    )

    if message.chat.type != ChatType.PRIVATE:
        bot_info = await message.bot.get_me()
        await message.answer(
            "\U0001f3ec\u2728 \u041c\u0430\u0433\u0430\u0437\u0438\u043d \u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f \u0432 \u043b\u0438\u0447\u043d\u044b\u0445 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f\u0445!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="\U0001f496 \u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043c\u0430\u0433\u0430\u0437\u0438\u043d",
                            url=f"https://t.me/{bot_info.username}?start=shop",
                        )
                    ]
                ]
            ),
        )
        return

    await show_shop(message)


@router.message(lambda message: command_is(message, "vip", "\u0432\u0438\u043f", "\u043a\u0443\u043f\u0438\u0442\u044c \u0432\u0438\u043f"))
async def vip_command(message: Message) -> None:
    await ensure_user(
        message.from_user.id,
        message.from_user.username or message.from_user.full_name,
    )
    await message.answer(STR_VIP_INFO, reply_markup=vip_payment_keyboard())


@router.callback_query(F.data == "shop:main")
async def shop_main_callback(callback: CallbackQuery) -> None:
    async with connect() as db:
        async with db.execute(
            "SELECT femcoins FROM users WHERE user_id = ?",
            (callback.from_user.id,),
        ) as cursor:
            user = await cursor.fetchone()

    balance = safe_int(user["femcoins"] if user else 0)
    await edit_message_safely(
        callback.message,
        f"\U0001f3ec\u2728 <b>\u041c\u0410\u0413\u0410\u0417\u0418\u041d \u0424\u0415\u041c\u0411\u041e\u0415\u0412</b> \u2728\U0001f3ec\n\n\U0001f4b0 \u0422\u0432\u043e\u0439 \u0431\u0430\u043b\u0430\u043d\u0441: <b>{balance} \U0001fa99</b>\n\n\u0412\u044b\u0431\u0435\u0440\u0438 \u0440\u0430\u0437\u0434\u0435\u043b! \U0001f496",
        shop_keyboard(),
    )
    await answer_callback(callback)


@router.callback_query(F.data == "shop:vip")
async def shop_vip_callback(callback: CallbackQuery) -> None:
    await edit_message_safely(
        callback.message,
        STR_VIP_INFO + "\n\n\U0001f4b3 <b>\u0412\u044b\u0431\u0435\u0440\u0438 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u043f\u043b\u0430\u0442\u044b:</b>",
        vip_payment_keyboard(),
    )
    await answer_callback(callback)


@router.callback_query(F.data == "vip:coins")
async def vip_coins_menu_callback(callback: CallbackQuery) -> None:
    await edit_message_safely(
        callback.message,
        STR_VIP_INFO + "\n\n\U0001f4b0 <b>VIP \u0437\u0430 \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u044b \u2014 \u0432\u044b\u0431\u0435\u0440\u0438 \u0441\u0440\u043e\u043a:</b>",
        vip_coins_keyboard(),
    )
    await answer_callback(callback)


@router.callback_query(F.data == "vip:stars")
async def vip_stars_menu_callback(callback: CallbackQuery) -> None:
    await edit_message_safely(
        callback.message,
        STR_VIP_INFO + "\n\n\u2b50 <b>VIP \u0437\u0430 Telegram Stars \u2014 \u0432\u044b\u0431\u0435\u0440\u0438 \u0441\u0440\u043e\u043a:</b>",
        vip_stars_keyboard(),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("vip_coins:"))
async def buy_vip_coins_callback(callback: CallbackQuery) -> None:
    raw = callback.data.removeprefix("vip_coins:")
    try:
        days = int(raw)
    except ValueError:
        await answer_callback(callback, "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u0441\u0440\u043e\u043a VIP", alert=True)
        return

    price = VIP_COIN_PRICES.get(days)
    if price is None:
        await answer_callback(callback, "\u0422\u0430\u0440\u0438\u0444 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", alert=True)
        return

    user_id = callback.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            "SELECT femcoins, vip_until FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user or safe_int(user["femcoins"]) < price:
            await answer_callback(callback, f"\u041d\u0435 \u0445\u0432\u0430\u0442\u0430\u0435\u0442 {price} \U0001fa99", alert=True)
            return

        vip_until = max(current_time, safe_float(user["vip_until"]))
        result = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - ?,
                vip_until = ?
            WHERE user_id = ? AND femcoins >= ?
            """,
            (price, vip_until + days * 86400, user_id, price),
        )

        if result.rowcount != 1:
            await answer_callback(callback, "\u0411\u0430\u043b\u0430\u043d\u0441 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0441\u044f. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437.", alert=True)
            return

    await answer_callback(callback, f"VIP \u043d\u0430 {days} \u0434\u043d. \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d! \U0001f451", alert=True)


@router.callback_query(F.data.startswith("vip_stars:"))
async def buy_vip_stars_callback(callback: CallbackQuery) -> None:
    raw = callback.data.removeprefix("vip_stars:")
    try:
        days = int(raw)
    except ValueError:
        await answer_callback(callback, "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u0441\u0440\u043e\u043a VIP", alert=True)
        return

    stars = VIP_STAR_PRICES.get(days)
    if stars is None:
        await answer_callback(callback, "\u0422\u0430\u0440\u0438\u0444 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", alert=True)
        return

    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"VIP \u043d\u0430 {days} \u0434\u043d\u0435\u0439",
            description=f"\u041f\u0440\u0435\u043c\u0438\u0443\u043c VIP-\u0441\u0442\u0430\u0442\u0443\u0441 \u043d\u0430 {days} \u0434\u043d.",
            payload=f"vip:{days}",
            currency="XTR",
            prices=[LabeledPrice(label=f"VIP {days} \u0434\u043d.", amount=stars)],
            provider_token="",
        )
    except Exception:
        logger.exception("\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438 Stars-\u0441\u0447\u0451\u0442\u0430 \u043d\u0430 VIP")
        await answer_callback(callback, "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043e\u043f\u043b\u0430\u0442\u0443. \u041e\u0442\u043a\u0440\u043e\u0439 \u041b\u0421 \u0441 \u0431\u043e\u0442\u043e\u043c.", alert=True)
        return

    await answer_callback(callback)


@router.callback_query(F.data == "shop:coins")
async def coins_stars_menu_callback(callback: CallbackQuery) -> None:
    await edit_message_safely(
        callback.message,
        "\U0001f4b0\u2b50 <b>\u041a\u0423\u041f\u0418\u0422\u042c \u0424\u0415\u041c\u041a\u041e\u0418\u041d\u042b</b> \u2b50\U0001f4b0\n\n\u0412\u044b\u0431\u0435\u0440\u0438 \u043f\u0430\u043a\u0435\u0442:",
        coins_stars_keyboard(),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("coins_stars:"))
async def buy_coins_stars_callback(callback: CallbackQuery) -> None:
    raw = callback.data.removeprefix("coins_stars:")
    try:
        coins = int(raw)
    except ValueError:
        await answer_callback(callback, "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u043f\u0430\u043a\u0435\u0442", alert=True)
        return

    stars = COIN_STAR_PRICES.get(coins)
    if stars is None:
        await answer_callback(callback, "\u041f\u0430\u043a\u0435\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", alert=True)
        return

    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"{coins} \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432",
            description=f"\u041f\u0430\u043a\u0435\u0442 \u0438\u0437 {coins} \u0438\u0433\u0440\u043e\u0432\u044b\u0445 \u043c\u043e\u043d\u0435\u0442",
            payload=f"coins:{coins}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{coins} \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432", amount=stars)],
            provider_token="",
        )
    except Exception:
        logger.exception("\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438 Stars-\u0441\u0447\u0451\u0442\u0430 \u043d\u0430 \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u044b")
        await answer_callback(callback, "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043e\u043f\u043b\u0430\u0442\u0443. \u041e\u0442\u043a\u0440\u043e\u0439 \u041b\u0421 \u0441 \u0431\u043e\u0442\u043e\u043c.", alert=True)
        return

    await answer_callback(callback)


@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery) -> None:
    try:
        payload = query.invoice_payload
        valid = False
        if payload.startswith("vip:"):
            try:
                valid = int(payload.split(":", 1)[1]) in VIP_STAR_PRICES
            except ValueError:
                valid = False
        elif payload.startswith("coins:"):
            try:
                valid = int(payload.split(":", 1)[1]) in COIN_STAR_PRICES
            except ValueError:
                valid = False

        if not valid:
            await query.answer(ok=False, error_message="\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u0442\u0430\u0440\u0438\u0444.")
            return
        await query.answer(ok=True)
    except Exception:
        logger.exception("\u041e\u0448\u0438\u0431\u043a\u0430 pre_checkout")
        try:
            await query.answer(ok=False, error_message="\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f.")
        except Exception:
            pass


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message) -> None:
    payment = message.successful_payment
    if not payment:
        return

    payload = payment.invoice_payload
    user_id = message.from_user.id
    charge_id = payment.telegram_payment_charge_id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            "SELECT telegram_charge_id FROM payments WHERE telegram_charge_id = ?",
            (charge_id,),
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            return

        if payload.startswith("coins:"):
            try:
                coins = int(payload.split(":", 1)[1])
            except ValueError:
                return

            if coins not in COIN_STAR_PRICES:
                return

            await db.execute(
                "UPDATE users SET femcoins = femcoins + ? WHERE user_id = ?",
                (coins, user_id),
            )

        elif payload.startswith("vip:"):
            try:
                days = int(payload.split(":", 1)[1])
            except ValueError:
                return

            if days not in VIP_STAR_PRICES:
                return

            async with db.execute(
                "SELECT vip_until FROM users WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            old_vip = safe_float(user["vip_until"] if user else 0)
            new_vip = max(current_time, old_vip) + days * 86400

            await db.execute(
                "UPDATE users SET vip_until = ? WHERE user_id = ?",
                (new_vip, user_id),
            )

        await db.execute(
            """
            INSERT INTO payments(telegram_charge_id, user_id, payload, amount, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (charge_id, user_id, payload, safe_int(payment.total_amount), current_time),
        )

    if payload.startswith("coins:"):
        await message.answer(f"\u2b50\U0001f389 <b>\u041e\u041f\u041b\u0410\u0422\u0410 \u041f\u0420\u041e\u0428\u041b\u0410 \u0423\u0421\u041f\u0415\u0428\u041d\u041e!</b>\n\n\u041d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e: <b>+{coins} \U0001fa99</b>")
    else:
        await message.answer(f"\u2b50\U0001f451 <b>VIP \u0423\u0421\u041f\u0415\u0428\u041d\u041e \u0410\u041a\u0422\u0418\u0412\u0418\u0420\u041e\u0412\u0410\u041d!</b>\n\n\u0421\u0440\u043e\u043a: <b>{days} \u0434\u043d.</b>")


# ============================================================
# ÐÐ ÐÐÐÐÐÐÐ«
# ============================================================

@router.message(lambda message: command_is(message, "\u043f\u0440\u043e\u043c\u043e", "promo"))
async def promo_command(message: Message, state: FSMContext) -> None:
    await state.set_state(UserStates.waiting_promo_code)
    await message.answer("\U0001f511\u2728 <b>\u0412\u0412\u0415\u0414\u0418 \u041f\u0420\u041e\u041c\u041e\u041a\u041e\u0414</b> \u2728\U0001f511\n\n\u041e\u0442\u043f\u0440\u0430\u0432\u044c \u0435\u0433\u043e \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u043c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435\u043c.")


@router.message(UserStates.waiting_promo_code)
async def activate_promo_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("\u274c \u041f\u0440\u043e\u043c\u043e\u043a\u043e\u0434 \u043d\u0443\u0436\u043d\u043e \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0442\u0435\u043a\u0441\u0442\u043e\u043c!")
        return

    code = message.text.strip().upper()
    user_id = message.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT code, p_type, reward_type, reward_val, expires_at, is_used
            FROM promo_codes
            WHERE UPPER(code) = ?
            """,
            (code,),
        ) as cursor:
            promo = await cursor.fetchone()

        if not promo:
            await state.clear()
            await message.answer("\u274c \u041f\u0440\u043e\u043c\u043e\u043a\u043e\u0434 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d!")
            return

        if safe_float(promo["expires_at"]) <= current_time:
            await state.clear()
            await message.answer("\u23f3 \u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434\u0430 \u0438\u0441\u0442\u0451\u043a!")
            return

        promo_type = str(promo["p_type"]).upper()
        if promo_type == "L" and safe_int(promo["is_used"]) != 0:
            await state.clear()
            await message.answer("\u274c \u041e\u0434\u043d\u043e\u0440\u0430\u0437\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434 \u0443\u0436\u0435 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d!")
            return

        async with db.execute(
            "SELECT 1 FROM promo_claims WHERE user_id = ? AND code = ?",
            (user_id, code),
        ) as cursor:
            claimed = await cursor.fetchone()

        if claimed:
            await state.clear()
            await message.answer("\u274c \u0422\u044b \u0443\u0436\u0435 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043b \u044d\u0442\u043e\u0442 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434!")
            return

        reward_type = str(promo["reward_type"]).lower()
        reward_value = safe_int(promo["reward_val"])

        if reward_type == "f":
            await db.execute(
                "UPDATE users SET femcoins = femcoins + ? WHERE user_id = ?",
                (reward_value, user_id),
            )
            reward_text = f"+{reward_value} \U0001fa99"

        elif reward_type == "k":
            await db.execute(
                """
                UPDATE users
                SET cd_resets_count = cd_resets_count + 1,
                    cd_reset_expires = ?
                WHERE user_id = ?
                """,
                (current_time + 3 * 3600, user_id),
            )
            reward_text = "+1 \u26a1 \u0441\u043a\u0438\u043f \u041a\u0414"

        elif reward_type == "v":
            async with db.execute(
                "SELECT vip_until FROM users WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            old_vip = safe_float(user["vip_until"] if user else 0)
            new_vip = max(current_time, old_vip) + reward_value * 3600

            await db.execute(
                "UPDATE users SET vip_until = ? WHERE user_id = ?",
                (new_vip, user_id),
            )
            reward_text = f"\U0001f451 VIP \u043d\u0430 {reward_value} \u0447."

        elif reward_type == "d":
            async with db.execute(
                "SELECT daily_streak FROM users WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            current_streak = safe_int(user["daily_streak"]) if user else 0
            new_streak = current_streak + reward_value

            await db.execute(
                "UPDATE users SET daily_streak = ? WHERE user_id = ?",
                (new_streak, user_id),
            )
            reward_text = f"\U0001f4c5 +{reward_value} \u043a \u0441\u0435\u0440\u0438\u0438 \u0434\u0435\u0439\u043b\u0438\u043a\u0430 (\u0438\u0442\u043e\u0433\u043e: {new_streak})"

        else:
            await state.clear()
            await message.answer("\u274c \u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u0442\u0438\u043f \u043d\u0430\u0433\u0440\u0430\u0434\u044b \u0443 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434\u0430.")
            return

        await db.execute(
            "INSERT INTO promo_claims(user_id, code, claimed_at) VALUES (?, ?, ?)",
            (user_id, code, current_time),
        )

        if promo_type == "L":
            await db.execute(
                "UPDATE promo_codes SET is_used = 1 WHERE code = ?",
                (promo["code"],),
            )

    await state.clear()
    await message.answer(
        "\U0001f389\u2728 <b>\u041f\u0420\u041e\u041c\u041e\u041a\u041e\u0414 \u0410\u041a\u0422\u0418\u0412\u0418\u0420\u041e\u0412\u0410\u041d!</b>\n\n"
        f"\U0001f381 \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>{esc(reward_text)}</b>"
    )


@router.message(lambda message: message.text and message.text.strip().lower().startswith("/create_p"))
async def create_promo_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 5:
        await message.answer(
            "\U0001f4c3 <b>\u0424\u043e\u0440\u043c\u0430\u0442:</b>\n"
            "<code>/create_p M d 10 24</code>\n\n"
            "1: M (\u043c\u043d\u043e\u0433\u043e\u0440\u0430\u0437\u043e\u0432\u044b\u0439) / L (\u043e\u0434\u043d\u043e\u0440\u0430\u0437\u043e\u0432\u044b\u0439);\n"
            "2: f (\u043a\u043e\u0438\u043d\u044b) / k (\u0441\u043a\u0438\u043f \u041a\u0414) / v (VIP \u0447) / d (\u0441\u0435\u0440\u0438\u044f \u0434\u0435\u0439\u043b\u0438\u043a\u0430);\n"
            "3: \u0440\u0430\u0437\u043c\u0435\u0440 \u043d\u0430\u0433\u0440\u0430\u0434\u044b;\n"
            "4: \u0432\u0440\u0435\u043c\u044f \u0436\u0438\u0437\u043d\u0438 \u0432 \u0447\u0430\u0441\u0430\u0445."
        )
        return

    promo_type = parts[1].upper()
    reward_type = parts[2].lower()

    if promo_type not in {"M", "L"}:
        await message.answer("\u274c \u0422\u0438\u043f \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c M \u0438\u043b\u0438 L.")
        return

    if reward_type not in {"f", "k", "v", "d"}:
        await message.answer("\u274c \u0422\u0438\u043f \u043d\u0430\u0433\u0440\u0430\u0434\u044b \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c f, k, v \u0438\u043b\u0438 d.")
        return

    try:
        reward_value = int(parts[3])
        lifetime_hours = float(parts[4])
    except ValueError:
        await message.answer("\u274c \u0427\u0438\u0441\u043b\u0430 \u0443\u043a\u0430\u0437\u0430\u043d\u044b \u043d\u0435\u0432\u0435\u0440\u043d\u043e.")
        return

    if reward_value <= 0 or lifetime_hours <= 0:
        await message.answer("\u274c \u0417\u043d\u0430\u0447\u0435\u043d\u0438\u044f \u0434\u043e\u043b\u0436\u043d\u044b \u0431\u044b\u0442\u044c \u0431\u043e\u043b\u044c\u0448\u0435 \u0437\u0435\u0440\u043e.")
        return

    code = make_promo_code()
    expires_at = now() + lifetime_hours * 3600

    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO promo_codes(code, p_type, reward_type, reward_val, expires_at, is_used)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (code, promo_type, reward_type, reward_value, expires_at),
        )

    await message.answer(
        "\u2705\u2728 <b>\u041f\u0420\u041e\u041c\u041e\u041a\u041e\u0414 \u0421\u041e\u0417\u0414\u0410\u041d!</b>\n\n"
        f"\U0001f511 \u041a\u043e\u0434: <code>{esc(code)}</code>\n"
        f"\U0001f381 \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>{reward_value}</b> ({reward_type})\n"
        f"\u23f3 \u0421\u0440\u043e\u043a \u0436\u0438\u0437\u043d\u0438: <b>{lifetime_hours:g} \u0447.</b>"
    )


# ============================================================
# ÐÐÐÐÐÐÐÐ¢ÐÐÐ¬ÐÐ«Ð Ð¢ÐÐÐÐ Ð« Ð ÐÐÐÐÐÐÐÐ
# ============================================================

@router.callback_query(F.data == "shop:skip")
async def shop_skip_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            "SELECT femcoins, cd_resets_count, cd_reset_expires FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user or safe_int(user["femcoins"]) < 150:
            await answer_callback(callback, "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432 \U0001fa99", alert=True)
            return

        count = safe_int(user["cd_resets_count"])
        expires = safe_float(user["cd_reset_expires"])
        if expires <= current_time:
            count = 0

        changed = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 150,
                cd_resets_count = ?,
                cd_reset_expires = ?
            WHERE user_id = ? AND femcoins >= 150
            """,
            (count + 1, current_time + 3 * 3600, user_id),
        )

        if changed.rowcount != 1:
            await answer_callback(callback, "\u0411\u0430\u043b\u0430\u043d\u0441 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0441\u044f, \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437", alert=True)
            return

    await answer_callback(callback, "\u26a1 \u0421\u043a\u0438\u043f \u041a\u0414 \u043a\u0443\u043f\u043b\u0435\u043d!", alert=True)


@router.callback_query(F.data == "shop:luck")
async def shop_luck_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            "SELECT femcoins, luck_expires FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user or safe_int(user["femcoins"]) < 250:
            await answer_callback(callback, "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432 \U0001fa99", alert=True)
            return

        old_luck = safe_float(user["luck_expires"])
        luck_start = max(current_time, old_luck)

        changed = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 250,
                luck_expires = ?
            WHERE user_id = ? AND femcoins >= 250
            """,
            (luck_start + 3 * 3600, user_id),
        )

        if changed.rowcount != 1:
            await answer_callback(callback, "\u0411\u0430\u043b\u0430\u043d\u0441 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0441\u044f, \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437", alert=True)
            return

    await answer_callback(callback, "\U0001f340 \u042d\u043b\u0438\u043a\u0441\u0438\u0440 \u0443\u0434\u0430\u0447\u0438 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d \u043d\u0430 3 \u0447\u0430\u0441\u0430!", alert=True)


@router.callback_query(F.data == "shop:artifacts")
async def shop_artifacts_callback(callback: CallbackQuery) -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\U0001f6e2 \u0421\u043b\u0430\u0431\u044b\u0439 \u0449\u0438\u0442 \u2014 30 \U0001fa99", callback_data="artifact:weak_shield")],
            [InlineKeyboardButton(text="\U0001f6e1 \u0411\u0440\u043e\u043d\u044f \u2014 300 \U0001fa99", callback_data="artifact:armor")],
            [InlineKeyboardButton(text="\u2b05\ufe0f \u041d\u0430\u0437\u0430\u0434", callback_data="shop:main")],
        ]
    )
    await edit_message_safely(
        callback.message,
        "\U0001f6e1\u2728 <b>\u041c\u0410\u0413\u0410\u0417\u0418\u041d \u0410\u0420\u0422\u0415\u0424\u0410\u041a\u0422\u041e\u0412</b> \u2728\U0001f6e1\n\n\u0421\u043b\u0430\u0431\u044b\u0439 \u0449\u0438\u0442: 30 \U0001fa99.",
        markup,
    )
    await answer_callback(callback)


@router.callback_query(F.data == "artifact:weak_shield")
async def buy_weak_shield_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with transaction() as db:
        changed = await db.execute(
            "UPDATE users SET femcoins = femcoins - 30 WHERE user_id = ? AND femcoins >= 30",
            (user_id,),
        )
        if changed.rowcount != 1:
            await answer_callback(callback, "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432 \U0001fa99", alert=True)
            return

        await db.execute(
            """
            INSERT INTO artifacts(user_id, artifact_type, subtype, amount, created_at)
            VALUES (?, 'shield', 'weak', 1, ?)
            ON CONFLICT(user_id, artifact_type, subtype)
            DO UPDATE SET amount = amount + 1
            """,
            (user_id, now()),
        )
    await answer_callback(callback, "\U0001f6e2 \u0421\u043b\u0430\u0431\u044b\u0439 \u0449\u0438\u0442 \u043a\u0443\u043f\u043b\u0435\u043d!", alert=True)


@router.callback_query(F.data == "artifact:armor")
async def buy_armor_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with transaction() as db:
        changed = await db.execute(
            "UPDATE users SET femcoins = femcoins - 300 WHERE user_id = ? AND femcoins >= 300",
            (user_id,),
        )
        if changed.rowcount != 1:
            await answer_callback(callback, "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432 \U0001fa99", alert=True)
            return

        await db.execute(
            """
            INSERT INTO artifacts(user_id, artifact_type, subtype, amount, created_at)
            VALUES (?, 'armor', '', 1, ?)
            ON CONFLICT(user_id, artifact_type, subtype)
            DO UPDATE SET amount = amount + 1
            """,
            (user_id, now()),
        )
    await answer_callback(callback, "\U0001f6e1 \u0411\u0440\u043e\u043d\u044f \u043a\u0443\u043f\u043b\u0435\u043d\u0430!", alert=True)


@router.callback_query(F.data == "shop:new_card")
async def shop_new_card_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    async with transaction() as db:
        async with db.execute("SELECT femcoins FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()

        if not user or safe_int(user["femcoins"]) < 400:
            await answer_callback(callback, "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0444\u0435\u043c\u043a\u043e\u0438\u043d\u043e\u0432 \U0001fa99", alert=True)
            return

        async with db.execute(
            """
            SELECT id, file_id, rarity, description
            FROM cards
            WHERE id NOT IN (SELECT card_id FROM inventory WHERE user_id = ?)
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (user_id,),
        ) as cursor:
            card = await cursor.fetchone()

        if not card:
            await answer_callback(callback, "\u0412\u0441\u0435 \u043a\u0430\u0440\u0442\u044b \u0443\u0436\u0435 \u0441\u043e\u0431\u0440\u0430\u043d\u044b \U0001f3b4", alert=True)
            return

        changed = await db.execute(
            "UPDATE users SET femcoins = femcoins - 400 WHERE user_id = ? AND femcoins >= 400",
            (user_id,),
        )
        if changed.rowcount != 1:
            await answer_callback(callback, "\u0411\u0430\u043b\u0430\u043d\u0441 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0441\u044f, \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437", alert=True)
            return

        await db.execute(
            """
            INSERT INTO inventory(user_id, card_id, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET count = count + 1
            """,
            (user_id, safe_int(card["id"])),
        )

    await callback.message.answer_photo(
        photo=card["file_id"],
        caption=(
            "\U0001f381\u2728 <b>\u041d\u041e\u0412\u0410\u042f \u041a\u0410\u0420\u0422\u0410 \u041a\u0423\u041f\u041b\u0415\u041d\u0410!</b> \u2728\U0001f381\n\n"
            f"\U0001f3b4 \u041d\u043e\u043c\u0435\u0440: <b>#{safe_int(card['id'])}</b>\n"
            f"\U0001f3f7 \u0420\u0435\u0434\u043a\u043e\u0441\u0442\u044c: <b>{esc(card['rarity'])}</b>"
        ),
    )
    await answer_callback(callback, "\u041a\u0430\u0440\u0442\u0430 \u043a\u0443\u043f\u043b\u0435\u043d\u0430! \U0001f3b4")
