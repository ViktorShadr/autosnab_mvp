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
        lambda _file_path, _filename, **_kwargs: {
            "provider": "google_drive_ocr",
            "payload": {"supplier": "OCR Supplier"},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda _file_path, _filename, **_kwargs: {
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


def test_extract_invoice_document_openai_collects_evidence_then_parses(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_collect_openai_evidence",
        lambda _file_path, _filename, **_kwargs: {
            "raw_text": "evidence",
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "google_drive_ocr",
            "pages": 1,
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        lambda evidence: {
            "supplier": "OpenAI Supplier",
            "items": [{"name": "Item"}],
            "parser_provider": "openai",
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="openai",
    )

    assert result["provider"] == "openai"
    assert result["selected_method"] == "openai"
    assert result["payload"]["supplier"] == "OpenAI Supplier"
    assert any(log["stage"] == "openai_request_complete" for log in result["pipeline_logs"])


def test_extract_invoice_document_openai_stops_on_empty_evidence(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_collect_openai_evidence",
        lambda _file_path, _filename, **_kwargs: {
            "raw_text": "",
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "manual_review_fallback",
            "pages": 0,
            "structured_document": None,
            "error": "OCR timeout",
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="openai",
    )

    assert result["provider"] == "openai_empty_evidence"
    assert result["stop_recommended"] is True
    assert result["retry_recommended_method"] == "openai"
    assert any(log["stage"] == "openai_skipped_empty_evidence" for log in result["pipeline_logs"])


def test_extract_invoice_document_openai_stops_on_empty_model_payload(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_collect_openai_evidence",
        lambda _file_path, _filename, **_kwargs: {
            "raw_text": "evidence",
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "google_drive_ocr",
            "pages": 1,
            "structured_document": None,
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        lambda evidence: {
            "supplier": None,
            "items": [],
            "parser_provider": "openai",
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="openai",
    )

    assert result["provider"] == "openai"
    assert result["stop_recommended"] is True
    assert result["error"] == "OpenAI parser вернул пустой структурированный JSON."
    assert any(log["stage"] == "openai_request_complete" and log["status"] == "error" for log in result["pipeline_logs"])


def test_extract_invoice_document_openai_stops_on_header_only_payload(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "_collect_openai_evidence",
        lambda _file_path, _filename, **_kwargs: {
            "raw_text": "evidence",
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "google_drive_ocr",
            "pages": 1,
            "structured_document": None,
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        lambda evidence: {
            "supplier": "ООО Поставщик",
            "invoice_number": "123",
            "items": [],
            "parser_provider": "openai",
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="openai",
    )

    assert result["stop_recommended"] is True
    assert result["validation_errors"] == ["товарные строки отсутствуют"]
    assert "неполный результат" in result["error"]


def test_collect_openai_evidence_never_attempts_mineru_when_ocr_succeeds(monkeypatch, tmp_path):
    """Google Drive OCR now runs first; a successful OCR result must return
    immediately without ever touching the slower MinerU provider."""
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")
    attempts = []
    mineru_calls = []
    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": None,
            "transformations": [],
            "quality": {},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda *_args: mineru_calls.append(_args),
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda *_args: {
            "provider": "google_drive_ocr",
            "raw_text": "recognized invoice",
            "pages": 1,
        },
    )

    evidence = document_extraction_service._collect_openai_evidence(
        str(source),
        source.name,
        on_attempt=attempts.append,
    )

    assert evidence["evidence_version"] == "1.0"
    assert evidence["logical_document_id"].startswith("document-")
    completed_attempts = [attempt for attempt in attempts if attempt["status"] != "running"]
    assert [attempt["provider"] for attempt in completed_attempts] == [
        "image_preparation",
        "google_drive_ocr",
    ]
    assert completed_attempts[1]["status"] == "success"
    assert evidence["raw_text"] == "recognized invoice"
    assert mineru_calls == []


def test_collect_openai_evidence_falls_back_to_mineru_after_empty_ocr(monkeypatch, tmp_path):
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")
    attempts = []
    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": None,
            "transformations": [],
            "quality": {},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda *_args: {"provider": "google_drive_ocr", "raw_text": "", "pages": None},
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda *_args: {
            "raw_text": "mineru text",
            "pages": 1,
            "structured_document": None,
            "payload": {"items": [{"name": "x"}]},
        },
    )

    evidence = document_extraction_service._collect_openai_evidence(
        str(source),
        source.name,
        on_attempt=attempts.append,
    )

    completed_attempts = [attempt for attempt in attempts if attempt["status"] != "running"]
    assert [attempt["provider"] for attempt in completed_attempts] == [
        "image_preparation",
        "google_drive_ocr",
        "mineru",
    ]
    assert completed_attempts[1]["status"] == "skipped"
    assert completed_attempts[2]["status"] == "success"
    assert evidence["raw_text"] == "mineru text"
    assert evidence["extraction_method"] == "mineru"


def test_collect_openai_evidence_skips_unhealthy_mineru_after_empty_ocr(monkeypatch, tmp_path):
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")
    attempts = []
    mineru_calls = []
    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": None,
            "transformations": [],
            "quality": {},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda *_args: {"provider": "google_drive_ocr", "raw_text": "", "pages": None},
    )
    monkeypatch.setattr(
        document_extraction_service,
        "mineru_health",
        lambda: {
            "ready": False,
            "reason": "MinerU model cache is incomplete: missing models/TabRec/UnetStructure/unet.onnx",
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda *_args: mineru_calls.append(_args),
    )

    evidence = document_extraction_service._collect_openai_evidence(
        str(source),
        source.name,
        on_attempt=attempts.append,
    )

    completed_attempts = [attempt for attempt in attempts if attempt["status"] != "running"]
    assert [attempt["provider"] for attempt in completed_attempts] == [
        "image_preparation",
        "google_drive_ocr",
        "mineru",
    ]
    assert completed_attempts[2]["status"] == "skipped"
    assert "model cache is incomplete" in completed_attempts[2]["error_message"]
    assert mineru_calls == []
    assert evidence["raw_text"] == ""
    assert any("model cache is incomplete" in error for error in evidence["errors"])
    assert any("не вернули текст" in warning for warning in evidence["consistency_warnings"])


def test_collect_openai_evidence_surfaces_image_quality_warnings(monkeypatch, tmp_path):
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")
    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda *_args, **_kwargs: {
            "prepared_path": None,
            "transformations": ["autocontrast"],
            "quality": {
                "review_reasons": ["На изображении мало текстовых областей после подготовки."],
                "stop_reasons": ["Качество страницы слишком низкое для надежного извлечения."],
            },
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda *_args: {"provider": "google_drive_ocr", "raw_text": "", "pages": None},
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda *_args: {
            "raw_text": "mineru text",
            "pages": 1,
            "structured_document": None,
            "payload": {"items": [{"name": "x"}]},
        },
    )

    evidence = document_extraction_service._collect_openai_evidence(str(source), source.name)

    assert evidence["consistency_warnings"] == [
        "Страница 1: На изображении мало текстовых областей после подготовки.",
        "Страница 1: Качество страницы слишком низкое для надежного извлечения.",
    ]


def test_collect_openai_evidence_flags_review_when_ocr_returns_empty_for_image(monkeypatch, tmp_path):
    """When Drive OCR genuinely fails/empties out (confirmed live: the same
    file can exhaust retries and still come back empty), the image itself
    still counts as evidence, so the pipeline does not stop - but it must not
    look like an ordinary successful run either.
    """
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")
    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": str(source),
            "transformations": [],
            "quality": {},
        },
    )
    monkeypatch.setattr(
        document_extraction_service,
        "mineru_health",
        lambda: {"ready": False, "reason": "MinerU model cache is incomplete"},
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda *_args: {"provider": "google_drive_ocr", "raw_text": "", "pages": None},
    )

    evidence = document_extraction_service._collect_openai_evidence(str(source), source.name)

    assert evidence["raw_text"] == ""
    assert any("не вернули текст" in warning for warning in evidence["consistency_warnings"])
    assert document_extraction_service._evidence_has_content(evidence) is True


def test_multipage_openai_merges_pages_before_single_parse(monkeypatch, tmp_path):
    first = tmp_path / "page-1.jpg"
    second = tmp_path / "page-2.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    parsed_evidence = []

    def fake_collect(path, filename, **_kwargs):
        page = 1 if filename == "page-1.jpg" else 2
        return {
            "evidence_version": "1.0",
            "logical_document_id": f"page-{page}",
            "filename": filename,
            "source_type": "image",
            "ocr_used": True,
            "extraction_method": "google_drive_ocr",
            "raw_text": f"text page {page}",
            "structured_document": {"page": page},
            "pages": 1,
            "page_sources": [
                {
                    "page_number": 1,
                    "filename": filename,
                    "source_type": "image",
                    "original_path": path,
                    "prepared_path": None,
                    "transformations": [],
                    "quality": {},
                }
            ],
            "provider_attempts": [],
            "errors": [],
            "consistency_warnings": [],
            "error": None,
        }

    def fake_parse(evidence):
        parsed_evidence.append(evidence)
        return {
            "supplier": "Supplier",
            "invoice_number": "42",
            "items": [{"name": "First"}, {"name": "Second"}],
            "parser_provider": "openai",
        }

    monkeypatch.setattr(document_extraction_service, "_collect_openai_evidence", fake_collect)
    monkeypatch.setattr(document_extraction_service, "parse_invoice_with_openai", fake_parse)

    result = document_extraction_service.extract_invoice_document_set(
        [str(first), str(second)],
        [first.name, second.name],
        extraction_method="openai",
    )

    assert result["stop_recommended"] is False
    assert len(parsed_evidence) == 1
    evidence = parsed_evidence[0]
    assert evidence["pages"] == 2
    assert "text page 1" in evidence["raw_text"]
    assert "text page 2" in evidence["raw_text"]
    assert [page["page_number"] for page in evidence["page_sources"]] == [1, 2]


def test_page_consistency_warnings_ignore_empty_continuation_headers():
    assert document_extraction_service._page_consistency_warnings(
        [
            {"page_number": 1, "invoice_number": "42", "supplier_inn": "3900040690"},
            {"page_number": 2, "invoice_number": None, "supplier_inn": None},
        ]
    ) == []

    warnings = document_extraction_service._page_consistency_warnings(
        [
            {"page_number": 1, "invoice_number": "42", "supplier_inn": "3900040690"},
            {"page_number": 2, "invoice_number": "43", "supplier_inn": "3900040690"},
        ]
    )
    assert warnings == ["На страницах найдены разные значения номера документа: 42, 43."]


def test_page_consistency_warnings_detect_missing_page_markers():
    warnings = document_extraction_service._page_consistency_warnings(
        [
            {"page_number": 1, "invoice_number": "42", "supplier_inn": "3900040690", "page_marker_current": 1, "page_marker_total": 3},
            {"page_number": 2, "invoice_number": "42", "supplier_inn": "3900040690", "page_marker_current": 3, "page_marker_total": 3},
        ]
    )

    assert warnings == [
        "Маркер страниц документа указывает минимум на 3 стр., но загружено только 2.",
        "В маркерах страниц пропущены страницы: 2.",
    ]


def test_source_image_counts_as_evidence_when_ocr_is_empty(tmp_path):
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")

    assert document_extraction_service._evidence_has_content(
        {
            "raw_text": "",
            "structured_document": None,
            "page_sources": [
                {
                    "source_type": "image",
                    "original_path": str(source),
                }
            ],
        }
    )


def test_extract_invoice_document_hybrid_falls_back_to_ocr(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "mineru_health",
        lambda: {"ready": True, "reason": None},
    )
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
        "mineru_health",
        lambda: {"ready": True, "reason": None},
    )
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


def test_extract_invoice_document_hybrid_skips_unhealthy_mineru_before_fallback(monkeypatch):
    monkeypatch.setattr(
        document_extraction_service,
        "mineru_health",
        lambda: {"ready": False, "reason": "MinerU model cache is incomplete"},
    )
    mineru_calls = []
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_mineru",
        lambda *_args: mineru_calls.append(_args),
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        lambda _file_path, _filename: {
            "provider": "google_drive_ocr",
            "raw_text": "ocr text",
            "payload": {"supplier": "OCR Supplier", "items": [{"name": "Item"}]},
            "parser_notes": [],
        },
    )

    result = document_extraction_service.extract_invoice_document(
        "invoice.jpg",
        "invoice.jpg",
        extraction_method="hybrid",
    )

    assert result["provider"] == "google_drive_ocr"
    assert result["selected_method"] == "hybrid"
    assert result["error"] == "MinerU model cache is incomplete"
    assert mineru_calls == []
    assert any(log["stage"] == "mineru_skipped_unhealthy" for log in result["pipeline_logs"])


def test_low_quality_image_stops_before_ocr_and_openai(monkeypatch, tmp_path):
    source = tmp_path / "blurred-invoice.jpg"
    source.write_bytes(b"image")

    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": str(source),
            "transformations": ["autocontrast"],
            "quality": {
                "stop_recommended": True,
                "stop_reasons": [
                    "Качество страницы слишком низкое для надежного извлечения."
                ],
                "review_reasons": ["Низкая резкость страницы."],
            },
        },
    )

    def unexpected_ocr(*_args, **_kwargs):
        raise AssertionError("OCR must not run after failed quality check")

    def unexpected_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI must not receive a rejected image")

    monkeypatch.setattr(document_extraction_service, "_extract_with_ocr", unexpected_ocr)
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        unexpected_openai,
    )

    result = document_extraction_service.extract_invoice_document(
        str(source),
        source.name,
        extraction_method="openai",
    )

    assert result["provider"] == "image_quality_rejected"
    assert result["stop_recommended"] is True
    assert result["replacement_recommended"] is True
    assert result["error_code"] == "image_quality_rejected"
    assert "После автоматического улучшения" in result["error"]
    assert "не передано на автоматическое распознавание" in result["error"]
    assert "Замените скан или перефотографируйте" in result["error"]
    assert not any(
        log["stage"] == "openai_request_start" for log in result["pipeline_logs"]
    )


