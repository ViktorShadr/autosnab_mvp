from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas.sbis_manual_import import (
    SbisManualDocumentListResponse,
    SbisManualDocumentSummary,
    SbisManualImportResultResponse,
)
from app.services import sbis_manual_session_service as session_service
from app.services.fns_upd_xml_parser_service import parse_fns_invoice_xml
from app.services.invoice_review_service import create_invoice_review, create_real_google_sheet_for_review
from app.services.sbis_client import SbisApiError, SbisAttachmentExpiredError, SbisAuthError, SbisClient
from app.services.sbis_manual_session_service import SbisManualSession
from app.services.sbis_sync_service import (
    UNSTRUCTURED_EXTENSIONS,
    _attachment_filename,
    _attachment_link,
    _configured_document_types,
    _group_by_document_id,
    _is_service_attachment,
    _iter_attachments,
    _merge_occurrences,
    _next_cursor,
    _parse_unstructured_document,
    _pick_target_attachment,
    _safe_part,
)

_MAX_LIST_PAGES = 30


def login(*, login: str, password: str, account_number: str | None) -> str:
    """Authenticate against SBIS with operator-supplied credentials and open
    a transient manual-import session. Raises ValueError on bad credentials."""
    client = SbisClient(login=login, password=password, account_number=account_number)
    try:
        client._ensure_sid()  # noqa: SLF001 - same fail-fast pattern run_sbis_preflight already uses
    except SbisAuthError as exc:
        raise ValueError(f"Не удалось войти в СБИС: {exc}") from exc
    return session_service.create_session(login=login, password=password, account_number=account_number)


def list_documents(
    session: SbisManualSession, *, date_from: str, date_to: str, cursor: str | None = None
) -> SbisManualDocumentListResponse:
    """List SBIS documents for [date_from, date_to] (both YYYY-MM-DD), filtered
    to the same document types the automatic scheduler already handles.

    СБИС.СписокИзменений is a change feed, not a date-range search: a wide
    period can carry far more change events than `_MAX_LIST_PAGES` covers in
    one call (confirmed live -- a query from January only reached early
    January before hitting the page cap). Pass the `next_cursor` this
    function returns back in as `cursor` to continue from where the previous
    call left off, without re-walking the events already seen."""
    from_dt = datetime.strptime(date_from, "%Y-%m-%d")
    to_bound = datetime.strptime(date_to, "%Y-%m-%d").date()
    if to_bound < from_dt.date():
        raise ValueError("Дата начала периода позже даты окончания.")

    client = SbisClient(login=session.login, password=session.password, account_number=session.account_number)
    current_cursor = cursor or from_dt.strftime("%d.%m.%Y 00:00:00")
    all_raw_documents: list[dict[str, Any]] = []
    pages_fetched = 0
    next_cursor: str | None = None

    for _ in range(_MAX_LIST_PAGES):
        payload = client.get_changes(date_from=current_cursor)
        changes = payload.get("result") or {}
        documents = changes.get("Документ") or []
        all_raw_documents.extend(documents)
        pages_fetched += 1

        advanced_cursor = _next_cursor(documents, current_cursor)
        navigation = changes.get("Навигация") or {}
        has_more = str(navigation.get("ЕстьЕще") or "").strip().casefold() == "да"
        if not documents or not has_more or not advanced_cursor or advanced_cursor == current_cursor:
            break
        current_cursor = advanced_cursor
    else:
        # Loop exhausted _MAX_LIST_PAGES without a natural break -> more events remain.
        next_cursor = current_cursor

    truncated = next_cursor is not None
    grouped = _group_by_document_id(all_raw_documents)
    merged = {doc_id: _merge_occurrences(occurrences) for doc_id, occurrences in grouped.items()}

    allowed_types = set(_configured_document_types())
    summaries: list[SbisManualDocumentSummary] = []
    cache: dict[str, dict[str, Any]] = {}
    for sbis_document_id, doc_payload in merged.items():
        document_type = doc_payload.get("Тип")
        if allowed_types and document_type not in allowed_types:
            continue
        doc_date = _document_date(doc_payload)
        if doc_date and (doc_date > to_bound or doc_date < from_dt.date()):
            continue
        cache[sbis_document_id] = doc_payload
        summaries.append(_build_summary(sbis_document_id, doc_payload))

    summaries.sort(key=lambda item: item.document_date or "", reverse=True)
    # `session` is the same object stored in the session service's internal
    # dict (get_session returns it by reference, not a copy), so mutating it
    # here persists the cache for the subsequent import_document call(s)
    # without needing to thread the opaque token back into this function.
    # A continuation call (cursor given) accumulates into the existing cache
    # instead of discarding what a prior page already found.
    if cursor is None:
        session.documents_cache = cache
    else:
        session.documents_cache.update(cache)
    return SbisManualDocumentListResponse(
        documents=summaries, truncated=truncated, pages_fetched=pages_fetched, next_cursor=next_cursor
    )


