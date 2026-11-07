from __future__ import annotations

import asyncio
import json
import logging
import random
import secrets
from typing import Any

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import SUPER_ADMIN_ID
from database import connect, now, transaction
from utils import answer_callback, command_is, display_name, esc, safe_float, safe_int

router = Router()
logger = logging.getLogger("femboy_bot.chests")

_spawn_locks: dict[int, asyncio.Lock] = {}
_rain_tasks: set[asyncio.Task] = set()


def _chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _spawn_locks:
        _spawn_locks[chat_id] = asyncio.Lock()
    return _spawn_locks[chat_id]


def chest_markup(chest_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Забрать сундук!",
                    callback_data=f"chest:claim:{chest_id}",
                )
            ]
        ]
    )


def choose_fem_chest() -> tuple[str, dict[str, Any]]:
    """Типы внутри сундуков, условные шансы: 50/25/20/5."""
    chest_type = random.choices(
        ["normal", "rare", "legendary", "artifact"],
        weights=[50, 25, 20, 5],
        k=1,
    )[0]

    if chest_type == "normal":
        return chest_type, {"coins": random.randint(5, 49)}

    if chest_type == "rare":
        return chest_type, {"coins": random.randint(50, 99)}

    if chest_type == "legendary":
        return chest_type, {"coins": random.randint(100, 199)}

    return chest_type, {}


def chest_title(chest_type: str) -> str:
    return {
        "normal": "📦✨ <b>ОБЫЧНЫЙ СУНДУК!</b> ✨📦",
        "rare": "💎✨ <b>РЕДКИЙ СУНДУК!</b> ✨💎",
        "legendary": "🌟👑 <b>ЛЕГЕНДАРНЫЙ СУНДУК!</b> 👑🌟",
        "artifact": "🩷🗡 <b>ФЕМБОЙСКИЙ АРТЕФАКТНЫЙ СУНДУК!</b> 🗡🩷",
    }.get(chest_type, "📦 <b>СУНДУК!</b>")


async def create_chest(
    chat_id: int,
    chest_type: str,
    payload: dict[str, Any],
    *,
    lifetime: int = 3600,
) -> str:
    chest_id = secrets.token_urlsafe(12)
    created = now()

    async with transaction() as db:
        await db.execute(
            """
            INSERT INTO chests(
                chest_id, chat_id, chest_type, payload,
                created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chest_id,
                chat_id,
                chest_type,
                json.dumps(payload, ensure_ascii=False),
                created,
                created + lifetime,
            ),
        )

    return chest_id


async def maybe_spawn_after_fem(message: Message) -> bool:
    """Один бросок 10% после карты; не создаёт второй активный сундук."""
    if message.chat.type not in {
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    }:
        return False

    if random.random() >= 0.10:
        return False

    async with _chat_lock(message.chat.id):
        async with connect() as db:
            async with db.execute(
                """
                SELECT 1
                FROM chests
                WHERE chat_id = ?
                  AND claimed_by IS NULL
                  AND expires_at > ?
                LIMIT 1
                """,
                (message.chat.id, now()),
            ) as cursor:
                active = await cursor.fetchone()

        if active:
            return False

        chest_type, payload = choose_fem_chest()
        chest_id = await create_chest(
            message.chat.id,
            chest_type,
            payload,
        )

        try:
            await message.answer(
                chest_title(chest_type)
                + "\n\n🎁 Кто первым нажмёт кнопку — "
                "тот получит награду!\n"
                "👀 Содержимое пока неизвестно!",
                reply_markup=chest_markup(chest_id),
            )
            return True
        except Exception:
            logger.exception("Не удалось отправить сундук")
            async with transaction() as db:
                await db.execute(
                    "DELETE FROM chests WHERE chest_id = ?",
                    (chest_id,),
                )
            return False


async def grant_artifact(
    db,
    user_id: int,
    artifact_type: str,
    subtype: str,
    amount: int,
) -> None:
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
        (user_id, artifact_type, subtype, amount, now()),
    )


async def reward_chest(
    db,
    user_id: int,
    chest_type: str,
    payload: dict[str, Any],
) -> str:
    rewards: list[str] = []

    if chest_type in {"normal", "rare", "legendary"}:
        coins = safe_int(payload.get("coins"), 0)

        if coins <= 0:
            return "Ошибка содержимого сундука"

        await db.execute(
            "UPDATE users SET femcoins = femcoins + ? WHERE user_id = ?",
            (coins, user_id),
        )
        rewards.append(f"+{coins} 🪙")

        if chest_type == "legendary" and random.random() < 0.05:
            await grant_artifact(db, user_id, "blade", "", 1)
            rewards.append("+1 🗡 клинок")

    elif chest_type == "artifact":
        roll = random.random()

        if roll < 0.50:
            coins = random.randint(200, 299)
            await db.execute(
                "UPDATE users SET femcoins = femcoins + ? WHERE user_id = ?",
                (coins, user_id),
            )
            await grant_artifact(db, user_id, "blade", "", 1)
            rewards.extend([f"+{coins} 🪙", "+1 🗡 клинок"])

        elif roll < 0.75:
            coins = random.randint(300, 349)
            await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins + ?,
                    cd_resets_count = cd_resets_count + 1,
                    cd_reset_expires = ?
                WHERE user_id = ?
                """,
                (coins, now() + 3 * 3600, user_id),
            )
            await grant_artifact(db, user_id, "blade", "", 1)
            rewards.extend(
                [f"+{coins} 🪙", "+1 🗡 клинок", "+1 ⚡ скип КД"]
            )

        elif roll < 0.92:
            coins = random.randint(300, 349)
            await db.execute(
                """
                UPDATE users
                SET femcoins = femcoins + ?,
                    cd_resets_count = cd_resets_count + 1,
                    cd_reset_expires = ?
                WHERE user_id = ?
                """,
                (coins, now() + 3 * 3600, user_id),
            )
            await grant_artifact(db, user_id, "blade", "", 1)
            await grant_artifact(db, user_id, "shield", "weak", 1)
            rewards.extend(
                [
                    f"+{coins} 🪙",
                    "+1 🗡 клинок",
                    "+1 🔰 слабый щит",
                    "+1 ⚡ скип КД",
                ]
            )

        else:
            await grant_artifact(db, user_id, "blade", "", 2)
            await grant_artifact(db, user_id, "shield", "weak", 2)
            await db.execute(
                """
                UPDATE users
                SET cd_resets_count = cd_resets_count + 1,
                    cd_reset_expires = ?
                WHERE user_id = ?
                """,
                (now() + 3 * 3600, user_id),
            )
            rewards.extend(
                ["+2 🗡 клинка", "+2 🔰 слабых щита", "+1 ⚡ сброс КД"]
            )

    return " и ".join(rewards)


