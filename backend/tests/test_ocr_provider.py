import ssl

import pytest

from app.services import ocr_service
from app.services.ocr_service import OcrProviderError


def test_google_operation_retries_transient_ssl_error(monkeypatch):
    calls = 0
    monkeypatch.setattr(ocr_service.settings, "google_api_retry_attempts", 3)
    monkeypatch.setattr(ocr_service.settings, "google_api_retry_backoff_seconds", 0)

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ssl.SSLError("handshake timed out")
        return "ok"

    assert ocr_service._execute_google_operation("test", operation) == "ok"
    assert calls == 3


def test_google_operation_exposes_typed_error_after_retries(monkeypatch):
    monkeypatch.setattr(ocr_service.settings, "google_api_retry_attempts", 2)
    monkeypatch.setattr(ocr_service.settings, "google_api_retry_backoff_seconds", 0)

    with pytest.raises(OcrProviderError) as exc_info:
        ocr_service._execute_google_operation(
            "export_ocr_text",
            lambda: (_ for _ in ()).throw(ssl.SSLError("handshake timed out")),
        )

    error = exc_info.value
    assert error.operation == "export_ocr_text"
    assert error.attempts == 2
    assert error.retryable is True