def _document_date(payload: dict[str, Any]) -> date | None:
    raw = str(payload.get("Дата") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        return None


def _build_summary(sbis_document_id: str, payload: dict[str, Any]) -> SbisManualDocumentSummary:
    counterparty = payload.get("Контрагент") or {}
    party = counterparty.get("СвЮЛ") or counterparty.get("СвФЛ") or {}
    recipient_party = _recipient_party(payload)
    attachment_count = sum(1 for a in _iter_attachments(payload) if not _is_service_attachment(a))
    return SbisManualDocumentSummary(
        sbis_document_id=sbis_document_id,
        document_type=payload.get("Тип"),
        document_number=payload.get("Номер"),
        document_date=payload.get("Дата"),
        title=payload.get("Название"),
        counterparty_name=party.get("НазваниеПолное") or party.get("Название"),
        counterparty_inn=party.get("ИНН"),
        recipient_name=recipient_party.get("НазваниеПолное") or recipient_party.get("Название"),
        recipient_inn=recipient_party.get("ИНН"),
        amount=payload.get("Сумма"),
        attachment_count=attachment_count,
        has_target_attachment=_pick_target_attachment(payload) is not None,
    )


def _recipient_party(payload: dict[str, Any]) -> dict[str, Any]:
    """`НашаОрганизация` is SBIS's own-organization ("recipient") field on each
    document -- distinct from `Контрагент` (the supplier). One SBIS login can
    have access to several of the client's legal entities, so this is what
    the manual tool filters on (confirmed present in the real 2026-07-20
    production dump)."""
    our_org = payload.get("НашаОрганизация") or {}
    return our_org.get("СвЮЛ") or our_org.get("СвФЛ") or {}


def import_document(
    db: Session, session: SbisManualSession, sbis_document_id: str
) -> SbisManualImportResultResponse:
    """Download, parse, and write one SBIS document to the manual-import
    spreadsheet. Never raises -- every failure path returns success=False
    with a `stage` label so one bad document never aborts a batch."""
    target_spreadsheet_id = settings.sbis_manual_import_target_spreadsheet_id
    if not target_spreadsheet_id:
        return _fail(
            sbis_document_id,
            "config",
            "SBIS_MANUAL_IMPORT_TARGET_SPREADSHEET_ID не настроен — укажите id таблицы-копии.",
        )

    payload = session.documents_cache.get(sbis_document_id)
    if payload is None:
        return _fail(
            sbis_document_id,
            "not_found",
            "Документ не найден в текущем списке — обновите список и попробуйте снова.",
        )

    attachment = _pick_target_attachment(payload)
    if attachment is None:
        return _fail(
            sbis_document_id,
            "attachment_missing",
            "Нет доступного вложения для скачивания (пустая ссылка или все вложения служебные).",
        )

    url = _attachment_link(attachment)
    filename = _attachment_filename(attachment)
    client = SbisClient(login=session.login, password=session.password, account_number=session.account_number)
    try:
        response = client.download_attachment(url)
    except SbisAttachmentExpiredError as exc:
        return _fail(sbis_document_id, "download", f"Ссылка на вложение истекла: {exc}")
    except SbisApiError as exc:
        return _fail(sbis_document_id, "download", str(exc))

    try:
        original_path = _save_binary_manual(sbis_document_id, response.content, filename)
    except OSError as exc:
        return _fail(sbis_document_id, "download", f"Не удалось сохранить вложение: {exc}")

    is_xml = Path(filename).suffix.casefold() == ".xml"
    try:
        if is_xml:
            request_payload = parse_fns_invoice_xml(
                response.content, file_id=sbis_document_id, file_url=str(original_path), provider="sbis"
            )
        elif settings.sbis_parse_unstructured_attachments and Path(filename).suffix.casefold() in UNSTRUCTURED_EXTENSIONS:
            request_payload = _parse_unstructured_document(original_path)
        else:
            return _fail(
                sbis_document_id, "parse", "Формат вложения не поддерживается (не XML и не PDF/изображение)."
            )
    except Exception as exc:  # noqa: BLE001 - one document's parse failure must not abort the batch
        return _fail(sbis_document_id, "parse", str(exc))

    request_payload.parser_metadata["sbis_document_id"] = sbis_document_id
    request_payload.parser_metadata["source_channel"] = "sbis_manual_import"
    request_payload.parser_metadata["imported_by"] = session.login

    try:
        receiving = create_invoice_review(db, request_payload)
    except Exception as exc:  # noqa: BLE001
        return _fail(sbis_document_id, "review_create", str(exc))

    try:
        result = create_real_google_sheet_for_review(
            db, receiving, settings.public_api_base_url, target_spreadsheet_id=target_spreadsheet_id
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(sbis_document_id, "sheet_write", str(exc))

    return SbisManualImportResultResponse(
        sbis_document_id=sbis_document_id,
        success=True,
        receiving_id=receiving.id,
        spreadsheet_url=result.get("spreadsheet_url"),
    )


def _save_binary_manual(sbis_document_id: str, content: bytes, filename: str) -> Path:
    root = Path(settings.sbis_documents_dir) / "manual" / _safe_part(sbis_document_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (_safe_part(Path(filename).stem) or "attachment")
    path = path.with_suffix(Path(filename).suffix or ".bin")
    path.write_bytes(content)
    return path


def _fail(sbis_document_id: str, stage: str, error: str) -> SbisManualImportResultResponse:
    return SbisManualImportResultResponse(
        sbis_document_id=sbis_document_id, success=False, stage=stage, error=error
    )
