from __future__ import annotations

import logging
import secrets
import string
import time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import SUPER_ADMIN_ID
from database import connect, ensure_user, now, transaction
from keyboards import (
    artifact_shop_keyboard,
    coins_stars_keyboard,
    shop_keyboard,
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
    format_date,
    safe_float,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.economy")


VIP_INFO = (
    "👑✨ <b>ФЕМБОЙСКИЙ VIP</b> ✨👑\n\n"
    "🎴 20% шанс на вторую карту\n"
    "⏳ Кулдаун фема — 2 часа\n"
    "💰 Компенсация за дубликаты\n"
    "🍀 Улучшенные веса карт\n"
    "💸 Комиссия переводов — 5%\n"
    "📅 Дейлик каждые 22 часа\n"
    "💖 +5 монет к дейлику"
)

VIP_COIN_PRICES = {
    1: 1500,
    7: 4500,
    30: 10000,
}

VIP_STAR_PRICES = {
    1: 250,
    7: 800,
    30: 2000,
}

COIN_STAR_PRICES = {
    100: 15,
    500: 70,
    1000: 135,
}


def make_promo_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


async def show_shop(
    message: Message,
) -> None:
    user_id = message.from_user.id

    async with connect() as db:
        async with db.execute(
            """
            SELECT femcoins
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

    balance = safe_int(
        user["femcoins"]
        if user
        else 0
    )

    await message.answer(
        "🏪✨ <b>ФЕМБОЙСКИЙ МАГАЗИН</b> ✨🏪\n\n"
        f"💰 Твой баланс: <b>{balance} 🪙</b>\n\n"
        "Выбери раздел или товар, солнышко! 💖",
        reply_markup=shop_keyboard(),
    )


@router.message(
    lambda message: command_is(
        message,
        "магазин",
        "shop",
    )
)
async def shop_command(message: Message) -> None:
    await ensure_user(
        message.from_user.id,
        message.from_user.username
        or message.from_user.full_name,
    )

    if message.chat.type != ChatType.PRIVATE:
        bot_info = await message.bot.get_me()

        await message.answer(
            "🏪✨ Магазин открывается в личных сообщениях!",
            reply_markup=__import__(
                "aiogram.types",
                fromlist=["InlineKeyboardMarkup"],
            ).InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        __import__(
                            "aiogram.types",
                            fromlist=["InlineKeyboardButton"],
                        ).InlineKeyboardButton(
                            text="💖 Открыть магазин",
                            url=(
                                f"https://t.me/{bot_info.username}"
                                "?start=shop"
                            ),
                        )
                    ]
                ]
            ),
        )
        return

    await show_shop(message)


@router.message(
    lambda message: command_is(
        message,
        "vip",
        "вип",
        "купить вип",
    )
)
async def vip_command(message: Message) -> None:
    await ensure_user(
        message.from_user.id,
        message.from_user.username
        or message.from_user.full_name,
    )

    await message.answer(
        VIP_INFO,
        reply_markup=vip_payment_keyboard(),
    )


@router.callback_query(F.data == "shop:main")
async def shop_main_callback(
    callback: CallbackQuery,
) -> None:
    async with connect() as db:
        async with db.execute(
            """
            SELECT femcoins
            FROM users
            WHERE user_id = ?
            """,
            (callback.from_user.id,),
        ) as cursor:
            user = await cursor.fetchone()

    balance = safe_int(
        user["femcoins"]
        if user
        else 0
    )

    await edit_message_safely(
        callback.message,
        "🏪✨ <b>ФЕМБОЙСКИЙ МАГАЗИН</b> ✨🏪\n\n"
        f"💰 Баланс: <b>{balance} 🪙</b>\n\n"
        "Выбери раздел! 💖",
        shop_keyboard(),
    )

    await answer_callback(callback)


@router.callback_query(F.data == "shop:vip")
async def shop_vip_callback(
    callback: CallbackQuery,
) -> None:
    await edit_message_safely(
        callback.message,
        VIP_INFO + "\n\n💳 <b>Выбери способ оплаты:</b>",
        vip_payment_keyboard(),
    )

    await answer_callback(callback)


@router.callback_query(F.data == "vip:coins")
async def vip_coins_menu_callback(
    callback: CallbackQuery,
) -> None:
    await edit_message_safely(
        callback.message,
        VIP_INFO
        + "\n\n🪙 <b>VIP за фемкоины — выбери срок:</b>",
        vip_coins_keyboard(),
    )

    await answer_callback(callback)


@router.callback_query(F.data == "vip:stars")
async def vip_stars_menu_callback(
    callback: CallbackQuery,
) -> None:
    await edit_message_safely(
        callback.message,
        VIP_INFO
        + "\n\n⭐ <b>VIP за Stars — выбери срок:</b>",
        vip_stars_keyboard(),
    )

    await answer_callback(callback)


@router.callback_query(
    F.data.startswith("vip_coins:")
)
async def buy_vip_coins_callback(
    callback: CallbackQuery,
) -> None:
    raw = callback.data.removeprefix("vip_coins:")

    try:
        days = int(raw)
    except ValueError:
        await answer_callback(
            callback,
            "Некорректный срок VIP",
            alert=True,
        )
        return

    price = VIP_COIN_PRICES.get(days)

    if price is None:
        await answer_callback(
            callback,
            "Такого тарифа нет",
            alert=True,
        )
        return

    user_id = callback.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT femcoins, vip_until
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            await answer_callback(
                callback,
                "Профиль не найден",
                alert=True,
            )
            return

        if safe_int(user["femcoins"]) < price:
            await answer_callback(
                callback,
                f"Нужно {price} 🪙",
                alert=True,
            )
            return

        vip_until = max(
            current_time,
            safe_float(user["vip_until"]),
        )

        result = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - ?,
                vip_until = ?
            WHERE user_id = ?
              AND femcoins >= ?
            """,
            (
                price,
                vip_until + days * 86400,
                user_id,
                price,
            ),
        )

        if result.rowcount != 1:
            await answer_callback(
                callback,
                "Баланс изменился. Попробуй ещё раз.",
                alert=True,
            )
            return

    await answer_callback(
        callback,
        f"VIP на {days} дн. активирован! 👑",
        alert=True,
    )


@router.callback_query(
    F.data.startswith("vip_stars:")
)
async def buy_vip_stars_callback(
    callback: CallbackQuery,
) -> None:
    raw = callback.data.removeprefix("vip_stars:")

    try:
        days = int(raw)
    except ValueError:
        await answer_callback(
            callback,
            "Некорректный срок VIP",
            alert=True,
        )
        return

    stars = VIP_STAR_PRICES.get(days)

    if stars is None:
        await answer_callback(
            callback,
            "Такого тарифа нет",
            alert=True,
        )
        return

    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"VIP на {days} дней",
            description=f"Фембойский VIP на {days} дней",
            payload=f"vip:{days}",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label=f"VIP на {days} дней",
                    amount=stars,
                )
            ],
            provider_token="",
        )
    except Exception:
        logger.exception(
            "Не удалось отправить Stars-счёт на VIP"
        )
        await answer_callback(
            callback,
            "Не удалось открыть оплату. Проверь, что бот запущен в ЛС.",
            alert=True,
        )
        return

    await answer_callback(callback)


