"""Bot/Dispatcher lifecycle, wired into `app.main`'s FastAPI `lifespan` the same
way the Diadoc/SBIS schedulers are (`start_diadoc_scheduler`/`stop_diadoc_scheduler`),
except this uses an asyncio task instead of a thread since aiogram is async-native.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.config import settings
from app.telegram_bot.handlers import router as bot_router

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_polling_task: asyncio.Task | None = None

_BOT_COMMANDS = [
    BotCommand(command="done", description="Завершить загрузку и обработать документ"),
    BotCommand(command="status", description="Статус текущего черновика или загрузки"),
    BotCommand(command="reset", description="Сбросить текущий черновик"),
]


async def start_bot() -> None:
    global _bot, _dispatcher, _polling_task
    if not settings.telegram_bot_enabled:
        return
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_ENABLED is true but TELEGRAM_BOT_TOKEN is empty; bot not started.")
        return

    _bot = Bot(token=settings.telegram_bot_token)
    _dispatcher = Dispatcher()
    _dispatcher.include_router(bot_router)
    # Telegram allows only one active delivery mode per bot token; releases any
    # webhook still held by a not-yet-decommissioned n8n workflow before polling.
    await _bot.delete_webhook(drop_pending_updates=False)
    # Populates the client's native "/" command menu, replacing the old permanent
    # ReplyKeyboardMarkup as the discoverability mechanism for done/status/reset.
    await _bot.set_my_commands(_BOT_COMMANDS)
    _polling_task = asyncio.create_task(_dispatcher.start_polling(_bot))
    logger.info("Native Telegram bot polling started.")


async def stop_bot() -> None:
    global _bot, _dispatcher, _polling_task
    if _dispatcher is not None:
        await _dispatcher.stop_polling()
    if _polling_task is not None:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
        _polling_task = None
    if _bot is not None:
        await _bot.session.close()
        _bot = None
    _dispatcher = None
