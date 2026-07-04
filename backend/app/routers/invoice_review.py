import html
import json
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
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
    get_latest_google_spreadsheet_info,
    send_google_sheet_and_confirm_to_iiko,
)
from app.services.invoice_parser_service import extract_invoice_payload_with_fallback
from app.services.ocr_service import OcrConfigurationError, recognize_invoice_image

router = APIRouter(prefix="/invoice-review", tags=["invoice-review"])




@router.get("/upload-page", response_class=HTMLResponse)
def upload_invoice_page():
    return HTMLResponse("""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>АвтоСнаб — загрузка накладной</title>
  <style>
    :root { color-scheme: light; }
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f5f7fb;
      color: #1f2937;
    }
    .page {
      max-width: 920px;
      margin: 0 auto;
      padding: 32px 16px;
    }
    .card {
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 28px;
    }
    h1 { margin: 0 0 8px; font-size: 28px; text-align: center; }
    .subtitle { color: #6b7280; margin-bottom: 24px; line-height: 1.5; }
    label { display: block; font-weight: 700; margin-bottom: 8px; }
    .checkbox-label {
      display: flex; align-items: center; gap: 10px; margin: 16px 0 10px;
      font-weight: 700; cursor: pointer;
    }
    .checkbox-label input { width: 18px; height: 18px; }
    .hint { color: #6b7280; font-size: 14px; line-height: 1.45; margin-top: 8px; }
    .selected-files {
      margin-top: 12px;
      border: 1px solid #dbeafe;
      background: #eff6ff;
      border-radius: 12px;
      padding: 12px 14px;
    }
    .selected-files-title { font-weight: 700; margin-bottom: 8px; }
    .selected-files ol { margin: 0; padding-left: 0; list-style: none; }
    .selected-files li { margin: 6px 0; line-height: 1.35; }
    .file-size { color: #6b7280; font-size: 13px; }
    .remove-file-btn {
      min-width: auto;
      margin-left: 8px;
      padding: 4px 8px;
      border-radius: 8px;
      background: #e5e7eb;
      color: #374151;
      font-size: 12px;
      vertical-align: middle;
    }
    .duplicate-hint { color: #b45309; font-size: 14px; line-height: 1.45; margin-top: 8px; }
    input[type="file"] {
      width: 100%; box-sizing: border-box; padding: 12px;
      border: 1px solid #d1d5db; border-radius: 10px; background: #fff;
      font-size: 15px;
      color: transparent;
    }
    input[type="file"]::file-selector-button {
      color: #1f2937;
      margin-right: 0;
    }
    input[type="file"]::-webkit-file-upload-button {
      color: #1f2937;
      margin-right: 0;
    }
    button {
      border: 0; border-radius: 12px; padding: 14px 18px;
      background: #2563eb; color: white; font-weight: 700; font-size: 16px;
      cursor: pointer;
      min-width: 240px;
    }
    button:disabled { opacity: .6; cursor: not-allowed; }
    .secondary-btn {
      display: inline-block;
      text-decoration: none;
      text-align: center;
      border: 0; border-radius: 12px; padding: 14px 18px;
      background: #2563eb; color: white; font-weight: 700; font-size: 16px;
      min-width: 240px;
      box-sizing: border-box;
      margin-top: 10px;
    }
    .status-box {
      margin-top: 22px;
      padding: 18px;
      border-radius: 12px;
      line-height: 1.6;
      border: 1px solid #d1fae5;
      background: #f0fdf4;
    }
    .status-box.warning {
      border-color: #fde68a;
      background: #fffbeb;
    }
    .status-line {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 6px;
      text-align: center;
    }
    .button-row {
      margin-top: 20px;
      text-align: center;
    }
    .result-actions {
      text-align: center;
    }
    .loading {
      margin-top: 22px;
      padding: 16px;
      border-radius: 12px;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      line-height: 1.45;
    }
    .error {
      margin-top: 22px;
      padding: 16px;
      border-radius: 12px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      line-height: 1.45;
      white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="card">
      <h1>АвтоСнаб - Загрузка накладной</h1>
      <div class="subtitle">
        Загрузите фото, скан или PDF накладной. Система распознает данные через Google Drive OCR и создаст Google Таблицу для проверки.
      </div>
      <form id="uploadForm">
        <label class="checkbox-label" for="multipageInvoice">
          <input id="multipageInvoice" name="multipage_invoice" type="checkbox" />
          <span>Многостраничная накладная</span>
        </label>
        <input id="file" name="file" type="file" accept="image/*,.pdf" capture="environment" />
        <div class="hint" id="fileHint">Если накладная одностраничная, выберите один файл.</div>
        <div class="duplicate-hint" id="duplicateHint"></div>
        <div class="selected-files" id="selectedFilesBox" hidden>
          <div class="selected-files-title">Выбранные файлы:</div>
          <ol id="selectedFilesList"></ol>
        </div>
        <div class="button-row">
          <button id="submitBtn" type="submit">Загрузить накладную заведения</button>
        </div>
      </form>
      <div id="output"></div>
    </section>
  </main>

  <script>
    const form = document.getElementById('uploadForm');
    const output = document.getElementById('output');
    const button = document.getElementById('submitBtn');
    const fileInput = document.getElementById('file');
    const multipageCheckbox = document.getElementById('multipageInvoice');
    const fileHint = document.getElementById('fileHint');
    const duplicateHint = document.getElementById('duplicateHint');
    const selectedFilesBox = document.getElementById('selectedFilesBox');
    const selectedFilesList = document.getElementById('selectedFilesList');
    const sheetWindowName = 'autosnab_google_sheet';
    let sheetWindow = null;
    let selectedInvoiceFiles = [];

    fileInput.addEventListener('change', () => {
      handleSelectedFiles(Array.from(fileInput.files || []));
      fileInput.value = '';
      output.innerHTML = '';
    });

    selectedFilesList.addEventListener('click', (event) => {
      const removeButton = event.target.closest('[data-remove-file-index]');
      if (!removeButton) {
        return;
      }

      const removeIndex = Number(removeButton.getAttribute('data-remove-file-index'));
      selectedInvoiceFiles = selectedInvoiceFiles.filter((_, index) => index !== removeIndex);
      duplicateHint.textContent = '';
      renderSelectedFiles();
    });

    multipageCheckbox.addEventListener('change', () => {
      fileInput.multiple = multipageCheckbox.checked;
      if (multipageCheckbox.checked) {
        fileInput.removeAttribute('capture');
      } else {
        fileInput.setAttribute('capture', 'environment');
      }
      resetSelectedFiles();
      output.innerHTML = '';
      fileHint.textContent = multipageCheckbox.checked
        ? 'Выбирайте файлы страниц одной накладной в правильном порядке. Повторно выбранный файл не будет добавлен и загружен.'
        : 'Если накладная одностраничная, выберите один файл.';
    });

    function getUserTimezone() {
      try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
      } catch (error) {
        return '';
      }
    }

    function getUserUtcOffsetMinutes() {
      try {
        return String(-new Date().getTimezoneOffset());
      } catch (error) {
        return '';
      }
    }

    function openSheetInSingleTab(url) {
      const targetUrl = String(url || '').trim();
      if (!targetUrl) {
        return false;
      }

      sheetWindow = window.open(targetUrl, sheetWindowName);
      if (sheetWindow) {
        sheetWindow.focus();
      }

      return false;
    }

    output.addEventListener('click', (event) => {
      const link = event.target.closest('[data-google-sheet-url]');
      if (!link) {
        return;
      }

      event.preventDefault();
      openSheetInSingleTab(link.getAttribute('data-google-sheet-url'));
    });

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>'"]/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
      }[ch]));
    }

    function normalizeOcrErrorMessage(value) {
      const rawText = String(value || '').trim();
      if (!rawText) {
        return '';
      }

      const uniqueParts = [];
      rawText
        .split(/\\s*;\\s*|\\n+/)
        .map((part) => part.replace(/^Страница\\s+\\d+\\s*:\\s*/, '').trim())
        .filter(Boolean)
        .forEach((part) => {
          if (!uniqueParts.includes(part)) {
            uniqueParts.push(part);
          }
        });

      return uniqueParts
        .join('\\n')
        .replace(/\\.\\s+Откройте\\s+/g, '.\\nОткройте ');
    }

    function renderOcrError(value) {
      const normalizedText = normalizeOcrErrorMessage(value);
      if (!normalizedText) {
        return '';
      }

      return `
        <div class="status-line">⚠️ OCR не сработал:</div>
        <div>${escapeHtml(normalizedText).replaceAll('\\n', '<br>')}</div>
      `;
    }

    function getFileKey(file) {
      return [file.name, file.size, file.lastModified, file.type].join('::');
    }

    function formatFileSize(size) {
      if (!Number.isFinite(size)) {
        return '';
      }
      if (size < 1024) {
        return `${size} Б`;
      }
      if (size < 1024 * 1024) {
        return `${(size / 1024).toFixed(1)} КБ`;
      }
      return `${(size / 1024 / 1024).toFixed(2)} МБ`;
    }

    function resetSelectedFiles() {
      selectedInvoiceFiles = [];
      duplicateHint.textContent = '';
      fileInput.value = '';
      renderSelectedFiles();
    }

    function handleSelectedFiles(files) {
      duplicateHint.textContent = '';
      if (!files.length) {
        renderSelectedFiles();
        return;
      }

      if (!multipageCheckbox.checked) {
        selectedInvoiceFiles = [files[0]];
        if (files.length > 1) {
          duplicateHint.textContent = 'Для одностраничной накладной выбран только первый файл.';
        }
        renderSelectedFiles();
        return;
      }

      const existingKeys = new Set(selectedInvoiceFiles.map(getFileKey));
      const skippedNames = [];
      for (const file of files) {
        const key = getFileKey(file);
        if (existingKeys.has(key)) {
          skippedNames.push(file.name);
        } else {
          selectedInvoiceFiles.push(file);
          existingKeys.add(key);
        }
      }
      if (skippedNames.length) {
        duplicateHint.textContent = `Повторно выбранные файлы не добавлены: ${skippedNames.join(', ')}`;
      }
      renderSelectedFiles();
    }

    function renderSelectedFiles() {
      selectedFilesBox.hidden = selectedInvoiceFiles.length === 0;
      selectedFilesList.innerHTML = selectedInvoiceFiles.map((file, index) => {
        const sizeText = formatFileSize(file.size);
        const pageText = `Страница ${index + 1}: `;
        return `
          <li>
            ${escapeHtml(pageText)}${escapeHtml(file.name)}
            ${sizeText ? `<span class="file-size">(${escapeHtml(sizeText)})</span>` : ''}
            <button class="remove-file-btn" type="button" data-remove-file-index="${index}">Убрать</button>
          </li>
        `;
      }).join('');
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const selectedFiles = selectedInvoiceFiles.slice();
      const isMultipage = multipageCheckbox.checked;
      const loadingText = 'Обрабатка через Google Drive OCR. Подождите...';
      output.innerHTML = `<div class="loading">${escapeHtml(loadingText)}</div>`;
      button.disabled = true;

      const formData = new FormData();
      if (!selectedFiles.length) {
        output.innerHTML = '<div class="error"><b>Ошибка:</b> выберите файл накладной.</div>';
        button.disabled = false;
        return;
      }
      if (!isMultipage && selectedFiles.length > 1) {
        output.innerHTML = '<div class="error"><b>Ошибка:</b> для одностраничной накладной выберите один файл или включите галочку «Многостраничная накладная».</div>';
        button.disabled = false;
        return;
      }
      if (isMultipage) {
        selectedFiles.forEach(file => formData.append('files', file));
      } else {
        formData.append('file', selectedFiles[0]);
      }
      formData.append('multipage_invoice', isMultipage ? 'true' : 'false');
      formData.append('create_google_sheet', 'true');
      formData.append('user_timezone', getUserTimezone());
      formData.append('user_utc_offset_minutes', getUserUtcOffsetMinutes());

      try {
        const response = await fetch('/api/v1/invoice-review/upload-photo', {
          method: 'POST',
          body: formData
        });
        const responseText = await response.text();
        let data = {};
        try {
          data = responseText ? JSON.parse(responseText) : {};
        } catch (parseError) {
          throw new Error(responseText || 'Сервер вернул не JSON-ответ.');
        }
        if (!response.ok) {
          throw new Error(data.detail || JSON.stringify(data, null, 2));
        }

        const hasGoogleSheet = Boolean(data.google_spreadsheet_url);
        const ocrError = data.ocr && data.ocr.error ? renderOcrError(data.ocr.error) : '';
        if (hasGoogleSheet) {
          output.innerHTML = `
            <div class="status-box">
              <div class="status-line">✅ Накладная обработана успешно.</div>
              <div class="status-line">✅ Данные добавлены в таблицу заведения.</div>
              ${ocrError}
              <div class="result-actions"><a class="secondary-btn" href="${escapeHtml(data.google_spreadsheet_url)}" data-google-sheet-url="${escapeHtml(data.google_spreadsheet_url)}">Открыть таблицу заведения</a></div>
            </div>
          `;
        } else if (ocrError) {
          output.innerHTML = `
            <div class="status-box warning">
              ${ocrError}
            </div>
          `;
        } else {
          const sheetError = data.google_spreadsheet_error ? `<div>Ошибка Google Таблицы: ${escapeHtml(data.google_spreadsheet_error)}</div>` : '';
          output.innerHTML = `
            <div class="status-box warning">
              <div class="status-line">⚠️ Накладная сохранена для ручной проверки.</div>
              <div>Google Таблица не создана.</div>
              ${sheetError}
            </div>
          `;
        }
      } catch (error) {
        output.innerHTML = `<div class="error"><b>Ошибка загрузки:</b> ${escapeHtml(error.message)}</div>`;
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
    """)