@router.callback_query(F.data == "shop:coins")
async def coins_stars_menu_callback(
    callback: CallbackQuery,
) -> None:
    await edit_message_safely(
        callback.message,
        "💰⭐ <b>ПОКУПКА ФЕМКОИНОВ</b> ⭐💰\n\n"
        "Выбери пакет:",
        coins_stars_keyboard(),
    )

    await answer_callback(callback)


@router.callback_query(
    F.data.startswith("coins_stars:")
)
async def buy_coins_stars_callback(
    callback: CallbackQuery,
) -> None:
    raw = callback.data.removeprefix("coins_stars:")

    try:
        coins = int(raw)
    except ValueError:
        await answer_callback(
            callback,
            "Некорректный пакет",
            alert=True,
        )
        return

    stars = COIN_STAR_PRICES.get(coins)

    if stars is None:
        await answer_callback(
            callback,
            "Такого пакета нет",
            alert=True,
        )
        return

    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"{coins} фемкоинов",
            description=f"Пакет из {coins} игровых монет",
            payload=f"coins:{coins}",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label=f"{coins} фемкоинов",
                    amount=stars,
                )
            ],
            provider_token="",
        )
    except Exception:
        logger.exception(
            "Не удалось отправить Stars-счёт на монеты"
        )
        await answer_callback(
            callback,
            "Не удалось открыть оплату. Открой бота в ЛС.",
            alert=True,
        )
        return

    await answer_callback(callback)


