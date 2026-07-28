import ssl

import pytest

from app.services import google_api_retry_service as retry_service


class _FakeError(RuntimeError):
    def __init__(self, message, *, operation, attempts, retryable):
        super().__init__(message)
        self.operation = operation
        self.attempts = attempts
        self.retryable = retryable


def _on_failure(operation, attempts, retryable, exc):
    return _FakeError(
        f"{operation} failed after {attempts} attempt(s): {exc}",
        operation=operation,
        attempts=attempts,
        retryable=retryable,
    )


def test_execute_google_operation_retries_transient_ssl_error(monkeypatch):
    calls = 0
    monkeypatch.setattr(retry_service.settings, "google_api_retry_attempts", 3)
    monkeypatch.setattr(retry_service.settings, "google_api_retry_backoff_seconds", 0)

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ssl.SSLError("handshake timed out")
        return "ok"

    assert retry_service.execute_google_operation("test", operation, on_failure=_on_failure) == "ok"
    assert calls == 3


def test_execute_google_operation_exposes_typed_error_after_retries(monkeypatch):
    monkeypatch.setattr(retry_service.settings, "google_api_retry_attempts", 2)
    monkeypatch.setattr(retry_service.settings, "google_api_retry_backoff_seconds", 0)

    with pytest.raises(_FakeError) as exc_info:
        retry_service.execute_google_operation(
            "export_ocr_text",
            lambda: (_ for _ in ()).throw(ssl.SSLError("handshake timed out")),
            on_failure=_on_failure,
        )

    error = exc_info.value
    assert error.operation == "export_ocr_text"
    assert error.attempts == 2
    assert error.retryable is True


def test_execute_google_operation_does_not_retry_non_retryable_errors(monkeypatch):
    monkeypatch.setattr(retry_service.settings, "google_api_retry_attempts", 5)
    monkeypatch.setattr(retry_service.settings, "google_api_retry_backoff_seconds", 0)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise ValueError("not retryable")

    with pytest.raises(_FakeError) as exc_info:
        retry_service.execute_google_operation("op", operation, on_failure=_on_failure)

    assert calls == 1
    assert exc_info.value.retryable is False


def test_is_retryable_google_error_matches_transport_errors():
    assert retry_service.is_retryable_google_error(ssl.SSLError("x")) is True
    assert retry_service.is_retryable_google_error(TimeoutError("x")) is True
    assert retry_service.is_retryable_google_error(ConnectionError("x")) is True
    assert retry_service.is_retryable_google_error(ValueError("x")) is False


def test_is_retryable_google_error_matches_http_status_codes():
    class _FakeResp:
        status = 503

    exc = RuntimeError("service unavailable")
    exc.resp = _FakeResp()

    assert retry_service.is_retryable_google_error(exc) is True
