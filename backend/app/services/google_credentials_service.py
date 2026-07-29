from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.google_oauth_service import get_google_user_credentials, get_oauth_status
from app.services.google_service_account_service import (
    GoogleServiceAccountConfigurationError,
    decode_service_account_info,
    get_google_service_account_credentials,
)

SHEETS_SERVICE_ACCOUNT_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
VISION_SERVICE_ACCOUNT_SCOPES = ["https://www.googleapis.com/auth/cloud-vision"]

_VALID_SHEETS_AUTH_MODES = {"oauth", "service_account"}
_VALID_OCR_PROVIDERS = {"google_drive_ocr", "google_cloud_vision"}


class GoogleAuthConfigurationError(RuntimeError):
    pass


def get_sheets_credentials():
    """Return credentials for the Sheets API, per GOOGLE_SHEETS_AUTH_MODE."""
    if settings.google_sheets_auth_mode == "service_account":
        return get_google_service_account_credentials(SHEETS_SERVICE_ACCOUNT_SCOPES)
    if settings.google_sheets_auth_mode == "oauth":
        return get_google_user_credentials()
    raise GoogleAuthConfigurationError(
        f"Неизвестный GOOGLE_SHEETS_AUTH_MODE={settings.google_sheets_auth_mode!r}. "
        "Допустимые значения: oauth, service_account."
    )


def get_sheets_auth_status() -> dict[str, Any]:
    """Diagnostic status reflecting whichever Sheets auth mode is active."""
    if settings.google_sheets_auth_mode == "service_account":
        result: dict[str, Any] = {"auth_mode": "service_account", "authorized": False}
        try:
            credentials = get_sheets_credentials()
            result["authorized"] = True
            result["service_account_email"] = getattr(credentials, "service_account_email", None)
        except Exception as exc:  # noqa: BLE001 - status endpoint should show diagnostics
            result["error"] = str(exc)
        return result
    return get_oauth_status()


def validate_google_auth_configuration() -> None:
    """Fail fast at startup on inconsistent Google auth settings. No network calls."""
    if settings.google_sheets_auth_mode not in _VALID_SHEETS_AUTH_MODES:
        raise GoogleAuthConfigurationError(
            f"Недопустимое значение GOOGLE_SHEETS_AUTH_MODE={settings.google_sheets_auth_mode!r}. "
            f"Допустимые значения: {sorted(_VALID_SHEETS_AUTH_MODES)}."
        )
    if settings.google_ocr_provider not in _VALID_OCR_PROVIDERS:
        raise GoogleAuthConfigurationError(
            f"Недопустимое значение GOOGLE_OCR_PROVIDER={settings.google_ocr_provider!r}. "
            f"Допустимые значения: {sorted(_VALID_OCR_PROVIDERS)}."
        )
    needs_service_account = (
        settings.google_sheets_auth_mode == "service_account"
        or settings.google_ocr_provider == "google_cloud_vision"
    )
    if needs_service_account:
        decode_service_account_info()  # raises GoogleServiceAccountConfigurationError if missing/malformed