def test_multipage_quality_rejection_stops_before_openai(monkeypatch, tmp_path):
    files = [tmp_path / f"page-{index}.jpg" for index in range(1, 4)]
    for file_path in files:
        file_path.write_bytes(b"image")
    collected = []

    def fake_collect(path, filename, **_kwargs):
        page_number = int(filename.removeprefix("page-").removesuffix(".jpg"))
        collected.append(page_number)
        rejected = page_number == 2
        return {
            "evidence_version": "1.0",
            "logical_document_id": f"page-{page_number}",
            "filename": filename,
            "source_type": "image",
            "ocr_used": not rejected,
            "extraction_method": (
                "image_quality_check" if rejected else "google_drive_ocr"
            ),
            "raw_text": "" if rejected else f"text page {page_number}",
            "structured_document": None,
            "pages": 1,
            "page_sources": [
                {
                    "page_number": 1,
                    "filename": filename,
                    "source_type": "image",
                    "original_path": path,
                    "prepared_path": path,
                    "transformations": [],
                    "quality": {
                        "stop_recommended": rejected,
                        "stop_reasons": ["На странице много бликов."]
                        if rejected
                        else [],
                    },
                }
            ],
            "provider_attempts": [],
            "errors": [],
            "consistency_warnings": [],
            "error": None,
        }

    def unexpected_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI must not receive a rejected document set")

    monkeypatch.setattr(document_extraction_service, "_collect_openai_evidence", fake_collect)
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        unexpected_openai,
    )

    result = document_extraction_service.extract_invoice_document_set(
        [str(file_path) for file_path in files],
        [file_path.name for file_path in files],
        extraction_method="openai",
    )

    assert collected == [1, 2]
    assert result["provider"] == "image_quality_rejected"
    assert result["quality_rejections"][0]["page_number"] == 2
    assert "страница 2" in result["error"]


