from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db.session import SessionLocal
from app.services.sbis_sync_service import sync_sbis_documents

logger = logging.getLogger(__name__)

_STOP_EVENT = threading.Event()
_THREAD: threading.Thread | None = None
_THREAD_LOCK = threading.Lock()
_STATUS_LOCK = threading.Lock()
_LAST_RUN_AT: str | None = None
_LAST_SUCCESS_AT: str | None = None
_LAST_ERROR: str | None = None
_LAST_RESULT: dict[str, Any] | None = None


def start_sbis_scheduler() -> bool:
    global _THREAD
    if not _scheduler_configuration_ready():
        return False
    with _THREAD_LOCK:
        if _THREAD and _THREAD.is_alive():
            return True
        _STOP_EVENT.clear()
        _THREAD = threading.Thread(target=_scheduler_loop, name="sbis-sync-scheduler", daemon=True)
        _THREAD.start()
    return True


def stop_sbis_scheduler() -> None:
    global _THREAD
    _STOP_EVENT.set()
    with _THREAD_LOCK:
        thread = _THREAD
        _THREAD = None
    if thread and thread.is_alive():
        thread.join(timeout=5)


def sbis_scheduler_status() -> dict[str, object]:
    with _STATUS_LOCK:
        return {
            "enabled": settings.sbis_scheduler_enabled,
            "configured": _scheduler_configuration_ready(),
            "running": bool(_THREAD and _THREAD.is_alive()),
            "interval_seconds": settings.sbis_sync_interval_seconds,
            "last_run_at": _LAST_RUN_AT,
            "last_success_at": _LAST_SUCCESS_AT,
            "last_error": _LAST_ERROR,
            "last_result": dict(_LAST_RESULT or {}),
        }


def _scheduler_configuration_ready() -> bool:
    return bool(
        settings.sbis_integration_enabled
        and settings.sbis_scheduler_enabled
        and settings.sbis_login
        and settings.sbis_password
    )


def _scheduler_loop() -> None:
    interval = max(30, settings.sbis_sync_interval_seconds)
    while not _STOP_EVENT.is_set():
        _run_once()
        _STOP_EVENT.wait(interval)


def _run_once() -> None:
    global _LAST_ERROR
    global _LAST_RESULT
    global _LAST_RUN_AT
    global _LAST_SUCCESS_AT

    run_at = datetime.now(timezone.utc).isoformat()
    db = SessionLocal()
    try:
        result = sync_sbis_documents(db, create_google_sheet=True)
        with _STATUS_LOCK:
            _LAST_RUN_AT = run_at
            _LAST_SUCCESS_AT = datetime.now(timezone.utc).isoformat()
            _LAST_ERROR = None
            _LAST_RESULT = dict(result)
    except Exception as exc:  # noqa: BLE001 - scheduler survives transient failures
        with _STATUS_LOCK:
            _LAST_RUN_AT = run_at
            _LAST_ERROR = str(exc)
            _LAST_RESULT = None
        logger.exception("Automatic SBIS synchronization failed")
    finally:
        db.close()
