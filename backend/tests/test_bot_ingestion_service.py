import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.models.receiving import Receiving, ReceivingDocument, ReceivingItem, ReceivingItemStatus  # noqa: E402
from app.services.bot_ingestion_service import build_bot_document_summary  # noqa: E402


def test_build_bot_document_summary_uses_stored_header_and_source_files():
    receiving = Receiving(
        request_id="bot-upload-1",
        order_number="INV-42",
        venue="Point",
        supplier="Supplier Display",
    )
    receiving.documents = [
        ReceivingDocument(
            invoice_number="INV-42",
            invoice_date="2026-07-09",
            supplier_legal_name="ООО Тестовый поставщик",
            recognized_items_json=(
                '{"header":{"document_form":"УПД","total_sum":1500.5,"duplicate_indicator":"?",'
                '"parser_metadata":{"source_files":[{"page_number":1},{"page_number":2}]}},"items":[{"name":"A"},{"name":"B"}]}'
            ),
        )
    ]

    summary = build_bot_document_summary(receiving)

    assert summary == {
        "supplier": "ООО Тестовый поставщик",
        "invoice_number": "INV-42",
        "invoice_date": "2026-07-09",
        "document_form": "УПД",
        "total_sum": 1500.5,
        "items_count": 2,
        "pages_count": 2,
        "duplicate_indicator": "?",
        "header_review_notes": None,
    }


def test_build_bot_document_summary_surfaces_document_scope_review_flags():
    """Regression test for the 2026-08-05 live batch test: a result card showed only
    `Сумма` with no explanation for the missing header fields. The document-scope
    (line_number is None) review flags already computed by normalization must be
    threaded into the summary so the Telegram card can explain *why*.
    """
    receiving = Receiving(
        request_id="bot-upload-3",
        order_number="INV-77",
        venue="Point",
        supplier=None,
    )
    receiving.documents = [
        ReceivingDocument(
            invoice_number=None,
            invoice_date=None,
            supplier_legal_name=None,
            recognized_items_json=(
                '{"header":{"total_sum":12840.0,"parser_metadata":{"review_flags":['
                '{"scope":"document","line_number":null,"field":"supplier_name",'
                '"reason":"Наименование поставщика не распознано.","severity":"error"},'
                '{"scope":"document","line_number":null,"field":"document_number",'
                '"reason":"Номер документа не распознан.","severity":"error"},'
                '{"scope":"item","line_number":1,"field":"quantity",'
                '"reason":"Количество отсутствует.","severity":"error"}'
                ']}},"items":[]}'
            ),
        )
    ]

    summary = build_bot_document_summary(receiving)

    assert summary["header_review_notes"] == {
        "supplier_name": "Наименование поставщика не распознано.",
        "document_number": "Номер документа не распознан.",
    }


def test_build_bot_document_summary_falls_back_to_receiving_items_when_json_is_invalid():
    receiving = Receiving(
        request_id="bot-upload-2",
        order_number="INV-99",
        venue="Point",
        supplier="ООО Резерв",
    )
    receiving.documents = [
        ReceivingDocument(
            invoice_number="INV-99",
            invoice_date="2026-07-09",
            supplier_legal_name=None,
            recognized_items_json="{invalid",
        )
    ]
    receiving.items = [
        ReceivingItem(
            item_name_from_invoice="Товар 1",
            received_quantity=1,
            invoice_price=100,
            status=ReceivingItemStatus.manual_review,
        )
    ]

    summary = build_bot_document_summary(receiving)

    assert summary["supplier"] == "ООО Резерв"
    assert summary["invoice_number"] == "INV-99"
    assert summary["items_count"] == 1
    assert summary["pages_count"] == 0
    assert summary["total_sum"] is None
