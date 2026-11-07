# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message

from config import BOT_TOKEN
from database import ensure_user, init_db, now, transaction
from utils import remember_activity

from handlers.admin import router as admin_router
from handlers.artifacts import router as artifacts_router
from handlers.cards import router as cards_router
from handlers.casino import router as casino_router
from handlers.chests import router as chests_router, spawn_tumbleweed
from handlers.clans import router as clans_router
from handlers.clan_shop import router as clan_shop_router
from handlers.common import router as common_router
from handlers.economy import router as economy_router
from handlers.quests import router as quests_router
from handlers.trading import router as trading_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("femboy_bot")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)

dp = Dispatcher()


@dp.message.outer_middleware()
async def registration_middleware(handler, event, data):
    if isinstance(event, Message) and event.from_user:
        try:
            await ensure_user(
                event.from_user.id,
                event.from_user.username or event.from_user.full_name,
            )
            await remember_activity(event)
        except Exception:
            logger.exception("Activity registration error")

    return await handler(event, data)


dp.include_router(common_router)
dp.include_router(economy_router)
dp.include_router(cards_router)
dp.include_router(quests_router)
dp.include_router(clans_router)
dp.include_router(clan_shop_router)
dp.include_router(artifacts_router)
dp.include_router(trading_router)
dp.include_router(casino_router)
dp.include_router(chests_router)
dp.include_router(admin_router)


@dp.errors()
async def global_error_handler(event):
    logger.exception("Event handling error: %r", event)
    return True


async def cleanup_worker() -> None:
    while True:
        try:
            current_time = now()
            async with transaction() as db:
                await db.execute("DELETE FROM chests WHERE expires_at <= ?", (current_time,))
                await db.execute(
                    "DELETE FROM trades WHERE status IN ('completed', 'cancelled') OR updated_at <= ?",
                    (current_time - 86400,),
                )
                await db.execute("DELETE FROM admin_codes WHERE used = 1 OR expires_at <= ?", (current_time,))
                await db.execute("DELETE FROM pending_actions WHERE expires_at <= ?", (current_time,))
        except Exception:
            logger.exception("Cleanup worker error")

        await asyncio.sleep(300)


async def inactivity_worker() -> None:
    while True:
        try:
            async with transaction() as db:
                async with db.execute(
                    """
                    SELECT chat_id, inactivity_interval, last_activity
                    FROM chats
                    WHERE chat_type IN ('group', 'supergroup')
                    """
                ) as cursor:
                    chats = await cursor.fetchall()

            for chat in chats:
                chat_id = int(chat["chat_id"])
                interval = max(60, min(86400, int(chat["inactivity_interval"] or 3600)))
                last_activity = float(chat["last_activity"] or 0)

                if last_activity <= 0 or (now() - last_activity) < interval:
                    continue

                spawned = await spawn_tumbleweed(bot, chat_id)
                if spawned:
                    async with transaction() as db:
                        await db.execute(
                            "UPDATE chats SET last_activity = ?, last_chest_at = ? WHERE chat_id = ?",
                            (now(), now(), chat_id),
                        )
        except Exception:
            logger.exception("Inactivity worker error")

        await asyncio.sleep(60)


async def main() -> None:
    await init_db()

    cleanup_task = asyncio.create_task(cleanup_worker(), name="cleanup_worker")
    inactivity_task = asyncio.create_task(inactivity_worker(), name="inactivity_worker")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot started successfully!")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        cleanup_task.cancel()
        inactivity_task.cancel()
        await asyncio.gather(cleanup_task, inactivity_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
