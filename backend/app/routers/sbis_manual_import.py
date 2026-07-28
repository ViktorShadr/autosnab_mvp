from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.sbis_manual_import import (
    SbisManualDocumentListResponse,
    SbisManualImportResultResponse,
    SbisManualLoginRequest,
    SbisManualLoginResponse,
    SbisManualSessionStatusResponse,
)
from app.services import sbis_manual_import_service as import_service
from app.services import sbis_manual_session_service as session_service
from app.services.sbis_manual_session_service import SbisManualSession, SbisManualSessionError

router = APIRouter(prefix="/sbis-manual", tags=["sbis-manual-import"])

_COOKIE_NAME = "sbis_manual_session"
_COOKIE_MAX_AGE = 3600


def require_manual_session(request: Request) -> SbisManualSession:
    token = request.cookies.get(_COOKIE_NAME)
    try:
        return session_service.get_session(token)
    except SbisManualSessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/session", response_model=SbisManualSessionStatusResponse)
def session_status(request: Request) -> SbisManualSessionStatusResponse:
    token = request.cookies.get(_COOKIE_NAME)
    try:
        session = session_service.get_session(token)
    except SbisManualSessionError:
        return SbisManualSessionStatusResponse(logged_in=False)
    return SbisManualSessionStatusResponse(logged_in=True, login=session.login)


