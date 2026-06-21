import csv
import io
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.accounting import AccountingExport
from app.models.receiving import Receiving, ReceivingDocument, ReceivingItem, ReceivingItemStatus, ReceivingStatus
from app.services.google_sheets_service import create_invoice_review_spreadsheet, serialize_sheet_result
from app.services.iiko_incoming_invoice_service import build_iiko_export_payload, build_incoming_invoice_xml
from app.services.iiko_reference_mapping_service import auto_fill_iiko_fields, get_iiko_reference_context, invalidate_iiko_reference_cache

REQUIRED_FIELDS = {
    "supplier": "поставщик",
    "invoice_date": "дата накладной",
    "invoice_number": "номер накладной",
    "venue": "заведение / точка доставки",
    "items": "товарные позиции",
}


def create_invoice_review(db: Session, payload) -> Receiving:
    supplier = _clean(payload.supplier) or "Поставщик не распознан"
    venue = _clean(payload.venue) or _clean(getattr(payload, "iiko_organization", None)) or "Точка доставки не распознана"
    invoice_number = _clean(payload.invoice_number) or f"INV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    request_id = payload.request_id or f"MVP4-{invoice_number}"

    receiving = Receiving(
        request_id=request_id,
        order_number=invoice_number,
        venue=venue,
        supplier=supplier,
        delivery_address=payload.delivery_address,
        chat_id=payload.chat_id,
        user_id=payload.user_id,
        status=ReceivingStatus.ocr_processed,
        comment="MVP-4: накладная загружена для ручной проверки перед отправкой в iiko",
    )
    db.add(receiving)
    db.flush()

    recognized_items = [_item_payload(item, index) for index, item in enumerate(payload.items, start=1)]
    header_meta = _header_payload(payload)
    mapping_result = auto_fill_iiko_fields(header_meta, recognized_items, supplier_name=supplier, venue=venue)
    header_meta = mapping_result["header"]
    recognized_items = mapping_result["items"]
    if mapping_result.get("notes"):
        header_meta["mapping_notes"] = mapping_result["notes"]
    document = ReceivingDocument(
        receiving_id=receiving.id,
        file_id=payload.file_id,
        file_type=payload.file_type,
        source="invoice_review_mvp4",
        file_url=payload.file_url,
        ocr_status="ocr_processed" if recognized_items else "manual_review",
        raw_text=payload.raw_text,
        recognized_items_json=json.dumps({"header": header_meta, "items": recognized_items}, ensure_ascii=False),
        supplier_legal_name=payload.supplier_legal_name or supplier,
        invoice_number=invoice_number,
        invoice_date=payload.invoice_date,
    )
    db.add(document)

    for index, item in enumerate(payload.items, start=1):
        status = ReceivingItemStatus.accepted if _item_is_complete(item) else ReceivingItemStatus.manual_review
        db.add(
            ReceivingItem(
                receiving_id=receiving.id,
                item_name_from_order=None,
                item_name_from_invoice=item.name,
                ordered_quantity=0,
                received_quantity=item.quantity or 0,
                unit=item.unit or "шт",
                ordered_price=0,
                invoice_price=item.price or 0,
                status=status,
                comment=_build_item_comment(item, index),
            )
        )

    db.commit()
    db.refresh(receiving)
    return receiving


