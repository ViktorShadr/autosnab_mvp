import json
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.services.ocr_service import parse_invoice_text_to_payload


class AiAgentConfigurationError(RuntimeError):
    pass


class AiAgentResponseError(RuntimeError):
    pass


INVOICE_JSON_SCHEMA_HINT = {
    "supplier": "string | null",
    "supplier_legal_name": "string | null",
    "invoice_number": "string | null",
    "invoice_date": "YYYY-MM-DD | null",
    "venue": "string | null",
    "delivery_address": "string | null",
    "items": [
        {
            "name": "string",
            "quantity": "number",
            "unit": "string",
            "price": "number",
            "sum": "number | null",
            "vat": "string | null",
            "comment": "string | null",
            "confidence": "number from 0 to 1 | null",
        }
    ],
    "agent_notes": ["string"],
}


def extract_invoice_payload_with_ai(raw_text: str, fallback_filename: str | None = None) -> dict:
    """Convert OCR text to structured invoice JSON with an AI Agent.

    This function performs a real external AI call only when AI_AGENT_ENABLED=true.
    If the AI Agent is disabled or fails, caller can use extract_invoice_payload_with_fallback().
    """
    if not settings.ai_agent_enabled:
        raise AiAgentConfigurationError("AI Agent отключен. Укажите AI_AGENT_ENABLED=true и API key.")
    if not settings.ai_agent_api_key:
        raise AiAgentConfigurationError("Не указан AI_AGENT_API_KEY для AI Agent.")

    payload = _call_chat_completion(raw_text)
    normalized = _normalize_agent_payload(payload, fallback_filename)
    normalized["parser_notes"] = normalized.get("parser_notes", []) + [
        f"Данные структурированы AI Agent: {settings.ai_agent_model}.",
        "Пользователь должен проверить результат в Google Таблице перед отправкой в iiko.",
    ]
    normalized["parser_provider"] = "ai_agent"
    return normalized


def extract_invoice_payload_with_fallback(raw_text: str, fallback_filename: str | None = None) -> dict:
    """Try AI Agent first, then deterministic parser.

    The fallback is important for local development and automated tests where external AI
    credentials are intentionally absent.
    """
    try:
        return extract_invoice_payload_with_ai(raw_text, fallback_filename)
    except (AiAgentConfigurationError, AiAgentResponseError, httpx.HTTPError, ValueError) as exc:
        parsed = parse_invoice_text_to_payload(raw_text, fallback_filename)
        parsed["parser_provider"] = "deterministic_fallback"
        parsed["ai_agent_error"] = str(exc)
        parsed["parser_notes"] = parsed.get("parser_notes", []) + [
            "AI Agent не использован или вернул ошибку; применен fallback parser.",
            str(exc),
        ]
        return parsed


def _call_chat_completion(raw_text: str) -> dict:
    request_body = {
        "model": settings.ai_agent_model,
        "temperature": settings.ai_agent_temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": _system_prompt(),
            },
            {
                "role": "user",
                "content": _user_prompt(raw_text),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.ai_agent_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.ai_agent_timeout_seconds) as client:
        response = client.post(settings.ai_agent_base_url, headers=headers, json=request_body)
    if response.status_code >= 400:
        raise AiAgentResponseError(f"AI Agent HTTP {response.status_code}: {response.text[:500]}")
    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiAgentResponseError("AI Agent вернул неожиданный формат ответа") from exc
    return _parse_json_content(content)


def _system_prompt() -> str:
    return (
        "Ты AI Agent для АвтоСнаб. Твоя задача — разобрать OCR-текст накладной HoReCa "
        "и вернуть только валидный JSON без markdown. Не выдумывай товары и цены. Если поле "
        "не найдено, укажи null. Если строка сомнительная, добавь comment и confidence ниже 0.7. "
        "Дата должна быть в формате YYYY-MM-DD. Числа возвращай как number. "
        "Структура JSON должна соответствовать схеме: "
        + json.dumps(INVOICE_JSON_SCHEMA_HINT, ensure_ascii=False)
    )


def _user_prompt(raw_text: str) -> str:
    trimmed = (raw_text or "")[: settings.ai_agent_max_ocr_chars]
    return (
        "Разбери OCR-текст накладной и верни JSON с поставщиком, номером, датой, точкой доставки "
        "и товарными позициями. OCR-текст:\n\n" + trimmed
    )


def _parse_json_content(content: str) -> dict:
    if not content:
        raise AiAgentResponseError("AI Agent вернул пустой ответ")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AiAgentResponseError("AI Agent вернул невалидный JSON") from exc
    if not isinstance(result, dict):
        raise AiAgentResponseError("AI Agent должен вернуть JSON object")
    return result


def _normalize_agent_payload(payload: dict[str, Any], fallback_filename: str | None = None) -> dict:
    items = []
    for raw_item in payload.get("items") or []:
        item = _normalize_item(raw_item)
        if item is not None:
            items.append(item)
    invoice_number = _clean(payload.get("invoice_number")) or _fallback_invoice_number(fallback_filename)
    return {
        "supplier": _clean(payload.get("supplier")),
        "supplier_legal_name": _clean(payload.get("supplier_legal_name")) or _clean(payload.get("supplier")),
        "invoice_number": invoice_number,
        "invoice_date": _normalize_date(payload.get("invoice_date")),
        "venue": _clean(payload.get("venue")),
        "delivery_address": _clean(payload.get("delivery_address")),
        "raw_text": payload.get("raw_text"),
        "items": items,
        "parser_notes": list(payload.get("agent_notes") or []),
    }


def _normalize_item(raw_item: Any) -> dict | None:
    if not isinstance(raw_item, dict):
        return None
    name = _clean(raw_item.get("name"))
    if not name:
        return None
    quantity = _to_float(raw_item.get("quantity"), default=0)
    price = _to_float(raw_item.get("price"), default=0)
    item_sum = _to_float(raw_item.get("sum"), default=None)
    confidence = _to_float(raw_item.get("confidence"), default=None)
    return {
        "name": name,
        "quantity": quantity,
        "unit": _clean(raw_item.get("unit")) or "шт",
        "price": price,
        "sum": item_sum,
        "vat": _clean(raw_item.get("vat")),
        "comment": _clean(raw_item.get("comment")),
        "confidence": confidence,
    }


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any, default: float | None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _normalize_date(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return text


def _fallback_invoice_number(filename: str | None) -> str | None:
    if not filename:
        return None
    stem = Path(filename).stem
    return re.sub(r"[^A-Za-zА-Яа-я0-9_-]", "", stem)[:64] or None
