from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.receiving import Receiving, ReceivingDocument
from app.services.receiving_backoffice_service import (
    build_discrepancy_analytics,
    build_invoice_html,
    document_to_dict,
)

router = APIRouter(tags=["receiving-backoffice"])


@router.get("/receiving/{receiving_id}/documents")
def list_receiving_documents(receiving_id: int, db: Session = Depends(get_db)):
    receiving = db.get(Receiving, receiving_id)
    if receiving is None:
        raise HTTPException(status_code=404, detail="Приемка не найдена")
    return {
        "receiving_id": receiving.id,
        "order_number": receiving.order_number,
        "documents": [document_to_dict(document) for document in receiving.documents],
    }


@router.get("/documents/history")
def invoice_history(
    supplier: str | None = None,
    venue: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(ReceivingDocument).join(Receiving)
    if supplier:
        query = query.filter(Receiving.supplier == supplier)
    if venue:
        query = query.filter(Receiving.venue == venue)
    documents = query.order_by(ReceivingDocument.created_at.desc()).all()
    return {"documents": [document_to_dict(document) for document in documents]}


@router.get("/documents/{document_id}")
def get_invoice_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(ReceivingDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Накладная не найдена")
    return document_to_dict(document)


@router.get("/documents/{document_id}/view", response_class=HTMLResponse)
def view_invoice_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(ReceivingDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Накладная не найдена")
    return HTMLResponse(build_invoice_html(document))


@router.get("/analytics/discrepancies")
def discrepancy_analytics(db: Session = Depends(get_db)):
    return build_discrepancy_analytics(db)


@router.get("/suppliers/control")
def supplier_control(db: Session = Depends(get_db)):
    analytics = build_discrepancy_analytics(db)
    return {
        "suppliers": analytics["by_supplier"],
        "rules": {
            "ok": "нет значимых расхождений",
            "watch": "есть повторяющиеся расхождения, нужен мониторинг",
            "control_required": "есть критичные расхождения или несовпадение поставщика",
        },
    }
