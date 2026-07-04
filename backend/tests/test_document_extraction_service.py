from pathlib import Path
import sys

from app.services import document_extraction_service
from app.services.document_extraction_service import (
    _build_mineru_command,
    _normalize_mineru_payload,
    _read_mineru_output,
)


def test_read_mineru_output_prefers_json(tmp_path: Path):
    output_dir = tmp_path / "mineru-out"
    output_dir.mkdir()
    (output_dir / "result.json").write_text('{"raw_text": "hello", "pages": 2}', encoding="utf-8")
    (output_dir / "result.md").write_text("# ignored", encoding="utf-8")

    result = _read_mineru_output(output_dir)

    assert result == {"raw_text": "hello", "pages": 2}


def test_read_mineru_output_joins_markdown_when_json_missing(tmp_path: Path):
    output_dir = tmp_path / "mineru-out"
    output_dir.mkdir()
    (output_dir / "page_1.md").write_text("first page", encoding="utf-8")
    (output_dir / "page_2.txt").write_text("second page", encoding="utf-8")

    result = _read_mineru_output(output_dir)

    assert result == "first page\n\nsecond page"


def test_read_mineru_output_combines_real_cli_content_list_with_markdown(tmp_path: Path):
    output_dir = tmp_path / "mineru-out"
    result_dir = output_dir / "invoice" / "auto"
    result_dir.mkdir(parents=True)
    (result_dir / "invoice_model.json").write_text(
        '[{"layout_dets": [], "page_info": {"page_no": 0}}]',
        encoding="utf-8",
    )
    (result_dir / "invoice_content_list.json").write_text(
        '[{"type": "text", "text": "Invoice", "page_idx": 0}]',
        encoding="utf-8",
    )
    (result_dir / "invoice.md").write_text("# Invoice\n\nItem 10.00", encoding="utf-8")

    result = _read_mineru_output(output_dir)

    assert result == {
        "markdown": "# Invoice\n\nItem 10.00",
        "content_list": [{"type": "text", "text": "Invoice", "page_idx": 0}],
        "pages": 1,
    }


def test_build_mineru_command_uses_active_python_and_preserves_paths(monkeypatch):
    monkeypatch.setattr(document_extraction_service.settings, "mineru_command", None)

    command = _build_mineru_command(
        "/tmp/invoice with spaces.jpg",
        "/tmp/mineru output",
    )

    assert command == [
        sys.executable,
        "-m",
        "mineru.cli.client",
        "-p",
        "/tmp/invoice with spaces.jpg",
        "-o",
        "/tmp/mineru output",
        "-b",
        "pipeline",
        "-l",
        "cyrillic",
    ]


def test_normalize_mineru_content_list_extracts_upd_header_and_item():
    result = _normalize_mineru_payload(
        {
            "markdown": "Универсальный передаточный документ",
            "content_list": [
                {
                    "type": "table",
                    "table_body": """
                    <table>
                      <tr>
                        <td>Общество с ограниченной ответственностью "ФРукТы АРИфА"</td>
                        <td>ИНН/КПП продавца 3900040690/390001001</td>
                        <td>Универсальный передаточный документ, №1928 от 23 июня 2026 г.</td>
                      </tr>
                      <tr>
                        <td>Документ составлен на</td>
                        <td>1Еноки вес Всero к оплате (9)</td>
                        <td></td>
                        <td>kr</td>
                        <td>3.140</td>
                        <td>650.00</td>
                        <td>5 2041.00 6 Без акциза 2041.00</td>
                      </tr>
                    </table>
                    """,
                    "page_idx": 0,
                }
            ],
            "pages": 1,
        },
        "invoice.jpg",
    )

    assert result["supplier"] == 'ООО "ФРУКТЫ АРИФА"'
    assert result["supplier_inn"] == "3900040690"
    assert result["invoice_number"] == "1928"
    assert result["total_sum"] == 2041.0
    assert result["items"] == [
        {
            "name": "Еноки вес",
            "quantity": 3.14,
            "unit": "кг",
            "price": 650.0,
            "sum": 2041.0,
            "vat": None,
            "vat_percent": None,
            "vat_sum": None,
            "comment": None,
            "confidence": None,
        }
    ]


def test_extract_invoice_document_google_ocr_forces_ocr(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda _file_path, _filename: {
            "provider": "google_drive_ocr",
            "payload": {"supplier": "OCR Supplier"},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda _file_path, _filename: {
            "provider": "mineru",
            "payload": {"supplier": "MinerU Supplier"},
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="google_ocr",
    )

    assert result["provider"] == "google_drive_ocr"
    assert result["selected_method"] == "google_ocr"


def test_extract_invoice_document_hybrid_falls_back_to_ocr(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda _file_path, _filename: {
            "provider": "mineru",
            "payload": {"supplier": None, "items": []},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda _file_path, _filename: {
            "provider": "google_drive_ocr",
            "payload": {"supplier": "OCR Supplier", "items": [{"name": "Item"}]},
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="hybrid",
    )

    assert result["provider"] == "google_drive_ocr"
    assert result["selected_method"] == "hybrid"


def test_extract_invoice_document_mineru_returns_manual_review_instead_of_500(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda _file_path, _filename: {
            "provider": "mineru",
            "payload": {"supplier": None, "items": []},
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="mineru",
    )

    assert result["provider"] == "manual_review_fallback"
    assert result["selected_method"] == "mineru"
    assert result["error"]
    assert result["payload"]["parser_provider"] == "manual_review_empty_sheet"
