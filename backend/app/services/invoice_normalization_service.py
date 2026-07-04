import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Literal

from app.schemas.invoice_parser import (
    InvoiceParserResult,
    InvoiceReviewFlag,
    NormalizedInvoiceResult,
)
from app.services.item_normalization_service import normalize_item_candidate


MONEY_TOLERANCE = Decimal("0.02")


def normalize_invoice_result(
    parsed: InvoiceParserResult | dict[str, Any],
    *,
    duplicate: Literal["", "Да", "?"] = "",
    ocr_error: str | None = None,
) -> NormalizedInvoiceResult:
    source = parsed if isinstance(parsed, InvoiceParserResult) else InvoiceParserResult.model_validate(parsed)
    result = NormalizedInvoiceResult(**source.model_dump())
    result.duplicate = duplicate

    result.document.document_date = _normalize_date(
        result.document.document_date,
        result.review_flags,
        result.normalization_log,
    )
    result.document.document_number = _clean_text(result.document.document_number)
    result.document.supplier_inn = _normalize_inn(
        result.document.supplier_inn,
        result.review_flags,
        result.normalization_log,
    )

    document_money_fields = ("total_without_vat", "vat_total", "total_with_vat")
    for field in document_money_fields:
        setattr(result.document, field, _money(getattr(result.document, field)))

    for position, item in enumerate(result.items, start=1):
        line_number = item.line_number or position
        item.line_number = line_number
        item.raw_name = _clean_text(item.raw_name)
        item.unit = _clean_text(item.unit)
        item.quantity = _number(item.quantity)
        item.price = _money(item.price)
        item.amount_without_vat = _money(item.amount_without_vat)
        item.vat_amount = _money(item.vat_amount)
        item.amount_with_vat = _money(item.amount_with_vat)
        item.vat_rate = _normalize_vat_rate(item.vat_rate)
        for issue in normalize_item_candidate(item):
            _flag(
                result,
                "item",
                line_number,
                issue["field"],
                issue["reason"],
                issue["severity"],
            )

        if not item.raw_name:
            _flag(result, "item", line_number, "raw_name", "Не распознано наименование товара.", "error")
        if item.quantity is None or item.quantity <= 0:
            _flag(result, "item", line_number, "quantity", "Количество отсутствует или не больше нуля.", "error")
        if item.price is None or item.price < 0:
            _flag(result, "item", line_number, "price", "Цена отсутствует или отрицательна.", "error")

        calculated = _multiply(item.quantity, item.price)
        if item.amount_without_vat is None and calculated is not None:
            item.amount_without_vat = calculated
            result.normalization_log.append(f"items[{line_number}].amount_without_vat calculated")
        elif calculated is not None and not _close(item.amount_without_vat, calculated):
            _flag(
                result,
                "item",
                line_number,
                "amount_without_vat",
                "Стоимость строки не совпадает с количеством, умноженным на цену.",
                "warning",
            )

        calculated_with_vat = _add(item.amount_without_vat, item.vat_amount)
        if item.amount_with_vat is None and calculated_with_vat is not None:
            item.amount_with_vat = calculated_with_vat
            result.normalization_log.append(f"items[{line_number}].amount_with_vat calculated")
        elif calculated_with_vat is not None and not _close(item.amount_with_vat, calculated_with_vat):
            _flag(
                result,
                "item",
                line_number,
                "amount_with_vat",
                "Итог строки не совпадает со стоимостью и суммой НДС.",
                "warning",
            )

    if not result.items:
        _flag(result, "document", None, "items", "В документе не распознаны товарные строки.", "error")

    item_total = _sum(item.amount_with_vat for item in result.items)
    if result.document.total_with_vat is None and item_total is not None:
        result.document.total_with_vat = item_total
        result.normalization_log.append("document.total_with_vat calculated from items")
    elif item_total is not None and not _close(result.document.total_with_vat, item_total):
        _flag(
            result,
            "document",
            None,
            "total_with_vat",
            "Сумма товарных строк не совпадает с итогом документа.",
            "warning",
        )

    if ocr_error:
        _flag(result, "document", None, "source_trace", f"Ошибка OCR: {ocr_error}", "error")
        result.upload_status = "Не готово"
        result.row_status = "Ошибка загрузки"
        for item in result.items or [None]:
            result.item_corrections[(item.line_number if item else 1) or 1] = "Ошибка OCR"
    elif duplicate == "Да":
        result.upload_status = "Не готово"
        result.row_status = "Распознано"
    elif duplicate == "?":
        result.upload_status = "Требует проверки"
        result.row_status = "Распознано"
    elif result.review_flags:
        result.upload_status = "Требует проверки"
        result.row_status = "Правка вручную"
        _assign_corrections(result)

    return result