@router.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery,
) -> None:
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
            await query.answer(
                ok=False,
                error_message="Неизвестный тариф оплаты.",
            )
            return

        await query.answer(ok=True)

    except Exception:
        logger.exception(
            "Ошибка предварительной проверки Stars-платежа"
        )
        try:
            await query.answer(
                ok=False,
                error_message="Не удалось подтвердить оплату.",
            )
        except Exception:
            logger.exception(
                "Не удалось ответить на pre_checkout"
            )


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
) -> None:
    payment = message.successful_payment

    if not payment:
        return

    payload = payment.invoice_payload
    user_id = message.from_user.id
    charge_id = payment.telegram_payment_charge_id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT telegram_charge_id
            FROM payments
            WHERE telegram_charge_id = ?
            """,
            (charge_id,),
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            logger.warning(
                "Повторный successful_payment charge=%s",
                charge_id,
            )
            return

        if payload.startswith("coins:"):
            try:
                coins = int(payload.split(":", 1)[1])
            except ValueError:
                await message.answer(
                    "❌ Платёж получен, но пакет распознать не удалось. "
                    "Обратись к администратору."
                )
                return

            if coins not in COIN_STAR_PRICES:
                await message.answer(
                    "❌ Неизвестный пакет. Обратись к администратору."
                )
                return

            await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins + ?
                WHERE user_id = ?
                """,
                (coins, user_id),
            )

        elif payload.startswith("vip:"):
            try:
                days = int(payload.split(":", 1)[1])
            except ValueError:
                await message.answer(
                    "❌ Платёж получен, но срок VIP распознать не удалось."
                )
                return

            if days not in VIP_STAR_PRICES:
                await message.answer(
                    "❌ Неизвестный срок VIP. Обратись к администратору."
                )
                return

            async with db.execute(
                """
                SELECT vip_until
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            old_vip = safe_float(
                user["vip_until"]
                if user
                else 0
            )

            new_vip = max(
                current_time,
                old_vip,
            ) + days * 86400

            await db.execute(
                """
                UPDATE users
                SET vip_until = ?
                WHERE user_id = ?
                """,
                (new_vip, user_id),
            )

        else:
            await message.answer(
                "❌ Неизвестный платёжный продукт. "
                "Обратись к администратору."
            )
            return

        await db.execute(
            """
            INSERT INTO payments(
                telegram_charge_id,
                user_id,
                payload,
                amount,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                charge_id,
                user_id,
                payload,
                safe_int(payment.total_amount),
                current_time,
            ),
        )

    if payload.startswith("coins:"):
        await message.answer(
            "⭐🎉 <b>ОПЛАТА ПРОШЛА УСПЕШНО!</b>\n\n"
            f"Начислено: <b>+{coins} 🪙</b>"
        )
    else:
        await message.answer(
            "⭐👑 <b>VIP АКТИВИРОВАН!</b>\n\n"
            f"Срок: <b>{days} дн.</b>"
        )


