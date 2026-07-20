from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Готово"), KeyboardButton(text="Статус")],
        [KeyboardButton(text="Сбросить")],
    ],
    resize_keyboard=True,
)