def update_invoice_review(db: Session, receiving_id: int, payload) -> Receiving:
    receiving = _get_receiving(db, receiving_id)
    receiving.venue = payload.venue or getattr(payload, "iiko_organization", None) or receiving.venue
    receiving.supplier = payload.supplier or receiving.supplier
    receiving.delivery_address = payload.delivery_address or receiving.delivery_address

    document = receiving.documents[-1] if receiving.documents else None
    header_meta = _header_payload(payload)
    recognized_items = [_item_payload(item, index) for index, item in enumerate(payload.items, start=1)]
    old_meta = _document_meta(document) if document is not None else {"header": {}, "items": []}
    merged_header = {**old_meta.get("header", {}), **{k: v for k, v in header_meta.items() if v not in (None, "")}}
    # Вариант 3: Google Таблица присылает только бизнес-поля.
    # Старые технические iiko-поля берем из backend metadata и сохраняем до повторного автосопоставления.
    recognized_items = _merge_stored_iiko_metadata(recognized_items, old_meta.get("items") or [])
    mapping_result = auto_fill_iiko_fields(merged_header, recognized_items, supplier_name=payload.supplier or receiving.supplier, venue=payload.venue or receiving.venue)
    merged_header = mapping_result["header"]
    recognized_items = mapping_result["items"]
    if mapping_result.get("notes"):
        merged_header["mapping_notes"] = mapping_result["notes"]
    if document is not None:
        document.invoice_number = payload.invoice_number or document.invoice_number
        document.invoice_date = payload.invoice_date or document.invoice_date
        document.supplier_legal_name = payload.supplier_legal_name or payload.supplier or document.supplier_legal_name
        document.raw_text = payload.raw_text or document.raw_text
        document.recognized_items_json = json.dumps({"header": merged_header, "items": recognized_items}, ensure_ascii=False)
        document.ocr_status = "ocr_processed"
    if payload.invoice_number:
        receiving.order_number = payload.invoice_number

    for item in list(receiving.items):
        db.delete(item)
    db.flush()

    for index, item in enumerate(payload.items, start=1):
        status = ReceivingItemStatus.accepted if _item_is_complete(item) else ReceivingItemStatus.manual_review
        db.add(
            ReceivingItem(
                receiving_id=receiving.id,
                item_name_from_order=None,
                item_name_from_invoice=item.name,
                ordered_quantity=0,
                received_quantity=item.quantity or 0,
                unit=item.unit or "шт",
                ordered_price=0,
                invoice_price=item.price or 0,
                status=status,
                comment=_build_item_comment(item, index),
            )
        )
    receiving.status = ReceivingStatus.ocr_processed
    db.commit()
    db.refresh(receiving)
    return receiving




def get_iiko_reference_status() -> dict:
    context = get_iiko_reference_context(force_refresh=False)
    if context.get("context"):
        refs = context["context"]
        return {
            "status": context.get("status"),
            "cached": context.get("cached", False),
            "counts": {
                "suppliers": len(refs.get("suppliers", [])),
                "products": len(refs.get("products", [])),
                "stores": len(refs.get("stores", [])),
                "units": len(refs.get("units", [])),
                "taxes": len(refs.get("taxes", [])),
            },
        }
    return {"status": context.get("status"), "message": context.get("message")}


def remap_review_with_iiko_references(db: Session, receiving_id: int, force_refresh: bool = False) -> Receiving:
    receiving = _get_receiving(db, receiving_id)
    document = receiving.documents[-1] if receiving.documents else None
    if document is None:
        raise ValueError("Накладная не найдена для автосопоставления")
    if force_refresh:
        invalidate_iiko_reference_cache()
    meta = _document_meta(document)
    header = meta.get("header", {})
    items = meta.get("items", [])
    mapping_result = auto_fill_iiko_fields(header, items, supplier_name=receiving.supplier, venue=receiving.venue)
    header = mapping_result["header"]
    if mapping_result.get("notes"):
        header["mapping_notes"] = mapping_result["notes"]
    document.recognized_items_json = json.dumps({"header": header, "items": mapping_result["items"]}, ensure_ascii=False)
    db.commit()
    db.refresh(receiving)
    return receiving