@router.message(
    lambda message: command_is(
        message,
        "промо",
        "promo",
    )
)
async def promo_command(
    message: Message,
    state,
) -> None:
    await state.set_state(
        UserStates.waiting_promo_code
    )

    await message.answer(
        "🔑✨ <b>ВВЕДИ ПРОМОКОД</b> ✨🔑\n\n"
        "Отправь его следующим сообщением текстом."
    )


@router.message(UserStates.waiting_promo_code)
async def activate_promo_handler(
    message: Message,
    state,
) -> None:
    if not message.text:
        await message.answer(
            "❌ Промокод нужно отправить обычным текстом!"
        )
        return

    code = message.text.strip().upper()
    user_id = message.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT code,
                   p_type,
                   reward_type,
                   reward_val,
                   expires_at,
                   is_used
            FROM promo_codes
            WHERE UPPER(code) = ?
            """,
            (code,),
        ) as cursor:
            promo = await cursor.fetchone()

        if not promo:
            await state.clear()
            await message.answer(
                "❌ Промокод не найден!"
            )
            return

        if safe_float(promo["expires_at"]) <= current_time:
            await state.clear()
            await message.answer(
                "⌛ Срок действия промокода истёк!"
            )
            return

        promo_type = str(promo["p_type"]).upper()

        if (
            promo_type == "L"
            and safe_int(promo["is_used"]) != 0
        ):
            await state.clear()
            await message.answer(
                "❌ Одноразовый промокод уже использован!"
            )
            return

        async with db.execute(
            """
            SELECT 1
            FROM promo_claims
            WHERE user_id = ?
              AND code = ?
            """,
            (user_id, code),
        ) as cursor:
            claimed = await cursor.fetchone()

        if claimed:
            await state.clear()
            await message.answer(
                "❌ Ты уже активировал этот промокод!"
            )
            return

        reward_type = str(
            promo["reward_type"]
        ).lower()

        reward_value = safe_int(
            promo["reward_val"]
        )

        if reward_type == "f":
            await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins + ?
                WHERE user_id = ?
                """,
                (reward_value, user_id),
            )
            reward_text = f"+{reward_value} 🪙"

        elif reward_type == "k":
            await db.execute(
                """
                UPDATE users
                SET cd_resets_count = cd_resets_count + 1,
                    cd_reset_expires = ?
                WHERE user_id = ?
                """,
                (
                    current_time + 3 * 3600,
                    user_id,
                ),
            )
            reward_text = "+1 ⚡ скип КД"

        elif reward_type == "v":
            async with db.execute(
                """
                SELECT vip_until
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            old_vip = safe_float(
                user["vip_until"]
                if user
                else 0
            )

            new_vip = max(
                current_time,
                old_vip,
            ) + reward_value * 3600

            await db.execute(
                """
                UPDATE users
                SET vip_until = ?
                WHERE user_id = ?
                """,
                (new_vip, user_id),
            )
            reward_text = (
                f"👑 VIP на {reward_value} ч."
            )
elif reward_type == "d":
            async with db.execute(
                """
                SELECT daily_streak
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cursor:
                user = await cursor.fetchone()

            current_streak = safe_int(user["daily_streak"]) if user else 0
            new_streak = current_streak + reward_value

            await db.execute(
                """
                UPDATE users
                SET daily_streak = ?
                WHERE user_id = ?
                """,
                (new_streak, user_id),
            )
            reward_text = f"📅 +{reward_value} к серии дейлика (итого: {new_streak})"


        else:
            await state.clear()
            await message.answer(
                "❌ У промокода неизвестный тип награды."
            )
            return

        await db.execute(
            """
            INSERT INTO promo_claims(
                user_id,
                code,
                claimed_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                code,
                current_time,
            ),
        )

        if promo_type == "L":
            await db.execute(
                """
                UPDATE promo_codes
                SET is_used = 1
                WHERE code = ?
                """,
                (promo["code"],),
            )

    await state.clear()

    await message.answer(
        "🎉✨ <b>ПРОМОКОД АКТИВИРОВАН!</b>\n\n"
        f"🎁 Награда: <b>{esc(reward_text)}</b>"
    )


@router.message(
    lambda message: (
        message.text
        and message.text.strip().lower().startswith("/create_p")
    )
)
async def create_promo_command(
    message: Message,
) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    parts = message.text.split()

    if len(parts) != 5:
        await message.answer(
            "🧾 <b>Формат:</b>\n"
            "<code>/create_p M v 5 24</code>\n\n"
            "M/L — многоразовый/одноразовый код;\n"
            "f/k/v — фемкоины/скип/VIP;\n"
            "4-й параметр — размер награды;\n"
            "5-й параметр — срок жизни кода в часах."
        )
        return

    promo_type = parts[1].upper()
    reward_type = parts[2].lower()

    if promo_type not in {"M", "L"}:
        await message.answer(
            "❌ Тип кода должен быть M или L."
        )
        return

    if reward_type not in {"f", "k", "v"}:
        await message.answer(
            "❌ Тип награды должен быть f, k или v."
        )
        return

    try:
        reward_value = int(parts[3])
        lifetime_hours = float(parts[4])
    except ValueError:
        await message.answer(
            "❌ Награда и срок должны быть числами."
        )
        return

    if reward_value <= 0 or lifetime_hours <= 0:
        await message.answer(
            "❌ Награда и срок должны быть больше нуля."
        )
        return

    code = make_promo_code()
    expires_at = now() + lifetime_hours * 3600

    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO promo_codes(
                code,
                p_type,
                reward_type,
                reward_val,
                expires_at,
                is_used
            )
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                code,
                promo_type,
                reward_type,
                reward_value,
                expires_at,
            ),
        )

    await message.answer(
        "✅✨ <b>ПРОМОКОД СОЗДАН!</b>\n\n"
        f"🔑 Код: <code>{esc(code)}</code>\n"
        f"🎁 Награда: <b>{reward_value}</b>\n"
        f"⏳ Код действует: "
        f"<b>{lifetime_hours:g} ч.</b>"
    )

# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ МАГАЗИНА
# ============================================================

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


@router.callback_query(F.data == "shop:skip")
async def shop_skip_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT femcoins,
                   cd_resets_count,
                   cd_reset_expires
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user or safe_int(user["femcoins"]) < 150:
            await answer_callback(
                callback,
                "Недостаточно фемкоинов 🪙",
                alert=True,
            )
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
            WHERE user_id = ?
              AND femcoins >= 150
            """,
            (
                count + 1,
                current_time + 3 * 3600,
                user_id,
            ),
        )

        if changed.rowcount != 1:
            await answer_callback(
                callback,
                "Баланс изменился, повтори покупку",
                alert=True,
            )
            return

    await answer_callback(
        callback,
        "⚡ Скип КД куплен!",
        alert=True,
    )


@router.callback_query(F.data == "shop:luck")
async def shop_luck_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT femcoins,
                   luck_expires
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user or safe_int(user["femcoins"]) < 250:
            await answer_callback(
                callback,
                "Недостаточно фемкоинов 🪙",
                alert=True,
            )
            return

        old_luck = safe_float(user["luck_expires"])
        luck_start = max(current_time, old_luck)

        changed = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 250,
                luck_expires = ?
            WHERE user_id = ?
              AND femcoins >= 250
            """,
            (
                luck_start + 3 * 3600,
                user_id,
            ),
        )

        if changed.rowcount != 1:
            await answer_callback(
                callback,
                "Баланс изменился, повтори покупку",
                alert=True,
            )
            return

    await answer_callback(
        callback,
        "🍀 Эликсир удачи активирован на 3 часа!",
        alert=True,
    )


@router.callback_query(F.data == "shop:artifacts")
async def shop_artifacts_callback(
    callback: CallbackQuery,
) -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔰 Слабый щит — 30 🪙",
                    callback_data="artifact:weak_shield",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛡 Броня — 300 🪙",
                    callback_data="artifact:armor",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop:main",
                )
            ],
        ]
    )

    await edit_message_safely(
        callback.message,
        "🛡✨ <b>МАГАЗИН АРТЕФАКТОВ</b> ✨🛡\n\n"
        "🔰 Слабый щит можно купить за 30 🪙.\n"
        "💎 Усиленный и фембойский щиты "
        "получаются только крафтом.",
        markup,
    )

    await answer_callback(callback)


@router.callback_query(F.data == "artifact:weak_shield")
async def buy_weak_shield_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id

    async with transaction() as db:
        changed = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 30
            WHERE user_id = ?
              AND femcoins >= 30
            """,
            (user_id,),
        )

        if changed.rowcount != 1:
            await answer_callback(
                callback,
                "Недостаточно фемкоинов 🪙",
                alert=True,
            )
            return

        await db.execute(
            """
            INSERT INTO artifacts(
                user_id,
                artifact_type,
                subtype,
                amount,
                created_at
            )
            VALUES (?, 'shield', 'weak', 1, ?)
            ON CONFLICT(user_id, artifact_type, subtype)
            DO UPDATE SET amount = amount + 1
            """,
            (
                user_id,
                now(),
            ),
        )

    await answer_callback(
        callback,
        "🔰 Слабый щит куплен!",
        alert=True,
    )


