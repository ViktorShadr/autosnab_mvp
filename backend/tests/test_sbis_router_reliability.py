from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import sbis as sbis_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(sbis_router.router, prefix="/api/v1")
    return TestClient(app)


def test_sbis_admin_endpoints_require_configured_key(monkeypatch):
    monkeypatch.setattr(sbis_router.settings, "sbis_admin_api_key", "secret-key")
    monkeypatch.setattr(sbis_router.settings, "bot_api_shared_secret", None)
    client = _client()

    unauthorized = client.get("/api/v1/sbis/scheduler/status")
    authorized = client.get(
        "/api/v1/sbis/scheduler/status",
        headers={"X-Sbis-Api-Key": "secret-key"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_sbis_admin_endpoints_open_when_no_secret_configured(monkeypatch):
    monkeypatch.setattr(sbis_router.settings, "sbis_admin_api_key", None)
    monkeypatch.setattr(sbis_router.settings, "bot_api_shared_secret", None)
    client = _client()

    response = client.get("/api/v1/sbis/scheduler/status")

    assert response.status_code == 200


def test_sbis_admin_endpoints_fall_back_to_bot_shared_secret(monkeypatch):
    monkeypatch.setattr(sbis_router.settings, "sbis_admin_api_key", None)
    monkeypatch.setattr(sbis_router.settings, "bot_api_shared_secret", "bot-secret")
    client = _client()

    unauthorized = client.get("/api/v1/sbis/scheduler/status")
    authorized = client.get(
        "/api/v1/sbis/scheduler/status",
        headers={"X-Sbis-Api-Key": "bot-secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