def _fallback_ocr_result(exc: Exception) -> dict:
    return {
        "provider": "manual_review_fallback",
        "raw_text": "",
        "confidence": None,
        "pages": 0,
        "error": str(exc),
    }

def _collect_invoice_uploads(
    file: UploadFile | None,
    files: list[UploadFile] | None,
    multipage_invoice: bool,
) -> list[UploadFile]:
    uploads = list(files or [])
    if file is not None:
        uploads.insert(0, file)
    if not multipage_invoice and len(uploads) > 1:
        raise HTTPException(
            status_code=400,
            detail="Для нескольких файлов включите галочку «Многостраничная накладная».",
        )
    return uploads


def _save_recognize_and_parse_invoice_page(
    upload_file: UploadFile,
    target_dir: Path,
    page_index: int,
) -> dict:
    safe_name = _safe_invoice_upload_name(upload_file.filename, page_index)
    file_path = target_dir / safe_name
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    try:
        ocr_result = recognize_invoice_image(str(file_path))
    except OcrConfigurationError as exc:
        ocr_result = _fallback_ocr_result(exc)
    except Exception as exc:  # noqa: BLE001 - external OCR errors must not break upload
        ocr_result = _fallback_ocr_result(exc)

    parsed = extract_invoice_payload_with_fallback(ocr_result["raw_text"], safe_name)
    return {
        "page_index": page_index,
        "saved_file": {
            "safe_name": safe_name,
            "path": str(file_path),
            "content_type": upload_file.content_type,
        },
        "ocr": ocr_result,
        "parsed": parsed,
    }