def to_legacy_invoice_payload(result: NormalizedInvoiceResult) -> dict[str, Any]:
    document = result.document
    return {
        "supplier": document.supplier_name or None,
        "supplier_legal_name": document.supplier_name or None,
        "invoice_number": document.document_number or None,
        "invoice_date": document.document_date or None,
        "supplier_inn": document.supplier_inn or None,
        "consignee": document.receiver or None,
        "recipient": document.receiver or None,
        "basis": document.basis or None,
        "total_sum": document.total_with_vat,
        "items": [
            {
                "name": item.raw_name,
                "raw_name": item.raw_name,
                "clean_name": item.clean_name,
                "normalized_name_candidate": item.normalized_name_candidate,
                "brand_or_descriptor": item.brand_or_descriptor,
                "package": item.package.model_dump(mode="json"),
                "document_unit": item.document_unit,
                "quantity_document": item.quantity_document,
                "quantity_multiplier": item.quantity_multiplier,
                "accounting_quantity_candidate": item.accounting_quantity_candidate,
                "accounting_unit_candidate": item.accounting_unit_candidate,
                "codes": item.codes,
                "quantity": item.quantity or 0,
                "unit": item.unit or "шт",
                "price": item.price or 0,
                "sum": item.amount_without_vat,
                "vat": item.vat_rate or None,
                "vat_percent": _vat_number(item.vat_rate),
                "vat_sum": item.vat_amount,
                "comment": item.source_fragment or None,
                "confidence": item.confidence,
                "needs_review": item.needs_review,
                "review_reason": item.review_reason,
                "line_number": item.line_number,
                "amount_with_vat": item.amount_with_vat,
                "correction": result.item_corrections.get(item.line_number or 0, ""),
            }
            for item in result.items
        ],
        "parser_provider": "openai",
        "parser_notes": [flag.reason for flag in result.review_flags],
        "parser_metadata": result.model_dump(mode="json"),
    }


def _normalize_date(
    value: str,
    flags: list[InvoiceReviewFlag],
    changes: list[str],
) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        flags.append(InvoiceReviewFlag(scope="document", field="document_date", reason="Дата документа не распознана.", severity="error"))
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            normalized = datetime.strptime(cleaned, fmt).date().isoformat()
            if normalized != cleaned:
                changes.append("document.document_date normalized")
            return normalized
        except ValueError:
            continue
    flags.append(InvoiceReviewFlag(scope="document", field="document_date", reason="Дата документа имеет неизвестный формат.", severity="error"))
    return cleaned


def _normalize_inn(
    value: str,
    flags: list[InvoiceReviewFlag],
    changes: list[str],
) -> str:
    cleaned = re.sub(r"\D", "", value or "")
    if cleaned != (value or ""):
        changes.append("document.supplier_inn normalized")
    if len(cleaned) not in {10, 12}:
        flags.append(InvoiceReviewFlag(scope="document", field="supplier_inn", reason="ИНН поставщика должен содержать 10 или 12 цифр.", severity="warning"))
    return cleaned


def _assign_corrections(result: NormalizedInvoiceResult) -> None:
    for flag in result.review_flags:
        if flag.scope != "item" or flag.line_number is None:
            continue
        reason = flag.reason.lower()
        correction = "Нет в справочнике" if "справочник" in reason else "Сопоставление" if "сопостав" in reason else "Другое"
        result.item_corrections.setdefault(flag.line_number, correction)


def _flag(
    result: NormalizedInvoiceResult,
    scope: Literal["document", "item"],
    line_number: int | None,
    field: str,
    reason: str,
    severity: Literal["warning", "error"],
) -> None:
    candidate = InvoiceReviewFlag(
        scope=scope,
        line_number=line_number,
        field=field,
        reason=reason,
        severity=severity,
    )
    if candidate not in result.review_flags:
        result.review_flags.append(candidate)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _number(value: Any) -> float | None:
    number = _decimal(value)
    return float(number) if number is not None else None


def _money(value: Any) -> float | None:
    number = _decimal(value)
    return float(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if number is not None else None


def _multiply(left: Any, right: Any) -> float | None:
    left_decimal = _decimal(left)
    right_decimal = _decimal(right)
    if left_decimal is None or right_decimal is None:
        return None
    return float((left_decimal * right_decimal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _add(left: Any, right: Any) -> float | None:
    left_decimal = _decimal(left)
    if left_decimal is None:
        return None
    right_decimal = _decimal(right) or Decimal("0")
    return float((left_decimal + right_decimal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _sum(values: Any) -> float | None:
    decimals = [_decimal(value) for value in values]
    present = [value for value in decimals if value is not None]
    if not present:
        return None
    return float(sum(present, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _close(left: Any, right: Any) -> bool:
    left_decimal = _decimal(left)
    right_decimal = _decimal(right)
    return left_decimal is not None and right_decimal is not None and abs(left_decimal - right_decimal) <= MONEY_TOLERANCE


def _normalize_vat_rate(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if cleaned.lower() in {"без ндс", "none", "no vat"}:
        return "Без НДС"
    match = re.search(r"\d+(?:[.,]\d+)?", cleaned)
    return f"{match.group(0).replace(',', '.')}%" if match else cleaned


def _vat_number(value: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", value or "")
    return float(match.group(0).replace(",", ".")) if match else None
