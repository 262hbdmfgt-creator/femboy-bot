from __future__ import annotations

import logging
import time

from aiogram import F, Router, types
from aiogram.enums import ChatType
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import CHANNEL_URL, CHANNEL_USERNAME
from database import connect, ensure_user, now, transaction
from keyboards import (
    bonus_keyboard,
    profile_keyboard,
    subscription_keyboard,
)
from utils import (
    answer_callback,
    command_is,
    display_name,
    esc,
    format_date,
    format_duration,
    safe_float,
    safe_int,
)

router = Router()
logger = logging.getLogger("femboy_bot.common")


DAILY_NORMAL_SECONDS = 24 * 3600
DAILY_VIP_SECONDS = 22 * 3600
MAX_DAILY_STREAK = 30


RARITIES = [
    "Редкое",
    "Ультра редкое",
    "Мифическое",
    "Легендарное",
    "Фембойский артефакт",
    "Редчайший фем",
]


def league_stage_level(
    level: int,
) -> tuple[str, str, int]:
    level = max(1, level)
    index = level - 1

    league_index = min(
        9,
        index // 30,
    )

    inside = index % 30

    if inside < 5:
        stage = "Начинающий"
        stage_level = inside + 1
    elif inside < 15:
        stage = "Опытный"
        stage_level = inside - 5 + 6
    else:
        stage = "Профессионал"
        stage_level = inside - 15 + 16

    leagues = [
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

    return leagues[league_index], stage, stage_level


async def referral_reward_for_new_user(
    user_id: int,
) -> int | None:
    """
    Реферальная награда выдаётся сразу после корректного
    первого перехода по ссылке.
    """
    async with transaction() as db:
        async with db.execute(
            """
            SELECT referred_by,
                   referral_reward_given
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            return None

        referrer_id = safe_int(
            user["referred_by"]
        )

        already_given = safe_int(
            user["referral_reward_given"]
        )

        if (
            referrer_id <= 0
            or referrer_id == user_id
            or already_given != 0
        ):
            return None

        async with db.execute(
            """
            SELECT 1
            FROM users
            WHERE user_id = ?
            """,
            (referrer_id,),
        ) as cursor:
            referrer = await cursor.fetchone()

        if not referrer:
            await db.execute(
                """
                UPDATE users
                SET referral_reward_given = 2
                WHERE user_id = ?
                """,
                (user_id,),
            )
            return None

        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + 25
            WHERE user_id = ?
            """,
            (referrer_id,),
        )

        await db.execute(
            """
            UPDATE users
            SET referral_reward_given = 1
            WHERE user_id = ?
            """,
            (user_id,),
        )

        return referrer_id


async def build_profile_text(
    user_id: int,
) -> str:
    current_time = now()

    async with connect() as db:
        async with db.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            return "💔 Профиль ещё не создан!"

        async with db.execute(
            """
            SELECT COUNT(DISTINCT card_id) AS unique_cards,
                   COALESCE(SUM(count), 0) AS copies
            FROM inventory
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            card_stats = await cursor.fetchone()

        async with db.execute(
            """
            SELECT COUNT(*) AS total
            FROM cards
            """
        ) as cursor:
            card_total = await cursor.fetchone()

        async with db.execute(
            """
            SELECT artifact_type,
                   subtype,
                   SUM(amount) AS amount
            FROM artifacts
            WHERE user_id = ?
              AND amount > 0
            GROUP BY artifact_type, subtype
            """,
            (user_id,),
        ) as cursor:
            artifacts = await cursor.fetchall()

        clan = None

        if user["clan_id"]:
            async with db.execute(
                """
                SELECT clan_number,
                       name,
                       level
                FROM clans
                WHERE clan_id = ?
                """,
                (user["clan_id"],),
            ) as cursor:
                clan = await cursor.fetchone()

    league, stage, stage_level = league_stage_level(
        safe_int(user["level"], 1)
    )

    lines = [
        "🌸💖 <b>ФЕМБОЙСКИЙ ПРОФИЛЬ</b> 💖🌸",
        "",
        f"💰 Баланс: <b>{safe_int(user['femcoins'])} 🪙</b>",
        f"🏆 Лига: <b>{esc(league)}</b>",
        f"🌟 Ступень: <b>{esc(stage)}</b>",
        f"📈 Уровень: <b>{stage_level}</b>",
    ]

    vip_until = safe_float(user["vip_until"])

    if vip_until > current_time:
        lines.append(
            f"👑 VIP до: <b>{esc(format_date(vip_until))}</b>"
        )

    unique_cards = safe_int(
        card_stats["unique_cards"]
    )
    copies = safe_int(
        card_stats["copies"]
    )
    total_cards = safe_int(
        card_total["total"]
    )

    if unique_cards:
        lines.append(
            f"🎴 Собрано карт: "
            f"<b>{unique_cards}/{total_cards}</b> "
            f"✨ Копий: <b>{copies}</b>"
        )

    skips = safe_int(user["cd_resets_count"])
    skip_expires = safe_float(user["cd_reset_expires"])

    if skips > 0 and skip_expires > current_time:
        lines.append(
            f"⚡ Скипы: <b>{skips}</b> "
            f"⏳ ещё {format_duration(skip_expires - current_time)}"
        )

    blades = 0
    armor = 0
    shields: dict[str, int] = {}

    for artifact in artifacts:
        artifact_type = str(
            artifact["artifact_type"]
        )
        subtype = str(
            artifact["subtype"] or ""
        )
        amount = safe_int(artifact["amount"])

        if artifact_type == "blade":
            blades += amount
        elif artifact_type == "armor":
            armor += amount
        elif artifact_type == "shield":
            shields[subtype] = (
                shields.get(subtype, 0) + amount
            )

    if blades and not safe_int(user["blade_hidden"]):
        lines.append(
            f"🗡 Клинки: <b>{blades}</b>"
        )

    if armor and not safe_int(user["armor_hidden"]):
        lines.append(
            f"🛡 Броня: <b>{armor}</b>"
        )

    shield_names = {
        "weak": "слабых",
        "reinforced": "усиленных",
        "femboy": "фембойских",
    }

    if shields and not safe_int(user["shield_hidden"]):
        shield_text = []

        for subtype, amount in shields.items():
            if amount > 0:
                shield_text.append(
                    f"{shield_names.get(subtype, subtype)}: {amount}"
                )

        if shield_text:
            lines.append(
                "🔰 Щиты: <b>"
                + ", ".join(shield_text)
                + "</b>"
            )

    if clan:
        lines.append(
            f"🏳️ Клан: <b>{esc(clan['name'])}</b> "
            f"№{safe_int(clan['clan_number'])} "
            f"🏰 Ур. {safe_int(clan['level'])}"
        )

    attack_block = safe_float(
        user["attack_block_until"]
    )

    if attack_block > current_time:
        lines.append(
            "🚫 Запрет сбора карт: "
            f"<b>{format_duration(attack_block - current_time)}</b>"
        )

    return "\n".join(lines)


async def send_profile(
    message: Message,
    user_id: int,
) -> None:
    text = await build_profile_text(user_id)
    markup = profile_keyboard(user_id)

    try:
        photos = await message.bot.get_user_profile_photos(
            user_id=user_id,
            limit=1,
        )
    except Exception:
        logger.exception(
            "Ошибка получения аватарки пользователя %s",
            user_id,
        )
        photos = None

    if photos and photos.total_count > 0:
        await message.answer_photo(
            photo=photos.photos[0][-1].file_id,
            caption=text,
            reply_markup=markup,
        )
    else:
        await message.answer(
            text,
            reply_markup=markup,
        )


@router.message(
    lambda message: command_is(
        message,
        "профиль",
        "profile",
        "profil",
    )
)
async def profile_command(
    message: Message,
) -> None:
    await send_profile(
        message,
        message.from_user.id,
    )


@router.message(
    lambda message: command_is(
        message,
        "дейлик",
        "daily",
    )
)
async def daily_command(
    message: Message,
) -> None:
    user_id = message.from_user.id
    current_time = now()

    async with transaction() as db:
        async with db.execute(
            """
            SELECT daily_streak,
                   last_daily_time,
                   vip_until,
                   clan_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            await message.answer(
                "💔 Профиль не найден!"
            )
            return

        vip = (
            safe_float(user["vip_until"])
            > current_time
        )

        interval = (
            DAILY_VIP_SECONDS
            if vip
            else DAILY_NORMAL_SECONDS
        )

        last_daily = safe_float(
            user["last_daily_time"]
        )

        if last_daily and current_time - last_daily < interval:
            await message.answer(
                "⏳💖 <b>Дейлик уже получен!</b>\n"
                f"Следующая награда через "
                f"<b>{format_duration(interval - (current_time - last_daily))}</b>"
            )
            return

        old_streak = safe_int(
            user["daily_streak"]
        )

        if (
            last_daily
            and current_time - last_daily <= interval + 86400
        ):
            streak = old_streak + 1
        else:
            streak = 1

        streak = min(streak, 30)

        reward = 20 + 10 * streak

        if vip:
            reward += 5

        clan_bonus = 0

        if user["clan_id"]:
            async with db.execute(
                """
                SELECT level
                FROM clans
                WHERE clan_id = ?
                """,
                (user["clan_id"],),
            ) as cursor:
                clan = await cursor.fetchone()

            if clan:
                clan_bonus = safe_int(
                    clan["level"]
                ) * 15
                reward += clan_bonus

        await db.execute(
            """
            UPDATE users
            SET daily_streak = ?,
                last_daily_time = ?,
                femcoins = femcoins + ?
            WHERE user_id = ?
            """,
            (
                streak,
                current_time,
                reward,
                user_id,
            ),
        )

        await db.execute(
            """
            UPDATE clan_quests
            SET progress = MIN(
                target,
                progress + 1
            )
            WHERE user_id = ?
              AND quest_date = ?
              AND quest_type = 'daily'
            """,
            (
                user_id,
                time.strftime("%Y-%m-%d"),
            ),
        )

        # Опыт за дейлик.
        await db.execute(
            """
            UPDATE users
            SET experience = experience + 2
            WHERE user_id = ?
            """,
            (user_id,),
        )

    text = (
        "📅✨ <b>ДЕЙЛИК ПОЛУЧЕН!</b> ✨📅\n\n"
        f"🔥 Серия: <b>{streak} дней</b>\n"
        f"💰 Награда: <b>+{reward} 🪙</b>\n"
        "💫 Опыт: <b>+2</b>"
    )

    if vip:
        text += "\n👑 VIP-бонус: <b>+5 🪙</b>"

    if clan_bonus:
        text += (
            f"\n🏳️ Бонус клана: "
            f"<b>+{clan_bonus} 🪙</b>"
        )

    await message.answer(text)


@router.message(CommandStart())
async def start_command(
    message: Message,
    command: CommandObject,
) -> None:
    argument = (
        command.args or ""
    ).strip()

    referrer_id = 0

    if argument.lower().startswith("ref"):
        try:
            referrer_id = int(
                argument[3:]
            )
        except ValueError:
            referrer_id = 0

    is_new = await ensure_user(
        message.from_user.id,
        message.from_user.username
        or message.from_user.full_name,
        referred_by=referrer_id,
    )

    if argument.lower() == "bonus":
        if message.chat.type != ChatType.PRIVATE:
            bot_info = await message.bot.get_me()

            await message.answer(
                "🎁💖 Бонус забирается в личных сообщениях!",
                reply_markup=bonus_keyboard(
                    bot_info.username or "",
                ),
            )
            return

        await message.answer(
            "🎁✨ <b>БОНУС ЗА ПОДПИСКУ!</b> ✨🎁\n\n"
            f"Подпишись на {esc(CHANNEL_USERNAME)}, "
            "затем нажми проверку.",
            reply_markup=subscription_keyboard(
                CHANNEL_URL,
            ),
        )
        return

    if argument.lower() == "shop":
        if message.chat.type != ChatType.PRIVATE:
            bot_info = await message.bot.get_me()

            await message.answer(
                "🏪✨ Магазин открывается в личных сообщениях!",
                reply_markup=bonus_keyboard(
                    bot_info.username or "",
                ),
            )
            return

        from handlers.economy import show_shop

        await show_shop(message)
        return


    if is_new and referrer_id:
        referrer = await referral_reward_for_new_user(
            message.from_user.id
        )

        if referrer:
            try:
                await message.bot.send_message(
                    referrer,
                    "👥✨ <b>НОВЫЙ РЕФЕРАЛ!</b>\n\n"
                    f"{display_name(message.from_user)} "
                    "перешёл по вашей ссылке!\n"
                    "Начислено: <b>+25 🪙</b>!",
                )
            except Exception:
                logger.exception(
                    "Ошибка уведомления реферера"
                )

        await message.answer(
            "🎉💖 Ты зарегистрирован по реферальной ссылке!\n"
            "Пригласившему начислено <b>+25 🪙</b>."
        )
        return

    await message.answer(
        "🌸💖 <b>ПРИВЕТ, ФЕМБОЙЧИК!</b> 💖🌸\n\n"
        "🎴 <b>фем</b> — получить карту\n"
        "📅 <b>дейлик</b> — ежедневная награда\n"
        "👤 <b>профиль</b> — профиль и коллекция\n"
        "🏪 <b>магазин</b> — покупки\n"
        "👥 <b>реф</b> — приглашения"
    )


@router.callback_query(
    F.data == "bonus:check"
)
async def bonus_check_callback(
    callback: CallbackQuery,
) -> None:
    user_id = callback.from_user.id
    current_time = now()

    channel = CHANNEL_USERNAME.strip()
    if not channel.startswith("@") and not channel.startswith("-100"):
        channel = f"@{channel}"

    try:
        member = await callback.bot.get_chat_member(
            chat_id=channel,
            user_id=user_id,
        )
        logger.info("Подписка проверена: user=%s, channel=%s, status=%s", user_id, channel, member.status)
    except Exception as e:
        logger.error("Ошибка проверки подписки: user=%s, channel=%s, err=%s", user_id, channel, e)
        await answer_callback(
            callback,
            f"Не удалось проверить подписку на {channel}. Убедитесь, что бот добавлен в канал!",
            alert=True,
        )
        return

    # В aiogram 3 статус member.status может быть объектом Enum (ChatMemberStatus),
    # поэтому приводим к строке и берем значение .value
    status_str = str(getattr(member.status, "value", member.status)).lower()

    if status_str not in {
        "creator",
        "administrator",
        "member",
        "restricted",
    }:
        await answer_callback(
            callback,
            "Сначала подпишись на канал 💖",
            alert=True,
        )
        return



    if str(member.status) not in {
        "creator",
        "administrator",
        "member",
        "restricted",
    }:
        await answer_callback(
            callback,
            "Сначала подпишись на канал 💖",
            alert=True,
        )
        return

    async with transaction() as db:
        async with db.execute(
            """
            SELECT last_weekly_bonus
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

        last_bonus = safe_float(
            user["last_weekly_bonus"]
        )

        if (
            last_bonus
            and current_time - last_bonus < 7 * 86400
        ):
            await answer_callback(
                callback,
                "Бонус доступен раз в неделю ⏳",
                alert=True,
            )
            return

        await db.execute(
            """
            UPDATE users
            SET femcoins = femcoins + 50,
                channel_bonus_claimed = 1,
                last_weekly_bonus = ?,
                cd_resets_count = cd_resets_count + 1,
                cd_reset_expires = ?
            WHERE user_id = ?
            """,
            (
                current_time,
                current_time,
                current_time + 3 * 3600,
                user_id,
            ),
        )

    await answer_callback(
        callback,
        "🎁 Получено +50 🪙 и +1 скип КД!",
        alert=True,
    )
