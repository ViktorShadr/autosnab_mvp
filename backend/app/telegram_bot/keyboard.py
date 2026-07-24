"""Compact inline keyboards attached to specific messages, replacing the old
permanent ReplyKeyboardMarkup that took over a large part of the chat window
(img_18.png, 2026-07-25).
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DRAFT_ACTIONS_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Готово", callback_data="bot:done"),
            InlineKeyboardButton(text="🗑 Сбросить", callback_data="bot:reset"),
        ]
    ]
)


def sheet_link_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Открыть таблицу", url=url)]])