@router.post("/login", response_model=SbisManualLoginResponse)
def login(payload: SbisManualLoginRequest, response: Response) -> SbisManualLoginResponse:
    try:
        token = import_service.login(
            login=payload.login, password=payload.password, account_number=payload.account_number
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response.set_cookie(
        _COOKIE_NAME, token, httponly=True, samesite="lax", max_age=_COOKIE_MAX_AGE
    )
    return SbisManualLoginResponse(login=payload.login)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    session_service.drop_session(request.cookies.get(_COOKIE_NAME))
    response.delete_cookie(_COOKIE_NAME)
    return {"ok": True}


@router.get("/documents", response_model=SbisManualDocumentListResponse)
def list_documents(
    date_from: str = Query(...),
    date_to: str = Query(...),
    cursor: str | None = Query(None),
    session: SbisManualSession = Depends(require_manual_session),
) -> SbisManualDocumentListResponse:
    try:
        return import_service.list_documents(session, date_from=date_from, date_to=date_to, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface SBIS transport/API errors as a clean 502
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/documents/{sbis_document_id}/import", response_model=SbisManualImportResultResponse)
def import_document(
    sbis_document_id: str,
    session: SbisManualSession = Depends(require_manual_session),
    db: Session = Depends(get_db),
) -> SbisManualImportResultResponse:
    try:
        return import_service.import_document(db, session, sbis_document_id)
    except Exception as exc:  # noqa: BLE001 - import_document itself never raises; this is a last-resort net
        return SbisManualImportResultResponse(
            sbis_document_id=sbis_document_id, success=False, stage="internal", error=str(exc)
        )


@router.get("/page", response_class=HTMLResponse)
def manual_import_page() -> HTMLResponse:
    return HTMLResponse(_PAGE_HTML)


_PAGE_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>СБИС — ручной импорт накладных</title>
  <style>
    :root { color-scheme: light; }
    body { margin: 0; font-family: Arial, sans-serif; background: #f5f7fb; color: #1f2937; }
    .page { max-width: 1100px; margin: 0 auto; padding: 32px 16px; }
    .card {
      background: white; border: 1px solid #e5e7eb; border-radius: 16px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); padding: 28px; margin-bottom: 20px;
    }
    h1 { margin: 0 0 8px; font-size: 26px; text-align: center; }
    .subtitle { color: #6b7280; margin-bottom: 20px; line-height: 1.5; text-align: center; }
    label { display: block; font-weight: 700; margin-bottom: 6px; }
    .field { margin-bottom: 14px; }
    input[type="text"], input[type="password"], input[type="date"], select {
      width: 100%; box-sizing: border-box; padding: 10px;
      border: 1px solid #d1d5db; border-radius: 10px; font-size: 15px;
    }
    button {
      border: 0; border-radius: 12px; padding: 12px 18px;
      background: #2563eb; color: white; font-weight: 700; font-size: 15px; cursor: pointer;
    }
    button:disabled { opacity: .5; cursor: not-allowed; }
    .secondary-btn { background: #6b7280; }
    .row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
    .row .field { flex: 1; min-width: 160px; margin-bottom: 0; }
    .hint { color: #6b7280; font-size: 13px; margin-top: 6px; }
    .error { color: #b91c1c; margin-top: 10px; font-weight: 700; }
    .hidden { display: none; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; }
    th { background: #f3f4f6; font-size: 13px; }
    tr.disabled-row { opacity: .5; }
    .status-cell.ok { color: #059669; font-weight: 700; }
    .status-cell.err { color: #b91c1c; font-weight: 700; }
    .summary { margin-top: 14px; font-weight: 700; }
    .logged-in-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  </style>
</head>
<body>
  <div class="page">
    <div class="card">
      <h1>СБИС — ручной импорт накладных</h1>
      <div class="subtitle">Войдите своим логином СБИС, выберите документы за период и импортируйте их в таблицу.</div>

      <div id="loginSection">
        <div class="field">
          <label for="loginInput">Логин СБИС</label>
          <input type="text" id="loginInput" autocomplete="off" />
        </div>
        <div class="field">
          <label for="passwordInput">Пароль</label>
          <input type="password" id="passwordInput" autocomplete="off" />
        </div>
        <div class="field">
          <label for="accountInput">Номер аккаунта (необязательно)</label>
          <input type="text" id="accountInput" autocomplete="off" />
        </div>
        <button id="loginBtn">Войти</button>
        <div id="loginError" class="error hidden"></div>
      </div>

      <div id="workSection" class="hidden">
        <div class="logged-in-bar">
          <div>Вы вошли как <strong id="loggedInLogin"></strong></div>
          <button class="secondary-btn" id="logoutBtn">Выйти</button>
        </div>

        <div class="row">
          <div class="field">
            <label for="dateFrom">С</label>
            <input type="date" id="dateFrom" />
          </div>
          <div class="field">
            <label for="dateTo">По</label>
            <input type="date" id="dateTo" />
          </div>
          <div class="field" style="flex: 0;">
            <button id="listBtn">Показать документы</button>
          </div>
        </div>
        <div id="listError" class="error hidden"></div>
        <div id="listHint" class="hint hidden"></div>
      </div>
    </div>

    <div class="card hidden" id="resultsCard">
      <div class="row">
        <div class="field" id="recipientFilterField" style="max-width: 420px;">
          <label for="recipientFilter">Юрлицо-получатель</label>
          <select id="recipientFilter"></select>
        </div>
        <div class="field" id="docTypeFilterField" style="max-width: 260px;">
          <label for="docTypeFilter">Тип документа</label>
          <select id="docTypeFilter"></select>
        </div>
        <div class="field" style="max-width: 420px;">
          <label for="supplierFilter">Поиск по поставщику</label>
          <input type="text" id="supplierFilter" placeholder="Название или ИНН поставщика" autocomplete="off" />
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th></th><th>Дата</th><th>Тип</th><th>Номер</th><th>Контрагент</th><th>ИНН</th><th>Получатель</th><th>Сумма</th><th>Статус</th>
          </tr>
        </thead>
        <tbody id="documentsBody"></tbody>
      </table>
      <div class="row" style="margin-top: 16px;">
        <button id="importBtn" disabled>Импортировать выбранные</button>
        <button class="secondary-btn hidden" id="loadMoreBtn">Показать ещё</button>
      </div>
      <div id="summary" class="summary hidden"></div>
    </div>
  </div>

  <script>
    const loginSection = document.getElementById('loginSection');
    const workSection = document.getElementById('workSection');
    const loginBtn = document.getElementById('loginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const loginError = document.getElementById('loginError');
    const loggedInLogin = document.getElementById('loggedInLogin');
    const listBtn = document.getElementById('listBtn');
    const listError = document.getElementById('listError');
    const listHint = document.getElementById('listHint');
    const resultsCard = document.getElementById('resultsCard');
    const documentsBody = document.getElementById('documentsBody');
    const importBtn = document.getElementById('importBtn');
    const summary = document.getElementById('summary');
    const dateTo = document.getElementById('dateTo');
    const dateFrom = document.getElementById('dateFrom');
    const recipientFilter = document.getElementById('recipientFilter');
    const docTypeFilter = document.getElementById('docTypeFilter');
    const supplierFilter = document.getElementById('supplierFilter');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    let allDocuments = [];
    let activeDateFrom = null;
    let activeDateTo = null;
    let pendingCursor = null;

    const DOC_TYPE_LABELS = {
      'ДокОтгрВх': 'Накладная / УПД (ДокОтгрВх)',
      'СчетВх': 'Счёт (СчетВх)',
    };

    function todayStr() {
      return new Date().toISOString().slice(0, 10);
    }
    dateTo.value = todayStr();

    function showWorkSection(login) {
      loginSection.classList.add('hidden');
      workSection.classList.remove('hidden');
      loggedInLogin.textContent = login;
    }

    async function checkSession() {
      const res = await fetch('/api/v1/sbis-manual/session');
      const data = await res.json();
      if (data.logged_in) {
        showWorkSection(data.login);
      }
    }

    loginBtn.addEventListener('click', async () => {
      loginError.classList.add('hidden');
      loginBtn.disabled = true;
      try {
        const res = await fetch('/api/v1/sbis-manual/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            login: document.getElementById('loginInput').value,
            password: document.getElementById('passwordInput').value,
            account_number: document.getElementById('accountInput').value || null,
          }),
        });
        document.getElementById('passwordInput').value = '';
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          loginError.textContent = err.detail || 'Не удалось войти.';
          loginError.classList.remove('hidden');
          return;
        }
        const data = await res.json();
        showWorkSection(data.login);
      } finally {
        loginBtn.disabled = false;
      }
    });

    logoutBtn.addEventListener('click', async () => {
      await fetch('/api/v1/sbis-manual/logout', { method: 'POST' });
      workSection.classList.add('hidden');
      loginSection.classList.remove('hidden');
      resultsCard.classList.add('hidden');
    });

    async function fetchDocuments(cursor) {
      const params = new URLSearchParams({ date_from: activeDateFrom, date_to: activeDateTo });
      if (cursor) params.set('cursor', cursor);
      const res = await fetch('/api/v1/sbis-manual/documents?' + params.toString());
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Не удалось получить список документов.');
      }
      return res.json();
    }

    function updateLoadMoreState(truncated) {
      if (truncated && pendingCursor) {
        loadMoreBtn.classList.remove('hidden');
        listHint.textContent = 'Показаны не все документы за период (лимит страниц за один запрос) — нажмите "Показать ещё", чтобы продолжить с того же места.';
        listHint.classList.remove('hidden');
      } else {
        loadMoreBtn.classList.add('hidden');
        listHint.classList.add('hidden');
      }
    }

    listBtn.addEventListener('click', async () => {
      listError.classList.add('hidden');
      listHint.classList.add('hidden');
      listBtn.disabled = true;
      activeDateFrom = dateFrom.value;
      activeDateTo = dateTo.value;
      try {
        const data = await fetchDocuments(null);
        allDocuments = data.documents;
        supplierFilter.value = '';
        pendingCursor = data.next_cursor || null;
        updateLoadMoreState(data.truncated);
        populateRecipientFilter();
        populateDocTypeFilter();
        renderFilteredRows();
        resultsCard.classList.remove('hidden');
        summary.classList.add('hidden');
        documentsBody.addEventListener('change', updateImportButtonState);
      } catch (err) {
        listError.textContent = err.message;
        listError.classList.remove('hidden');
        resultsCard.classList.add('hidden');
      } finally {
        listBtn.disabled = false;
      }
    });

    loadMoreBtn.addEventListener('click', async () => {
      if (!pendingCursor) return;
      loadMoreBtn.disabled = true;
      try {
        const data = await fetchDocuments(pendingCursor);
        const existingIds = new Set(allDocuments.map((doc) => doc.sbis_document_id));
        for (const doc of data.documents) {
          if (!existingIds.has(doc.sbis_document_id)) {
            allDocuments.push(doc);
            existingIds.add(doc.sbis_document_id);
          }
        }
        pendingCursor = data.next_cursor || null;
        updateLoadMoreState(data.truncated);
        populateRecipientFilter();
        populateDocTypeFilter();
        renderFilteredRows();
      } catch (err) {
        listError.textContent = err.message;
        listError.classList.remove('hidden');
      } finally {
        loadMoreBtn.disabled = false;
      }
    });

    function recipientKey(doc) {
      return (doc.recipient_inn || '') + '|' + (doc.recipient_name || '');
    }

    function populateDocTypeFilter() {
      const seen = new Map();
      for (const doc of allDocuments) {
        const type = doc.document_type || '';
        if (!seen.has(type)) {
          seen.set(type, DOC_TYPE_LABELS[type] || type || 'Без типа');
        }
      }
      docTypeFilter.innerHTML = '';
      const allOption = document.createElement('option');
      allOption.value = '';
      allOption.textContent = 'Все типы (' + allDocuments.length + ')';
      docTypeFilter.appendChild(allOption);
      for (const [type, label] of seen) {
        const option = document.createElement('option');
        option.value = type;
        option.textContent = label;
        docTypeFilter.appendChild(option);
      }
      document.getElementById('docTypeFilterField').classList.toggle('hidden', seen.size === 0);
    }

    function populateRecipientFilter() {
      const seen = new Map();
      for (const doc of allDocuments) {
        const key = recipientKey(doc);
        if (!seen.has(key)) {
          seen.set(key, doc.recipient_name ? doc.recipient_name + (doc.recipient_inn ? ' (ИНН ' + doc.recipient_inn + ')' : '') : 'Без получателя');
        }
      }
      recipientFilter.innerHTML = '';
      const allOption = document.createElement('option');
      allOption.value = '';
      allOption.textContent = 'Все юрлица (' + allDocuments.length + ')';
      recipientFilter.appendChild(allOption);
      for (const [key, label] of seen) {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = label;
        recipientFilter.appendChild(option);
      }
      document.getElementById('recipientFilterField').classList.toggle('hidden', seen.size === 0);
    }

    function renderFilteredRows() {
      const filterValue = recipientFilter.value;
      let documents = filterValue ? allDocuments.filter((doc) => recipientKey(doc) === filterValue) : allDocuments;
      const typeValue = docTypeFilter.value;
      if (typeValue) {
        documents = documents.filter((doc) => (doc.document_type || '') === typeValue);
      }
      const supplierQuery = supplierFilter.value.trim().toLowerCase();
      if (supplierQuery) {
        documents = documents.filter((doc) => {
          const name = (doc.counterparty_name || '').toLowerCase();
          const inn = (doc.counterparty_inn || '').toLowerCase();
          return name.includes(supplierQuery) || inn.includes(supplierQuery);
        });
      }
      documentsBody.innerHTML = '';
      for (const doc of documents) {
        const tr = document.createElement('tr');
        tr.dataset.id = doc.sbis_document_id;
        const checkboxCell = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'doc-checkbox';
        if (!doc.has_target_attachment) {
          checkbox.disabled = true;
          tr.title = 'Нет вложения для скачивания';
          tr.classList.add('disabled-row');
        }
        checkboxCell.appendChild(checkbox);
        tr.appendChild(checkboxCell);
        for (const value of [doc.document_date, doc.document_type, doc.document_number, doc.counterparty_name, doc.counterparty_inn, doc.recipient_name, doc.amount]) {
          const td = document.createElement('td');
          td.textContent = value || '';
          tr.appendChild(td);
        }
        const statusCell = document.createElement('td');
        statusCell.className = 'status-cell';
        tr.appendChild(statusCell);
        documentsBody.appendChild(tr);
      }
      importBtn.disabled = documents.length === 0;
      updateImportButtonState();
    }

    recipientFilter.addEventListener('change', renderFilteredRows);
    docTypeFilter.addEventListener('change', renderFilteredRows);
    supplierFilter.addEventListener('input', renderFilteredRows);

    function updateImportButtonState() {
      const checked = documentsBody.querySelectorAll('.doc-checkbox:checked');
      importBtn.disabled = checked.length === 0;
    }

    importBtn.addEventListener('click', async () => {
      const rows = Array.from(documentsBody.querySelectorAll('tr')).filter(
        (tr) => tr.querySelector('.doc-checkbox') && tr.querySelector('.doc-checkbox').checked
      );
      if (rows.length === 0) return;
      if (!confirm('Импортировать ' + rows.length + ' документ(ов) в Google Таблицу?')) return;
      importBtn.disabled = true;
      let succeeded = 0;
      let failed = 0;
      for (const tr of rows) {
        const checkbox = tr.querySelector('.doc-checkbox');
        const statusCell = tr.querySelector('.status-cell');
        statusCell.textContent = 'Импорт...';
        statusCell.className = 'status-cell';
        try {
          const res = await fetch('/api/v1/sbis-manual/documents/' + encodeURIComponent(tr.dataset.id) + '/import', {
            method: 'POST',
          });
          const data = await res.json();
          if (data.success) {
            succeeded += 1;
            statusCell.innerHTML = '';
            statusCell.className = 'status-cell ok';
            const label = document.createTextNode('✅ Готово');
            statusCell.appendChild(label);
            if (data.spreadsheet_url) {
              statusCell.appendChild(document.createTextNode(' — '));
              const link = document.createElement('a');
              link.href = data.spreadsheet_url;
              link.target = '_blank';
              link.textContent = 'таблица';
              statusCell.appendChild(link);
            }
            checkbox.disabled = true;
          } else {
            failed += 1;
            statusCell.textContent = '❌ ' + (data.error || data.stage || 'Ошибка');
            statusCell.className = 'status-cell err';
          }
        } catch (exc) {
          failed += 1;
          statusCell.textContent = '❌ ' + String(exc);
          statusCell.className = 'status-cell err';
        }
      }
      summary.textContent = 'Готово: импортировано ' + succeeded + ' из ' + rows.length + (failed ? ', ошибок ' + failed : '');
      summary.classList.remove('hidden');
      updateImportButtonState();
    });

    checkSession();
  </script>
</body>
</html>
"""
