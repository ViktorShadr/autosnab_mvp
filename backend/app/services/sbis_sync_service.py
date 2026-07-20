from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.receiving import Receiving
from app.models.sbis import SbisArtifact, SbisDelivery, SbisDocument, SbisLease, SbisSyncState
from app.schemas.invoice_review import InvoiceReviewCreateRequest, RecognizedInvoiceItem
from app.schemas.receiving import CompareInvoiceRequest, InvoiceItemIn
from app.services.document_extraction_service import extract_invoice_document
from app.services.fns_upd_xml_parser_service import parse_fns_invoice_xml
from app.services.invoice_review_service import (
    create_invoice_review,
    create_real_google_sheet_for_review,
    update_invoice_review,
)
from app.services.receiving_service import compare_invoice
from app.services.sbis_client import SbisApiError, SbisAttachmentExpiredError, SbisBinaryResponse, SbisClient

UNSTRUCTURED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
RETRY_STATUSES = {"failed", "content_unavailable"}
MANUAL_RETRY_STATUSES = RETRY_STATUSES | {"dead_letter"}
DELIVERY_RETRY_STATUSES = {"pending", "failed"}
DELIVERY_TYPES = {"google_sheets"}
_SYNC_LOCK = threading.Lock()
_SYNC_OWNER_ID = uuid4().hex
_SYNC_LEASE_NAME = "sbis_sync"
_ACCOUNT_KEY = "default"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PermanentSbisDocumentError(ValueError):
    pass


def get_sbis_status(db: Session) -> dict[str, Any]:
    state = _get_or_create_state(db, _ACCOUNT_KEY)
    failed_count = db.query(SbisDocument).filter(SbisDocument.status.in_(MANUAL_RETRY_STATUSES)).count()
    delivery_queue_size = (
        db.query(SbisDelivery)
        .filter(SbisDelivery.status.in_(DELIVERY_RETRY_STATUSES | {"in_progress", "dead_letter"}))
        .count()
    )
    dead_letter_count = db.query(SbisDocument).filter(SbisDocument.status == "dead_letter").count()
    delivery_dead_letter_count = db.query(SbisDelivery).filter(SbisDelivery.status == "dead_letter").count()
    return {
        "enabled": settings.sbis_integration_enabled,
        "configured": bool(settings.sbis_login and settings.sbis_password),
        "last_sync_at": state.last_sync_at.isoformat() if state.last_sync_at else None,
        "cursor_present": bool(state.last_datetime_from),
        "last_error": state.last_error,
        "scheduler_enabled": settings.sbis_scheduler_enabled,
        "sync_interval_seconds": settings.sbis_sync_interval_seconds,
        "document_types": _configured_document_types(),
        "retry_queue_size": failed_count,
        "delivery_queue_size": delivery_queue_size,
        "dead_letter_count": dead_letter_count,
        "delivery_dead_letter_count": delivery_dead_letter_count,
    }


def run_sbis_preflight() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ready: bool, detail: str, *, required: bool = True) -> None:
        checks.append({"name": name, "ready": ready, "required": required, "detail": detail})

    add(
        "integration_enabled",
        settings.sbis_integration_enabled,
        "Интеграция включена" if settings.sbis_integration_enabled else "Установите SBIS_INTEGRATION_ENABLED=true",
    )
    add(
        "credentials",
        bool(settings.sbis_login and settings.sbis_password),
        "Логин/пароль заданы" if settings.sbis_login and settings.sbis_password else "Заполните SBIS_LOGIN и SBIS_PASSWORD",
    )
    storage_ready, storage_detail = _check_document_storage()
    add("document_storage", storage_ready, storage_detail)
    if settings.google_sheets_enabled:
        sheet_configured = bool(settings.google_target_spreadsheet_id and settings.google_target_sheet_name)
        add(
            "google_sheets",
            sheet_configured,
            "Целевая Google-таблица настроена" if sheet_configured else "Заполните GOOGLE_TARGET_SPREADSHEET_ID и GOOGLE_TARGET_SHEET_NAME",
        )
    else:
        add("google_sheets", True, "Google Sheets отключён настройкой", required=False)

    if settings.sbis_integration_enabled and settings.sbis_login and settings.sbis_password:
        try:
            SbisClient()._ensure_sid()  # noqa: SLF001 - preflight diagnostic only
            add("auth", True, "Аутентификация в СБИС прошла успешно")
        except Exception as exc:  # noqa: BLE001 - preflight reports diagnostics
            add("auth", False, f"Не удалось аутентифицироваться в СБИС: {exc}")

    required_ready = all(item["ready"] for item in checks if item["required"])
    return {"ready": required_ready, "checks": checks, "document_types": _configured_document_types()}


