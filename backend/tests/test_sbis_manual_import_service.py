from types import SimpleNamespace

import pytest

from app.config import settings
from app.schemas.invoice_review import InvoiceReviewCreateRequest
from app.services import sbis_manual_import_service as import_service
from app.services.sbis_client import SbisAttachmentExpiredError, SbisBinaryResponse, SbisClient
from app.services.sbis_manual_session_service import SbisManualSession


def _event(*attachments):
    return {"Вложение": list(attachments)}


def _xml_document(
    document_id: str, *, document_type="ДокОтгрВх", date_="15.07.2026", recipient_inn="9990001122"
) -> dict:
    return {
        "Идентификатор": document_id,
        "Тип": document_type,
        "Номер": "173",
        "Дата": date_,
        "Название": "Накладная",
        "Сумма": "1200.00",
        "Контрагент": {"СвЮЛ": {"НазваниеПолное": "ООО Ромашка", "ИНН": "1234567890"}},
        "НашаОрганизация": {"СвЮЛ": {"НазваниеПолное": "ООО АвтоСнаб", "ИНН": recipient_inn}},
        "Событие": [
            _event(
                {
                    "Служебный": "Нет",
                    "Название": "invoice.xml",
                    "Файл": {"Имя": "invoice.xml", "Ссылка": "https://disk.sbis.ru/invoice.xml"},
                }
            )
        ],
    }


def _session() -> SbisManualSession:
    return SbisManualSession(login="op", password="pw", account_number=None, last_used_at=0.0)


# --- list_documents ---------------------------------------------------------


def test_list_documents_filters_by_configured_type_and_date_to(monkeypatch):
    monkeypatch.setattr(settings, "sbis_document_types", "ДокОтгрВх,СчетВх")
    documents = [
        _xml_document("doc-in-range", document_type="ДокОтгрВх", date_="15.07.2026"),
        _xml_document("doc-out-of-range", document_type="ДокОтгрВх", date_="20.07.2026"),
        _xml_document("doc-wrong-type", document_type="ДоговорВх", date_="15.07.2026"),
    ]

    def fake_get_changes(self, *, date_from):
        return {"result": {"Документ": documents, "Навигация": {"ЕстьЕще": "Нет"}}}

    monkeypatch.setattr(SbisClient, "get_changes", fake_get_changes)

    session = _session()
    result = import_service.list_documents(session, date_from="2026-07-01", date_to="2026-07-16")

    ids = {doc.sbis_document_id for doc in result.documents}
    assert ids == {"doc-in-range"}
    assert "doc-in-range" in session.documents_cache


def test_list_documents_filters_by_date_from(monkeypatch):
    """СБИС.СписокИзменений filters by change-event time, not the document's
    own `Дата`, so a document dated well before `date_from` can still be
    returned if it had a recent event -- the service must filter it back out."""
    documents = [
        _xml_document("doc-in-range", document_type="ДокОтгрВх", date_="15.07.2026"),
        _xml_document("doc-before-range", document_type="ДокОтгрВх", date_="31.03.2026"),
    ]

    def fake_get_changes(self, *, date_from):
        return {"result": {"Документ": documents, "Навигация": {"ЕстьЕще": "Нет"}}}

    monkeypatch.setattr(SbisClient, "get_changes", fake_get_changes)

    session = _session()
    result = import_service.list_documents(session, date_from="2026-07-10", date_to="2026-07-31")

    ids = {doc.sbis_document_id for doc in result.documents}
    assert ids == {"doc-in-range"}


