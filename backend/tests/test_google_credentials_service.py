from types import SimpleNamespace

import pytest

from app.services import google_credentials_service


def test_get_sheets_credentials_delegates_to_oauth_by_default(monkeypatch):
    monkeypatch.setattr(google_credentials_service.settings, "google_sheets_auth_mode", "oauth")
    sentinel = SimpleNamespace(name="oauth-credentials")
    monkeypatch.setattr(
        google_credentials_service, "get_google_user_credentials", lambda: sentinel
    )

    assert google_credentials_service.get_sheets_credentials() is sentinel


def test_get_sheets_credentials_delegates_to_service_account_when_configured(monkeypatch):
    monkeypatch.setattr(
        google_credentials_service.settings, "google_sheets_auth_mode", "service_account"
    )
    sentinel = SimpleNamespace(name="service-account-credentials")
    captured = {}

    def fake_get_service_account_credentials(scopes):
        captured["scopes"] = scopes
        return sentinel

    monkeypatch.setattr(
        google_credentials_service,
        "get_google_service_account_credentials",
        fake_get_service_account_credentials,
    )

    assert google_credentials_service.get_sheets_credentials() is sentinel
    assert captured["scopes"] == google_credentials_service.SHEETS_SERVICE_ACCOUNT_SCOPES


def test_get_sheets_credentials_rejects_unknown_mode(monkeypatch):
    monkeypatch.setattr(google_credentials_service.settings, "google_sheets_auth_mode", "bogus")

    with pytest.raises(google_credentials_service.GoogleAuthConfigurationError):
        google_credentials_service.get_sheets_credentials()


def test_get_sheets_auth_status_oauth_mode_delegates(monkeypatch):
    monkeypatch.setattr(google_credentials_service.settings, "google_sheets_auth_mode", "oauth")
    monkeypatch.setattr(
        google_credentials_service, "get_oauth_status", lambda: {"auth_mode": "oauth"}
    )

    assert google_credentials_service.get_sheets_auth_status() == {"auth_mode": "oauth"}


def test_get_sheets_auth_status_service_account_mode_authorized(monkeypatch):
    monkeypatch.setattr(
        google_credentials_service.settings, "google_sheets_auth_mode", "service_account"
    )
    sentinel = SimpleNamespace(service_account_email="fake@fake-project.iam.gserviceaccount.com")
    monkeypatch.setattr(
        google_credentials_service, "get_sheets_credentials", lambda: sentinel
    )

    status = google_credentials_service.get_sheets_auth_status()

    assert status["auth_mode"] == "service_account"
    assert status["authorized"] is True
    assert status["service_account_email"] == sentinel.service_account_email


def test_get_sheets_auth_status_service_account_mode_reports_error(monkeypatch):
    monkeypatch.setattr(
        google_credentials_service.settings, "google_sheets_auth_mode", "service_account"
    )

    def raise_error():
        raise google_credentials_service.GoogleAuthConfigurationError("boom")

    monkeypatch.setattr(google_credentials_service, "get_sheets_credentials", raise_error)

    status = google_credentials_service.get_sheets_auth_status()

    assert status["authorized"] is False
    assert status["error"] == "boom"


def test_validate_google_auth_configuration_passes_on_defaults(monkeypatch):
    monkeypatch.setattr(google_credentials_service.settings, "google_sheets_auth_mode", "oauth")
    monkeypatch.setattr(
        google_credentials_service.settings, "google_ocr_provider", "google_drive_ocr"
    )

    google_credentials_service.validate_google_auth_configuration()


def test_validate_google_auth_configuration_rejects_unknown_sheets_mode(monkeypatch):
    monkeypatch.setattr(google_credentials_service.settings, "google_sheets_auth_mode", "bogus")

    with pytest.raises(google_credentials_service.GoogleAuthConfigurationError):
        google_credentials_service.validate_google_auth_configuration()


def test_validate_google_auth_configuration_rejects_unknown_ocr_provider(monkeypatch):
    monkeypatch.setattr(google_credentials_service.settings, "google_sheets_auth_mode", "oauth")
    monkeypatch.setattr(google_credentials_service.settings, "google_ocr_provider", "bogus")

    with pytest.raises(google_credentials_service.GoogleAuthConfigurationError):
        google_credentials_service.validate_google_auth_configuration()


def test_validate_google_auth_configuration_requires_service_account_when_needed(monkeypatch):
    monkeypatch.setattr(
        google_credentials_service.settings, "google_sheets_auth_mode", "service_account"
    )
    monkeypatch.setattr(
        google_credentials_service.settings, "google_ocr_provider", "google_drive_ocr"
    )
    monkeypatch.setattr(
        google_credentials_service.settings, "google_service_account_json_b64", None
    )

    with pytest.raises(google_credentials_service.GoogleServiceAccountConfigurationError):
        google_credentials_service.validate_google_auth_configuration()