def _check_document_storage() -> tuple[bool, str]:
    root = Path(settings.sbis_documents_dir)
    probe = root / ".sbis-write-test"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, f"Каталог доступен для записи: {root}"
    except OSError as exc:
        return False, f"Каталог недоступен для записи: {exc}"


def _configured_document_types() -> list[str]:
    return [item.strip() for item in (settings.sbis_document_types or "").split(",") if item.strip()]


def sync_sbis_documents(db: Session, *, create_google_sheet: bool = True) -> dict[str, Any]:
    _validate_configuration()
    if not _SYNC_LOCK.acquire(blocking=False):
        return _empty_result(status="busy")
    lease_acquired = False
    try:
        lease_acquired = _acquire_sync_lease(db)
        if not lease_acquired:
            return _empty_result(status="busy")
        return _sync_locked(db, create_google_sheet=create_google_sheet)
    finally:
        if lease_acquired:
            _release_sync_lease(db)
        _SYNC_LOCK.release()


def retry_failed_sbis_documents(
    db: Session,
    *,
    client: SbisClient | None = None,
    create_google_sheet: bool = True,
    include_dead_letter: bool = False,
    force: bool = False,
    document_id: int | None = None,
) -> dict[str, int]:
    client = client or SbisClient()
    counters = {"retried": 0, "recovered": 0, "failed": 0}
    statuses = MANUAL_RETRY_STATUSES if include_dead_letter else RETRY_STATUSES
    query = db.query(SbisDocument).filter(SbisDocument.status.in_(statuses))
    if document_id is not None:
        query = query.filter(SbisDocument.id == document_id)
    candidates = query.order_by(SbisDocument.updated_at.asc()).limit(max(1, settings.sbis_retry_batch_size)).all()
    now = _utcnow()
    for document in candidates:
        metadata = _metadata(document)
        if not force and not _retry_due(metadata, now):
            continue
        if force and document.status == "dead_letter":
            _reset_document_retry(db, document)
        counters["retried"] += 1
        payload = _find_stored_payload(document)
        try:
            if payload is None:
                raise SbisApiError("Исходный payload документа СБИС не сохранён для повторной обработки")
            _process_document(db, client, document, payload, create_google_sheet=create_google_sheet)
            counters["recovered"] += 1
        except Exception as exc:  # noqa: BLE001 - retry queue must persist diagnostics
            _record_failure(db, document, exc)
            counters["failed"] += 1
    return counters


def retry_sbis_deliveries(
    db: Session,
    *,
    include_dead_letter: bool = False,
    force: bool = False,
    document_id: int | None = None,
) -> dict[str, int]:
    counters = {"retried": 0, "recovered": 0, "failed": 0}
    statuses = set(DELIVERY_RETRY_STATUSES) | {"in_progress"}
    if include_dead_letter:
        statuses.add("dead_letter")
    query = db.query(SbisDelivery).filter(SbisDelivery.status.in_(statuses))
    if document_id is not None:
        query = query.filter(SbisDelivery.sbis_document_id == document_id)
    deliveries = query.order_by(SbisDelivery.updated_at.asc()).limit(max(1, settings.sbis_retry_batch_size)).all()
    now = _utcnow()
    stale_before = now - timedelta(seconds=max(30, settings.sbis_delivery_stale_seconds))
    for delivery in deliveries:
        if delivery.status == "in_progress" and not force and delivery.updated_at > stale_before:
            continue
        if not force and not _delivery_due(delivery, now):
            continue
        if force and delivery.status == "dead_letter":
            delivery.status = "pending"
            delivery.attempts = 0
            delivery.next_retry_at = None
            delivery.last_error = None
            db.add(delivery)
            db.commit()
        counters["retried"] += 1
        result = _execute_delivery(db, delivery)
        if result["success"]:
            counters["recovered"] += 1
        else:
            counters["failed"] += 1
    return counters


