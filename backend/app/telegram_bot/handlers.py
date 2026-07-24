"""Telegram update handlers: the transport/session layer over `bot_gateway_service`.

Maps directly onto the retired n8n workflow's `Normalize Update` / `Route Intent`
node chain — see docs/wiki/n8n-to-native-bot-migration-plan.md for the mapping
table (n8n node -> native replacement).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.db.session import SessionLocal
from app.services import bot_gateway_service
from app.telegram_bot import poller
from app.telegram_bot.keyboard import DRAFT_ACTIONS_KEYBOARD
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
    # Clears any leftover ReplyKeyboardMarkup from before the inline-buttons redesign
    # (img_18.png, 2026-07-25) for clients that still have the old bottom keyboard cached.
    await message.answer(START_TEXT, reply_markup=ReplyKeyboardRemove())


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
    await message.answer(result.message, reply_markup=DRAFT_ACTIONS_KEYBOARD)


def _append_draft_page_sync(**kwargs):
    db = SessionLocal()
    try:
        return bot_gateway_service.append_draft_page(db, **kwargs)
    finally:
        db.close()


async def _finalize_and_start_poll(bot, chat_id: str) -> str | None:
    """Finalize the draft and start the progress poll. Returns an error message on
    failure (nothing to finalize), or None once the poll has started.
    """
    try:
        accepted = await asyncio.to_thread(_finalize_draft_sync, chat_id)
    except ValueError as exc:
        return str(exc)
    # No reply_markup here: Telegram's editMessageText rejects edits on any message
    # carrying a custom (non-inline) reply keyboard, and the poller edits this message
    # in place as stages progress.
    sent = await bot.send_message(chat_id, STARTED_REPLY)
    poller.start_poll(bot, chat_id, accepted.upload_id, sent.message_id)
    return None


def _finalize_draft_sync(chat_id: str):
    db = SessionLocal()
    try:
        return bot_gateway_service.finalize_draft(db, chat_id)
    finally:
        db.close()


@router.message(F.text.func(_matches(*_DONE_TEXTS)))
async def handle_done(message: Message) -> None:
    error = await _finalize_and_start_poll(message.bot, _chat_id(message))
    if error:
        await message.answer(error)


@router.callback_query(F.data == "bot:done")
async def handle_done_callback(callback: CallbackQuery) -> None:
    chat_id = str(callback.message.chat.id)
    error = await _finalize_and_start_poll(callback.bot, chat_id)
    if error:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer()
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message(F.text.func(_matches(*_STATUS_TEXTS)))
async def handle_status(message: Message) -> None:
    chat_id = _chat_id(message)
    draft, latest = await asyncio.to_thread(_status_sync, chat_id)
    if draft is not None:
        await message.answer(
            f"Черновик: {draft.pages_count} стр. Отправьте еще страницы или нажмите «✅ Готово».",
            reply_markup=DRAFT_ACTIONS_KEYBOARD,
        )
        return
    if latest is not None:
        await message.answer(f"{LAST_PROCESSED_PREFIX} {latest.message}", reply_markup=ReplyKeyboardRemove())
        return
    await message.answer(NO_HISTORY_STATUS, reply_markup=ReplyKeyboardRemove())


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


def _reset_sync(chat_id: str):
    db = SessionLocal()
    try:
        return bot_gateway_service.reset_draft(db, chat_id)
    finally:
        db.close()


@router.message(F.text.func(_matches(*_RESET_TEXTS)))
async def handle_reset(message: Message) -> None:
    chat_id = _chat_id(message)
    result = await asyncio.to_thread(_reset_sync, chat_id)
    await message.answer(result.message, reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == "bot:reset")
async def handle_reset_callback(callback: CallbackQuery) -> None:
    chat_id = str(callback.message.chat.id)
    result = await asyncio.to_thread(_reset_sync, chat_id)
    await callback.answer(result.message)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message()
async def handle_unknown(message: Message) -> None:
    await message.answer(UNKNOWN_TEXT_HELP, reply_markup=ReplyKeyboardRemove())
