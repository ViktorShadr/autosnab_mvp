"""Tests for the hidden technical `Факты фасовки AI` sheet row builder.

See docs/wiki/unit-conversion-rules.md -> "Lilia's answers: source-of-truth,
duplicate rules, packaging_facts delivery (2026-07-25)": Apps Script reads
this sheet by `ID документа`/`ID строки` to build packaging-rule drafts, so
the backend's only job is to project each item's AI-extracted
`packaging_facts`/`packaging_risk_flags` into one row per fact.
"""

from types import SimpleNamespace

from app.services.invoice_review_service import (
    build_packaging_facts_rows,
    _packaging_facts_item_rows,
)


def test_packaging_facts_item_rows_one_row_per_fact_and_risk_flag():
    item = SimpleNamespace(id=42, item_name_from_invoice="10ШТ МЕШКИ ДЛЯ МУСОРА 120Л", item_name_from_order="")
    receiving = SimpleNamespace(id=7)
    row_meta = {
        "raw_name": "10ШТ МЕШКИ ДЛЯ МУСОРА 120Л",
        "packaging_facts": [
            {"type": "count_in_package", "value": 10, "unit": "шт", "source": "10 шт", "confidence": 0.95},
            {"type": "unit_volume", "value": 120, "unit": "л", "source": "120 л", "confidence": 0.9},
        ],
        "packaging_risk_flags": ["dry_weight_unknown"],
    }

    rows = _packaging_facts_item_rows(receiving, item, row_meta)

    assert len(rows) == 3
    assert rows[0]["ID документа"] == 7
    assert rows[0]["ID строки"] == "42"
    assert rows[0]["Наименование товара из документа"] == "10ШТ МЕШКИ ДЛЯ МУСОРА 120Л"
    assert rows[0]["Тип факта"] == "количество вложений"
    assert rows[0]["Значение"] == 10
    assert rows[0]["Единица"] == "шт"
    assert rows[0]["Исходный фрагмент текста"] == "10 шт"
    assert rows[0]["Уверенность AI"] == 0.95
    assert rows[0]["Признак риска"] == "Нет"

    assert rows[1]["Тип факта"] == "объем"
    assert rows[1]["Значение"] == 120

    assert rows[2]["Тип факта"] == "риск"
    assert rows[2]["Признак риска"] == "Да"
    assert rows[2]["Значение"] == ""
    assert "сухой вес" in rows[2]["Комментарий AI"]


def test_packaging_facts_item_rows_empty_when_no_facts_or_risk_flags():
    item = SimpleNamespace(id=1, item_name_from_invoice="x", item_name_from_order="")
    receiving = SimpleNamespace(id=1)

    assert _packaging_facts_item_rows(receiving, item, {}) == []
    assert _packaging_facts_item_rows(
        receiving, item, {"packaging_facts": [], "packaging_risk_flags": []}
    ) == []


def test_packaging_facts_item_rows_falls_back_to_raw_name_when_no_invoice_item_name():
    item = SimpleNamespace(id=5, item_name_from_invoice="", item_name_from_order="")
    receiving = SimpleNamespace(id=3)
    row_meta = {
        "raw_name": "Салфетки 24х24",
        "packaging_facts": [{"type": "length", "value": 24, "unit": "см", "source": "24х24", "confidence": 0.7}],
        "packaging_risk_flags": [],
    }

    rows = _packaging_facts_item_rows(receiving, item, row_meta)

    assert len(rows) == 1
    assert rows[0]["Наименование товара из документа"] == "Салфетки 24х24"
    assert rows[0]["Тип факта"] == "размер"


def test_build_packaging_facts_rows_iterates_items_in_document_order():
    receiving = SimpleNamespace(
        id=99,
        documents=[],
        items=[
            SimpleNamespace(id=1, item_name_from_invoice="A", item_name_from_order=""),
            SimpleNamespace(id=2, item_name_from_invoice="B", item_name_from_order=""),
        ],
    )
    item_meta = [
        {
            "packaging_facts": [
                {"type": "unit_weight", "value": 5, "unit": "кг", "source": "5 кг", "confidence": 0.8}
            ],
            "packaging_risk_flags": [],
        },
        {"packaging_facts": [], "packaging_risk_flags": ["in_brine"]},
    ]

    rows = build_packaging_facts_rows(receiving, item_meta=item_meta, parser_items=[])

    assert len(rows) == 2
    assert rows[0]["ID строки"] == "1"
    assert rows[0]["Тип факта"] == "вес"
    assert rows[1]["ID строки"] == "2"
    assert rows[1]["Тип факта"] == "риск"
    assert rows[1]["Признак риска"] == "Да"


def test_build_packaging_facts_rows_empty_when_items_have_no_facts():
    receiving = SimpleNamespace(
        id=1,
        documents=[],
        items=[SimpleNamespace(id=1, item_name_from_invoice="A", item_name_from_order="")],
    )

    rows = build_packaging_facts_rows(receiving, item_meta=[{}], parser_items=[])

    assert rows == []