def build_review_sheet(receiving: Receiving) -> dict:
    """Build the human-facing MVP-4 Google Sheet.

    Правило MVP-4 / вариант 3:
    - пользователь редактирует только бизнес-поля накладной;
    - технические iiko-поля не записываются в Google Таблицу;
    - backend хранит iiko supplier/defaultStore/product/amountUnit/vat/system status в recognized_items_json
      и пересопоставляет их после пользовательских правок.
    """
    document = receiving.documents[-1] if receiving.documents else None
    meta = _document_meta(document)
    header_meta = meta.get("header", {})
    item_meta = meta.get("items", [])
    items = list(receiving.items)
    total_sum = round(sum((item.received_quantity or 0) * (item.invoice_price or 0) for item in items), 2)
    issues = validate_review(receiving)

    mapping_status = "ready" if not issues else "needs_review"
    mapping_error = "; ".join(issues)

    # Лист 1: только понятные бизнес-поля. Их пользователь может проверять и исправлять.
    summary_rows = [
        ["Поле", "Значение", "Кто заполняет", "Комментарий"],
        ["ID проверки", receiving.id, "система", "Не редактировать"],
        ["Статус проверки", mapping_status, "система", mapping_error or "Можно отправлять после проверки бизнес-данных"],
        ["Поставщик", receiving.supplier, "пользователь / OCR", "Исправьте только если OCR распознал неверно"],
        ["Номер накладной", document.invoice_number if document else receiving.order_number, "пользователь / OCR", "Номер документа из накладной"],
        ["Дата накладной", document.invoice_date if document else "", "пользователь / OCR", "Дата из накладной"],
        ["Заведение / точка доставки", receiving.venue, "пользователь / OCR", "Куда относится поставка"],
        ["Склад / подразделение", header_meta.get("display_store") or header_meta.get("iiko_default_store_name") or "", "пользователь, если система не определила", "Обычное название склада/подразделения, не GUID"],
        ["Итоговая сумма", total_sum, "система", "Считается по строкам: количество × цена"],
        ["Комментарий пользователя", header_meta.get("user_comment") or "", "пользователь", "Необязательно"],
    ]

    item_rows = [[
        "№",
        "Статус проверки",
        "Что исправить",
        "Наименование товара",
        "Количество",
        "Ед. изм.",
        "Цена",
        "Сумма",
        "НДС %",
        "НДС сумма",
        "Комментарий пользователя",
    ]]

    # Технические iiko-поля сознательно не добавляются в Google Таблицу.
    # Они остаются в backend metadata: document.recognized_items_json.

    for index, item in enumerate(items, start=1):
        row_meta = item_meta[index - 1] if index - 1 < len(item_meta) else {}
        quantity = item.received_quantity or 0
        price = item.invoice_price or 0
        line_sum = row_meta.get("sum") if row_meta.get("sum") is not None else round(quantity * price, 2)
        vat_percent = row_meta.get("vat_percent") if row_meta.get("vat_percent") is not None else _extract_vat_percent(item.comment)
        vat_sum = row_meta.get("vat_sum") if row_meta.get("vat_sum") is not None else ""
        row_mapping_status = row_meta.get("mapping_status") or "ready"
        row_mapping_error = row_meta.get("mapping_error") or ""
        business_status = "Готово" if row_mapping_status == "ready" and not row_mapping_error else "Нужно проверить"
        item_rows.append([
            row_meta.get("line_number") or index,
            business_status,
            row_mapping_error,
            item.item_name_from_invoice or item.item_name_from_order or "",
            quantity,
            item.unit,
            price,
            line_sum,
            vat_percent,
            vat_sum,
            _user_comment_from_item_comment(item.comment),
        ])

    return {
        "review_id": receiving.id,
        "spreadsheet_name": f"АвтоСнаб MVP-4 Проверка накладной {receiving.order_number}",
        "sheets": {
            "Проверка накладной": summary_rows,
            "Товарные позиции": item_rows,
        },
        "action": {
            "button_label": "Подтвердить и отправить в iiko",
            "method": "POST",
            "endpoint": f"/api/v1/invoice-review/{receiving.id}/confirm-send",
        },
        "status": "ready" if not issues else "needs_review",
        "issues": issues,
    }


def build_review_csv(receiving: Receiving) -> str:
    sheet = build_review_sheet(receiving)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([sheet["spreadsheet_name"]])
    writer.writerow([])
    for title, rows in sheet["sheets"].items():
        writer.writerow([title])
        for row in rows:
            writer.writerow(row)
        writer.writerow([])
    return output.getvalue()