def _safe_invoice_upload_name(filename: str | None, page_index: int) -> str:
    original_name = Path(filename or f"invoice_page_{page_index}").name or f"invoice_page_{page_index}"
    original_path = Path(original_name)
    stem = original_path.stem or f"invoice_page_{page_index}"
    suffix = original_path.suffix
    unique_part = uuid4().hex[:8]
    return f"page_{page_index}_{unique_part}_{stem}{suffix}"


def _merge_invoice_page_payloads(page_results: list[dict]) -> dict:
    merged = dict(page_results[0]["parsed"] or {})
    all_items = []
    raw_text_parts = []
    parser_notes = []
    parser_providers = []

    for page in page_results:
        parsed = page["parsed"] or {}
        saved_file = page["saved_file"]
        raw_text = parsed.get("raw_text") or page["ocr"].get("raw_text") or ""
        raw_text_parts.append(f"--- File {page['page_index']}: {saved_file['safe_name']} ---\n{raw_text}")
        all_items.extend(parsed.get("items") or [])
        _extend_unique(parser_notes, parsed.get("parser_notes") or [])
        if parsed.get("parser_provider"):
            _extend_unique(parser_providers, [parsed["parser_provider"]])
        if page["page_index"] > 1:
            _fill_missing_invoice_header_fields(merged, parsed)

    merged["raw_text"] = "\n\n".join(raw_text_parts)
    merged["items"] = all_items
    if len(page_results) > 1 and all_items:
        # Для многостраничной накладной итог в таблице должен считаться по всем
        # добавленным строкам, а не по возможному промежуточному итогу первой страницы.
        merged["total_sum"] = None
    if len(page_results) > 1:
        parser_notes.insert(0, f"Многостраничная накладная: объединено файлов/страниц: {len(page_results)}.")
    merged["parser_notes"] = parser_notes
    if len(parser_providers) == 1:
        merged["parser_provider"] = parser_providers[0]
    elif parser_providers:
        merged["parser_provider"] = "multipage_" + "+".join(parser_providers)
    return merged


