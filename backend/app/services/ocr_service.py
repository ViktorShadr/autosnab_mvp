import json
import re
from pathlib import Path

from app.config import settings


class OcrConfigurationError(RuntimeError):
    pass


def recognize_invoice_image(file_path: str) -> dict:
    """Recognize invoice image/PDF with Google Cloud Vision when enabled.

    The function performs a real external OCR call if GOOGLE_VISION_ENABLED=true and
    a Google service account is configured. It is intentionally isolated from route
    code so tests can run without Google credentials.
    """
    if not settings.google_vision_enabled:
        raise OcrConfigurationError(
            "Google Vision OCR отключен. Укажите GOOGLE_VISION_ENABLED=true и credentials service account."
        )
    credentials_path = _credentials_path()
    if credentials_path is None:
        raise OcrConfigurationError(
            "Не указан GOOGLE_APPLICATION_CREDENTIALS или GOOGLE_SERVICE_ACCOUNT_FILE для Google Vision OCR."
        )
    try:
        from google.cloud import vision
        from google.oauth2 import service_account
    except ImportError as exc:
        raise OcrConfigurationError(
            "Google Vision OCR: не установлены зависимости google-cloud-vision/google-auth. Выполните pip install -r requirements.txt."
        ) from exc

    credentials = service_account.Credentials.from_service_account_file(credentials_path)
    client = vision.ImageAnnotatorClient(credentials=credentials)
    content = Path(file_path).read_bytes()
    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"Google Vision OCR error: {response.error.message}")
    text = response.full_text_annotation.text if response.full_text_annotation else ""
    return {
        "provider": "google_vision",
        "raw_text": text,
        "confidence": None,
        "pages": len(response.full_text_annotation.pages) if response.full_text_annotation else 0,
    }


def parse_invoice_text_to_payload(raw_text: str, fallback_filename: str | None = None) -> dict:
    """Small deterministic parser for MVP-4.

    Real OCR extracts text; this parser creates a first draft that the user verifies
    in Google Sheets. It does not pretend to be perfect and marks uncertain fields.
    """
    text = raw_text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    supplier = _extract_supplier(lines)
    invoice_number = _extract_invoice_number(joined) or _fallback_invoice_number(fallback_filename)
    invoice_date = _extract_date(joined)
    items = _extract_items(lines)
    return {
        "supplier": supplier,
        "supplier_legal_name": supplier,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "venue": None,
        "delivery_address": None,
        "raw_text": raw_text,
        "items": items,
        "parser_notes": [
            "Поля распознаны автоматически и должны быть проверены пользователем в Google Таблице.",
            "Если товарные строки не распознаны, заполните их вручную в таблице перед отправкой.",
        ],
    }


def _credentials_path() -> str | None:
    return settings.google_application_credentials or settings.google_service_account_file


def _extract_supplier(lines: list[str]) -> str | None:
    for line in lines[:20]:
        lowered = line.lower()
        if "поставщик" in lowered:
            return _clean_value(line.split(":", 1)[-1])
        if any(marker in line for marker in ["ООО", "ИП ", "АО ", "ЗАО"]):
            return line
    return None


def _extract_invoice_number(text: str) -> str | None:
    patterns = [
        r"(?:накладн(?:ая|ой)?|счет|сч[её]т|invoice|inv)\D{0,20}(\d{2,}[A-Za-zА-Яа-я0-9\-/]*)",
        r"№\s*([A-Za-zА-Яа-я0-9\-/]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_date(text: str) -> str | None:
    match = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return match.group(0)
    return None


def _extract_items(lines: list[str]) -> list[dict]:
    items = []
    # Heuristic: item lines often contain name + quantity + unit + price + sum.
    pattern = re.compile(
        r"^(?P<name>.+?)\s+(?P<qty>\d+(?:[,.]\d+)?)\s*(?P<unit>шт|кг|л|г|мл|уп|кор|pcs|kg|l)?\s+"
        r"(?P<price>\d+(?:[,.]\d+)?)\s+(?P<sum>\d+(?:[,.]\d+)?)$",
        flags=re.IGNORECASE,
    )
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        match = pattern.match(normalized)
        if match:
            name = match.group("name").strip(" -—\t")
            if len(name) < 3:
                continue
            items.append(
                {
                    "name": name,
                    "quantity": _to_float(match.group("qty")),
                    "unit": match.group("unit") or "шт",
                    "price": _to_float(match.group("price")),
                    "sum": _to_float(match.group("sum")),
                    "vat": None,
                    "comment": "распознано OCR, требуется проверка",
                    "confidence": None,
                }
            )
    return items


def _fallback_invoice_number(filename: str | None) -> str | None:
    if not filename:
        return None
    stem = Path(filename).stem
    return re.sub(r"[^A-Za-zА-Яа-я0-9_-]", "", stem)[:64] or None


def _clean_value(value: str) -> str | None:
    value = value.strip(" :-—\t")
    return value or None


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def pretty_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