def save_review_csv(receiving: Receiving, base_dir: str = "exports") -> str:
    target_dir = Path(base_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"invoice_review_{receiving.id}.csv"
    path = target_dir / filename
    path.write_text(build_review_csv(receiving), encoding="utf-8-sig")
    return str(path)


def build_iiko_preview(receiving: Receiving, target_organization: str | None = None, target_warehouse: str | None = None, target_organization_id: str | None = None, target_warehouse_id: str | None = None) -> dict:
    document = receiving.documents[-1] if receiving.documents else None
    meta = _document_meta(document)
    header_meta = meta.get("header", {})
    item_meta = meta.get("items", [])
    warehouse = target_warehouse_id or target_warehouse or header_meta.get("iiko_default_store_id") or "Основной склад"
    items = []
    for index, item in enumerate(receiving.items, start=1):
        row_meta = item_meta[index - 1] if index - 1 < len(item_meta) else {}
        if item.status not in {ReceivingItemStatus.rejected, ReceivingItemStatus.crossed_out}:
            quantity = item.received_quantity or 0
            price = item.invoice_price or 0
            line_sum = row_meta.get("sum") if row_meta.get("sum") is not None else round(quantity * price, 2)
            items.append(
                {
                    "num": row_meta.get("line_number") or index,
                    "name": item.item_name_from_invoice or item.item_name_from_order or "",
                    "iikoProductId": row_meta.get("iiko_product_id"),
                    "productArticle": row_meta.get("product_article"),
                    "supplierProduct": row_meta.get("supplier_product"),
                    "supplierProductArticle": row_meta.get("supplier_product_article"),
                    "amount": quantity,
                    "quantity": quantity,
                    "unit": item.unit,
                    "amountUnit": row_meta.get("amount_unit") or item.unit,
                    "price": price,
                    "sum": line_sum,
                    "vatPercent": row_meta.get("vat_percent") if row_meta.get("vat_percent") is not None else _extract_vat_percent(item.comment),
                    "vatSum": row_meta.get("vat_sum"),
                    "store": row_meta.get("store_id") or warehouse,
                    "status": item.status.value,
                    "mappingStatus": row_meta.get("mapping_status") or "ready",
                    "mappingError": row_meta.get("mapping_error"),
                    "comment": item.comment,
                }
            )
    total_sum = round(sum(float(item.get("sum") or 0) for item in items), 2)
    preview = {
        "review_id": receiving.id,
        "target_system": "iiko",
        "target": {
            "organization": target_organization or header_meta.get("iiko_organization") or receiving.venue,
            "organizationId": target_organization_id or header_meta.get("iiko_organization_id"),
            "warehouse": warehouse,
            "defaultStoreId": warehouse,
            "venue": receiving.venue,
        },
        "supplier": {
            "displayName": receiving.supplier,
            "legalName": document.supplier_legal_name if document else None,
            "iikoSupplierId": header_meta.get("iiko_supplier_id"),
        },
        "invoice": {
            "number": document.invoice_number if document else receiving.order_number,
            "documentNumber": header_meta.get("document_number") or (document.invoice_number if document else receiving.order_number),
            "date": document.invoice_date if document else None,
            "incomingDate": header_meta.get("incoming_date") or (document.invoice_date if document else None),
            "dueDate": header_meta.get("due_date"),
            "totalSum": total_sum,
            "files": [doc.file_url or doc.file_id for doc in receiving.documents if doc.file_url or doc.file_id],
        },
        "items": items,
        "statusBeforeSend": receiving.status.value,
        "issues": validate_review(receiving),
        "source": "autosnab_iiko_incoming_invoice_adapter",
    }
    preview["iikoXml"] = build_incoming_invoice_xml(preview)
    return preview


def confirm_and_send_to_iiko(db: Session, receiving_id: int, payload) -> AccountingExport:
    receiving = _get_receiving(db, receiving_id)
    if not payload.approved:
        raise ValueError("Перед отправкой пользователь должен подтвердить проверку накладной")
    issues = validate_review(receiving)
    if issues and not payload.allow_with_warnings:
        raise ValueError("Накладная требует проверки: " + "; ".join(issues))

    preview = build_iiko_preview(
        receiving,
        payload.target_organization,
        payload.target_warehouse,
        payload.target_organization_id,
        payload.target_warehouse_id,
    )
    preview["userConfirmation"] = {
        "approved": payload.approved,
        "approvedBy": payload.approved_by,
        "comment": payload.comment,
        "confirmedAt": datetime.utcnow().isoformat(),
    }
    preview["comment"] = payload.comment or preview.get("comment")

    try:
        export_payload = build_iiko_export_payload(preview, dry_run=payload.dry_run)
        iiko_result = export_payload.get("iikoResult", {})
        if payload.dry_run:
            status = "iiko_xml_prepared"
        elif iiko_result.get("status") == "sent_to_iiko":
            status = "sent_to_iiko"
        else:
            status = "iiko_sent_mock"
        error_message = None
    except Exception as exc:  # noqa: BLE001 - external iiko errors must be persisted
        export_payload = {
            "preview": preview,
            "iikoXml": build_incoming_invoice_xml(preview),
            "iikoResult": {"status": "iiko_error", "error": str(exc)},
            "source": "autosnab_iiko_incoming_invoice_adapter",
        }
        status = "iiko_error"
        error_message = str(exc)

    export = AccountingExport(
        receiving_id=receiving.id,
        request_id=receiving.request_id,
        order_number=receiving.order_number,
        target_system="iiko",
        status=status,
        payload_json=json.dumps(export_payload, ensure_ascii=False),
        error_message=error_message,
    )
    if status == "iiko_error":
        receiving.status = ReceivingStatus.accounting_error
    elif payload.dry_run:
        receiving.status = ReceivingStatus.confirmed_full
    else:
        receiving.status = ReceivingStatus.sent_to_accounting
    receiving.comment = payload.comment or receiving.comment
    db.add(export)
    db.commit()
    db.refresh(export)
    return export


def build_apps_script_sample(receiving: Receiving, public_api_base_url: str = "https://YOUR_API_HOST") -> str:
    endpoint = f"{public_api_base_url.rstrip()}/api/v1/invoice-review/{receiving.id}/sync-sheet-and-confirm-send"
    return f"""function onOpen() {{
  SpreadsheetApp.getUi()
    .createMenu('АвтоСнаб')
    .addItem('👁 Предпросмотр отправки', 'previewInvoiceForIiko')
    .addItem('✅ Отправить в iiko', 'sendInvoiceToIiko')
    .addToUi();
}}

function readSummary_() {{
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const summarySheet = ss.getSheetByName('Проверка накладной');
  const values = summarySheet.getDataRange().getValues();
  const summary = {{}};
  for (let i = 1; i < values.length; i++) {{
    summary[String(values[i][0])] = values[i][1];
  }}
  return summary;
}}

function readItems_() {{
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const itemSheet = ss.getSheetByName('Товарные позиции');
  const itemValues = itemSheet.getDataRange().getValues();
  const items = [];
  for (let i = 1; i < itemValues.length; i++) {{
    const row = itemValues[i];
    if (!row[3]) continue;
    items.push({{
      line_number: Number(row[0] || i),
      name: String(row[3]),
      quantity: Number(row[4]),
      unit: String(row[5] || 'шт'),
      price: Number(row[6]),
      sum: row[7] === '' ? null : Number(row[7]),
      vat_percent: row[8] === '' ? null : Number(row[8]),
      vat_sum: row[9] === '' ? null : Number(row[9]),
      comment: row[10] ? String(row[10]) : null
    }});
  }}
  return items;
}}

function buildPayload_() {{
  const summary = readSummary_();
  return {{
    approved: true,
    dry_run: false,
    allow_with_warnings: false,
    target_organization: String(summary['Заведение / точка доставки'] || ''),
    target_organization_id: null,
    target_warehouse: String(summary['Склад / подразделение'] || ''),
    target_warehouse_id: null,
    approved_by: Session.getActiveUser().getEmail(),
    comment: String(summary['Комментарий пользователя'] || 'Подтверждено из Google Таблицы'),
    supplier: String(summary['Поставщик'] || ''),
    supplier_legal_name: String(summary['Поставщик'] || ''),
    iiko_supplier_id: null,
    invoice_number: String(summary['Номер накладной'] || ''),
    document_number: String(summary['Номер накладной'] || ''),
    invoice_date: String(summary['Дата накладной'] || ''),
    incoming_date: String(summary['Дата накладной'] || ''),
    venue: String(summary['Заведение / точка доставки'] || ''),
    iiko_default_store_id: null,
    items: readItems_()
  }};
}}

function previewInvoiceForIiko() {{
  const payload = buildPayload_();
  const total = payload.items.reduce((sum, item) => sum + (Number(item.sum) || Number(item.quantity) * Number(item.price)), 0);
  SpreadsheetApp.getUi().alert(
    'Предпросмотр отправки в iiko',
    'Поставщик: ' + payload.supplier + '\n' +
    'Точка: ' + payload.venue + '\n' +
    'Склад: ' + payload.target_warehouse + '\n' +
    'Накладная: ' + payload.invoice_number + ' от ' + payload.invoice_date + '\n' +
    'Позиций: ' + payload.items.length + '\n' +
    'Итого: ' + total.toFixed(2),
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}}

function sendInvoiceToIiko() {{
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sendSheet = ss.getSheetByName('Отправка в iiko');
  const url = '{endpoint}';
  const payload = buildPayload_();
  const confirm = SpreadsheetApp.getUi().alert(
    'Отправить в iiko?',
    'Будут отправлены только бизнес-поля из Google Таблицы. Backend сам возьмет/обновит технические iiko-поля из базы и справочников. Отправить накладную ' + payload.invoice_number + '?',
    SpreadsheetApp.getUi().ButtonSet.YES_NO
  );
  if (confirm !== SpreadsheetApp.getUi().Button.YES) {{
    return;
  }}
  const response = UrlFetchApp.fetch(url, {{
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  }});
  const statusText = response.getResponseCode() + ': ' + response.getContentText();
  sendSheet.getRange('B11').setValue(statusText);
  sendSheet.getRange('B12').setValue(new Date());
  ss.toast(statusText, 'Статус отправки в iiko');
}}
"""


def create_real_google_sheet_for_review(db: Session, receiving: Receiving, public_api_base_url: str | None = None) -> dict:
    sheet = build_review_sheet(receiving)
    script = build_apps_script_sample(receiving, public_api_base_url or "https://YOUR_API_HOST")
    result = create_invoice_review_spreadsheet(receiving, sheet, script)
    export = AccountingExport(
        receiving_id=receiving.id,
        request_id=receiving.request_id,
        order_number=receiving.order_number,
        target_system="google_sheets",
        status="spreadsheet_created",
        payload_json=serialize_sheet_result(result),
    )
    db.add(export)
    db.commit()
    return result


def sync_sheet_and_confirm_to_iiko(db: Session, receiving_id: int, payload) -> AccountingExport:
    from app.schemas.invoice_review import InvoiceReviewUpdateRequest, RecognizedInvoiceItem

    receiving = _get_receiving(db, receiving_id)
    if payload.items:
        update_payload = InvoiceReviewUpdateRequest(
            raw_text=None,
            supplier=payload.supplier,
            supplier_legal_name=payload.supplier_legal_name,
            iiko_supplier_id=payload.iiko_supplier_id,
            invoice_date=payload.invoice_date,
            invoice_number=payload.invoice_number,
            document_number=payload.document_number,
            incoming_date=payload.incoming_date,
            due_date=payload.due_date,
            venue=payload.venue or payload.target_organization,
            delivery_address=payload.delivery_address,
            iiko_default_store_id=payload.iiko_default_store_id or payload.target_warehouse_id or payload.target_warehouse,
            iiko_organization=payload.iiko_organization or payload.target_organization,
            iiko_organization_id=payload.iiko_organization_id or payload.target_organization_id,
            items=[RecognizedInvoiceItem(**item.model_dump()) for item in payload.items],
        )
        receiving = update_invoice_review(db, receiving_id, update_payload)
    return confirm_and_send_to_iiko(db, receiving.id, payload)


def validate_review(receiving: Receiving) -> list[str]:
    document = receiving.documents[-1] if receiving.documents else None
    meta = _document_meta(document)
    header = meta.get("header", {})
    item_meta = meta.get("items", [])
    issues = []
    if not receiving.supplier or receiving.supplier == "Поставщик не распознан":
        issues.append("не распознан поставщик")
    if not receiving.venue or receiving.venue == "Точка доставки не распознана":
        issues.append("не распознана точка доставки / организация")
    if document is None:
        issues.append("не загружена накладная")
    else:
        if not document.invoice_number:
            issues.append("не распознан номер накладной")
        if not document.invoice_date:
            issues.append("не распознана дата накладной")
    if header.get("iiko_mapping_status") == "needs_review":
        issues.append("требуется проверка сопоставления шапки накладной: " + (header.get("iiko_mapping_error") or "нет уверенного совпадения"))
    if not header.get("iiko_supplier_id"):
        issues.append("не указан поставщик iiko/supplier id")
    if not (header.get("iiko_default_store_id") or header.get("target_warehouse")):
        issues.append("не указан склад iiko/defaultStore")
    if not receiving.items:
        issues.append("нет товарных позиций")
    for index, item in enumerate(receiving.items, start=1):
        row_meta = item_meta[index - 1] if index - 1 < len(item_meta) else {}
        item_name = item.item_name_from_invoice or item.item_name_from_order or f"строка {index}"
        if not item_name:
            issues.append("есть позиция без наименования")
        if row_meta.get("mapping_status") == "needs_review":
            issues.append(f"требуется проверка сопоставления по позиции: {item_name} ({row_meta.get('mapping_error') or 'нет уверенного совпадения'})")
        if not (row_meta.get("iiko_product_id") or row_meta.get("product_article")):
            issues.append(f"нет iiko product/productArticle по позиции: {item_name}")
        if not (row_meta.get("line_number") or index):
            issues.append(f"нет num по позиции: {item_name}")
        if (item.received_quantity or 0) <= 0:
            issues.append(f"некорректное количество по позиции: {item_name}")
        if (item.invoice_price or 0) < 0:
            issues.append(f"некорректная цена по позиции: {item_name}")
        line_sum = row_meta.get("sum")
        if line_sum is None:
            line_sum = round((item.received_quantity or 0) * (item.invoice_price or 0), 2)
        if line_sum is None or float(line_sum) < 0:
            issues.append(f"нет или некорректная sum по позиции: {item_name}")
    return list(dict.fromkeys(issues))


def _get_receiving(db: Session, receiving_id: int) -> Receiving:
    receiving = db.get(Receiving, receiving_id)
    if receiving is None:
        raise ValueError("Проверка накладной не найдена")
    return receiving


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _header_payload(payload) -> dict[str, Any]:
    return {
        "iiko_supplier_id": getattr(payload, "iiko_supplier_id", None),
        "document_number": getattr(payload, "document_number", None),
        "incoming_date": getattr(payload, "incoming_date", None),
        "due_date": getattr(payload, "due_date", None),
        "iiko_default_store_id": getattr(payload, "iiko_default_store_id", None),
        "iiko_organization": getattr(payload, "iiko_organization", None),
        "iiko_organization_id": getattr(payload, "iiko_organization_id", None),
    }


def _item_payload(item, index: int | None = None) -> dict:
    quantity = item.quantity or 0
    price = item.price or 0
    calculated_sum = round(quantity * price, 2)
    return {
        "line_number": item.line_number or index,
        "name": item.name,
        "iiko_product_id": item.iiko_product_id,
        "product_article": item.product_article,
        "supplier_product": item.supplier_product,
        "supplier_product_article": item.supplier_product_article,
        "quantity": quantity,
        "unit": item.unit,
        "amount_unit": item.amount_unit or item.unit,
        "price": price,
        "sum": item.sum if item.sum is not None else calculated_sum,
        "vat": item.vat,
        "vat_percent": item.vat_percent if item.vat_percent is not None else _parse_vat_percent(item.vat),
        "vat_sum": item.vat_sum,
        "store_id": item.store_id,
        "mapping_status": getattr(item, "mapping_status", None),
        "mapping_error": getattr(item, "mapping_error", None),
        "comment": item.comment,
        "confidence": item.confidence,
    }



def _merge_stored_iiko_metadata(new_items: list[dict[str, Any]], old_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    technical_keys = {
        "iiko_product_id",
        "product_article",
        "supplier_product",
        "supplier_product_article",
        "amount_unit",
        "store_id",
        "mapping_status",
        "mapping_error",
        "iiko_product_name",
        "iiko_product_match_confidence",
        "iiko_unit_name",
        "iiko_unit_match_confidence",
    }
    old_by_line = {str(item.get("line_number") or index): item for index, item in enumerate(old_items, start=1)}
    merged = []
    for index, item in enumerate(new_items, start=1):
        line = str(item.get("line_number") or index)
        old = old_by_line.get(line, {})
        result = dict(item)
        for key in technical_keys:
            if result.get(key) in (None, "") and old.get(key) not in (None, ""):
                result[key] = old.get(key)
        if result.get("vat_percent") is None and old.get("vat_percent") is not None:
            result["vat_percent"] = old.get("vat_percent")
        if result.get("vat_sum") is None and old.get("vat_sum") is not None:
            result["vat_sum"] = old.get("vat_sum")
        merged.append(result)
    return merged

def _document_meta(document: ReceivingDocument | None) -> dict[str, Any]:
    if document is None or not document.recognized_items_json:
        return {"header": {}, "items": []}
    try:
        data = json.loads(document.recognized_items_json)
        if isinstance(data, list):
            return {"header": {}, "items": data}
        if isinstance(data, dict):
            return {"header": data.get("header") or {}, "items": data.get("items") or []}
    except json.JSONDecodeError:
        return {"header": {}, "items": []}
    return {"header": {}, "items": []}


def _item_is_complete(item) -> bool:
    return bool(item.name) and (item.quantity or 0) > 0 and (item.price or 0) >= 0


def _build_item_comment(item, index: int | None = None) -> str | None:
    parts = []
    if item.vat is not None:
        parts.append(f"НДС: {item.vat}")
    if item.vat_percent is not None:
        parts.append(f"vatPercent: {item.vat_percent}")
    if item.vat_sum is not None:
        parts.append(f"vatSum: {item.vat_sum}")
    if item.iiko_product_id:
        parts.append(f"iiko_product_id: {item.iiko_product_id}")
    if item.product_article:
        parts.append(f"productArticle: {item.product_article}")
    if item.confidence is not None:
        parts.append(f"confidence: {item.confidence}")
    if item.comment:
        parts.append(item.comment)
    if item.sum is not None:
        expected = round((item.quantity or 0) * (item.price or 0), 2)
        try:
            incoming_sum = float(Decimal(str(item.sum)))
            if abs(incoming_sum - expected) > 0.01:
                parts.append(f"Расхождение суммы: распознано {incoming_sum}, рассчитано {expected}")
        except (InvalidOperation, ValueError):
            parts.append("Сумма распознана некорректно")
    return "; ".join(parts) if parts else None



def _user_comment_from_item_comment(comment: str | None) -> str:
    """Return only the human comment, hiding technical markers saved in comments."""
    if not comment:
        return ""
    hidden_prefixes = ("НДС:", "vatPercent:", "vatSum:", "iiko_product_id:", "productArticle:", "confidence:")
    parts = []
    for part in comment.split(";"):
        text = part.strip()
        if not text:
            continue
        if text.startswith(hidden_prefixes):
            continue
        parts.append(text)
    return "; ".join(parts)

def _extract_vat_percent(comment: str | None) -> float | str | None:
    if not comment:
        return ""
    for part in comment.split(";"):
        if "vatPercent" in part:
            return part.split(":", 1)[1].strip()
        if "НДС" in part:
            return _parse_vat_percent(part.replace("НДС:", "").strip())
    return ""


def _parse_vat_percent(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).replace("%", "").replace(",", ".").strip()
    try:
        return float(text)
    except ValueError:
        return None
