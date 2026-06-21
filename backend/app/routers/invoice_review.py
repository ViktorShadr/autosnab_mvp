import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.models.accounting import AccountingExport
from app.models.receiving import Receiving
from app.schemas.invoice_review import (
    ConfirmSendToIikoRequest,
    InvoiceReviewCreateRequest,
    InvoiceReviewResponse,
    InvoiceReviewUpdateRequest,
    RecognizedInvoiceItem,
    SyncSheetAndConfirmRequest,
)
from app.services.invoice_review_service import (
    build_apps_script_sample,
    build_iiko_preview,
    build_review_csv,
    build_review_sheet,
    create_real_google_sheet_for_review,
    confirm_and_send_to_iiko,
    create_invoice_review,
    save_review_csv,
    sync_sheet_and_confirm_to_iiko,
    update_invoice_review,
    remap_review_with_iiko_references,
    get_iiko_reference_status,
)
from app.services.ai_invoice_agent_service import extract_invoice_payload_with_fallback
from app.services.ocr_service import OcrConfigurationError, recognize_invoice_image

router = APIRouter(prefix="/invoice-review", tags=["invoice-review"])


@router.post("/upload-photo", response_model=InvoiceReviewResponse)
async def upload_invoice_photo_real_ocr(
    file: UploadFile = File(...),
    venue: str | None = Form(default=None),
    delivery_address: str | None = Form(default=None),
    request_id: str | None = Form(default=None),
    chat_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
    create_google_sheet: bool = Form(default=True),
    public_api_base_url: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    target_dir = Path(settings.uploaded_invoices_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "invoice_upload").name
    file_path = target_dir / safe_name
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        ocr_result = recognize_invoice_image(str(file_path))
    except OcrConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    parsed = extract_invoice_payload_with_fallback(ocr_result["raw_text"], safe_name)
    payload = InvoiceReviewCreateRequest(
        file_id=safe_name,
        file_type=file.content_type or "image",
        file_url=str(file_path),
        raw_text=ocr_result["raw_text"],
        request_id=request_id,
        supplier=parsed.get("supplier"),
        supplier_legal_name=parsed.get("supplier_legal_name"),
        invoice_date=parsed.get("invoice_date"),
        invoice_number=parsed.get("invoice_number"),
        venue=venue or parsed.get("venue"),
        delivery_address=delivery_address or parsed.get("delivery_address"),
        chat_id=chat_id,
        user_id=user_id,
        items=[RecognizedInvoiceItem(**item) for item in parsed.get("items", [])],
    )
    receiving = create_invoice_review(db, payload)
    sheet = build_review_sheet(receiving)
    csv_path = save_review_csv(receiving)
    response = _review_response(receiving, sheet, csv_path)
    response["ocr"] = {
        "provider": ocr_result["provider"],
        "pages": ocr_result.get("pages"),
        "raw_text_length": len(ocr_result.get("raw_text") or ""),
    }
    response["parser_notes"] = parsed.get("parser_notes", [])
    response["parser_provider"] = parsed.get("parser_provider")
    if parsed.get("ai_agent_error"):
        response["ai_agent_error"] = parsed.get("ai_agent_error")
    if create_google_sheet:
        try:
            spreadsheet = create_real_google_sheet_for_review(db, receiving, public_api_base_url or settings.public_api_base_url)
            response["google_spreadsheet_id"] = spreadsheet["spreadsheet_id"]
            response["google_spreadsheet_url"] = spreadsheet["spreadsheet_url"]
        except Exception as exc:  # noqa: BLE001 - external provider errors must be surfaced to user
            response["google_spreadsheet_error"] = str(exc)
    return response


@router.post("/upload", response_model=InvoiceReviewResponse)
def upload_invoice_for_review(payload: InvoiceReviewCreateRequest, db: Session = Depends(get_db)):
    receiving = create_invoice_review(db, payload)
    sheet = build_review_sheet(receiving)
    csv_path = save_review_csv(receiving)
    return _review_response(receiving, sheet, csv_path)


@router.put("/{review_id}", response_model=InvoiceReviewResponse)
def update_review(review_id: int, payload: InvoiceReviewUpdateRequest, db: Session = Depends(get_db)):
    try:
        receiving = update_invoice_review(db, review_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sheet = build_review_sheet(receiving)
    csv_path = save_review_csv(receiving)
    return _review_response(receiving, sheet, csv_path)




@router.get("/iiko/references/status")
def get_iiko_references_status():
    return get_iiko_reference_status()


@router.post("/{review_id}/iiko-auto-map", response_model=InvoiceReviewResponse)
def auto_map_review_iiko_fields(review_id: int, force_refresh: bool = Query(default=False), db: Session = Depends(get_db)):
    try:
        receiving = remap_review_with_iiko_references(db, review_id, force_refresh=force_refresh)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sheet = build_review_sheet(receiving)
    csv_path = save_review_csv(receiving)
    return _review_response(receiving, sheet, csv_path)


@router.get("/{review_id}/sheet")
def get_google_sheet_preview(review_id: int, db: Session = Depends(get_db)):
    receiving = _get_review(db, review_id)
    return build_review_sheet(receiving)


@router.get("/{review_id}/sheet.csv", response_class=PlainTextResponse)
def get_google_sheet_csv(review_id: int, db: Session = Depends(get_db)):
    receiving = _get_review(db, review_id)
    return PlainTextResponse(build_review_csv(receiving), media_type="text/csv; charset=utf-8")


@router.get("/{review_id}/preview")
def get_iiko_send_preview(
    review_id: int,
    target_organization: str | None = None,
    target_warehouse: str | None = None,
    db: Session = Depends(get_db),
):
    receiving = _get_review(db, review_id)
    return build_iiko_preview(receiving, target_organization, target_warehouse)


@router.get("/{review_id}/apps-script", response_class=PlainTextResponse)
def get_apps_script_sample(
    review_id: int,
    public_api_base_url: str = Query("https://YOUR_API_HOST"),
    db: Session = Depends(get_db),
):
    receiving = _get_review(db, review_id)
    return PlainTextResponse(build_apps_script_sample(receiving, public_api_base_url), media_type="text/plain")


@router.post("/{review_id}/google-sheet")
def create_google_sheet_for_review(
    review_id: int,
    public_api_base_url: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    receiving = _get_review(db, review_id)
    try:
        return create_real_google_sheet_for_review(db, receiving, public_api_base_url or settings.public_api_base_url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{review_id}/sync-sheet-and-confirm-send")
def sync_sheet_and_confirm_send(review_id: int, payload: SyncSheetAndConfirmRequest, db: Session = Depends(get_db)):
    try:
        export = sync_sheet_and_confirm_to_iiko(db, review_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "export_id": export.id,
        "review_id": review_id,
        "status": export.status,
        "target_system": export.target_system,
        "payload": json.loads(export.payload_json),
    }


@router.post("/{review_id}/confirm-send")
def confirm_send(review_id: int, payload: ConfirmSendToIikoRequest, db: Session = Depends(get_db)):
    try:
        export = confirm_and_send_to_iiko(db, review_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "export_id": export.id,
        "review_id": review_id,
        "status": export.status,
        "target_system": export.target_system,
        "payload": json.loads(export.payload_json),
    }


@router.get("/exports/iiko")
def list_invoice_review_exports(db: Session = Depends(get_db)):
    exports = (
        db.query(AccountingExport)
        .filter(AccountingExport.target_system == "iiko")
        .order_by(AccountingExport.id.desc())
        .all()
    )
    return {
        "exports": [
            {
                "id": export.id,
                "receiving_id": export.receiving_id,
                "request_id": export.request_id,
                "order_number": export.order_number,
                "status": export.status,
                "error_message": export.error_message,
                "created_at": export.created_at.isoformat() if export.created_at else None,
            }
            for export in exports
        ]
    }


def _get_review(db: Session, review_id: int) -> Receiving:
    receiving = db.get(Receiving, review_id)
    if receiving is None:
        raise HTTPException(status_code=404, detail="Проверка накладной не найдена")
    return receiving


def _review_response(receiving: Receiving, sheet: dict, csv_path: str) -> dict:
    return {
        "review_id": receiving.id,
        "status": sheet["status"],
        "issues": sheet["issues"],
        "spreadsheet_name": sheet["spreadsheet_name"],
        "csv_path": csv_path,
        "next_actions": {
            "open_sheet": f"/api/v1/invoice-review/{receiving.id}/sheet",
            "open_csv": f"/api/v1/invoice-review/{receiving.id}/sheet.csv",
            "create_google_sheet": f"/api/v1/invoice-review/{receiving.id}/google-sheet",
            "apps_script": f"/api/v1/invoice-review/{receiving.id}/apps-script",
            "preview": f"/api/v1/invoice-review/{receiving.id}/preview",
            "confirm_send": f"/api/v1/invoice-review/{receiving.id}/confirm-send",
            "sync_sheet_and_confirm_send": f"/api/v1/invoice-review/{receiving.id}/sync-sheet-and-confirm-send",
        },
    }
