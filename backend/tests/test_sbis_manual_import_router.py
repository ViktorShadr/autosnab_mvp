from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import sbis_manual_import as router_module
from app.schemas.sbis_manual_import import (
    SbisManualDocumentListResponse,
    SbisManualDocumentSummary,
    SbisManualImportResultResponse,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    return TestClient(app)


def test_documents_and_import_require_session_cookie():
    client = _client()

    documents_response = client.get("/api/v1/sbis-manual/documents?date_from=2026-01-01&date_to=2026-01-31")
    import_response = client.post("/api/v1/sbis-manual/documents/doc-1/import")

    assert documents_response.status_code == 401
    assert import_response.status_code == 401


def test_login_success_sets_cookie_and_bad_credentials_return_401(monkeypatch):
    def fake_login(*, login, password, account_number):
        if password == "wrong":
            raise ValueError("Не удалось войти в СБИС: неверный пароль")
        return "fake-token"

    monkeypatch.setattr(router_module.import_service, "login", fake_login)
    client = _client()

    bad = client.post(
        "/api/v1/sbis-manual/login", json={"login": "op", "password": "wrong"}
    )
    assert bad.status_code == 401
    assert "sbis_manual_session" not in bad.cookies

    good = client.post(
        "/api/v1/sbis-manual/login", json={"login": "op", "password": "right"}
    )
    assert good.status_code == 200
    assert good.json() == {"ok": True, "login": "op"}
    assert "sbis_manual_session" in client.cookies


def test_authenticated_calls_succeed_and_logout_invalidates_session(monkeypatch):
    monkeypatch.setattr(
        router_module.import_service,
        "login",
        lambda **kwargs: router_module.session_service.create_session(
            login=kwargs["login"], password=kwargs["password"], account_number=kwargs.get("account_number")
        ),
    )
    canned_list = SbisManualDocumentListResponse(
        documents=[
            SbisManualDocumentSummary(
                sbis_document_id="doc-1", document_type="ДокОтгрВх", has_target_attachment=True
            )
        ],
        truncated=False,
        pages_fetched=1,
    )
    monkeypatch.setattr(
        router_module.import_service, "list_documents", lambda session, **kwargs: canned_list
    )
    monkeypatch.setattr(
        router_module.import_service,
        "import_document",
        lambda db, session, sbis_document_id: SbisManualImportResultResponse(
            sbis_document_id=sbis_document_id, success=True, receiving_id=1, spreadsheet_url="https://sheet"
        ),
    )

    client = _client()
    client.post("/api/v1/sbis-manual/login", json={"login": "op", "password": "pw"})

    documents_response = client.get(
        "/api/v1/sbis-manual/documents?date_from=2026-01-01&date_to=2026-01-31"
    )
    assert documents_response.status_code == 200
    assert documents_response.json()["documents"][0]["sbis_document_id"] == "doc-1"

    import_response = client.post("/api/v1/sbis-manual/documents/doc-1/import")
    assert import_response.status_code == 200
    assert import_response.json()["success"] is True

    logout_response = client.post("/api/v1/sbis-manual/logout")
    assert logout_response.status_code == 200

    after_logout = client.get(
        "/api/v1/sbis-manual/documents?date_from=2026-01-01&date_to=2026-01-31"
    )
    assert after_logout.status_code == 401


def test_session_status_reflects_login_state(monkeypatch):
    monkeypatch.setattr(
        router_module.import_service,
        "login",
        lambda **kwargs: router_module.session_service.create_session(
            login=kwargs["login"], password=kwargs["password"], account_number=kwargs.get("account_number")
        ),
    )
    client = _client()

    before = client.get("/api/v1/sbis-manual/session")
    assert before.json() == {"logged_in": False, "login": None}

    client.post("/api/v1/sbis-manual/login", json={"login": "op", "password": "pw"})
    after = client.get("/api/v1/sbis-manual/session")
    assert after.json() == {"logged_in": True, "login": "op"}


def test_no_admin_api_key_header_is_required(monkeypatch):
    """Regression guard: this tool is explicitly unauthenticated-by-header
    (unlike sbis.py's require_sbis_admin) -- an easy copy-paste mistake to
    accidentally reintroduce."""
    monkeypatch.setattr(
        router_module.import_service,
        "login",
        lambda **kwargs: router_module.session_service.create_session(
            login=kwargs["login"], password=kwargs["password"], account_number=kwargs.get("account_number")
        ),
    )
    client = _client()

    response = client.post("/api/v1/sbis-manual/login", json={"login": "op", "password": "pw"})

    assert response.status_code == 200
    assert "X-Sbis-Api-Key" not in response.request.headers
