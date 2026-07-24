"""Telegram update handlers: the transport/session layer over `bot_gateway_service`.

Maps directly onto the retired n8n workflow's `Normalize Update` / `Route Intent`
node chain — see docs/wiki/n8n-to-native-bot-migration-plan.md for the mapping
table (n8n node -> native replacement).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.db.session import SessionLocal
from app.services import bot_gateway_service
from app.telegram_bot import poller
from app.telegram_bot.keyboard import MAIN_KEYBOARD
from app.telegram_bot.messages import (
    LAST_PROCESSED_PREFIX,
    NO_HISTORY_STATUS,
    START_TEXT,
    STARTED_REPLY,
    UNKNOWN_TEXT_HELP,
)

logger = logging.getLogger(__name__)

router = Router(name="telegram_bot")

_DONE_TEXTS = {"готово", "/done", "done"}
_STATUS_TEXTS = {"статус", "/status", "status"}
_RESET_TEXTS = {"сбросить", "/reset", "reset"}
_MENU_TEXTS = {"меню", "/menu", "menu"}


def _matches(*texts: str):
    def predicate(text: str | None) -> bool:
        return bool(text) and text.strip().casefold() in texts
    return predicate


def _chat_id(message: Message) -> str:
    return str(message.chat.id)


@router.message(CommandStart())
@router.message(F.text.func(_matches(*_MENU_TEXTS)))
async def handle_menu(message: Message) -> None:
    await message.answer(START_TEXT, reply_markup=MAIN_KEYBOARD)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    photo = message.photo[-1]
    buffer = await message.bot.download(photo.file_id)
    await _append_page(
        message,
        filename=f"{photo.file_unique_id}.jpg",
        content_type="image/jpeg",
        file_bytes=buffer.read(),
    )


@router.message(F.document)
async def handle_document(message: Message) -> None:
    document = message.document
    buffer = await message.bot.download(document.file_id)
    await _append_page(
        message,
        filename=document.file_name or document.file_unique_id,
        content_type=document.mime_type,
        file_bytes=buffer.read(),
    )


async def _append_page(message: Message, *, filename: str, content_type: str | None, file_bytes: bytes) -> None:
    chat_id = _chat_id(message)
    user = message.from_user
    try:
        result = await asyncio.to_thread(
            _append_draft_page_sync,
            chat_id=chat_id,
            source_user_id=str(user.id) if user else chat_id,
            source_username=user.username if user else None,
            filename=filename,
            content_type=content_type,
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(result.message, reply_markup=MAIN_KEYBOARD)


def _append_draft_page_sync(**kwargs):
    db = SessionLocal()
    try:
        return bot_gateway_service.append_draft_page(db, **kwargs)
    finally:
        db.close()


@router.message(F.text.func(_matches(*_DONE_TEXTS)))
async def handle_done(message: Message) -> None:
    chat_id = _chat_id(message)
    try:
        accepted = await asyncio.to_thread(_finalize_draft_sync, chat_id)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    sent = await message.answer(STARTED_REPLY, reply_markup=MAIN_KEYBOARD)
    poller.start_poll(message.bot, chat_id, accepted.upload_id, sent.message_id)


def _finalize_draft_sync(chat_id: str):
    db = SessionLocal()
    try:
        return bot_gateway_service.finalize_draft(db, chat_id)
    finally:
        db.close()


@router.message(F.text.func(_matches(*_STATUS_TEXTS)))
async def handle_status(message: Message) -> None:
    chat_id = _chat_id(message)
    draft, latest = await asyncio.to_thread(_status_sync, chat_id)
    if draft is not None:
        await message.answer(
            f"Черновик: {draft.pages_count} стр. Отправьте еще страницы или нажмите «Готово».",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    if latest is not None:
        await message.answer(f"{LAST_PROCESSED_PREFIX} {latest.message}", reply_markup=MAIN_KEYBOARD)
        return
    await message.answer(NO_HISTORY_STATUS, reply_markup=MAIN_KEYBOARD)


def _status_sync(chat_id: str):
    db = SessionLocal()
    try:
        draft_status = bot_gateway_service.get_draft_status(db, chat_id)
        latest = None
        if draft_status.draft is None:
            latest = bot_gateway_service.get_latest_upload_status(db, chat_id)
        return draft_status.draft, latest
    finally:
        db.close()


@router.message(F.text.func(_matches(*_RESET_TEXTS)))
async def handle_reset(message: Message) -> None:
    chat_id = _chat_id(message)
    result = await asyncio.to_thread(_reset_sync, chat_id)
    await message.answer(result.message, reply_markup=MAIN_KEYBOARD)


def _reset_sync(chat_id: str):
    db = SessionLocal()
    try:
        return bot_gateway_service.reset_draft(db, chat_id)
    finally:
        db.close()


@router.message()
async def handle_unknown(message: Message) -> None:
    await message.answer(UNKNOWN_TEXT_HELP, reply_markup=MAIN_KEYBOARD)
