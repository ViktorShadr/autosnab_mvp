from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_SESSION_IDLE_TTL_SECONDS = 3600
_LOCK = threading.Lock()


class SbisManualSessionError(RuntimeError):
    pass


@dataclass
class SbisManualSession:
    login: str
    password: str
    account_number: str | None
    last_used_at: float
    # Replaced wholesale by the most recent list_documents call; import looks
    # documents up here by id instead of re-fetching/re-merging from SBIS.
    # Not durable across a restart or a second worker process -- acceptable
    # for this simple, single-operator internal tool.
    documents_cache: dict[str, dict[str, Any]] = field(default_factory=dict)


_SESSIONS: dict[str, SbisManualSession] = {}


def _prune_expired_locked() -> None:
    now = time.time()
    expired = [
        token
        for token, session in _SESSIONS.items()
        if now - session.last_used_at > _SESSION_IDLE_TTL_SECONDS
    ]
    for token in expired:
        _SESSIONS.pop(token, None)


def create_session(*, login: str, password: str, account_number: str | None) -> str:
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _prune_expired_locked()
        _SESSIONS[token] = SbisManualSession(
            login=login,
            password=password,
            account_number=account_number,
            last_used_at=time.time(),
        )
    return token


def get_session(token: str | None) -> SbisManualSession:
    if not token:
        raise SbisManualSessionError("Сессия не найдена. Войдите заново.")
    with _LOCK:
        _prune_expired_locked()
        session = _SESSIONS.get(token)
        if session is None:
            raise SbisManualSessionError("Сессия истекла или не найдена. Войдите заново.")
        session.last_used_at = time.time()
        return session


def drop_session(token: str | None) -> None:
    if not token:
        return
    with _LOCK:
        _SESSIONS.pop(token, None)