def _sync_locked(db: Session, *, create_google_sheet: bool) -> dict[str, Any]:
    state = _get_or_create_state(db, _ACCOUNT_KEY)
    client = SbisClient()
    result = _empty_result()
    try:
        _reconcile_missing_deliveries(db, create_google_sheet=create_google_sheet)
        delivery_result = retry_sbis_deliveries(db)
        result["deliveries_retried"] = delivery_result["retried"]
        result["deliveries_recovered"] = delivery_result["recovered"]
        result["deliveries_failed"] = delivery_result["failed"]

        retry_result = retry_failed_sbis_documents(db, client=client, create_google_sheet=create_google_sheet)
        result["documents_retried"] = retry_result["retried"]
        result["documents_recovered"] = retry_result["recovered"]
        result["documents_failed"] += retry_result["failed"]

        cursor = state.last_datetime_from or _initial_date_from()
        page_limit = max(1, min(settings.sbis_sync_limit, 500))
        max_pages = max(1, settings.sbis_max_pages_per_sync)

        for _page_number in range(max_pages):
            payload = client.get_changes(date_from=cursor)
            changes = payload.get("result") or {}
            documents = changes.get("Документ") or []
            result["pages_received"] += 1
            result["events_received"] += len(documents)

            grouped = _group_by_document_id(documents)
            for sbis_document_id, occurrences in grouped.items():
                if not sbis_document_id:
                    result["documents_skipped"] += 1
                    continue
                document_payload = _merge_occurrences(occurrences)
                _process_change(
                    db,
                    client,
                    sbis_document_id,
                    document_payload,
                    result,
                    create_google_sheet=create_google_sheet,
                )

            next_cursor = _next_cursor(documents, cursor)
            navigation = changes.get("Навигация") or {}
            has_more = str(navigation.get("ЕстьЕще") or "").strip().casefold() == "да"
            if next_cursor and next_cursor != cursor:
                cursor = next_cursor
                state.last_datetime_from = cursor
                result["next_cursor_present"] = True
                state.last_sync_at = _utcnow()
                state.last_error = None
                db.add(state)
                db.commit()
                _renew_sync_lease(db)
            if not documents or not has_more or next_cursor == cursor:
                break

        state.last_sync_at = _utcnow()
        state.last_error = None
        db.add(state)
        db.commit()
    except Exception as exc:
        db.rollback()
        state = _get_or_create_state(db, _ACCOUNT_KEY)
        state.last_sync_at = _utcnow()
        state.last_error = str(exc)
        db.add(state)
        db.commit()
        raise
    return result


def _reconcile_missing_deliveries(db: Session, *, create_google_sheet: bool) -> None:
    documents = (
        db.query(SbisDocument)
        .filter(SbisDocument.status == "processed", SbisDocument.review_id.is_not(None))
        .order_by(SbisDocument.id.asc())
        .limit(max(1, settings.sbis_retry_batch_size * 4))
        .all()
    )
    for document in documents:
        if create_google_sheet and settings.google_sheets_enabled:
            _ensure_delivery(db, document, "google_sheets")


def _process_change(
    db: Session,
    client: SbisClient,
    sbis_document_id: str,
    document_payload: dict[str, Any],
    result: dict[str, Any],
    *,
    create_google_sheet: bool,
) -> None:
    document_type = document_payload.get("Тип")
    if document_type not in _configured_document_types():
        result["documents_skipped"] += 1
        return
    result["documents_discovered"] += 1
    document = _get_existing_document(db, sbis_document_id)
    if document and document.status in {"processed", "downloaded"}:
        result["documents_skipped"] += 1
        return
    document = document or _new_document(sbis_document_id, document_payload)
    db.add(document)
    db.commit()
    db.refresh(document)
    try:
        outcome = _process_document(
            db, client, document, document_payload, create_google_sheet=create_google_sheet
        )
        result["artifacts_downloaded"] += outcome["artifacts_downloaded"]
        result["deliveries_recovered"] += outcome["deliveries_succeeded"]
        result["deliveries_failed"] += outcome["deliveries_failed"]
        if outcome["processed"]:
            result["documents_processed"] += 1
            if document.review_id and document.review_id not in result["review_ids"]:
                result["review_ids"].append(document.review_id)
        else:
            result["documents_downloaded"] += 1
    except Exception as exc:  # noqa: BLE001 - one bad document must not stop the sync
        _record_failure(db, document, exc)
        result["documents_failed"] += 1


