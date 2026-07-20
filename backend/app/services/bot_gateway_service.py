"""Bot-facing gateway over the invoice-review pipeline.

Plain async-callable functions with no FastAPI request/response coupling, so
both the HTTP `/bot/*` endpoints and the native Telegram bot (`app.telegram_bot`)
can call the same logic. Mirrors the six `/bot/*` endpoints in
`app.routers.invoice_review`, which now wrap these functions directly.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from threading import Thread
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.models.receiving import Receiving
from app.schemas.invoice_review import (
    BotDocumentSummary,
    BotDraftInfo,
    BotDraftPageResponse,
    BotDraftResetResponse,
    BotDraftStatusResponse,
    BotUploadAcceptedResponse,
    BotUploadStatusResponse,
    PipelineLogEntry,
)
from app.services.bot_ingestion_service import (
    DRAFT_STATUS,
    append_draft_file,
    build_bot_document_summary,
    build_bot_next_actions,
    build_source_metadata,
    classify_bot_file,
    create_upload_journal,
    delete_draft,
    derive_bot_result,
    draft_display_name,
    get_active_draft,
    get_latest_upload_for_chat,
    get_upload_journal,
    list_draft_files,
    update_upload_journal,
)
from app.services.database_health_service import describe_database_write_error
from app.services.upload_trace_service import (
    append_trace_log,
    finalize_trace,
    get_trace,
    initialize_trace,
    set_trace_metadata,
)


def append_draft_page(
    db: Session,
    *,
    chat_id: str,
    source_user_id: str,
    source_username: str | None,
    document_kind: str = "primary_document",
    organization_name: str | None = None,
    point_name: str | None = None,
    filename: str,
    content_type: str | None,
    file_bytes: bytes,
) -> BotDraftPageResponse:
    safe_name = Path(filename or "file").name
    supported_now, reason, _ = classify_bot_file(safe_name, content_type, document_kind=document_kind)
    if not supported_now:
        return BotDraftPageResponse(
            upload_id="",
            status="unsupported_format",
            message=reason or "Формат файла пока не поддерживается.",
            pages_count=0,
            unsupported_reason=reason,
        )

    upload = get_active_draft(db, chat_id)
    if upload is None:
        document_upload_id = f"bot-draft-{uuid4().hex}"
        target_dir = Path(settings.uploaded_invoices_dir) / document_upload_id
        target_dir.mkdir(parents=True, exist_ok=True)
        upload = create_upload_journal(
            db,
            source_channel="telegram_bot",
            document_kind=document_kind,
            user_id=source_user_id,
            username=source_username,
            chat_id=chat_id,
            organization_name=organization_name,
            point_name=point_name,
            original_filename=safe_name,
            file_type=content_type or "application/octet-stream",
            raw_file_path=str(target_dir),
            files_count=0,
            trace_id=None,
            status=DRAFT_STATUS,
        )
    if upload.files_count >= settings.openai_max_image_pages:
        raise ValueError(f"Слишком много страниц в черновике: максимум {settings.openai_max_image_pages}.")

    target_dir = Path(upload.raw_file_path)
    index = upload.files_count + 1
    target = target_dir / f"{index:03d}-{safe_name}"
    target.write_bytes(file_bytes)
    if target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ValueError(f"Файл {safe_name} пустой.")
    if target.stat().st_size > settings.bot_upload_max_file_bytes:
        target.unlink(missing_ok=True)
        raise ValueError(f"Файл {safe_name} превышает лимит {settings.bot_upload_max_file_bytes} байт.")

    upload = append_draft_file(db, upload, filename=safe_name)
    return BotDraftPageResponse(
        upload_id=upload.upload_id,
        status=DRAFT_STATUS,
        message=f"Страница {upload.files_count} добавлена.",
        pages_count=upload.files_count,
        filenames=[draft_display_name(path) for path in list_draft_files(upload)],
    )


def get_draft_status(db: Session, chat_id: str) -> BotDraftStatusResponse:
    upload = get_active_draft(db, chat_id)
    if upload is None:
        return BotDraftStatusResponse(draft=None)
    return BotDraftStatusResponse(
        draft=BotDraftInfo(
            upload_id=upload.upload_id,
            pages_count=upload.files_count,
            filenames=[draft_display_name(path) for path in list_draft_files(upload)],
            organization_name=upload.organization_name,
            point_name=upload.point_name,
        )
    )


def reset_draft(db: Session, chat_id: str) -> BotDraftResetResponse:
    upload = get_active_draft(db, chat_id)
    if upload is None:
        return BotDraftResetResponse(status="no_active_draft", message="Черновика еще нет.")
    delete_draft(db, upload)
    return BotDraftResetResponse(status="reset", message="Черновик очищен.")


def finalize_draft(
    db: Session,
    chat_id: str,
    *,
    create_google_sheet: bool = True,
    extraction_method: str | None = None,
    public_api_base_url: str | None = None,
) -> BotUploadAcceptedResponse:
    upload = get_active_draft(db, chat_id)
    if upload is None or upload.files_count == 0:
        raise ValueError("Сначала пришлите хотя бы одну страницу документа.")
    files = list_draft_files(upload)
    file_paths = [str(path) for path in files]
    file_names = [draft_display_name(path) for path in files]
    file_types = [mimetypes.guess_type(path.name)[0] or "application/octet-stream" for path in files]
    return start_bot_processing(
        db,
        upload,
        file_paths=file_paths,
        file_names=file_names,
        file_types=file_types,
        create_google_sheet=create_google_sheet,
        extraction_method=extraction_method,
        public_api_base_url=public_api_base_url,
    )


def get_latest_upload_status(db: Session, chat_id: str) -> BotUploadStatusResponse | None:
    upload = get_latest_upload_for_chat(db, chat_id)
    if upload is None:
        return None
    return _build_bot_upload_status_response(db, upload)


def get_upload_status(db: Session, upload_id: str) -> BotUploadStatusResponse:
    upload = get_upload_journal(db, upload_id)
    return _build_bot_upload_status_response(db, upload)


def start_bot_processing(
    db: Session,
    upload,
    *,
    file_paths: list[str],
    file_names: list[str],
    file_types: list[str],
    create_google_sheet: bool,
    extraction_method: str | None,
    public_api_base_url: str | None,
) -> BotUploadAcceptedResponse:
    trace_id = f"trace-{upload.upload_id}"
    update_upload_journal(db, upload.upload_id, status="accepted_for_processing", trace_id=trace_id)
    initialize_trace(trace_id)
    set_trace_metadata(
        trace_id,
        upload_id=upload.upload_id,
        source_channel=upload.source_channel,
        document_kind=upload.document_kind,
    )
    append_trace_log(
        trace_id,
        {
            "stage": "job_queued",
            "status": "running",
            "message": "Документ принят в обработку от бота.",
            "details": {
                "upload_id": upload.upload_id,
                "pages": len(file_paths),
                "filenames": file_names,
            },
        },
    )
    thread = Thread(
        target=_process_bot_upload_background,
        kwargs={
            "trace_id": trace_id,
            "upload_id": upload.upload_id,
            "file_paths": file_paths,
            "file_names": file_names,
            "file_types": file_types,
            "create_google_sheet": create_google_sheet,
            "extraction_method": extraction_method,
            "public_api_base_url": public_api_base_url or settings.public_api_base_url,
        },
        daemon=True,
    )
    thread.start()
    return BotUploadAcceptedResponse(
        upload_id=upload.upload_id,
        trace_id=trace_id,
        status="accepted_for_processing",
        message="Документ принят в обработку.",
        source_channel=upload.source_channel,
        document_kind=upload.document_kind,
        files_count=len(file_paths),
    )


def _process_bot_upload_background(
    *,
    trace_id: str,
    upload_id: str,
    file_paths: list[str],
    file_names: list[str],
    file_types: list[str],
    create_google_sheet: bool,
    extraction_method: str | None,
    public_api_base_url: str,
) -> None:
    # Deferred import: `_process_invoice_upload` is the shared extraction/write
    # engine also used by the non-bot web-upload endpoint, so it stays defined
    # in the router module. Importing it lazily here avoids a circular import
    # (the router imports this module's public functions at module load time).
    from app.routers.invoice_review import _process_invoice_upload

    db = SessionLocal()
    try:
        upload = get_upload_journal(db, upload_id)
        update_upload_journal(db, upload_id, status="processing", error_text=None, trace_id=trace_id)
        source_metadata = build_source_metadata(upload)
        response = _process_invoice_upload(
            file_path=file_paths[0],
            file_name=file_names[0],
            file_type="multipage" if len(file_paths) > 1 else file_types[0],
            file_paths=file_paths,
            file_names=file_names,
            file_types=file_types,
            venue=upload.point_name or upload.organization_name,
            delivery_address=None,
            request_id=upload.upload_id,
            chat_id=upload.chat_id,
            user_id=upload.user_id,
            create_google_sheet=create_google_sheet,
            extraction_method=extraction_method,
            public_api_base_url=public_api_base_url,
            db=db,
            upload_trace_id=trace_id,
            source_metadata=source_metadata,
        )
        review_id = response.get("review_id")
        receiving = db.get(Receiving, review_id) if review_id else None
        final_status, _, _, _ = derive_bot_result(response, receiving=receiving)
        update_upload_journal(
            db,
            upload_id,
            status=final_status,
            error_text=response.get("google_spreadsheet_error"),
            trace_id=trace_id,
            review_id=review_id,
        )
    except Exception as exc:  # noqa: BLE001 - background job must surface fatal failures in the journal/trace
        if isinstance(exc, HTTPException):
            error_detail = exc.detail
            error_message = (
                error_detail.get("error_message") or str(error_detail)
                if isinstance(error_detail, dict)
                else str(error_detail)
            )
        else:
            db_hint = describe_database_write_error(exc)
            error_message = db_hint or str(exc)
        append_trace_log(
            trace_id,
            {
                "stage": "job_failed",
                "status": "error",
                "message": "Обработка документа для бота завершилась ошибкой.",
                "details": {"error": error_message},
            },
        )
        update_upload_journal(db, upload_id, status="processing_error", error_text=error_message, trace_id=trace_id)
        finalize_trace(trace_id, error_message=error_message)
    finally:
        db.close()


def _build_bot_upload_status_response(db: Session, upload) -> BotUploadStatusResponse:
    trace = get_trace(upload.trace_id) if upload.trace_id else None
    response = trace.get("result") if trace else None
    receiving = db.get(Receiving, upload.review_id) if upload.review_id else None
    result_code = None
    review_status = None
    duplicate = False
    next_actions = {}
    document_summary = None
    google_spreadsheet_url = None
    google_spreadsheet_error = upload.error_text
    if response:
        result_code, _, duplicate, review_status = derive_bot_result(response, receiving=receiving)
        next_actions = build_bot_next_actions(response)
        google_spreadsheet_url = response.get("google_spreadsheet_url")
        google_spreadsheet_error = response.get("google_spreadsheet_error") or google_spreadsheet_error
    if receiving:
        document_summary = build_bot_document_summary(receiving)
    completed_statuses = {
        "unsupported_format",
        "processing_error",
        "processed",
        "transferred_to_review",
        "requires_review",
        "possible_duplicate",
    }
    return BotUploadStatusResponse(
        upload_id=upload.upload_id,
        trace_id=upload.trace_id,
        status=upload.status,
        message=_bot_status_message(upload.status, upload.error_text),
        completed=bool(trace["completed"]) if trace else upload.status in completed_statuses,
        source_channel=upload.source_channel,
        document_kind=upload.document_kind,
        files_count=upload.files_count,
        original_filename=upload.original_filename,
        organization_name=upload.organization_name,
        point_name=upload.point_name,
        user_id=upload.user_id,
        username=upload.username,
        review_id=upload.review_id,
        review_status=review_status,
        result_code=result_code,
        duplicate=duplicate,
        error_text=upload.error_text,
        uploaded_at=upload.created_at.isoformat() if upload.created_at else None,
        updated_at=upload.updated_at.isoformat() if upload.updated_at else None,
        google_spreadsheet_url=google_spreadsheet_url,
        google_spreadsheet_error=google_spreadsheet_error,
        document_summary=BotDocumentSummary(**document_summary) if document_summary else None,
        pipeline_logs=[PipelineLogEntry(**log) for log in (trace.get("logs") or [])] if trace else [],
        next_actions=next_actions,
    )


def _bot_status_message(status: str, error_text: str | None) -> str:
    if status == "collecting":
        return "Черновик документа собирается."
    if status == "accepted_for_processing":
        return "Документ принят в обработку."
    if status == "processing":
        return "Документ обрабатывается."
    if status == "transferred_to_review":
        return "Документ обработан и передан в модуль проверки данных."
    if status == "requires_review":
        return "Документ обработан, но требует проверки в модуле проверки данных."
    if status == "possible_duplicate":
        return "Документ похож на уже загруженный и требует проверки на дубль."
    if status == "unsupported_format":
        return error_text or "Формат файла пока не поддерживается."
    if status == "processing_error":
        return error_text or "Во время обработки произошла ошибка."
    if status == "processed":
        return "Документ обработан."
    return error_text or "Статус загрузки обновлен."
