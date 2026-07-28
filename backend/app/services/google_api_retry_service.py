from __future__ import annotations

import socket
import ssl
import time
from typing import Any, Callable

from app.config import settings

OnFailure = Callable[[str, int, bool, Exception], Exception]


def execute_google_operation(operation: str, call: Callable[[], Any], *, on_failure: OnFailure) -> Any:
    """Execute `call`, retrying transient Google API failures with backoff.

    `on_failure(operation, attempts, retryable, exc)` builds the exception to
    raise once retries are exhausted -- each caller supplies its own
    provider-specific exception type.
    """
    attempts = max(1, settings.google_api_retry_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary by transport
            retryable = is_retryable_google_error(exc)
            if not retryable or attempt >= attempts:
                raise on_failure(operation, attempt, retryable, exc) from exc
            delay = max(0.0, settings.google_api_retry_backoff_seconds) * (2 ** (attempt - 1))
            if delay:
                time.sleep(delay)
    raise AssertionError("unreachable")


def is_retryable_google_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout, ssl.SSLError, ConnectionError)):
        return True
    status_code = getattr(getattr(exc, "resp", None), "status", None)
    return status_code in {408, 429, 500, 502, 503, 504}