def test_list_documents_continues_from_cursor_when_truncated(monkeypatch):
    """When СБИС.СписокИзменений has more events than `_MAX_LIST_PAGES` covers
    (confirmed live on a wide date range), list_documents must report a
    resumable `next_cursor` instead of silently dropping later documents --
    and a follow-up call with that cursor must accumulate into the same
    session cache rather than replacing the first page's results."""
    monkeypatch.setattr(import_service, "_MAX_LIST_PAGES", 1)
    page1_doc = _xml_document("doc-page1", date_="10.07.2026")
    page1_doc["ДатаВремяСоздания"] = "10.07.2026 10:00:00"
    page2_doc = _xml_document("doc-page2", date_="12.07.2026")
    page2_doc["ДатаВремяСоздания"] = "12.07.2026 10:00:00"

    def fake_get_changes(self, *, date_from):
        if date_from == "10.07.2026 00:00:00":
            return {"result": {"Документ": [page1_doc], "Навигация": {"ЕстьЕще": "Да"}}}
        return {"result": {"Документ": [page2_doc], "Навигация": {"ЕстьЕще": "Нет"}}}

    monkeypatch.setattr(SbisClient, "get_changes", fake_get_changes)

    session = _session()
    first = import_service.list_documents(session, date_from="2026-07-10", date_to="2026-07-31")

    assert first.truncated is True
    assert first.next_cursor == "10.07.2026 10:00:00"
    assert {doc.sbis_document_id for doc in first.documents} == {"doc-page1"}

    second = import_service.list_documents(
        session, date_from="2026-07-10", date_to="2026-07-31", cursor=first.next_cursor
    )

    assert second.truncated is False
    assert {doc.sbis_document_id for doc in second.documents} == {"doc-page2"}
    assert {"doc-page1", "doc-page2"} <= set(session.documents_cache.keys())


def test_list_documents_computes_attachment_flags(monkeypatch):
    document = _xml_document("doc-1")
    monkeypatch.setattr(
        SbisClient,
        "get_changes",
        lambda self, *, date_from: {"result": {"Документ": [document], "Навигация": {"ЕстьЕще": "Нет"}}},
    )

    result = import_service.list_documents(_session(), date_from="2026-07-01", date_to="2026-07-31")

    summary = result.documents[0]
    assert summary.has_target_attachment is True
    assert summary.attachment_count == 1
    assert summary.counterparty_name == "ООО Ромашка"
    assert summary.counterparty_inn == "1234567890"
    assert summary.recipient_name == "ООО АвтоСнаб"
    assert summary.recipient_inn == "9990001122"


def test_list_documents_exposes_distinct_recipient_orgs(monkeypatch):
    """`НашаОрганизация` (recipient legal entity) must survive into the
    summary so the manual-import page can filter by it -- one SBIS login
    can have access to several of the client's legal entities."""
    documents = [
        _xml_document("doc-org-a", recipient_inn="1110001111"),
        _xml_document("doc-org-b", recipient_inn="2220002222"),
    ]
    monkeypatch.setattr(
        SbisClient,
        "get_changes",
        lambda self, *, date_from: {"result": {"Документ": documents, "Навигация": {"ЕстьЕще": "Нет"}}},
    )

    result = import_service.list_documents(_session(), date_from="2026-07-01", date_to="2026-07-31")

    recipient_inns = {doc.recipient_inn for doc in result.documents}
    assert recipient_inns == {"1110001111", "2220002222"}


def test_list_documents_rejects_inverted_date_range():
    with pytest.raises(ValueError):
        import_service.list_documents(_session(), date_from="2026-07-31", date_to="2026-07-01")


# --- import_document ---------------------------------------------------------


def _canned_payload() -> InvoiceReviewCreateRequest:
    return InvoiceReviewCreateRequest(
        file_id="doc-1",
        supplier="ООО Ромашка",
        invoice_number="173",
        parser_metadata={},
    )


