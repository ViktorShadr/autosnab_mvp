from __future__ import annotations

import json

import httpx

from app.config import settings
from app.services import sbis_client as client_module
from app.services.sbis_client import SbisAttachmentExpiredError, SbisClient


def _response(status_code: int, body: bytes = b"{}") -> httpx.Response:
    return httpx.Response(
        status_code,
        content=body,
        request=httpx.Request("POST", "https://online.sbis.ru/test"),
    )


def _clear_sid_cache():
    client_module._SID_CACHE.clear()


def test_authenticate_caches_sid_across_calls(monkeypatch):
    _clear_sid_cache()
    monkeypatch.setattr(settings, "sbis_login", "user")
    monkeypatch.setattr(settings, "sbis_password", "pass")
    calls = {"auth": 0, "other": 0}

    def fake_post(_self, url, *, headers, content):
        if url == settings.sbis_auth_url:
            calls["auth"] += 1
            return _response(200, json.dumps({"jsonrpc": "2.0", "result": "SID-1", "id": 1}).encode())
        calls["other"] += 1
        return _response(200, json.dumps({"jsonrpc": "2.0", "result": {"Документ": []}, "id": 1}).encode())

    monkeypatch.setattr(SbisClient, "_post", fake_post)
    client = SbisClient()

    client.get_changes(date_from="01.01.2026 00:00:00")
    client.get_changes(date_from="01.01.2026 00:00:00")

    assert calls["auth"] == 1
    assert calls["other"] == 2


def test_session_error_triggers_single_reauth(monkeypatch):
    _clear_sid_cache()
    monkeypatch.setattr(settings, "sbis_login", "user")
    monkeypatch.setattr(settings, "sbis_password", "pass")
    calls = {"auth": 0, "other": 0}

    def fake_post(_self, url, *, headers, content):
        if url == settings.sbis_auth_url:
            calls["auth"] += 1
            return _response(200, json.dumps({"jsonrpc": "2.0", "result": f"SID-{calls['auth']}", "id": 1}).encode())
        calls["other"] += 1
        if calls["other"] == 1:
            return _response(200, json.dumps({"jsonrpc": "2.0", "error": "Сессия истекла", "id": 1}).encode())
        return _response(200, json.dumps({"jsonrpc": "2.0", "result": {"Документ": []}, "id": 1}).encode())

    monkeypatch.setattr(SbisClient, "_post", fake_post)
    client = SbisClient()

    payload = client.get_changes(date_from="01.01.2026 00:00:00")

    assert payload["result"] == {"Документ": []}
    assert calls["auth"] == 2
    assert calls["other"] == 2


def test_client_retries_transient_http_status(monkeypatch):
    _clear_sid_cache()
    monkeypatch.setattr(settings, "sbis_login", "user")
    monkeypatch.setattr(settings, "sbis_password", "pass")
    monkeypatch.setattr(settings, "sbis_http_retry_attempts", 3)
    monkeypatch.setattr(settings, "sbis_http_retry_base_delay_seconds", 0)
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)
    calls = {"count": 0}

    def fake_send_post_once(_self, url, *, headers, content):
        if url == settings.sbis_auth_url:
            return _response(200, json.dumps({"jsonrpc": "2.0", "result": "SID-1", "id": 1}).encode())
        calls["count"] += 1
        if calls["count"] == 1:
            return _response(503, b"temporary")
        return _response(200, json.dumps({"jsonrpc": "2.0", "result": {"Документ": []}, "id": 1}).encode())

    monkeypatch.setattr(SbisClient, "_send_post_once", fake_send_post_once)
    client = SbisClient()

    payload = client.get_changes(date_from="01.01.2026 00:00:00")

    assert payload["result"] == {"Документ": []}
    assert calls["count"] == 2


def test_download_attachment_403_raises_expired_error(monkeypatch):
    _clear_sid_cache()
    monkeypatch.setattr(settings, "sbis_login", "user")
    monkeypatch.setattr(settings, "sbis_password", "pass")

    def fake_post(_self, url, *, headers, content):
        return _response(200, json.dumps({"jsonrpc": "2.0", "result": "SID-1", "id": 1}).encode())

    def fake_get_binary(_self, url, *, headers):
        return _response(403, b"forbidden")

    monkeypatch.setattr(SbisClient, "_post", fake_post)
    monkeypatch.setattr(SbisClient, "_get_binary", fake_get_binary)
    client = SbisClient()

    try:
        client.download_attachment("https://disk.sbis.ru/some-file")
        assert False, "expected SbisAttachmentExpiredError"
    except SbisAttachmentExpiredError:
        pass
