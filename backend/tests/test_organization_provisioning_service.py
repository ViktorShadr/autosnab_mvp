import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.config import settings  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.services import organization_provisioning_service as provisioning_module  # noqa: E402
from app.services.organization_provisioning_service import (  # noqa: E402
    OrganizationProvisioningConfigurationError,
    provision_organization_spreadsheet,
    resolve_target_spreadsheet_id,
)


@pytest.fixture(autouse=True)
def _restore_settings():
    original = {
        "google_target_spreadsheet_id": settings.google_target_spreadsheet_id,
        "google_organization_template_spreadsheet_id": settings.google_organization_template_spreadsheet_id,
    }
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_resolve_target_spreadsheet_id_falls_back_to_global_setting_when_no_organization():
    settings.google_target_spreadsheet_id = "global-sheet-id"

    assert resolve_target_spreadsheet_id(None) == "global-sheet-id"


def test_resolve_target_spreadsheet_id_falls_back_when_organization_has_no_sheet_yet():
    settings.google_target_spreadsheet_id = "global-sheet-id"
    organization = Organization(name="Кафе Ромашка", slug="cafe-romashka")

    assert resolve_target_spreadsheet_id(organization) == "global-sheet-id"


def test_resolve_target_spreadsheet_id_prefers_organizations_own_sheet():
    settings.google_target_spreadsheet_id = "global-sheet-id"
    organization = Organization(
        name="Кафе Ромашка", slug="cafe-romashka", google_spreadsheet_id="org-sheet-id"
    )

    assert resolve_target_spreadsheet_id(organization) == "org-sheet-id"


def test_provision_organization_spreadsheet_raises_without_template_configured():
    settings.google_organization_template_spreadsheet_id = None
    organization = Organization(name="Новая организация", slug="new-org")

    with pytest.raises(OrganizationProvisioningConfigurationError):
        provision_organization_spreadsheet(organization)


class _FakeFilesResource:
    def __init__(self):
        self.copy_calls = []
        self.update_calls = []

    def copy(self, **kwargs):
        self.copy_calls.append(kwargs)
        return SimpleNamespace(execute=lambda: {"id": "cloned-sheet-id"})

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return SimpleNamespace(execute=lambda: {"id": "cloned-sheet-id", "parents": []})


class _FakeDriveService:
    def __init__(self):
        self.files_resource = _FakeFilesResource()

    def files(self):
        return self.files_resource


def test_provision_organization_spreadsheet_copies_template_and_persists_id(monkeypatch):
    settings.google_organization_template_spreadsheet_id = "template-sheet-id"
    fake_drive_service = _FakeDriveService()
    monkeypatch.setattr(
        provisioning_module, "_build_google_services", lambda: (None, fake_drive_service)
    )
    organization = Organization(name="Новая организация", slug="new-org")

    spreadsheet_id = provision_organization_spreadsheet(organization)

    assert spreadsheet_id == "cloned-sheet-id"
    assert organization.google_spreadsheet_id == "cloned-sheet-id"
    assert fake_drive_service.files_resource.copy_calls[0]["fileId"] == "template-sheet-id"
    assert fake_drive_service.files_resource.update_calls == []  # no Drive folder configured


def test_provision_organization_spreadsheet_moves_into_organization_drive_folder(monkeypatch):
    settings.google_organization_template_spreadsheet_id = "template-sheet-id"
    fake_drive_service = _FakeDriveService()
    monkeypatch.setattr(
        provisioning_module, "_build_google_services", lambda: (None, fake_drive_service)
    )
    organization = Organization(
        name="Новая организация", slug="new-org", google_drive_folder_id="folder-id"
    )

    provision_organization_spreadsheet(organization)

    assert fake_drive_service.files_resource.update_calls[0]["addParents"] == "folder-id"
