from __future__ import annotations

import base64
import io
from pathlib import Path

from app.config import settings
from app.services.google_api_retry_service import execute_google_operation
from app.services.google_credentials_service import VISION_SERVICE_ACCOUNT_SCOPES
from app.services.google_service_account_service import get_google_service_account_credentials
from app.services.ocr_service import OcrConfigurationError, OcrProviderError

SUPPORTED_VISION_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif"}
SUPPORTED_VISION_EXTENSIONS = SUPPORTED_VISION_IMAGE_EXTENSIONS | {".pdf"}
PAGE_BREAK_MARKER = "\n\n----- PAGE BREAK -----\n\n"


def recognize_invoice_with_google_vision_ocr(file_path: str) -> dict:
    """Recognize invoice image/PDF through Google Cloud Vision (DOCUMENT_TEXT_DETECTION).

    Uses a service-account credential (no Drive quota involved) via the
    generic googleapiclient REST client, not the separate google-cloud-vision
    SDK -- matches how this codebase already talks to Google APIs elsewhere.
    """
    path = Path(file_path)
    if not path.exists():
        raise OcrConfigurationError(f"Файл для OCR не найден: {file_path}")
    if path.suffix.lower() not in SUPPORTED_VISION_EXTENSIONS:
        raise OcrConfigurationError(
            "Google Cloud Vision OCR поддерживает JPG, JPEG, PNG, PDF, TIFF, BMP и GIF."
        )

    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise OcrConfigurationError(
            "Google Cloud Vision OCR: не установлены зависимости "
            "google-api-python-client/google-auth. Выполните pip install -r backend/requirements.txt."
        ) from exc

    credentials = get_google_service_account_credentials(VISION_SERVICE_ACCOUNT_SCOPES)
    vision_service = build("vision", "v1", credentials=credentials)

    images_b64 = (
        _render_pdf_pages_to_base64_png(path)
        if path.suffix.lower() == ".pdf"
        else [base64.b64encode(path.read_bytes()).decode("ascii")]
    )
    page_texts = [
        _annotate_image(vision_service, image, i) for i, image in enumerate(images_b64, start=1)
    ]

    return {
        "provider": "google_cloud_vision",
        "raw_text": PAGE_BREAK_MARKER.join(page_texts),
        "confidence": None,
        "pages": len(images_b64),
        "temporary_document_id": None,
    }


def _annotate_image(vision_service, image_b64: str, page_number: int) -> str:
    body = {
        "requests": [
            {
                "image": {"content": image_b64},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                "imageContext": {"languageHints": [settings.google_drive_ocr_language]},
            }
        ]
    }
    operation = f"annotate_page_{page_number}"
    response = execute_google_operation(
        operation,
        lambda: vision_service.images().annotate(body=body).execute(),
        on_failure=lambda op, attempts, retryable, exc: OcrProviderError(
            f"Google Cloud Vision OCR operation {op} failed after {attempts} attempt(s): {exc}",
            provider="google_cloud_vision",
            operation=op,
            attempts=attempts,
            retryable=retryable,
        ),
    )
    result = (response.get("responses") or [{}])[0]
    if "error" in result:
        raise OcrProviderError(
            f"Google Cloud Vision вернул ошибку для страницы {page_number}: "
            f"{result['error'].get('message')}",
            provider="google_cloud_vision",
            operation=operation,
            attempts=1,
            retryable=False,
        )
    return result.get("fullTextAnnotation", {}).get("text", "")


def _render_pdf_pages_to_base64_png(path: Path) -> list[str]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrConfigurationError(
            "Google Cloud Vision OCR: не установлена зависимость pypdfium2. "
            "Выполните pip install -r backend/requirements.txt."
        ) from exc

    scale = max(1.0, settings.google_vision_pdf_render_scale)
    pdf = pdfium.PdfDocument(str(path))
    images_b64 = []
    for page in pdf:
        buffer = io.BytesIO()
        page.render(scale=scale).to_pil().save(buffer, format="PNG")
        images_b64.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
    return images_b64