def test_import_document_happy_path(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()
    session.documents_cache = {"doc-1": _xml_document("doc-1")}

    monkeypatch.setattr(
        SbisClient,
        "download_attachment",
        lambda self, url: SbisBinaryResponse(content=b"<xml/>", content_type="text/xml"),
    )
    monkeypatch.setattr(import_service, "parse_fns_invoice_xml", lambda *a, **kw: _canned_payload())
    monkeypatch.setattr(
        import_service, "create_invoice_review", lambda db, payload: SimpleNamespace(id=42)
    )
    captured = {}

    def fake_create_sheet(db, receiving, public_api_base_url, target_spreadsheet_id=None):
        captured["target_spreadsheet_id"] = target_spreadsheet_id
        return {"spreadsheet_url": "https://sheets.example/copy"}

    monkeypatch.setattr(import_service, "create_real_google_sheet_for_review", fake_create_sheet)

    result = import_service.import_document(db=None, session=session, sbis_document_id="doc-1")

    assert result.success is True
    assert result.receiving_id == 42
    assert result.spreadsheet_url == "https://sheets.example/copy"
    assert captured["target_spreadsheet_id"] == "COPY-ID"


def test_import_document_fails_when_target_spreadsheet_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", None)
    session = _session()
    session.documents_cache = {"doc-1": _xml_document("doc-1")}

    result = import_service.import_document(db=None, session=session, sbis_document_id="doc-1")

    assert result.success is False
    assert result.stage == "config"


def test_import_document_fails_when_document_not_in_cache(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()

    result = import_service.import_document(db=None, session=session, sbis_document_id="unknown")

    assert result.success is False
    assert result.stage == "not_found"


def test_import_document_fails_when_no_attachment(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()
    document = _xml_document("doc-1")
    document["Событие"] = [_event({"Служебный": "Да", "Название": "notice", "Файл": {"Имя": "n.xml", "Ссылка": "https://x"}})]
    session.documents_cache = {"doc-1": document}

    result = import_service.import_document(db=None, session=session, sbis_document_id="doc-1")

    assert result.success is False
    assert result.stage == "attachment_missing"


def test_import_document_fails_when_attachment_expired(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()
    session.documents_cache = {"doc-1": _xml_document("doc-1")}

    def fake_download(self, url):
        raise SbisAttachmentExpiredError("expired")

    monkeypatch.setattr(SbisClient, "download_attachment", fake_download)

    result = import_service.import_document(db=None, session=session, sbis_document_id="doc-1")

    assert result.success is False
    assert result.stage == "download"


def test_import_document_fails_when_parse_raises(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()
    session.documents_cache = {"doc-1": _xml_document("doc-1")}

    monkeypatch.setattr(
        SbisClient, "download_attachment", lambda self, url: SbisBinaryResponse(content=b"<bad/>")
    )

    def fake_parse(*args, **kwargs):
        raise ValueError("bad xml")

    monkeypatch.setattr(import_service, "parse_fns_invoice_xml", fake_parse)

    result = import_service.import_document(db=None, session=session, sbis_document_id="doc-1")

    assert result.success is False
    assert result.stage == "parse"


def test_import_document_fails_when_sheet_write_raises(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()
    session.documents_cache = {"doc-1": _xml_document("doc-1")}

    monkeypatch.setattr(
        SbisClient, "download_attachment", lambda self, url: SbisBinaryResponse(content=b"<xml/>")
    )
    monkeypatch.setattr(import_service, "parse_fns_invoice_xml", lambda *a, **kw: _canned_payload())
    monkeypatch.setattr(import_service, "create_invoice_review", lambda db, payload: SimpleNamespace(id=42))

    def fake_create_sheet(*args, **kwargs):
        raise RuntimeError("sheets down")

    monkeypatch.setattr(import_service, "create_real_google_sheet_for_review", fake_create_sheet)

    result = import_service.import_document(db=None, session=session, sbis_document_id="doc-1")

    assert result.success is False
    assert result.stage == "sheet_write"


def test_import_document_never_raises_and_a_later_call_is_unaffected_by_earlier_failure(monkeypatch):
    monkeypatch.setattr(settings, "sbis_manual_import_target_spreadsheet_id", "COPY-ID")
    session = _session()
    session.documents_cache = {
        "doc-fail": _xml_document("doc-fail"),
        "doc-ok": _xml_document("doc-ok"),
    }

    calls = {"n": 0}

    def fake_download(self, url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SbisAttachmentExpiredError("expired")
        return SbisBinaryResponse(content=b"<xml/>")

    monkeypatch.setattr(SbisClient, "download_attachment", fake_download)
    monkeypatch.setattr(import_service, "parse_fns_invoice_xml", lambda *a, **kw: _canned_payload())
    monkeypatch.setattr(import_service, "create_invoice_review", lambda db, payload: SimpleNamespace(id=1))
    monkeypatch.setattr(
        import_service,
        "create_real_google_sheet_for_review",
        lambda *a, **kw: {"spreadsheet_url": "https://sheets.example"},
    )

    first = import_service.import_document(db=None, session=session, sbis_document_id="doc-fail")
    second = import_service.import_document(db=None, session=session, sbis_document_id="doc-ok")

    assert first.success is False
    assert second.success is True
