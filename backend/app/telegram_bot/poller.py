"""Poll-after-finalize loop: watches a bot upload until it completes and
reports pipeline stage changes, replacing the n8n `Wait`/`Check Upload Status`/
`Compute Stage`/`Send Stage Update` node chain with plain asyncio.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from app.config import settings
from app.db.session import SessionLocal
from app.services import bot_gateway_service
from app.telegram_bot.messages import format_result_message, stage_text_for

logger = logging.getLogger(__name__)

# One poll task per chat: a repeated "Готово" cancels and replaces any still-running poll.
_active_polls: dict[str, asyncio.Task] = {}


def start_poll(bot: Bot, chat_id: str, upload_id: str) -> None:
    existing = _active_polls.get(chat_id)
    if existing is not None and not existing.done():
        existing.cancel()
    _active_polls[chat_id] = asyncio.create_task(_poll_loop(bot, chat_id, upload_id))


async def _poll_loop(bot: Bot, chat_id: str, upload_id: str) -> None:
    last_stage_text: str | None = None
    processed_logs = 0
    try:
        for _ in range(settings.telegram_bot_max_poll_attempts):
            await asyncio.sleep(settings.telegram_bot_poll_interval_seconds)
            status = await asyncio.to_thread(_fetch_status, upload_id)
            # `pipeline_logs` is append-only across polls of the same upload; only scan the
            # entries that arrived since the last tick, or every stage re-triggers a resend
            # every 5s as the loop re-walks the whole (growing) log from the start.
            new_logs = status.pipeline_logs[processed_logs:]
            processed_logs = len(status.pipeline_logs)
            for log in new_logs:
                stage_text = stage_text_for(log.stage)
                if stage_text and stage_text != last_stage_text:
                    last_stage_text = stage_text
                    await bot.send_message(chat_id, stage_text)
            if status.completed:
                await bot.send_message(chat_id, format_result_message(status))
                return
        await bot.send_message(
            chat_id,
            "Обработка документа занимает необычно долго. Проверьте статус позже кнопкой «Статус».",
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a poll-loop crash must not take down the bot process
        logger.exception("Bot upload poll loop failed for chat_id=%s upload_id=%s", chat_id, upload_id)
        await bot.send_message(chat_id, "Не удалось получить статус обработки. Попробуйте «Статус» позже.")
    finally:
        _active_polls.pop(chat_id, None)


def _fetch_status(upload_id: str):
    db = SessionLocal()
    try:
        return bot_gateway_service.get_upload_status(db, upload_id)
    finally:
        db.close()