def test_unresolved_upside_down_orientation_stops_before_ocr_and_openai(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "upside-down-invoice.jpg"
    source.write_bytes(b"image")

    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": str(source),
            "transformations": [],
            "quality": {
                "orientation_rotation_detected": 180,
                "orientation_confidence": 1.77,
                "orientation_unresolved": True,
                "orientation_unresolved_reason": (
                    "nonzero_osd_below_confidence"
                ),
                "critical_error_codes": [
                    "critical_orientation_unresolved"
                ],
                "stop_recommended": True,
                "stop_reasons": [
                    "Ориентацию документа определить надёжно не удалось."
                ],
            },
        },
    )

    def unexpected_ocr(*_args, **_kwargs):
        raise AssertionError("OCR must not run for unresolved 180-degree orientation")

    def unexpected_openai(*_args, **_kwargs):
        raise AssertionError(
            "Automatic recognition must not receive unresolved orientation"
        )

    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        unexpected_ocr,
    )
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        unexpected_openai,
    )

    result = document_extraction_service.extract_invoice_document(
        str(source),
        source.name,
        extraction_method="openai",
    )

    assert result["provider"] == "image_quality_rejected"
    assert result["error_code"] == "image_quality_rejected"
    assert result["replacement_recommended"] is True
    assert result["stop_recommended"] is True
    assert not any(
        log["stage"] == "openai_request_start"
        for log in result["pipeline_logs"]
    )