@router.callback_query(F.data == "artifact:armor")
async def buy_armor_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id

    async with transaction() as db:
        changed = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 300
            WHERE user_id = ?
              AND femcoins >= 300
            """,
            (user_id,),
        )

        if changed.rowcount != 1:
            await answer_callback(
                callback,
                "Недостаточно фемкоинов 🪙",
                alert=True,
            )
            return

        await db.execute(
            """
            INSERT INTO artifacts(
                user_id,
                artifact_type,
                subtype,
                amount,
                created_at
            )
            VALUES (?, 'armor', '', 1, ?)
            ON CONFLICT(user_id, artifact_type, subtype)
            DO UPDATE SET amount = amount + 1
            """,
            (
                user_id,
                now(),
            ),
        )

    await answer_callback(
        callback,
        "🛡 Броня куплена!",
        alert=True,
    )


@router.callback_query(F.data == "shop:new_card")
async def shop_new_card_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id

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

        if not user or safe_int(user["femcoins"]) < 400:
            await answer_callback(
                callback,
                "Недостаточно фемкоинов 🪙",
                alert=True,
            )
            return

        async with db.execute(
            """
            SELECT id,
                   file_id,
                   rarity,
                   description
            FROM cards
            WHERE id NOT IN (
                SELECT card_id
                FROM inventory
                WHERE user_id = ?
            )
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (user_id,),
        ) as cursor:
            card = await cursor.fetchone()

        if not card:
            await answer_callback(
                callback,
                "Все карты уже собраны 🎴",
                alert=True,
            )
            return

        changed = await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins - 400
            WHERE user_id = ?
              AND femcoins >= 400
            """,
            (user_id,),
        )

        if changed.rowcount != 1:
            await answer_callback(
                callback,
                "Баланс изменился, повтори покупку",
                alert=True,
            )
            return

        await db.execute(
            """
            INSERT INTO inventory(
                user_id,
                card_id,
                count
            )
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET count = count + 1
            """,
            (
                user_id,
                safe_int(card["id"]),
            ),
        )

    await callback.message.answer_photo(
        photo=card["file_id"],
        caption=(
            "🎁✨ <b>НОВАЯ КАРТА КУПЛЕНА!</b> ✨🎁\n\n"
            f"🎴 Номер: <b>#{safe_int(card['id'])}</b>\n"
            f"🏷 Редкость: <b>{esc(card['rarity'])}</b>\n"
            f"📝 {esc(card['description']) or 'Без описания'}"
        ),
    )

    await answer_callback(
        callback,
        "Карта куплена! 🎴",
    )
