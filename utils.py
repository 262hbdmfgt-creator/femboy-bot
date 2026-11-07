from __future__ import annotations

import html
import logging
import re
import secrets
import string
import time
from datetime import datetime
from typing import Optional

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import SUPER_ADMIN_ID
from database import (
    connect,
    ensure_user,
    find_user_by_username,
    now,
)

logger = logging.getLogger("femboy_bot.utils")


# ============================================================
# ТЕКСТ И ВРЕМЯ
# ============================================================

def esc(value: object) -> str:
    """Экранирует пользовательский текст для Telegram HTML."""
    return html.escape(str(value or ""), quote=False)


def format_date(timestamp: float) -> str:
    if timestamp <= 0:
        return ""

    return datetime.fromtimestamp(timestamp).strftime(
        "%d.%m.%Y %H:%M"
    )


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)

    if hours:
        return f"{hours} ч. {minutes} мин."
    if minutes:
        return f"{minutes} мин. {seconds} сек."
    return f"{seconds} сек."


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# КОМАНДЫ
# ============================================================

def normalize_command(text: Optional[str]) -> str:
    """
    Возвращает первый токен сообщения в нижнем регистре.
    Удаляет суффикс @botname у команд Telegram.
    """
    if not text or not text.strip():
        return ""

    token = text.strip().split(maxsplit=1)[0].lower()

    if "@" in token:
        token = token.split("@", 1)[0]

    return token


def command_is(
    message: Message,
    *aliases: str,
) -> bool:
    """
    Сравнивает команду точно, не используя startswith.
    Поддерживает команды с аргументами и фразы-команды.

    Например:
      /daily
      daily
      /бот +вип 12
      мой клан
    """
    if not message.text:
        return False

    text = message.text.strip().lower()
    first_token = normalize_command(text)

    for alias in aliases:
        alias = alias.strip().lower()

        if " " in alias:
            if text in {alias, f"/{alias}"}:
                return True
            continue

        normalized_alias = alias.lstrip("/")

        if first_token in {
            normalized_alias,
            f"/{normalized_alias}",
        }:
            return True

    return False


def parse_callback_payload(
    data: Optional[str],
    prefix: str,
) -> Optional[str]:
    """Безопасно извлекает payload, не разбирая его через split('_')."""
    if data is None or not data.startswith(prefix):
        return None

    return data[len(prefix):]


def make_token(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


def parse_time_interval(value: str) -> Optional[int]:
    """
    Поддерживает секунды и суффиксы s/m/h:
      3600, 30m, 2h, 90s.
    Результат ограничивается диапазоном 60 секунд — 24 часа.
    """
    value = value.strip().lower()

    try:
        if value.endswith("h"):
            seconds = int(value[:-1]) * 3600
        elif value.endswith("m"):
            seconds = int(value[:-1]) * 60
        elif value.endswith("s"):
            seconds = int(value[:-1])
        else:
            seconds = int(value)
    except ValueError:
        return None

    return max(60, min(86400, seconds))


# ============================================================
# ИМЕНА И ПОИСК ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

def display_name(user: types.User) -> str:
    if user.username:
        return f"@{esc(user.username)}"

    return esc(
        user.full_name
        or user.first_name
        or str(user.id)
    )


def plain_username(user: types.User) -> str:
    """Имя для рейтинга без @, чтобы не создавать упоминание."""
    if user.username:
        return esc(user.username.lstrip("@"))

    return esc(
        user.full_name
        or user.first_name
        or str(user.id)
    )


async def resolve_user_id(
    message: Message,
    *,
    username: Optional[str] = None,
) -> Optional[int]:
    """
    Ищет адресата сначала по reply, затем по @username.
    Telegram не позволяет боту разрешить произвольный username,
    если пользователь не известен боту; в таком случае вернёт None.
    """
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
    ):
        target = message.reply_to_message.from_user

        try:
            await ensure_user(
                target.id,
                target.username or target.full_name,
            )
        except Exception:
            logger.exception(
                "Не удалось зарегистрировать адресата reply"
            )

        return target.id

    candidate = username

    if candidate is None and message.text:
        for token in reversed(message.text.split()):
            if token.startswith("@"):
                candidate = token
                break

    if not candidate:
        return None

    return await find_user_by_username(candidate)


