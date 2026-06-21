import json
from typing import Any

from app.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/script.projects",
]


class GoogleSheetsConfigurationError(RuntimeError):
    pass


def create_invoice_review_spreadsheet(receiving, sheet_data: dict, apps_script_text: str) -> dict[str, Any]:
    """Create a real Google Spreadsheet and attach the MVP-4 Apps Script menu.

    Requires GOOGLE_SHEETS_ENABLED=true and service account credentials.
    If GOOGLE_APPS_SCRIPT_ENABLED=true, the service automatically creates a
    container-bound Apps Script project for the spreadsheet and writes Code.gs.
    The Apps Script source is also kept on a backup sheet so the user can copy
    it manually if the Apps Script API is unavailable in a client's Google Cloud
    project.
    """
    if not settings.google_sheets_enabled:
        raise GoogleSheetsConfigurationError(
            "Google Sheets API отключен. Укажите GOOGLE_SHEETS_ENABLED=true и credentials service account."
        )
    credentials_path = _credentials_path()
    if credentials_path is None:
        raise GoogleSheetsConfigurationError(
            "Не указан GOOGLE_APPLICATION_CREDENTIALS или GOOGLE_SERVICE_ACCOUNT_FILE для Google Sheets API."
        )
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleSheetsConfigurationError(
            "Не установлены зависимости google-api-python-client/google-auth. Выполните pip install -r requirements.txt."
        ) from exc

    credentials = service_account.Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    sheets_service = build("sheets", "v4", credentials=credentials)
    drive_service = build("drive", "v3", credentials=credentials)

    spreadsheet_body = {
        "properties": {"title": sheet_data["spreadsheet_name"]},
        "sheets": [
            {"properties": {"title": "Проверка накладной"}},
            {"properties": {"title": "Товарные позиции"}},
            {"properties": {"title": "Отправка в iiko"}},
            {"properties": {"title": "Apps Script backup"}},
        ],
    }
    spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet_body, fields="spreadsheetId,spreadsheetUrl").execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]
    spreadsheet_url = spreadsheet["spreadsheetUrl"]

    appsscript_install_result = _install_bound_apps_script(
        credentials=credentials,
        spreadsheet_id=spreadsheet_id,
        title=f"АвтоСнаб MVP-4 menu {receiving.id}",
        apps_script_text=apps_script_text,
    )

    values = [
        {"range": "Проверка накладной!A1:D50", "values": sheet_data["sheets"]["Проверка накладной"]},
        {"range": "Товарные позиции!A1:K500", "values": sheet_data["sheets"]["Товарные позиции"]},
        {
            "range": "Отправка в iiko!A1:B40",
            "values": _send_sheet_values(receiving, sheet_data, appsscript_install_result),
        },
        {
            "range": "Apps Script backup!A1:A250",
            "values": [[line] for line in apps_script_text.splitlines()],
        },
    ]
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": values},
    ).execute()
    _format_spreadsheet(sheets_service, spreadsheet_id, hide_backup_sheet=appsscript_install_result.get("installed", False))

    if settings.google_drive_folder_id:
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=settings.google_drive_folder_id,
            fields="id, parents",
        ).execute()

    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "spreadsheet_name": sheet_data["spreadsheet_name"],
        "apps_script": appsscript_install_result,
    }


def _install_bound_apps_script(credentials, spreadsheet_id: str, title: str, apps_script_text: str) -> dict[str, Any]:
    if not settings.google_apps_script_enabled:
        return {
            "installed": False,
            "status": "disabled",
            "message": "GOOGLE_APPS_SCRIPT_ENABLED=false. Код сохранен на листе 'Apps Script backup'.",
        }
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        return {"installed": False, "status": "dependency_error", "message": str(exc)}

    try:
        script_service = build("script", "v1", credentials=credentials)
        project = script_service.projects().create(
            body={"title": title, "parentId": spreadsheet_id}
        ).execute()
        script_id = project["scriptId"]
        manifest = {
            "timeZone": "Europe/Moscow",
            "exceptionLogging": "STACKDRIVER",
            "oauthScopes": [
                "https://www.googleapis.com/auth/spreadsheets.currentonly",
                "https://www.googleapis.com/auth/script.external_request",
                "https://www.googleapis.com/auth/userinfo.email",
            ],
        }
        script_service.projects().updateContent(
            scriptId=script_id,
            body={
                "files": [
                    {
                        "name": "appsscript",
                        "type": "JSON",
                        "source": json.dumps(manifest, ensure_ascii=False, indent=2),
                    },
                    {"name": "Code", "type": "SERVER_JS", "source": apps_script_text},
                ]
            },
        ).execute()
        return {
            "installed": True,
            "status": "installed",
            "script_id": script_id,
            "script_url": f"https://script.google.com/d/{script_id}/edit",
            "message": "Apps Script автоматически привязан к Google Таблице. После открытия таблицы появится меню 'АвтоСнаб'.",
        }
    except Exception as exc:  # noqa: BLE001 - Google API errors must not block sheet creation
        return {
            "installed": False,
            "status": "install_error",
            "message": str(exc),
            "fallback": "Код сохранен на листе 'Apps Script backup'. Проверьте, что Google Apps Script API включен в Google Cloud.",
        }


def _send_sheet_values(receiving, sheet_data: dict, apps_script_result: dict[str, Any] | None = None) -> list[list[Any]]:
    apps_script_result = apps_script_result or {}
    script_status = apps_script_result.get("status") or "unknown"
    script_message = apps_script_result.get("message") or ""
    script_url = apps_script_result.get("script_url") or ""
    return [
        ["Поле", "Значение"],
        ["ID проверки", receiving.id],
        ["Статус", sheet_data["status"]],
        ["Что сделать", "Проверьте бизнес-поля на листах 'Проверка накладной' и 'Товарные позиции'. После проверки используйте меню АвтоСнаб → Предпросмотр отправки, затем АвтоСнаб → Отправить в iiko."],
        ["Endpoint предпросмотра", f"/api/v1/invoice-review/{receiving.id}/preview"],
        ["Endpoint отправки", f"/api/v1/invoice-review/{receiving.id}/sync-sheet-and-confirm-send"],
        ["Важно", "Перед отправкой пользователь должен видеть поставщика, точку доставки, товары, количества, цены, суммы, НДС и статус. iiko ID остаются служебными в backend."],
        ["Apps Script статус", script_status],
        ["Apps Script сообщение", script_message],
        ["Apps Script URL", script_url],
        ["Последний статус отправки", ""],
        ["Время последней отправки", ""],
    ]


def _format_spreadsheet(sheets_service, spreadsheet_id: str, hide_backup_sheet: bool = False) -> None:
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in spreadsheet["sheets"]}
    requests = []
    for title, sheet_id in sheet_ids.items():
        requests.append(
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        )
        requests.append(
            {
                "autoResizeDimensions": {
                    "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 14}
                }
            }
        )
    if hide_backup_sheet and "Apps Script backup" in sheet_ids:
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_ids["Apps Script backup"], "hidden": True},
                    "fields": "hidden",
                }
            }
        )
    if requests:
        sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()


def _credentials_path() -> str | None:
    return settings.google_application_credentials or settings.google_service_account_file


def serialize_sheet_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
