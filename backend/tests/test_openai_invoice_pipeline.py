from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.invoice_parser import InvoiceParsedItem, InvoiceParserResult
from app.services.item_normalization_service import (
    apply_reference_mapping_to_payload,
    normalize_item_candidate,
)
from app.services.invoice_normalization_service import (
    normalize_invoice_result,
    normalize_supplier_inn_value,
    to_legacy_invoice_payload,
)
from app.services.openai_invoice_parser_service import SYSTEM_PROMPT, parse_invoice_with_openai
from app.services.invoice_review_service import ensure_upload_status_allows_send


def _parsed_invoice(**overrides):
    payload = {
        "document": {
            "document_date": "04.07.2026",
            "document_number": "A-42",
            "supplier_name": 'ООО "Поставщик"',
            "supplier_inn": "77 0123 4567",
            "shipper": "",
            "receiver": 'ООО "Кафе"',
            "basis": "Договор 1",
            "total_without_vat": 100,
            "vat_total": 20,
            "total_with_vat": 120,
        },
        "items": [
            {
                "line_number": 1,
                "raw_name": "Молоко",
                "unit": "шт",
                "quantity": 2,
                "price": 50,
                "amount_without_vat": 100,
                "vat_rate": "20",
                "vat_amount": 20,
                "amount_with_vat": 120,
                "confidence": 0.98,
                "source_fragment": "Товар 2 шт 50 100 НДС 20 120",
            }
        ],
        "review_flags": [],
        "source_trace": {
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "google_drive_ocr",
            "raw_text_sample": "sample",
        },
    }
    payload.update(overrides)
    return payload


def test_parser_contract_forbids_unknown_fields():
    payload = _parsed_invoice()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        InvoiceParserResult.model_validate(payload)


def test_parser_contract_forbids_unknown_package_fields():
    payload = _parsed_invoice()
    payload["items"][0]["package"] = {"value": 1, "unit": "л", "raw": "1Л", "unknown": True}

    with pytest.raises(ValidationError):
        InvoiceParserResult.model_validate(payload)


def test_openai_parser_uses_structured_response_and_returns_legacy_payload(tmp_path, monkeypatch):
    parsed = InvoiceParserResult.model_validate(_parsed_invoice())

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def parse(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_parsed=parsed)

    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    monkeypatch.setattr("app.services.openai_invoice_parser_service.settings.openai_debug_log_enabled", False)

    result = parse_invoice_with_openai(
        {
            "filename": "invoice.jpg",
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "google_drive_ocr",
            "raw_text": "invoice evidence",
        },
        client=client,
    )

    assert responses.kwargs["text_format"] is InvoiceParserResult
    assert result["parser_provider"] == "openai"
    assert result["invoice_date"] == "2026-07-04"
    assert result["supplier_inn"] == "7701234567"
    assert result["items"][0]["sum"] == 100.0
    assert result["parser_metadata"]["upload_status"] == "Проверить"
    assert "Справочник фасовок" in SYSTEM_PROMPT
    assert "quantity_multiplier" in SYSTEM_PROMPT


def test_item_normalization_extracts_code_package_and_accounting_quantity():
    item = InvoiceParsedItem(
        raw_name="3 ТОВАР : ШТ. [N+13968 КЕФИР ФЕРМЕРСКИЙ 800Г",
        unit="ШТ",
        quantity=5,
        price=100,
        confidence=0.95,
    )

    issues = normalize_item_candidate(item)

    assert issues == []
    assert item.clean_name == "КЕФИР ФЕРМЕРСКИЙ"
    assert item.normalized_name_candidate == "Кефир Фермерский"
    assert item.codes == ["N+13968"]
    assert item.package.model_dump() == {"value": 800.0, "unit": "г", "raw": "800Г"}
    assert item.quantity_multiplier == 0.8
    assert item.accounting_quantity_candidate == 4.0
    assert item.accounting_unit_candidate == "кг"


def test_item_normalization_multiplies_nested_liquid_package():
    item = InvoiceParsedItem(
        raw_name="ВОДА ПИТЬЕВАЯ 0,5Л 12ШТ",
        document_unit="УПАК",
        quantity_document=3,
        confidence=0.9,
    )

    issues = normalize_item_candidate(item)

    assert issues == []
    assert item.package.model_dump() == {"value": 0.5, "unit": "л", "raw": "0,5Л"}
    assert item.quantity_multiplier == 6.0
    assert item.accounting_quantity_candidate == 18.0
    assert item.accounting_unit_candidate == "л"


def test_item_normalization_flags_ambiguous_sheets_unit():
    item = InvoiceParsedItem(
        raw_name="САЛФЕТКИ БУМ 24Х24 100Л",
        document_unit="УПАК",
        quantity_document=1,
        confidence=0.9,
    )

    issues = normalize_item_candidate(item)

    assert item.needs_review is True
    assert any("листы" in issue["reason"] for issue in issues)


