"""Map low-level exceptions from external services (DB, OpenAI, Google) to
short, non-technical Russian messages safe to show a Telegram end user.

Callers are responsible for logging the real exception separately (this
module never does I/O) — masking the message to the user is not a substitute
for server-side visibility into what actually failed.
"""

from __future__ import annotations

GENERIC_MESSAGE = (
    "Не получилось обработать документ, мы уже разбираемся. "
    "Попробуйте прислать фото ещё раз через пару минут."
)

_DATABASE_MESSAGE = (
    "Сервис временно недоступен — технический сбой на нашей стороне. "
    "Мы уже знаем и разбираемся, попробуйте прислать документ ещё раз через несколько минут."
)
_OPENAI_MESSAGE = (
    "Не получилось распознать документ через ИИ. "
    "Мы уже разбираемся, попробуйте прислать фото ещё раз через пару минут."
)
_GOOGLE_MESSAGE = (
    "Не получилось сохранить результат в Google Таблицы. "
    "Данные не потеряны, мы уже разбираемся — можно продолжать загрузку следующих накладных."
)

_MODULE_PREFIX_MESSAGES: tuple[tuple[str, str], ...] = (
    ("psycopg2", _DATABASE_MESSAGE),
    ("psycopg", _DATABASE_MESSAGE),
    ("sqlalchemy", _DATABASE_MESSAGE),
    ("sqlite3", _DATABASE_MESSAGE),
    ("openai", _OPENAI_MESSAGE),
    ("google", _GOOGLE_MESSAGE),
    ("googleapiclient", _GOOGLE_MESSAGE),
)


def mask_error_for_user(exc: BaseException) -> str:
    """Return a short, Russian, non-technical message safe to send a user.

    Never returns the raw exception text, class name, traceback, or any
    other implementation detail (file paths, hostnames, API error codes).
    """
    module = type(exc).__module__ or ""
    for prefix, message in _MODULE_PREFIX_MESSAGES:
        if module == prefix or module.startswith(f"{prefix}."):
            return message
    return GENERIC_MESSAGE