@router.callback_query(F.data.startswith("chest:claim:"))
async def chest_claim_callback(callback: CallbackQuery) -> None:
    chest_id = (callback.data or "").removeprefix("chest:claim:")

    if not chest_id:
        await answer_callback(callback, "Некорректный сундук", alert=True)
        return

    user_id = callback.from_user.id

    async with transaction() as db:
        async with db.execute(
            """
            SELECT chest_type, payload, claimed_by, expires_at
            FROM chests
            WHERE chest_id = ?
            """,
            (chest_id,),
        ) as cursor:
            chest = await cursor.fetchone()

        if not chest:
            await answer_callback(callback, "Сундук уже исчез 💨", alert=True)
            return

        if chest["claimed_by"] is not None:
            await answer_callback(callback, "Сундук уже забрали 😿", alert=True)
            return

        if safe_float(chest["expires_at"]) <= now():
            await answer_callback(callback, "Срок сундука истёк ⏳", alert=True)
            return

        claimed = await db.execute(
            """
            UPDATE chests
            SET claimed_by = ?, claimed_at = ?
            WHERE chest_id = ?
              AND claimed_by IS NULL
              AND expires_at > ?
            """,
            (user_id, now(), chest_id, now()),
        )

        if claimed.rowcount != 1:
            await answer_callback(callback, "Сундук уже забрали 💔", alert=True)
            return

        try:
            payload = json.loads(chest["payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}

        reward = await reward_chest(
            db,
            user_id,
            str(chest["chest_type"]),
            payload,
        )

        await db.execute(
            """
            UPDATE users
            SET experience = experience + 2
            WHERE user_id = ?
            """,
            (user_id,),
        )

    try:
        await callback.message.edit_text(
            "🎉✨ <b>СУНДУК ОТКРЫТ!</b> ✨🎉\n\n"
            f"👤 Победитель: {display_name(callback.from_user)}\n"
            f"🎁 Награда: <b>{esc(reward)}</b>\n"
            "💫 Опыт: <b>+2</b>"
        )
    except Exception:
        logger.exception("Не удалось обновить сообщение сундука")

    await answer_callback(callback, "Награда зачислена! 💖")


# Золотой дождь

def parse_rain_args(message: Message) -> tuple[int, float]:
    parts = (message.text or "").split()
    numbers = []

    for part in parts[1:]:
        try:
            numbers.append(float(part.replace(",", ".")))
        except ValueError:
            continue

    count = int(numbers[0]) if numbers else 10
    interval = numbers[1] if len(numbers) > 1 else 3.0

    return max(1, min(50, count)), max(1.0, interval)


@router.message(
    lambda message: (
        message.text is not None
        and (
            "золотой дождь" in message.text.lower()
            or "золотой_дождь" in message.text.lower()
            or "golden_rain" in message.text.lower()
        )
    )
)
async def golden_rain_command(message: Message) -> None:
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    if message.chat.type not in {
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    }:
        await message.answer("🌧 Золотой дождь запускается только в группе!")
        return

    count, interval = parse_rain_args(message)

    try:
        member_count = await message.bot.get_chat_member_count(
            message.chat.id
        )
    except Exception:
        logger.exception("Не удалось проверить размер чата")
        await message.answer(
            "❌ Не удалось подтвердить размер группы. Дождь не запущен."
        )
        return

    if member_count < 1:
        await message.answer("❌ Telegram вернул некорректный размер группы.")
        return

    legendary_count = 2 if count == 50 else (1 if 10 <= count <= 49 else 0)
    legendary_positions = set(
        random.sample(range(count), legendary_count)
    ) if legendary_count else set()

    await message.answer(
        "🌧✨ <b>ЗОЛОТОЙ ДОЖДЬ НАЧИНАЕТСЯ!</b> ✨🌧\n"
        f"📦 Сундуков: <b>{count}</b>\n"
        f"⏱ Интервал: <b>{interval:g} сек.</b>"
    )

    task = asyncio.create_task(
        _golden_rain_worker(
    message.bot,
    message.chat.id,
    count,
    interval,
    legendary_positions,
        )
    )
    _rain_tasks.add(task)
    task.add_done_callback(_rain_tasks.discard)


async def _golden_rain_worker(
    bot,
    chat_id: int,
    count: int,
    interval: float,
    legendary_positions: set[int],
) -> None:
    for index in range(count):
        await asyncio.sleep(interval)

        if index in legendary_positions:
            chest_type = "legendary"
            payload = {"coins": 250, "golden_rain": True}
        elif random.random() < 0.25:
            chest_type = "rare"
            payload = {
                "coins": random.randint(50, 100),
                "golden_rain": True,
            }
        else:
            chest_type = "normal"
            payload = {
                "coins": random.randint(3, 15),
                "golden_rain": True,
            }

        try:
            chest_id = await create_chest(
                chat_id,
                chest_type,
                payload,
                lifetime=1800,
            )
            await router.bot.send_message(
                chat_id,
                chest_title(chest_type)
                + f"\n📦 Сундук {index + 1}/{count}!\n"
                "🎁 Кто первый — тот забрал!",
                reply_markup=chest_markup(chest_id),
            )
        except Exception:
            logger.exception("Ошибка отправки сундука золотого дождя")


# Обработчики активности и перекати-поля будут подключены
# в фоновой задаче приложения после регистрации роутеров.
async def spawn_tumbleweed(chat_id: int) -> bool:
    try:
        member_count = await router.bot.get_chat_member_count(chat_id)
    except Exception:
        logger.warning(
            "Не подтверждён размер группы %s; перекати-поле не создаётся",
            chat_id,
        )
        return False

    if member_count < 30:
        return False

    async with _chat_lock(chat_id):
        async with connect() as db:
            async with db.execute(
                """
                SELECT 1
                FROM chests
                WHERE chat_id = ?
                  AND claimed_by IS NULL
                  AND expires_at > ?
                LIMIT 1
                """,
                (chat_id, now()),
            ) as cursor:
                active = await cursor.fetchone()

        if active:
            return False

        reward = random.choices(
            [20, 35, 50, 75, 120],
            weights=[45, 25, 18, 8, 4],
            k=1,
        )[0]

        chest_id = await create_chest(
            chat_id,
            "normal",
            {"coins": reward, "tumbleweed": True},
        )

        try:
            await router.bot.send_message(
                chat_id,
                "🌵✨ <b>ПЕРЕКАТИ-ПОЛЕ!</b> ✨🌵\n"
                "В чате было тихо, и появился сундук!",
                reply_markup=chest_markup(chest_id),
            )
            return True
        except Exception:
            logger.exception("Ошибка отправки перекати-поля")
            return False