def _fill_missing_invoice_header_fields(merged: dict, parsed: dict) -> None:
    fields = (
        "supplier",
        "supplier_legal_name",
        "invoice_number",
        "invoice_date",
        "document_form",
        "supplier_inn",
        "consignee",
        "recipient",
        "trade_point",
        "warehouse",
        "basis",
        "venue",
        "delivery_address",
        "store",
        "display_store",
        "iiko_default_store_id",
        "total_sum",
    )
    for field in fields:
        if _is_empty_value(merged.get(field)) and not _is_empty_value(parsed.get(field)):
            merged[field] = parsed.get(field)


def _merge_invoice_page_ocr_results(page_results: list[dict]) -> dict:
    raw_text = "\n\n".join(page["ocr"].get("raw_text") or "" for page in page_results)
    providers = []
    errors = []
    for page in page_results:
        ocr = page["ocr"]
        _extend_unique(providers, [ocr.get("provider") or "unknown"])
        if ocr.get("error"):
            error_text = str(ocr["error"]).strip()
            if error_text and error_text not in errors:
                errors.append(error_text)
    result = {
        "provider": providers[0] if len(providers) == 1 else "+".join(providers),
        "raw_text": raw_text,
        "confidence": None,
        "pages": len(page_results),
    }
    if errors:
        result["error"] = "; ".join(errors)
    return result