def test_initial_quality_failure_does_not_stop_after_successful_improvement(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "improved-invoice.jpg"
    prepared = tmp_path / "prepared-invoice.jpg"
    source.write_bytes(b"source-image")
    prepared.write_bytes(b"prepared-image")
    ocr_calls = []

    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        lambda _path: {
            "prepared_path": str(prepared),
            "transformations": ["autocontrast", "deskew_+8.00deg"],
            "quality": {
                "original_quality": {
                    "quality_decision": "reject",
                    "stop_recommended": True,
                    "critical_error_codes": ["critical_blur"],
                },
                "prepared_quality": {
                    "quality_decision": "accept",
                    "stop_recommended": False,
                },
                "quality_decision": "accept",
                "stop_recommended": False,
                "stop_reasons": [],
                "review_reasons": [],
                "improvement_successful": True,
                "final_quality_gate_stage": "after_automatic_improvement",
            },
        },
    )

    def fake_ocr(path, _filename):
        ocr_calls.append(path)
        return {
            "provider": "google_drive_ocr",
            "raw_text": "Накладная после улучшения",
            "pages": 1,
            "error": None,
        }

    monkeypatch.setattr(document_extraction_service, "_extract_with_ocr", fake_ocr)

    evidence = document_extraction_service._collect_openai_evidence(
        str(source),
        source.name,
    )

    assert ocr_calls == [str(prepared)]
    assert evidence["raw_text"] == "Накладная после улучшения"
    assert evidence["extraction_method"] == "google_drive_ocr"
    assert evidence["error"] is None
    assert evidence["page_sources"][0]["quality"]["improvement_successful"] is True