def test_reference_mapping_fills_us_fields_deterministically():
    payload = {
        "items": [
            {
                "line_number": 1,
                "name": "КЕФИР ФЕРМЕРСКИЙ 800Г",
                "normalized_name_candidate": "Кефир Фермерский",
                "package": {"value": 800, "unit": "г", "raw": "800Г"},
                "quantity": 5,
                "quantity_document": 5,
                "quantity_multiplier": 0.8,
                "accounting_unit_candidate": "кг",
            }
        ],
        "parser_metadata": {
            "upload_status": "Проверить",
            "row_status": "Распознано",
            "review_flags": [],
            "item_corrections": {},
        },
        "parser_notes": [],
    }

    result = apply_reference_mapping_to_payload(
        payload,
        products=[{"Наименование": "Кефир", "Код": "01-00017", "Ед. изм.": "л"}],
        packages=[
            {
                "ID": "0-00800",
                "Фасовка в документе": "800 г",
                "Коэффициент пересчета": 0.8,
                "Единица учета в УС": "кг",
                "Активна": "да",
            }
        ],
    )

    item = result["items"][0]
    assert item["product_found"] == "Да"
    assert item["us_product_name"] == "Кефир"
    assert item["us_unit"] == "кг"
    assert item["quantity_us"] == 4.0
    assert item.get("correction", "") == ""


def test_reference_mapping_marks_missing_product_and_package():
    payload = {
        "items": [
            {
                "line_number": 2,
                "name": "НЕИЗВЕСТНЫЙ ПРОДУКТ 333Г",
                "normalized_name_candidate": "Неизвестный продукт",
                "package": {"value": 333, "unit": "г", "raw": "333Г"},
                "quantity": 2,
                "quantity_document": 2,
                "quantity_multiplier": 0.333,
                "accounting_unit_candidate": "кг",
                "correction": "",
            }
        ],
        "parser_metadata": {
            "upload_status": "Проверить",
            "row_status": "Распознано",
            "review_flags": [],
            "item_corrections": {},
        },
        "parser_notes": [],
    }

    result = apply_reference_mapping_to_payload(
        payload,
        products=[{"Наименование": "Кефир", "Код": "01-00017", "Ед. изм.": "л"}],
        packages=[{"Фасовка в документе": "250г", "Коэффициент пересчета": 0.25}],
    )

    item = result["items"][0]
    assert item["product_found"] == "Нет"
    assert item["us_product_name"] == "Неизвестный продукт"
    assert item["correction"] == "Нет в справочнике"
    assert result["parser_metadata"]["upload_status"] == "Требует проверки"
    assert result["parser_metadata"]["row_status"] == "Правка вручную"
    assert len(result["parser_metadata"]["review_flags"]) == 2


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("3900040690/390001001", "3900040690"),
        ("3906406206390601001", "3906406206"),
        ("3900040690390001001", "3900040690"),
        ("77 0123 4567", "7701234567"),
    ],
)
def test_supplier_inn_normalization_extracts_real_inn(raw_value, expected):
    assert normalize_supplier_inn_value(raw_value) == expected


@pytest.mark.parametrize(
    ("case", "mutator", "duplicate", "expected_upload", "expected_row", "correction"),
    [
        ("normal", lambda data: None, "", "Проверить", "Распознано", ""),
        (
            "poor_line",
            lambda data: data["items"][0].update(raw_name="", confidence=0.2),
            "",
            "Требует проверки",
            "Правка вручную",
            "Другое",
        ),
        (
            "not_in_catalog",
            lambda data: data["review_flags"].append(
                {
                    "scope": "item",
                    "line_number": 1,
                    "field": "raw_name",
                    "reason": "Товар отсутствует в справочнике.",
                    "severity": "warning",
                }
            ),
            "",
            "Требует проверки",
            "Правка вручную",
            "Нет в справочнике",
        ),
        (
            "total_mismatch",
            lambda data: data["document"].update(total_with_vat=999),
            "",
            "Требует проверки",
            "Правка вручную",
            "",
        ),
        ("possible_duplicate", lambda data: None, "?", "Требует проверки", "Распознано", ""),
        ("confirmed_duplicate", lambda data: None, "Да", "Не готово", "Распознано", ""),
    ],
)
def test_golden_invoice_scenarios(
    case,
    mutator,
    duplicate,
    expected_upload,
    expected_row,
    correction,
):
    data = _parsed_invoice()
    mutator(data)

    result = normalize_invoice_result(data, duplicate=duplicate)
    payload = to_legacy_invoice_payload(result)

    assert result.upload_status == expected_upload, case
    assert result.row_status == expected_row, case
    assert payload["parser_metadata"]["duplicate"] == duplicate
    if correction:
        assert payload["items"][0]["correction"] == correction


def test_ocr_error_has_deterministic_not_ready_status():
    result = normalize_invoice_result(_parsed_invoice(), ocr_error="provider unavailable")

    assert result.upload_status == "Не готово"
    assert result.row_status == "Ошибка загрузки"
    assert result.item_corrections == {1: "Ошибка OCR"}


@pytest.mark.parametrize("status", ["Не готово", "Требует проверки", "Проверить"])
def test_only_upload_status_can_be_sent_to_accounting(status):
    with pytest.raises(ValueError, match="требуется 'Загрузить'"):
        ensure_upload_status_allows_send(status)

    ensure_upload_status_allows_send("Загрузить")
