from app.config import settings
from app.models.organization import Organization
from app.services.google_sheets_service import _build_google_services


class OrganizationProvisioningConfigurationError(RuntimeError):
    pass


def resolve_target_spreadsheet_id(organization: Organization | None) -> str | None:
    """Falls back to the single global settings.google_target_spreadsheet_id
    when no organization is given or it has no spreadsheet of its own yet --
    every existing single-tenant caller is unaffected by Phase 1. See
    docs/wiki/multi-tenant-provisioning-and-document-archive.md.
    """
    if organization is not None and organization.google_spreadsheet_id:
        return organization.google_spreadsheet_id
    return settings.google_target_spreadsheet_id


def provision_organization_spreadsheet(
    organization: Organization,
    template_spreadsheet_id: str | None = None,
) -> str:
    """Clone the configured template spreadsheet (Drive files.copy) for a new
    organization, move it into that organization's Drive folder if one is
    configured, and persist the new spreadsheet id onto `organization` (the
    caller is responsible for committing it).

    Manually triggered only -- not a self-serve API. Google Sheets has no
    native mechanism to propagate later template edits into an already-
    provisioned clone (confirmed unsolved industry-wide, not something this
    project is missing an API for); see the Phase 1 scope note and the
    recommended mitigation in
    docs/wiki/multi-tenant-provisioning-and-document-archive.md.
    """
    template_id = template_spreadsheet_id or settings.google_organization_template_spreadsheet_id
    if not template_id:
        raise OrganizationProvisioningConfigurationError(
            "Не задан GOOGLE_ORGANIZATION_TEMPLATE_SPREADSHEET_ID."
        )

    _sheets_service, drive_service = _build_google_services()
    copied = drive_service.files().copy(
        fileId=template_id,
        body={"name": f"АвтоСнаб — {organization.name}"},
        fields="id",
    ).execute()
    spreadsheet_id = copied["id"]

    if organization.google_drive_folder_id:
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=organization.google_drive_folder_id,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

    organization.google_spreadsheet_id = spreadsheet_id
    return spreadsheet_id
