import importlib.util
from typing import Any

from app.config import settings


def provider_health() -> dict[str, Any]:
    return {
        "mineru": _mineru_health(),
        "google_ocr": _google_ocr_health(),
        "openai": _openai_health(),
    }


def _mineru_health() -> dict[str, Any]:
    if importlib.util.find_spec("mineru") is None:
        return {"ready": False, "reason": "mineru package is not installed"}
    try:
        import cv2  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - native import failures must be visible
        return {"ready": False, "reason": f"OpenCV import failed: {exc}"}
    return {"ready": True, "reason": None}


def _google_ocr_health() -> dict[str, Any]:
    if not settings.google_drive_ocr_enabled:
        return {"ready": False, "reason": "GOOGLE_DRIVE_OCR_ENABLED is false"}
    required = {
        "GOOGLE_OAUTH_CLIENT_ID": settings.google_oauth_client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": settings.google_oauth_client_secret,
        "GOOGLE_OAUTH_REFRESH_TOKEN": settings.google_oauth_refresh_token,
    }
    missing = [name for name, value in required.items() if not value]
    return {
        "ready": not missing,
        "reason": f"Missing settings: {', '.join(missing)}" if missing else None,
    }


def _openai_health() -> dict[str, Any]:
    return {
        "ready": bool(settings.openai_api_key),
        "reason": None if settings.openai_api_key else "OPENAI_API_KEY is not configured",
        "model": settings.openai_invoice_model,
    }
