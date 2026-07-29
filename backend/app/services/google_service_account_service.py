from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from app.config import settings

GOOGLE_SERVICE_ACCOUNT_ENV_VAR = "GOOGLE_SERVICE_ACCOUNT_JSON_B64"


class GoogleServiceAccountConfigurationError(RuntimeError):
    pass


def decode_service_account_info() -> dict[str, Any]:
    """Base64-decode and JSON-parse the service-account key. No network calls."""
    raw_b64 = settings.google_service_account_json_b64
    if not raw_b64:
        raise GoogleServiceAccountConfigurationError(
            f"Не задан {GOOGLE_SERVICE_ACCOUNT_ENV_VAR}. Укажите его в .env "
            "(base64 от JSON-ключа сервисного аккаунта)."
        )
    try:
        raw_json = base64.b64decode(raw_b64, validate=True).decode("utf-8")
    except (ValueError, binascii.Error) as exc:
        raise GoogleServiceAccountConfigurationError(
            f"{GOOGLE_SERVICE_ACCOUNT_ENV_VAR} должен быть валидной base64-строкой."
        ) from exc
    try:
        info = json.loads(raw_json)
    except ValueError as exc:
        raise GoogleServiceAccountConfigurationError(
            f"{GOOGLE_SERVICE_ACCOUNT_ENV_VAR} после base64-декодирования должен "
            "содержать валидный JSON-ключ сервисного аккаунта."
        ) from exc
    return info


def get_google_service_account_credentials(scopes: list[str]):
    try:
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    except ImportError as exc:
        raise GoogleServiceAccountConfigurationError(
            "Не установлены зависимости Google Auth. Выполните pip install -r backend/requirements.txt."
        ) from exc

    info = decode_service_account_info()
    return ServiceAccountCredentials.from_service_account_info(info, scopes=scopes)