def test_image_preparation_failure_stops_before_ocr_and_openai(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "invoice.jpg"
    source.write_bytes(b"image")

    def failed_preparation(_path):
        raise RuntimeError("quality gate crashed")

    def unexpected_ocr(*_args, **_kwargs):
        raise AssertionError("OCR must not run after quality-gate failure")

    def unexpected_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI must not run after quality-gate failure")

    monkeypatch.setattr(
        document_extraction_service,
        "prepare_document_page",
        failed_preparation,
    )
    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        unexpected_ocr,
    )
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        unexpected_openai,
    )

    result = document_extraction_service.extract_invoice_document(
        str(source),
        source.name,
        extraction_method="openai",
    )

    assert result["provider"] == "image_quality_rejected"
    assert result["error_code"] == "image_quality_rejected"
    assert result["stop_recommended"] is True
    assert result["replacement_recommended"] is True
    page_quality = result["evidence"]["page_sources"][0]["quality"]
    assert page_quality["quality_gate_failed"] is True
    assert page_quality["quality_decision"] == "reject"
    assert page_quality["critical_error_codes"] == [
        "critical_quality_gate_failure"
    ]
    assert "не удалось завершить автоматическую проверку" in result[
        "error"
    ].lower()
    assert not any(
        log["stage"] == "openai_request_start"
        for log in result["pipeline_logs"]
    )