def _process_document(
    db: Session,
    client: SbisClient,
    document: SbisDocument,
    payload: dict[str, Any],
    *,
    create_google_sheet: bool,
) -> dict[str, Any]:
    attachment = _pick_target_attachment(payload)
    if attachment is None:
        raise PermanentSbisDocumentError(
            "Не найдено ни одного скачиваемого неслужебного вложения (Ссылка пуста или все вложения служебные)"
        )
    url = _attachment_link(attachment)
    filename = _attachment_filename(attachment)
    try:
        response = client.download_attachment(url)
    except SbisAttachmentExpiredError as exc:
        raise SbisApiError(str(exc)) from exc
    original_path = _save_binary(document, response, filename)
    is_xml = Path(filename).suffix.casefold() == ".xml"

    request_payload: InvoiceReviewCreateRequest | None = None
    if is_xml:
        request_payload = parse_fns_invoice_xml(
            response.content,
            file_id=document.sbis_document_id,
            file_url=str(original_path),
            provider="sbis",
        )
    elif settings.sbis_parse_unstructured_attachments and Path(filename).suffix.casefold() in UNSTRUCTURED_EXTENSIONS:
        request_payload = _parse_unstructured_document(original_path)

    artifacts_downloaded = 1
    deliveries_succeeded = 0
    deliveries_failed = 0
    if request_payload is not None:
        request_payload.parser_metadata["sbis_document_id"] = document.sbis_document_id
        receiving = _transfer_to_verification(db, document, request_payload)
        document.review_id = receiving.id
        document.status = "processed"
        document.error_text = None
        _clear_retry_metadata(document)
        db.add(document)
        db.commit()
        if create_google_sheet and settings.google_sheets_enabled:
            delivery = _ensure_delivery(db, document, "google_sheets")
            delivery_result = _execute_delivery(db, delivery)
            deliveries_succeeded += int(delivery_result["success"])
            deliveries_failed += int(not delivery_result["success"])
    else:
        document.status = "downloaded"
        document.error_text = None
        _clear_retry_metadata(document)
        db.add(document)
        db.commit()
    return {
        "processed": request_payload is not None,
        "artifacts_downloaded": artifacts_downloaded,
        "deliveries_succeeded": deliveries_succeeded,
        "deliveries_failed": deliveries_failed,
    }


def _parse_unstructured_document(path: Path) -> InvoiceReviewCreateRequest:
    extraction = extract_invoice_document(
        str(path), path.name, extraction_method=settings.sbis_unstructured_extraction_method
    )
    if extraction.get("stop_recommended"):
        raise ValueError(extraction.get("error") or "Не удалось разобрать вложение СБИС")
    parsed = extraction.get("payload") or {}
    metadata = parsed.get("parser_metadata") or {}
    metadata["source_channel"] = "sbis"
    metadata["source_path"] = str(path)
    return InvoiceReviewCreateRequest(
        file_id=path.name,
        file_type=path.suffix.lstrip(".") or "file",
        file_url=str(path),
        raw_text=extraction.get("raw_text"),
        request_id=f"SBIS-{path.stem}",
        supplier=parsed.get("supplier"),
        supplier_legal_name=parsed.get("supplier_legal_name"),
        invoice_date=parsed.get("invoice_date"),
        invoice_number=parsed.get("invoice_number"),
        document_number=parsed.get("document_number"),
        venue=parsed.get("venue"),
        delivery_address=parsed.get("delivery_address"),
        document_form=parsed.get("document_form"),
        supplier_inn=parsed.get("supplier_inn"),
        shipper=parsed.get("shipper"),
        consignee=parsed.get("consignee"),
        recipient=parsed.get("recipient"),
        trade_point=parsed.get("trade_point"),
        warehouse=parsed.get("warehouse"),
        basis=parsed.get("basis"),
        total_sum=parsed.get("total_sum"),
        items=[RecognizedInvoiceItem(**item) for item in parsed.get("items") or []],
        parser_metadata=metadata,
    )


def _transfer_to_verification(db: Session, document: SbisDocument, payload: InvoiceReviewCreateRequest) -> Receiving:
    if document.review_id:
        existing = db.get(Receiving, document.review_id)
        if existing is not None:
            return existing
    target = _find_order_receiving(db, payload)
    if target is None:
        return create_invoice_review(db, payload)
    if not target.order_items:
        return update_invoice_review(db, target.id, payload)
    compare_payload = CompareInvoiceRequest(
        invoice_number=payload.invoice_number,
        invoice_date=payload.invoice_date,
        supplier_legal_name=payload.supplier_legal_name or payload.supplier,
        items=[
            InvoiceItemIn(name=item.name, quantity=item.quantity, unit=item.unit, price=item.price, comment=item.comment)
            for item in payload.items
        ],
    )
    return compare_invoice(db, target.id, compare_payload)