async def get_user_label(user_id: int) -> str:
    async with connect() as db:
        async with db.execute(
            """
            SELECT username
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row["username"]:
        return f"ID:{user_id}"

    return esc(str(row["username"]).lstrip("@"))


async def user_is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True

    async with connect() as db:
        async with db.execute(
            """
            SELECT 1
            FROM admins
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            return await cursor.fetchone() is not None


# ============================================================
# CALLBACK И СЕТЕВЫЕ ОТВЕТЫ
# ============================================================

async def answer_callback(
    callback: CallbackQuery,
    text: str = "",
    *,
    alert: bool = False,
) -> None:
    try:
        await callback.answer(
            text,
            show_alert=alert,
        )
    except TelegramBadRequest as error:
        description = str(error).lower()

        if any(
            phrase in description
            for phrase in (
                "query is too old",
                "query id is invalid",
                "response timeout expired",
            )
        ):
            return

        logger.warning(
            "Telegram отказал в callback.answer: %s",
            error,
        )
    except TelegramNetworkError:
        logger.warning(
            "Сетевая ошибка при callback.answer"
        )
    except Exception:
        logger.exception(
            "Непредвиденная ошибка callback.answer"
        )


async def edit_message_safely(
    message: Optional[Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    if message is None:
        return

    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            logger.warning(
                "Не удалось изменить сообщение: %s",
                error,
            )
    except TelegramNetworkError:
        logger.warning(
            "Сетевая ошибка при редактировании сообщения"
        )
    except Exception:
        logger.exception(
            "Ошибка редактирования сообщения"
        )


# ============================================================
# АКТИВНОСТЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================

async def remember_activity(
    message: Message,
) -> None:
    """
    Запоминает последний личный чат или последнюю группу.
    Используется для поздравлений с повышениями.
    """
    if not message.from_user:
        return

    user_id = message.from_user.id
    timestamp = now()

    try:
        if message.chat.type == "private":
            async with connect() as db:
                await db.execute(
                    """
                    UPDATE users
                    SET last_private_activity = ?
                    WHERE user_id = ?
                    """,
                    (timestamp, user_id),
                )
                await db.commit()

        elif message.chat.type in {"group", "supergroup"}:
            async with connect() as db:
                await db.execute(
                    """
                    UPDATE users
                    SET last_group_chat_id = ?
                    WHERE user_id = ?
                    """,
                    (message.chat.id, user_id),
                )
                await db.commit()

    except Exception:
        logger.exception(
            "Не удалось сохранить активность пользователя %s",
            user_id,
        )


async def destination_for_user(
    user_id: int,
) -> int:
    """
    Возвращает чат для уведомлений:
    ЛС, если пользователь недавно писал боту;
    иначе последнюю известную группу;
    иначе личный чат по user_id.
    """
    async with connect() as db:
        async with db.execute(
            """
            SELECT last_private_activity,
                   last_group_chat_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return user_id

    last_private = safe_float(
        row["last_private_activity"]
    )
    last_group = row["last_group_chat_id"]

    # Считаем личную активность актуальной в течение 30 дней.
    if last_private > 0 and now() - last_private <= 30 * 86400:
        return user_id

    if last_group is not None:
        return safe_int(last_group, user_id)

    return user_id


async def send_user_notification(
    bot: Bot,
    user_id: int,
    text: str,
) -> bool:
    """
    Отправляет уведомление в последнее подходящее место.
    Если групповая отправка не удалась, пробует ЛС.
    """
    destination = await destination_for_user(user_id)

    try:
        await bot.send_message(
            destination,
            text,
        )
        return True
    except Exception:
        logger.warning(
            "Не удалось уведомить пользователя %s в чат %s",
            user_id,
            destination,
            exc_info=True,
        )

    if destination != user_id:
        try:
            await bot.send_message(
                user_id,
                text,
            )
            return True
        except Exception:
            logger.warning(
                "Не удалось отправить уведомление пользователю %s в ЛС",
                user_id,
                exc_info=True,
            )

    return False


# ============================================================
# ПРОВЕРКА CALLBACK-ДАННЫХ
# ============================================================

def callback_data_size(data: str) -> int:
    """Telegram ограничивает callback_data 64 байтами."""
    return len(data.encode("utf-8"))


def validate_callback_data(data: str) -> str:
    if callback_data_size(data) > 64:
        raise ValueError(
            "callback_data превышает лимит Telegram в 64 байта"
        )

    return data
