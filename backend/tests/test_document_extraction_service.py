from pathlib import Path

from app.services.document_extraction_service import _read_mineru_output


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
