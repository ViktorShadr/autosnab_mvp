import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.invoice_parser_service import extract_invoice_payload_with_fallback
from app.services.ocr_service import OcrConfigurationError, recognize_invoice_image


class DocumentExtractionError(RuntimeError):
    pass


def extract_invoice_document(file_path: str, fallback_filename: str | None = None) -> dict[str, Any]:
    """Extract a normalized invoice payload from a local file.

    OCR remains the default path. When the MinerU backend is enabled, we try it
    first and fall back to OCR + deterministic parsing if the MinerU run is not
    available or produces weak output.
    """
    backend = (settings.document_extraction_backend or "ocr").strip().lower()
    if backend == "mineru":
        try:
            mineru_result = _extract_with_mineru(file_path, fallback_filename)
            if _payload_has_useful_data(mineru_result["payload"]):
                return mineru_result
        except Exception as exc:  # noqa: BLE001 - fallback is intentional
            mineru_error = str(exc)
        else:
            mineru_error = None

        if settings.document_extraction_fallback_to_ocr:
            ocr_result = _extract_with_ocr(file_path, fallback_filename)
            if mineru_error:
                ocr_result["error"] = mineru_error
                ocr_result["parser_notes"] = [*ocr_result.get("parser_notes", []), f"MinerU fallback: {mineru_error}"]
            return ocr_result

        raise DocumentExtractionError(
            "MinerU extraction returned an empty payload and OCR fallback is disabled."
        )

    return _extract_with_ocr(file_path, fallback_filename)


def _extract_with_ocr(file_path: str, fallback_filename: str | None) -> dict[str, Any]:
    try:
        ocr_result = recognize_invoice_image(file_path)
    except OcrConfigurationError as exc:
        return {
            "provider": "manual_review_fallback",
            "raw_text": "",
            "confidence": None,
            "pages": 0,
            "error": str(exc),
            "payload": extract_invoice_payload_with_fallback("", fallback_filename),
        }
    except Exception as exc:  # noqa: BLE001 - external OCR failures must not break upload
        return {
            "provider": "manual_review_fallback",
            "raw_text": "",
            "confidence": None,
            "pages": 0,
            "error": str(exc),
            "payload": extract_invoice_payload_with_fallback("", fallback_filename),
        }

    payload = extract_invoice_payload_with_fallback(ocr_result.get("raw_text") or "", fallback_filename)
    return {
        "provider": ocr_result.get("provider") or "google_drive_ocr",
        "raw_text": ocr_result.get("raw_text") or "",
        "confidence": ocr_result.get("confidence"),
        "pages": ocr_result.get("pages"),
        "temporary_document_id": ocr_result.get("temporary_document_id"),
        "payload": payload,
        "parser_provider": payload.get("parser_provider"),
        "parser_notes": payload.get("parser_notes", []),
    }


def _extract_with_mineru(file_path: str, fallback_filename: str | None) -> dict[str, Any]:
    raw_result = _run_mineru_command(file_path)
    mineru_payload = _normalize_mineru_payload(raw_result, fallback_filename)
    fallback_payload = extract_invoice_payload_with_fallback(
        mineru_payload.get("raw_text") or "",
        fallback_filename,
    )
    payload = _merge_payloads(mineru_payload, fallback_payload)
    payload["parser_provider"] = "mineru"
    notes = list(payload.get("parser_notes", []))
    notes.append("MinerU used as the primary document extraction backend.")
    payload["parser_notes"] = notes
    return {
        "provider": "mineru",
        "raw_text": mineru_payload.get("raw_text") or "",
        "confidence": mineru_payload.get("confidence"),
        "pages": mineru_payload.get("pages"),
        "payload": payload,
        "parser_provider": payload.get("parser_provider"),
        "parser_notes": payload.get("parser_notes", []),
        "structured_document": raw_result if isinstance(raw_result, dict) else None,
    }


def _run_mineru_command(file_path: str) -> Any:
    with tempfile.TemporaryDirectory(prefix="mineru-") as output_dir:
        command_template = settings.mineru_command or "mineru -p {file_path} -o {output_dir} -b pipeline"
        command_text = command_template.format(
            file_path=file_path,
            file=shlex.quote(file_path),
            output_dir=output_dir,
        )
        command = shlex.split(command_text)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.mineru_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise DocumentExtractionError(
                f"MinerU command failed with exit code {completed.returncode}: {stderr or 'no stderr output'}"
            )
        structured_output = _read_mineru_output(Path(output_dir))
        stdout = (completed.stdout or "").strip()
        if structured_output is not None:
            if stdout and isinstance(structured_output, dict):
                structured_output = {**structured_output, "_stdout": stdout}
            return structured_output
        if not stdout:
            raise DocumentExtractionError("MinerU command returned no output and no output files were found.")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return stdout


def _read_mineru_output(output_dir: Path) -> Any:
    if not output_dir.exists():
        return None

    json_candidates = sorted(
        [path for path in output_dir.rglob("*.json") if path.is_file()],
        key=lambda path: (len(path.parts), len(path.name), str(path)),
    )
    for candidate in json_candidates:
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

    markdown_candidates = sorted(
        [path for path in output_dir.rglob("*.md") if path.is_file()]
        + [path for path in output_dir.rglob("*.markdown") if path.is_file()]
        + [path for path in output_dir.rglob("*.txt") if path.is_file()],
        key=lambda path: (len(path.parts), len(path.name), str(path)),
    )
    if not markdown_candidates:
        return None

    texts = []
    for candidate in markdown_candidates:
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            texts.append(text)
    if not texts:
        return None
    return "\n\n".join(texts)


