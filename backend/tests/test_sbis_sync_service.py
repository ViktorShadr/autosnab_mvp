from app.config import settings
from app.services.sbis_sync_service import (
    _configured_document_types,
    _group_by_document_id,
    _merge_occurrences,
    _normalize_datetime_for_filter,
    _pick_target_attachment,
)


def _event(*attachments):
    return {"Вложение": list(attachments)}


def test_configured_document_types_reads_comma_separated_setting(monkeypatch):
    monkeypatch.setattr(settings, "sbis_document_types", "ДокОтгрВх, СчетВх")
    assert _configured_document_types() == ["ДокОтгрВх", "СчетВх"]


def test_normalize_datetime_for_filter_converts_dots_to_colons():
    # Confirmed against a real production dump: ДатаВремяСоздания uses dots,
    # but the СписокИзменений filter requires colons.
    assert _normalize_datetime_for_filter("12.07.2026 08.43.08") == "12.07.2026 08:43:08"


def test_group_by_document_id_merges_repeated_events():
    documents = [
        {"Идентификатор": "doc-1", "Событие": [{"Название": "Получение"}]},
        {"Идентификатор": "doc-1", "Событие": [{"Название": "Извещение о получении"}]},
        {"Идентификатор": "doc-2", "Событие": [{"Название": "Получение"}]},
    ]

    grouped = _group_by_document_id(documents)

    assert set(grouped.keys()) == {"doc-1", "doc-2"}
    assert len(grouped["doc-1"]) == 2
    merged = _merge_occurrences(grouped["doc-1"])
    assert len(merged["Событие"]) == 2


def test_pick_target_attachment_prefers_xml_over_pdf():
    document = {
        "Номер": "173",
        "Событие": [
            _event(
                {"Служебный": "Нет", "Название": "invoice.pdf", "Файл": {"Имя": "invoice.pdf", "Ссылка": "https://x/1"}},
                {"Служебный": "Нет", "Название": "invoice.xml", "Файл": {"Имя": "invoice.xml", "Ссылка": "https://x/2"}},
                {"Служебный": "Да", "Название": "Извещение", "Файл": {"Имя": "notice.xml", "Ссылка": "https://x/3"}},
            )
        ],
    }

    attachment = _pick_target_attachment(document)

    assert attachment["Файл"]["Ссылка"] == "https://x/2"


def test_pick_target_attachment_skips_empty_link():
    # Confirmed against a real dump: a non-служебный УПД attachment can have
    # an empty Файл.Ссылка even though its Имя is populated.
    document = {
        "Номер": "173",
        "Событие": [
            _event(
                {"Служебный": "Нет", "Название": "УпдДоп", "Файл": {"Имя": "upd.xml", "Ссылка": ""}},
                {"Служебный": "Нет", "Название": "УпдДопПокуп", "Файл": {"Имя": "upd_pokup.xml", "Ссылка": "https://x/real"}},
            )
        ],
    }

    attachment = _pick_target_attachment(document)

    assert attachment["Файл"]["Ссылка"] == "https://x/real"


def test_pick_target_attachment_matches_pdf_by_document_number_when_no_xml():
    # Regression for the multi-PDF-bundle finding: several non-служебный PDFs
    # can exist on one document (счёт, комплект, ведомость, акт) — the one
    # whose own Номер matches the parent Документ.Номер should be preferred.
    document = {
        "Номер": "4166",
        "Событие": [
            _event(
                {"Служебный": "Нет", "Номер": "0", "Название": "ON_SCHETKOMPLEKT.PDF", "Файл": {"Имя": "komplekt.pdf", "Ссылка": "https://x/wrong"}},
                {"Служебный": "Нет", "Номер": "4166", "Название": "ON_SCHET.PDF", "Файл": {"Имя": "schet.pdf", "Ссылка": "https://x/right"}},
            )
        ],
    }

    attachment = _pick_target_attachment(document)

    assert attachment["Файл"]["Ссылка"] == "https://x/right"


def test_pick_target_attachment_returns_none_when_nothing_downloadable():
    document = {
        "Номер": "1",
        "Событие": [_event({"Служебный": "Да", "Название": "Извещение", "Файл": {"Имя": "notice.xml", "Ссылка": "https://x/1"}})],
    }

    assert _pick_target_attachment(document) is None
