from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
}

_SID_LOCK = threading.Lock()
_SID_CACHE: dict[str, str] = {}


class SbisApiError(RuntimeError):
    pass


class SbisAuthError(SbisApiError):
    pass


class SbisTransportError(SbisApiError):
    pass


class SbisAttachmentExpiredError(SbisApiError):
    """Raised on HTTP 403 when downloading an attachment — the signed link expired."""


@dataclass
class SbisBinaryResponse:
    content: bytes
    content_type: str | None = None


def _sid_cache_key() -> str:
    return f"{settings.sbis_login}:{settings.sbis_account_number or ''}"


class SbisClient:
    def __init__(self) -> None:
        self.auth_url = settings.sbis_auth_url
        self.api_url = f"{settings.sbis_api_base_url.rstrip('/')}/service/?srv=1"
        self.timeout = settings.sbis_timeout_seconds

    def get_changes(self, *, date_from: str) -> dict[str, Any]:
        return self._call(
            "СБИС.СписокИзменений",
            {"Фильтр": {"ДатаВремяС": date_from}},
        )

    def download_attachment(self, url: str) -> SbisBinaryResponse:
        sid = self._ensure_sid()
        headers = {"X-SBISSessionID": sid, "Cookie": f"sid={sid}"}
        response = self._get_binary(url, headers=headers)
        if response.status_code == 403:
            raise SbisAttachmentExpiredError(
                f"Ссылка на вложение СБИС истекла или недоступна: HTTP 403 ({url})"
            )
        if response.status_code >= 400:
            raise SbisApiError(
                f"СБИС вернул HTTP {response.status_code} при скачивании вложения"
            )
        return SbisBinaryResponse(
            content=response.content,
            content_type=response.headers.get("Content-Type"),
        )

    def _call(self, method: str, params: dict[str, Any], *, _retried_auth: bool = False) -> dict[str, Any]:
        sid = self._ensure_sid()
        payload = self._rpc_call(self.api_url, method, params, sid=sid)
        error = payload.get("error")
        if error:
            if not _retried_auth and _looks_like_session_error(error):
                self._invalidate_sid()
                return self._call(method, params, _retried_auth=True)
            raise SbisApiError(f"СБИС вернул ошибку в методе {method}: {error}")
        return payload

    def _ensure_sid(self) -> str:
        with _SID_LOCK:
            cached = _SID_CACHE.get(_sid_cache_key())
        if cached:
            return cached
        return self._authenticate()

    def _invalidate_sid(self) -> None:
        with _SID_LOCK:
            _SID_CACHE.pop(_sid_cache_key(), None)

    def _authenticate(self) -> str:
        params: dict[str, Any] = {
            "Параметр": {
                "Логин": settings.sbis_login,
                "Пароль": settings.sbis_password,
            }
        }
        if settings.sbis_account_number:
            params["Параметр"]["НомерАккаунта"] = settings.sbis_account_number
        payload = self._rpc_call(self.auth_url, "СБИС.Аутентифицировать", params)
        error = payload.get("error")
        if error:
            raise SbisAuthError(f"Ошибка аутентификации СБИС: {error}")
        sid = payload.get("result")
        if not sid:
            raise SbisAuthError("СБИС не вернул SID при аутентификации")
        with _SID_LOCK:
            _SID_CACHE[_sid_cache_key()] = sid
        return sid

    def _rpc_call(
        self,
        url: str,
        method: str,
        params: dict[str, Any],
        *,
        sid: str | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = dict(_HEADERS)
        if sid:
            headers["X-SBISSessionID"] = sid
        response = self._post(url, headers=headers, content=body)
        try:
            return response.json()
        except ValueError as exc:
            raise SbisApiError(f"СБИС вернул невалидный JSON от {method}") from exc

    def _post(self, url: str, *, headers: dict[str, str], content: bytes) -> httpx.Response:
        attempts = max(1, settings.sbis_http_retry_attempts)
        last_transport_error: SbisTransportError | None = None
        for attempt in range(attempts):
            try:
                response = self._send_post_once(url, headers=headers, content=content)
            except httpx.HTTPError as exc:
                last_transport_error = SbisTransportError(f"Ошибка соединения с СБИС: {exc}")
                if attempt + 1 >= attempts:
                    raise last_transport_error from exc
                time.sleep(_retry_delay(attempt))
                continue
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt + 1 < attempts:
                time.sleep(_retry_delay(attempt))
                continue
            if response.status_code >= 400:
                raise SbisApiError(
                    f"СБИС вернул HTTP {response.status_code}: {response.text[:500]}"
                )
            return response
        if last_transport_error is not None:
            raise last_transport_error
        raise SbisApiError("СБИС API не вернул ответ")

    def _send_post_once(self, url: str, *, headers: dict[str, str], content: bytes) -> httpx.Response:
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, headers=headers, content=content)

    def _get_binary(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        attempts = max(1, settings.sbis_http_retry_attempts)
        last_transport_error: SbisTransportError | None = None
        for attempt in range(attempts):
            try:
                return self._send_get_once(url, headers=headers)
            except httpx.HTTPError as exc:
                last_transport_error = SbisTransportError(f"Ошибка соединения с СБИС: {exc}")
                if attempt + 1 >= attempts:
                    raise last_transport_error from exc
                time.sleep(_retry_delay(attempt))
        raise last_transport_error or SbisApiError("Не удалось скачать вложение СБИС")

    def _send_get_once(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=self.timeout) as client:
            return client.get(url, headers=headers)


def _looks_like_session_error(error: Any) -> bool:
    text = json.dumps(error, ensure_ascii=False) if not isinstance(error, str) else error
    return bool(re.search(r"сесси|sid|автор", text, re.IGNORECASE))


def _retry_delay(attempt: int) -> float:
    base = max(0.0, settings.sbis_http_retry_base_delay_seconds)
    maximum = max(base, settings.sbis_http_retry_max_delay_seconds)
    return min(base * (2**attempt), maximum)