def _normalize_mineru_payload(raw_result: Any, fallback_filename: str | None) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        raw_text = (
            raw_result.get("raw_text")
            or raw_result.get("markdown")
            or raw_result.get("text")
            or raw_result.get("content")
            or ""
        )
        pages = raw_result.get("pages")
        if isinstance(pages, list):
            pages = len(pages)
        confidence = raw_result.get("confidence")
        header_source = raw_result.get("document") or raw_result.get("header") or raw_result
        payload = extract_invoice_payload_with_fallback(str(raw_text or ""), fallback_filename)
        mapped = {
            **payload,
            "supplier": _first_non_empty(header_source, "supplier", "seller", "supplier_name") or payload.get("supplier"),
            "supplier_legal_name": _first_non_empty(header_source, "supplier_legal_name", "supplier_name") or payload.get("supplier_legal_name"),
            "invoice_number": _first_non_empty(header_source, "invoice_number", "document_number", "number") or payload.get("invoice_number"),
            "invoice_date": _first_non_empty(header_source, "invoice_date", "date") or payload.get("invoice_date"),
            "venue": _first_non_empty(header_source, "venue", "trade_point", "recipient") or payload.get("venue"),
            "delivery_address": _first_non_empty(header_source, "delivery_address") or payload.get("delivery_address"),
            "display_store": _first_non_empty(header_source, "display_store", "store") or payload.get("display_store"),
            "store": _first_non_empty(header_source, "store") or payload.get("store"),
            "document_form": _first_non_empty(header_source, "document_form", "form") or payload.get("document_form"),
            "supplier_inn": _first_non_empty(header_source, "supplier_inn", "inn") or payload.get("supplier_inn"),
            "consignee": _first_non_empty(header_source, "consignee") or payload.get("consignee"),
            "recipient": _first_non_empty(header_source, "recipient", "buyer") or payload.get("recipient"),
            "trade_point": _first_non_empty(header_source, "trade_point") or payload.get("trade_point"),
            "warehouse": _first_non_empty(header_source, "warehouse") or payload.get("warehouse"),
            "basis": _first_non_empty(header_source, "basis") or payload.get("basis"),
            "total_sum": _first_non_empty(header_source, "total_sum", "sum", "amount") or payload.get("total_sum"),
        }
        items = raw_result.get("items")
        if isinstance(items, list) and items:
            mapped["items"] = [_normalize_item(item) for item in items]
        mapped["raw_text"] = str(raw_text or "")
        mapped["parser_provider"] = "mineru"
        mapped["pages"] = pages
        mapped["confidence"] = confidence
        notes = list(mapped.get("parser_notes", []))
        notes.append("MinerU returned JSON output.")
        mapped["parser_notes"] = notes
        return mapped

    raw_text = str(raw_result or "")
    payload = extract_invoice_payload_with_fallback(raw_text, fallback_filename)
    payload["parser_provider"] = "mineru"
    payload["parser_notes"] = [*payload.get("parser_notes", []), "MinerU returned plain text output."]
    return payload


def _merge_payloads(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    for key, value in primary.items():
        if key == "parser_notes":
            continue
        if key == "items" and value:
            merged[key] = value
            continue
        if value not in (None, "", []):
            merged[key] = value
    merged_notes = list(fallback.get("parser_notes", []))
    merged_notes.extend(primary.get("parser_notes", []))
    merged["parser_notes"] = merged_notes
    if primary.get("parser_provider"):
        merged["parser_provider"] = primary["parser_provider"]
    return merged


def _normalize_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "name": str(item),
            "quantity": 1.0,
            "unit": "шт",
            "price": 0.0,
            "sum": None,
            "vat": None,
            "comment": None,
            "confidence": None,
        }
    return {
        "name": _first_non_empty(item, "name", "item_name", "product_name") or "",
        "quantity": _coerce_float(item.get("quantity") or item.get("qty") or 0),
        "unit": str(item.get("unit") or "шт"),
        "price": _coerce_float(item.get("price") or 0),
        "sum": _coerce_float(item.get("sum") or item.get("line_sum") or item.get("total") or 0) if item.get("sum") is not None or item.get("line_sum") is not None or item.get("total") is not None else None,
        "vat": item.get("vat"),
        "comment": item.get("comment"),
        "confidence": item.get("confidence"),
        "vat_percent": _coerce_float(item.get("vat_percent")) if item.get("vat_percent") not in (None, "") else None,
        "vat_sum": _coerce_float(item.get("vat_sum")) if item.get("vat_sum") not in (None, "") else None,
    }


def _first_non_empty(source: Any, *keys: str) -> Any:
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if value not in (None, "", []):
            return value
    return None


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _payload_has_useful_data(payload: dict[str, Any]) -> bool:
    if payload.get("items"):
        return True
    for field in ("supplier", "invoice_number", "invoice_date", "venue", "document_form", "total_sum"):
        if payload.get(field) not in (None, ""):
            return True
    return False