def test_critical_original_resolution_stops_before_ocr_after_upscale(
    monkeypatch,
    tmp_path,
):
    from PIL import Image, ImageDraw

    from app.services import (
        document_image_preparation_service as preparation_service,
    )

    source = tmp_path / "critically-small-invoice.jpg"
    image = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(image)
    for y in range(60, 820, 45):
        for x in range(50, 550, 35):
            draw.rectangle((x, y, x + 24, y + 18), fill="black")
    image.save(source, quality=95)

    monkeypatch.setattr(
        preparation_service.settings,
        "uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    monkeypatch.setattr(
        preparation_service,
        "_orientation_analysis",
        lambda _image: preparation_service._empty_orientation_analysis(),
    )
    monkeypatch.setattr(
        preparation_service,
        "_estimate_skew_angle",
        lambda _image: 0.0,
    )
    monkeypatch.setattr(
        preparation_service,
        "_perspective_crop",
        lambda _image: None,
    )

    def unexpected_ocr(*_args, **_kwargs):
        raise AssertionError("OCR must not run for critical original resolution")

    def unexpected_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI must not receive a critically small image")

    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        unexpected_ocr,
    )
    monkeypatch.setattr(
        document_extraction_service,
        "parse_invoice_with_openai",
        unexpected_openai,
    )

    result = document_extraction_service.extract_invoice_document(
        str(source),
        source.name,
        extraction_method="openai",
    )

    page_quality = result["evidence"]["page_sources"][0]["quality"]
    assert result["provider"] == "image_quality_rejected"
    assert result["error_code"] == "image_quality_rejected"
    assert page_quality["original_short_side"] == 600
    assert "critical_low_resolution" in page_quality["critical_error_codes"]
    assert page_quality["quality_decision"] == "reject"
    assert page_quality["stop_recommended"] is True


def test_resolution_below_900_alone_continues_to_ocr(monkeypatch, tmp_path):
    from PIL import Image, ImageDraw

    from app.services import (
        document_image_preparation_service as preparation_service,
    )

    source = tmp_path / "small-but-readable-invoice.jpg"
    image = Image.new("RGB", (820, 1160), "white")
    draw = ImageDraw.Draw(image)
    for y in range(80, 1050, 55):
        for x in range(80, 740, 45):
            draw.rectangle((x, y, x + 25, y + 18), fill="black")
    image.save(source, quality=95)

    monkeypatch.setattr(
        preparation_service.settings,
        "uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    monkeypatch.setattr(
        preparation_service,
        "_orientation_analysis",
        lambda _image: preparation_service._empty_orientation_analysis(),
    )
    monkeypatch.setattr(
        preparation_service,
        "_estimate_skew_angle",
        lambda _image: 0.0,
    )
    monkeypatch.setattr(
        preparation_service,
        "_perspective_crop",
        lambda _image: None,
    )
    ocr_calls = []

    def fake_ocr(path, _filename):
        ocr_calls.append(path)
        return {
            "provider": "google_drive_ocr",
            "raw_text": "Читаемая накладная",
            "pages": 1,
            "error": None,
        }

    monkeypatch.setattr(
        document_extraction_service,
        "_extract_with_ocr",
        fake_ocr,
    )

    evidence = document_extraction_service._collect_openai_evidence(
        str(source),
        source.name,
    )

    page_quality = evidence["page_sources"][0]["quality"]
    assert len(ocr_calls) == 1
    assert page_quality["original_short_side"] == 820
    assert page_quality["warning_codes"] == ["low_resolution"]
    assert page_quality["critical_error_codes"] == []
    assert page_quality["quality_decision"] == "review"
    assert page_quality["stop_recommended"] is False
