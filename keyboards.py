from __future__ import annotations

from typing import Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def inline(
    *rows: list[InlineKeyboardButton],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=list(rows)
    )


def bonus_keyboard(
    bot_username: str,
    extra_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🎁 Забрать бонус ✨",
                url=(
                    f"https://t.me/{bot_username}"
                    "?start=bonus"
                ),
            )
        ]
    ]

    if extra_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💖 Присоединиться / Подробнее",
                    url=extra_url,
                )
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def subscription_keyboard(
    channel_url: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🩷 Подписаться на канал",
                    url=channel_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Проверить подписку",
                    callback_data="bonus:check",
                )
            ],
        ]
    )


def shop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Сброс КД — 150 🪙",
                    callback_data="shop:skip",
                ),
                InlineKeyboardButton(
                    text="🍀 Удача — 250 🪙",
                    callback_data="shop:luck",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎴 Новая карта — 400 🪙",
                    callback_data="shop:new_card",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛡 Артефакты",
                    callback_data="shop:artifacts",
                ),
                InlineKeyboardButton(
                    text="👑 VIP",
                    callback_data="shop:vip",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Фемкоины за Stars",
                    callback_data="shop:coins",
                )
            ],
        ]
    )


def artifact_shop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
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


def vip_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪙 Купить за фемкоины",
                    callback_data="vip:coins",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Купить за Stars",
                    callback_data="vip:stars",
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


def vip_coins_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 день — 1500 🪙",
                    callback_data="vip_coins:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="7 дней — 4500 🪙",
                    callback_data="vip_coins:7",
                )
            ],
            [
                InlineKeyboardButton(
                    text="30 дней — 10000 🪙",
                    callback_data="vip_coins:30",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop:vip",
                )
            ],
        ]
    )


def vip_stars_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 день — 250 ⭐",
                    callback_data="vip_stars:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="7 дней — 800 ⭐",
                    callback_data="vip_stars:7",
                )
            ],
            [
                InlineKeyboardButton(
                    text="30 дней — 2000 ⭐",
                    callback_data="vip_stars:30",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="shop:vip",
                )
            ],
        ]
    )


def coins_stars_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="100 фемкоинов — 15 ⭐",
                    callback_data="coins_stars:100",
                )
            ],
            [
                InlineKeyboardButton(
                    text="500 фемкоинов — 70 ⭐",
                    callback_data="coins_stars:500",
                )
            ],
            [
                InlineKeyboardButton(
                    text="1000 фемкоинов — 135 ⭐",
                    callback_data="coins_stars:1000",
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


def profile_keyboard(
    user_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎴 Мои карты",
                    callback_data=(
                        f"profile:cards:{user_id}:0"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗡 Мои клинки",
                    callback_data=(
                        f"profile:artifact:{user_id}:blade"
                    ),
                ),
                InlineKeyboardButton(
                    text="🛡 Моя броня",
                    callback_data=(
                        f"profile:artifact:{user_id}:armor"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔰 Мои щиты",
                    callback_data=(
                        f"profile:artifact:{user_id}:shield"
                    ),
                )
            ],
        ]
    )


def card_navigation_keyboard(
    user_id: int,
    index: int,
    total: int,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []

    if index > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=(
                    f"profile:cards:{user_id}:{index - 1}"
                ),
            )
        )

    if index < total - 1:
        buttons.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=(
                    f"profile:cards:{user_id}:{index + 1}"
                ),
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[buttons] if buttons else []
    )


def shield_craft_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔰 3 слабых → усиленный",
                    callback_data="craft:shield:weak",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 3 усиленных → фембойский",
                    callback_data="craft:shield:reinforced",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👑 3 фембойских → броня",
                    callback_data="craft:shield:femboy",
                )
            ],
        ]
    )


def quest_keyboard(
    quest_ids: list[tuple[int, bool]],
    all_ready: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for slot, ready in quest_ids:
        if ready:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🎁 Забрать квест {slot}",
                        callback_data=f"quest:claim:{slot}",
                    )
                ]
            )

    if all_ready:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✨ Забрать всё",
                    callback_data="quest:claim_all",
                )
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def clan_create_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏳️ Ввести название",
                    callback_data="clan:create_confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data="clan:create_cancel",
                )
            ],
        ]
    )


def clan_join_keyboard(
    clan_number: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💖 Вступить в клан",
                    callback_data=(
                        f"clan:join:{clan_number}"
                    ),
                )
            ]
        ]
    )


def clan_leave_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💔 Покинуть клан",
                    callback_data="clan:leave",
                )
            ]
        ]
    )


def clan_shop_keyboard(
    owner: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🍀 Эликсир для всех",
                callback_data="clanshop:luck",
            )
        ],
        [
            InlineKeyboardButton(
                text="🗡 Клинок каждому",
                callback_data="clanshop:blade",
            )
        ],
        [
            InlineKeyboardButton(
                text="💫 Личный опыт",
                callback_data="clanshop:xp",
            )
        ],
        [
            InlineKeyboardButton(
                text="🏰 Улучшить клан",
                callback_data="clanshop:level",
            )
        ],
        [
            InlineKeyboardButton(
                text="⭐ Купить кланкоины",
                callback_data="clanshop:stars",
            )
        ],
    ]

    if not owner:
        rows.append(
            [
                InlineKeyboardButton(
                    text="👀 Только просмотр",
                    callback_data="clanshop:readonly",
                )
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def top_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📜 Топ-100 в ЛС",
                    callback_data="top:100",
                )
            ]
        ]
    )


def admin_remove_keyboard(
    admin_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Снять администратора",
                    callback_data=(
                        f"admin:remove:{admin_id}"
                    ),
                )
            ]
        ]
    )