def _extend_unique(target: list, values: list) -> None:
    for value in values:
        if value not in (None, "") and value not in target:
            target.append(value)


def _is_empty_value(value) -> bool:
    return value is None or value == "" or value == []


@router.post("/upload-photo", response_model=InvoiceReviewResponse)
async def upload_invoice_photo_real_ocr(
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    multipage_invoice: bool = Form(default=False),
    venue: str | None = Form(default=None),
    delivery_address: str | None = Form(default=None),
    request_id: str | None = Form(default=None),
    chat_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
    user_timezone: str | None = Form(default=None),
    user_utc_offset_minutes: str | None = Form(default=None),
    create_google_sheet: bool = Form(default=True),
    public_api_base_url: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    upload_files = _collect_invoice_uploads(file, files, multipage_invoice)
    if not upload_files:
        raise HTTPException(status_code=400, detail="Выберите файл накладной.")

    target_dir = Path(settings.uploaded_invoices_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    page_results = []
    for page_index, upload_file in enumerate(upload_files, start=1):
        page_results.append(_save_recognize_and_parse_invoice_page(upload_file, target_dir, page_index))

    parsed = _merge_invoice_page_payloads(page_results)
    ocr_result = _merge_invoice_page_ocr_results(page_results)
    saved_files = [page["saved_file"] for page in page_results]
    first_file = saved_files[0]
    payload = InvoiceReviewCreateRequest(
        file_id=", ".join(saved_file["safe_name"] for saved_file in saved_files),
        file_type=first_file["content_type"] or "image",
        file_url=", ".join(saved_file["path"] for saved_file in saved_files),
        raw_text=parsed.get("raw_text") or ocr_result["raw_text"],
        request_id=request_id,
        supplier=parsed.get("supplier"),
        supplier_legal_name=parsed.get("supplier_legal_name"),
        invoice_date=parsed.get("invoice_date"),
        invoice_number=parsed.get("invoice_number"),
        venue=venue or parsed.get("venue"),
        delivery_address=delivery_address or parsed.get("delivery_address"),
        display_store=parsed.get("display_store") or parsed.get("store"),
        document_form=parsed.get("document_form"),
        supplier_inn=parsed.get("supplier_inn"),
        consignee=parsed.get("consignee"),
        recipient=parsed.get("recipient"),
        trade_point=parsed.get("trade_point"),
        warehouse=parsed.get("warehouse") or parsed.get("display_store") or parsed.get("store"),
        basis=parsed.get("basis"),
        total_sum=parsed.get("total_sum"),
        iiko_default_store_id=parsed.get("iiko_default_store_id") or parsed.get("store"),
        chat_id=chat_id,
        user_id=user_id,
        user_timezone=user_timezone,
        user_utc_offset_minutes=user_utc_offset_minutes or None,
        multipage_invoice=len(page_results) > 1,
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
    if ocr_result.get("error"):
        response["ocr"]["error"] = ocr_result["error"]
    response["parser_notes"] = parsed.get("parser_notes", [])
    response["parser_provider"] = parsed.get("parser_provider")
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



@router.get("/{review_id}/send-page", response_class=HTMLResponse)
def open_iiko_send_page(review_id: int, db: Session = Depends(get_db)):
    receiving = _get_review(db, review_id)
    try:
        spreadsheet = get_latest_google_spreadsheet_info(db, review_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    invoice_number = html.escape(receiving.order_number or str(review_id))
    spreadsheet_url = html.escape(spreadsheet.get("spreadsheet_url") or "")
    spreadsheet_link = (
        f'<a href="{spreadsheet_url}" data-google-sheet-url="{spreadsheet_url}">Вернуться в Google Таблицу</a>'
        if spreadsheet_url
        else ""
    )
    return HTMLResponse(f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>АвтоСнаб — отправка в iiko</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f5f7fb; color: #111827; margin: 0; }}
    .page {{ max-width: 760px; margin: 0 auto; padding: 40px 16px; }}
    .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 16px; padding: 28px; box-shadow: 0 10px 30px rgba(15,23,42,.08); }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    .muted {{ color: #6b7280; line-height: 1.5; }}
    .btn {{ margin-top: 22px; border: 0; border-radius: 12px; padding: 14px 22px; background: #2563eb; color: #fff; font-weight: 700; font-size: 16px; cursor: pointer; }}
    .btn:disabled {{ opacity: .6; cursor: not-allowed; }}
    .options {{ margin-top: 18px; line-height: 1.8; }}
    .result {{ margin-top: 22px; padding: 16px; border-radius: 12px; background: #f0fdf4; border: 1px solid #bbf7d0; white-space: pre-wrap; }}
    .error {{ margin-top: 22px; padding: 16px; border-radius: 12px; background: #fef2f2; border: 1px solid #fecaca; white-space: pre-wrap; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <main class="page">
    <section class="card">
      <h1>Отправка накладной в iiko</h1>
      <p class="muted">Накладная: <b>{invoice_number}</b></p>
      <p class="muted">Перед отправкой проверьте лист <b>«Накладные»</b>. После нажатия кнопки backend прочитает данные из Google Таблицы и отправит их в iiko.</p>
      <div>{spreadsheet_link}</div>
      <div class="options">
        <label><input id="allowWarnings" type="checkbox" checked /> Разрешить отправку с предупреждениями проверки</label><br />
        <label><input id="dryRun" type="checkbox" /> Тестовый режим без реальной отправки</label>
      </div>
      <button id="sendBtn" class="btn" type="button">Отправить в iiko</button>
      <div id="result"></div>
    </section>
  </main>
  <script>
    const btn = document.getElementById('sendBtn');
    const result = document.getElementById('result');
    const sheetWindowName = 'autosnab_google_sheet';
    let sheetWindow = null;

    function openSheetInSingleTab(url) {{
      const targetUrl = String(url || '').trim();
      if (!targetUrl) {{
        return false;
      }}

      sheetWindow = window.open(targetUrl, sheetWindowName);
      if (sheetWindow) {{
        sheetWindow.focus();
      }}

      return false;
    }}

    document.addEventListener('click', (event) => {{
      const link = event.target.closest('[data-google-sheet-url]');
      if (!link) {{
        return;
      }}

      event.preventDefault();
      openSheetInSingleTab(link.getAttribute('data-google-sheet-url'));
    }});

    btn.addEventListener('click', async () => {{
      if (!confirm('Отправить накладную в iiko?')) return;
      btn.disabled = true;
      result.innerHTML = '<div class="result">Отправка выполняется...</div>';
      const allow = document.getElementById('allowWarnings').checked;
      const dry = document.getElementById('dryRun').checked;
      try {{
        const response = await fetch(`/api/v1/invoice-review/{review_id}/send-from-google-sheet?allow_with_warnings=${{allow}}&dry_run=${{dry}}`, {{ method: 'POST' }});
        const text = await response.text();
        let data = {{}};
        try {{ data = text ? JSON.parse(text) : {{}}; }} catch (_) {{ throw new Error(text || 'Сервер вернул не JSON-ответ.'); }}
        if (!response.ok) throw new Error(data.detail || JSON.stringify(data, null, 2));
        result.innerHTML = '<div class="result">Готово. Статус: ' + data.status + '\nExport ID: ' + data.export_id + '</div>';
      }} catch (err) {{
        result.innerHTML = '<div class="error">Ошибка отправки: ' + String(err.message || err) + '</div>';
      }} finally {{
        btn.disabled = false;
      }}
    }});
  </script>
</body>
</html>
    """)


@router.post("/{review_id}/send-from-google-sheet")
def send_from_google_sheet_button(
    review_id: int,
    allow_with_warnings: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    try:
        export = send_google_sheet_and_confirm_to_iiko(
            db,
            review_id,
            allow_with_warnings=allow_with_warnings,
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - external send errors must be visible to user
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "export_id": export.id,
        "review_id": review_id,
        "status": export.status,
        "target_system": export.target_system,
        "error_message": export.error_message,
        "payload": json.loads(export.payload_json),
    }

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
            "send_page": f"/api/v1/invoice-review/{receiving.id}/send-page",
            "apps_script": f"/api/v1/invoice-review/{receiving.id}/apps-script",
            "preview": f"/api/v1/invoice-review/{receiving.id}/preview",
            "confirm_send": f"/api/v1/invoice-review/{receiving.id}/confirm-send",
            "sync_sheet_and_confirm_send": f"/api/v1/invoice-review/{receiving.id}/sync-sheet-and-confirm-send",
        },
    }
