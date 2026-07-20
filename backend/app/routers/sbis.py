from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.models.sbis import SbisDelivery, SbisDocument
from app.schemas.sbis import SbisStatusResponse, SbisSyncResponse
from app.services.sbis_client import SbisApiError
from app.services.sbis_scheduler_service import sbis_scheduler_status, start_sbis_scheduler, stop_sbis_scheduler
from app.services.sbis_sync_service import (
    get_sbis_status,
    retry_failed_sbis_documents,
    retry_sbis_deliveries,
    run_sbis_preflight,
    sync_sbis_documents,
)

router = APIRouter(prefix="/sbis", tags=["sbis"])


def require_sbis_admin(
    x_sbis_api_key: str | None = Header(default=None, alias="X-Sbis-Api-Key"),
    admin_key: str | None = Query(default=None),
) -> None:
    expected = settings.sbis_admin_api_key or settings.bot_api_shared_secret
    if not expected:
        return
    supplied = x_sbis_api_key or admin_key or ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-Sbis-Api-Key.")


@router.get("/status", response_model=SbisStatusResponse)
def status(db: Session = Depends(get_db), _admin: None = Depends(require_sbis_admin)):
    return get_sbis_status(db)


@router.get("/scheduler/status")
def scheduler_status(_admin: None = Depends(require_sbis_admin)):
    return sbis_scheduler_status()


@router.get("/preflight")
def preflight(_admin: None = Depends(require_sbis_admin)):
    return run_sbis_preflight()


@router.post("/sync", response_model=SbisSyncResponse)
def sync(
    create_google_sheet: bool = Query(default=True),
    db: Session = Depends(get_db),
    _admin: None = Depends(require_sbis_admin),
):
    try:
        return sync_sbis_documents(db, create_google_sheet=create_google_sheet)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SbisApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/retry")
def retry_failed(
    create_google_sheet: bool = Query(default=True),
    db: Session = Depends(get_db),
    _admin: None = Depends(require_sbis_admin),
):
    try:
        documents = retry_failed_sbis_documents(db, create_google_sheet=create_google_sheet)
        deliveries = retry_sbis_deliveries(db)
        return {"documents": documents, "deliveries": deliveries}
    except SbisApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/dead-letter")
def dead_letter(db: Session = Depends(get_db), _admin: None = Depends(require_sbis_admin)):
    documents = (
        db.query(SbisDocument)
        .filter(SbisDocument.status == "dead_letter")
        .order_by(SbisDocument.updated_at.desc())
        .limit(200)
        .all()
    )
    deliveries = (
        db.query(SbisDelivery)
        .filter(SbisDelivery.status == "dead_letter")
        .order_by(SbisDelivery.updated_at.desc())
        .limit(200)
        .all()
    )
    return {
        "documents": [
            {
                "id": item.id,
                "sbis_document_id": item.sbis_document_id,
                "document_type": item.document_type,
                "document_number": item.document_number,
                "error": item.error_text,
                "updated_at": item.updated_at,
            }
            for item in documents
        ],
        "deliveries": [
            {
                "id": item.id,
                "document_id": item.sbis_document_id,
                "delivery_type": item.delivery_type,
                "attempts": item.attempts,
                "error": item.last_error,
                "updated_at": item.updated_at,
            }
            for item in deliveries
        ],
    }


@router.post("/dead-letter/retry-all")
def retry_all_dead_letters(
    create_google_sheet: bool = Query(default=True),
    db: Session = Depends(get_db),
    _admin: None = Depends(require_sbis_admin),
):
    documents = retry_failed_sbis_documents(
        db, create_google_sheet=create_google_sheet, include_dead_letter=True, force=True
    )
    deliveries = retry_sbis_deliveries(db, include_dead_letter=True, force=True)
    return {"documents": documents, "deliveries": deliveries}


@router.post("/dead-letter/{document_id}/retry")
def retry_dead_letter_document(
    document_id: int,
    create_google_sheet: bool = Query(default=True),
    db: Session = Depends(get_db),
    _admin: None = Depends(require_sbis_admin),
):
    documents = retry_failed_sbis_documents(
        db,
        create_google_sheet=create_google_sheet,
        include_dead_letter=True,
        force=True,
        document_id=document_id,
    )
    deliveries = retry_sbis_deliveries(db, include_dead_letter=True, force=True, document_id=document_id)
    return {"documents": documents, "deliveries": deliveries}


@router.post("/scheduler/start")
def scheduler_start(_admin: None = Depends(require_sbis_admin)):
    started = start_sbis_scheduler()
    return {"started": started}


@router.post("/scheduler/stop")
def scheduler_stop(_admin: None = Depends(require_sbis_admin)):
    stop_sbis_scheduler()
    return {"stopped": True}