def _find_order_receiving(db: Session, payload: InvoiceReviewCreateRequest) -> Receiving | None:
    candidates = _order_candidates(payload.basis, payload.parser_metadata)
    if not candidates:
        return None
    receivings = db.query(Receiving).filter(Receiving.order_number.in_(candidates)).all()
    for receiving in receivings:
        if receiving.order_items:
            return receiving
    return None


def _order_candidates(basis: str | None, metadata: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for value in (basis, metadata.get("order_number"), metadata.get("purchase_order_number")):
        text = str(value or "").strip()
        if not text:
            continue
        result.add(text)
        result.update(re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9._/-]{2,}", text))
    return result


def _ensure_delivery(db: Session, document: SbisDocument, delivery_type: str) -> SbisDelivery:
    if delivery_type not in DELIVERY_TYPES:
        raise ValueError(f"Неизвестный тип доставки СБИС: {delivery_type}")
    delivery = (
        db.query(SbisDelivery)
        .filter(SbisDelivery.sbis_document_id == document.id, SbisDelivery.delivery_type == delivery_type)
        .first()
    )
    if delivery is None:
        delivery = SbisDelivery(sbis_document_id=document.id, delivery_type=delivery_type, status="pending")
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
    return delivery


def _execute_delivery(db: Session, delivery: SbisDelivery) -> dict[str, Any]:
    if delivery.status == "succeeded":
        return {"success": True}
    document = db.get(SbisDocument, delivery.sbis_document_id)
    if document is None:
        _record_delivery_failure(db, delivery, ValueError("Документ СБИС не найден"))
        return {"success": False}
    delivery.attempts += 1
    delivery.status = "in_progress"
    delivery.next_retry_at = None
    delivery.last_error = None
    db.add(delivery)
    db.commit()
    try:
        if delivery.delivery_type == "google_sheets":
            result = _deliver_google_sheet(db, document)
        else:
            raise ValueError(f"Неизвестный тип доставки: {delivery.delivery_type}")
        delivery = db.get(SbisDelivery, delivery.id) or delivery
        delivery.status = "succeeded"
        delivery.last_error = None
        delivery.next_retry_at = None
        delivery.completed_at = _utcnow()
        delivery.result_json = json.dumps(result or {}, ensure_ascii=False, default=str)
        db.add(delivery)
        db.commit()
        return {"success": True}
    except Exception as exc:  # noqa: BLE001 - delivery remains recoverable
        _record_delivery_failure(db, delivery, exc)
        return {"success": False}


def _deliver_google_sheet(db: Session, document: SbisDocument) -> dict[str, Any]:
    if not document.review_id:
        raise ValueError("Для документа СБИС не создана карточка проверки")
    receiving = db.get(Receiving, document.review_id)
    if receiving is None:
        raise ValueError("Карточка проверки СБИС не найдена")
    return create_real_google_sheet_for_review(db, receiving, settings.public_api_base_url)


def _record_delivery_failure(db: Session, delivery: SbisDelivery, exc: Exception) -> None:
    db.rollback()
    delivery = db.get(SbisDelivery, delivery.id) or delivery
    attempts = max(1, int(delivery.attempts or 0))
    delivery.status = "dead_letter" if attempts >= settings.sbis_retry_max_attempts else "failed"
    delivery.last_error = str(exc)
    delivery.next_retry_at = _utcnow() + timedelta(
        seconds=settings.sbis_retry_base_delay_seconds * (2 ** max(0, attempts - 1))
    )
    db.add(delivery)
    db.commit()


def _delivery_due(delivery: SbisDelivery, now: datetime) -> bool:
    return delivery.next_retry_at is None or delivery.next_retry_at <= now


def _reset_document_retry(db: Session, document: SbisDocument) -> None:
    metadata = _metadata(document)
    metadata.pop("retry", None)
    document.raw_metadata_json = json.dumps(metadata, ensure_ascii=False)
    document.status = "failed"
    document.error_text = None
    db.add(document)
    db.commit()


def _save_binary(document: SbisDocument, response: SbisBinaryResponse, filename: str) -> Path:
    root = Path(settings.sbis_documents_dir) / _safe_part(document.sbis_document_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (_safe_part(Path(filename).stem) or "attachment")
    path = path.with_suffix(Path(filename).suffix or ".bin")
    path.write_bytes(response.content)
    return path


def _record_failure(db: Session, document: SbisDocument, exc: Exception) -> None:
    db.rollback()
    document = db.get(SbisDocument, document.id) or document
    metadata = _metadata(document)
    retry = metadata.setdefault("retry", {})
    attempts = int(retry.get("attempts") or 0) + 1
    permanent = isinstance(exc, PermanentSbisDocumentError)
    if permanent:
        attempts = max(attempts, settings.sbis_retry_max_attempts)
    retry["attempts"] = attempts
    retry["permanent"] = permanent
    retry["last_error_at"] = _utcnow().isoformat()
    retry["next_retry_at"] = (
        _utcnow() + timedelta(seconds=settings.sbis_retry_base_delay_seconds * (2 ** max(0, attempts - 1)))
    ).isoformat()
    document.status = "dead_letter" if attempts >= settings.sbis_retry_max_attempts else "content_unavailable"
    document.error_text = str(exc)
    document.raw_metadata_json = json.dumps(metadata, ensure_ascii=False)
    db.add(document)
    db.commit()


def _retry_due(metadata: dict[str, Any], now: datetime) -> bool:
    value = (metadata.get("retry") or {}).get("next_retry_at")
    if not value:
        return True
    try:
        return datetime.fromisoformat(value) <= now
    except ValueError:
        return True


def _clear_retry_metadata(document: SbisDocument) -> None:
    metadata = _metadata(document)
    metadata.pop("retry", None)
    document.raw_metadata_json = json.dumps(metadata, ensure_ascii=False)


def _metadata(document: SbisDocument) -> dict[str, Any]:
    try:
        value = json.loads(document.raw_metadata_json or "{}")
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _find_stored_payload(document: SbisDocument) -> dict[str, Any] | None:
    metadata = _metadata(document)
    return metadata.get("payload")


def _acquire_sync_lease(db: Session) -> bool:
    now = _utcnow()
    expires_at = now + timedelta(seconds=max(60, settings.sbis_sync_lease_seconds))
    lease = db.query(SbisLease).filter(SbisLease.name == _SYNC_LEASE_NAME).first()
    if lease is None:
        try:
            db.add(SbisLease(name=_SYNC_LEASE_NAME, owner_id=_SYNC_OWNER_ID, expires_at=expires_at))
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
    updated = (
        db.query(SbisLease)
        .filter(
            SbisLease.name == _SYNC_LEASE_NAME,
            or_(SbisLease.expires_at <= now, SbisLease.owner_id == _SYNC_OWNER_ID),
        )
        .update({SbisLease.owner_id: _SYNC_OWNER_ID, SbisLease.expires_at: expires_at}, synchronize_session=False)
    )
    db.commit()
    return updated == 1


def _renew_sync_lease(db: Session) -> None:
    expires_at = _utcnow() + timedelta(seconds=max(60, settings.sbis_sync_lease_seconds))
    updated = (
        db.query(SbisLease)
        .filter(SbisLease.name == _SYNC_LEASE_NAME, SbisLease.owner_id == _SYNC_OWNER_ID)
        .update({SbisLease.expires_at: expires_at}, synchronize_session=False)
    )
    db.commit()
    if updated != 1:
        raise RuntimeError("Потеряна блокировка синхронизации СБИС")


def _release_sync_lease(db: Session) -> None:
    try:
        db.rollback()
        db.query(SbisLease).filter(
            SbisLease.name == _SYNC_LEASE_NAME, SbisLease.owner_id == _SYNC_OWNER_ID
        ).update({SbisLease.expires_at: _utcnow()}, synchronize_session=False)
        db.commit()
    except Exception:  # noqa: BLE001 - an expired lease is self-healing
        db.rollback()


def _validate_configuration() -> None:
    if not settings.sbis_integration_enabled:
        raise ValueError("Интеграция СБИС выключена")
    if not settings.sbis_login or not settings.sbis_password:
        raise ValueError("Заполните SBIS_LOGIN и SBIS_PASSWORD")


def _empty_result(*, status: str = "ok") -> dict[str, Any]:
    return {
        "status": status,
        "pages_received": 0,
        "events_received": 0,
        "documents_discovered": 0,
        "documents_processed": 0,
        "documents_downloaded": 0,
        "documents_skipped": 0,
        "documents_failed": 0,
        "documents_retried": 0,
        "documents_recovered": 0,
        "deliveries_retried": 0,
        "deliveries_recovered": 0,
        "deliveries_failed": 0,
        "artifacts_downloaded": 0,
        "review_ids": [],
        "next_cursor_present": False,
    }


def _get_or_create_state(db: Session, account_key: str) -> SbisSyncState:
    state = db.query(SbisSyncState).filter(SbisSyncState.account_key == account_key).first()
    if state is None:
        state = SbisSyncState(account_key=account_key)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _get_existing_document(db: Session, sbis_document_id: str) -> SbisDocument | None:
    return db.query(SbisDocument).filter(SbisDocument.sbis_document_id == sbis_document_id).first()


def _new_document(sbis_document_id: str, payload: dict[str, Any]) -> SbisDocument:
    counterparty = payload.get("Контрагент") or {}
    party = counterparty.get("СвЮЛ") or counterparty.get("СвФЛ") or {}
    metadata = {"payload": payload}
    return SbisDocument(
        sbis_document_id=sbis_document_id,
        document_type=payload.get("Тип"),
        document_number=payload.get("Номер"),
        document_date=payload.get("Дата"),
        counterparty_inn=party.get("ИНН"),
        counterparty_name=party.get("НазваниеПолное") or party.get("Название"),
        status="discovered",
        raw_metadata_json=json.dumps(metadata, ensure_ascii=False),
    )


def _group_by_document_id(documents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        document_id = document.get("Идентификатор")
        if not document_id:
            continue
        grouped.setdefault(document_id, []).append(document)
    return grouped


def _merge_occurrences(occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    """СБИС repeats one document once per related event; merge all Событие[] together."""
    merged = dict(occurrences[0])
    events: list[dict[str, Any]] = []
    for occurrence in occurrences:
        events.extend(occurrence.get("Событие") or [])
    merged["Событие"] = events
    return merged


def _iter_attachments(document: dict[str, Any]):
    for event in document.get("Событие", []) or []:
        yield from (event.get("Вложение", []) or [])


def _is_service_attachment(attachment: dict[str, Any]) -> bool:
    return str(attachment.get("Служебный", "")).strip().casefold() == "да"


def _attachment_filename(attachment: dict[str, Any]) -> str:
    file_obj = attachment.get("Файл") or {}
    return str(file_obj.get("Имя") or attachment.get("Название") or "")


def _attachment_link(attachment: dict[str, Any]) -> str | None:
    file_obj = attachment.get("Файл") or {}
    link = file_obj.get("Ссылка")
    return link or None


def _pick_target_attachment(document: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [a for a in _iter_attachments(document) if not _is_service_attachment(a)]
    xml_candidates = [a for a in candidates if _attachment_filename(a).casefold().endswith(".xml") and _attachment_link(a)]
    if xml_candidates:
        return xml_candidates[0]
    pdf_candidates = [
        a for a in candidates if Path(_attachment_filename(a)).suffix.casefold() in UNSTRUCTURED_EXTENSIONS and _attachment_link(a)
    ]
    if not pdf_candidates:
        return None
    document_number = str(document.get("Номер") or "").strip()
    matched = [a for a in pdf_candidates if document_number and str(a.get("Номер") or "").strip() == document_number]
    return (matched or pdf_candidates)[0]


def _next_cursor(documents: list[dict[str, Any]], previous_cursor: str) -> str | None:
    latest: str | None = None
    for document in documents:
        raw = document.get("ДатаВремяСоздания")
        if raw:
            latest = raw
    if not latest:
        return None
    normalized = _normalize_datetime_for_filter(latest)
    return normalized if normalized != previous_cursor else None


def _normalize_datetime_for_filter(value: str) -> str:
    """SBIS renders ДатаВремяСоздания with dots as the time separator
    ("12.07.2026 08.43.08"), but the СписокИзменений filter requires colons
    ("12.07.2026 08:43:08") — confirmed against a real production dump."""
    date_part, _, time_part = value.strip().partition(" ")
    if not time_part:
        return value.strip()
    return f"{date_part} {time_part.replace('.', ':')}"


def _initial_date_from() -> str:
    since = _utcnow() - timedelta(days=max(1, settings.sbis_initial_sync_days_back))
    return since.strftime("%d.%m.%Y %H:%M:%S")


def _safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-zА-Яа-я0-9._-]+", "_", value).strip("._")[:160]
