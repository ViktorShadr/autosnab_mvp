import json
from typing import Any

from app.config import settings
from app.services.google_oauth_service import get_google_user_credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


INVOICE_REGISTER_COLUMN_WIDTHS = {
    0: 190,   # Время загрузки документа
    2: 210,   # Индикатор дубля документа
    13: 280,  # Наименование товара из документа
    14: 180,  # Госсистемы
    15: 240,  # Наименование товара в УС
    16: 220,  # Товар найден в справочнике
    18: 190,  # Кол-во из документа
    20: 180,  # Стоимость без НДС
    32: 200,  # Последняя дата поставки
    34: 230,  # Отклонение от цены прайса
    37: 250,  # Причина ручной корректировки
}


class GoogleSheetsConfigurationError(RuntimeError):
    pass


def create_invoice_review_spreadsheet(
    receiving,
    sheet_data: dict,
    apps_script_text: str | None = None,
    public_api_base_url: str | None = None,
) -> dict[str, Any]:
    """Create a real Google Spreadsheet for invoice review.

    The user-facing spreadsheet contains one editable invoice-register sheet:
    - Накладные

    The table follows the header layout from «АвтоСнаб_Шапка.xlsx».
    """
    if not settings.google_sheets_enabled:
        raise GoogleSheetsConfigurationError(
            "Google Sheets API отключен. Укажите GOOGLE_SHEETS_ENABLED=true и credentials OAuth user."
        )
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleSheetsConfigurationError(
            "Не установлены зависимости google-api-python-client/google-auth/google-auth-oauthlib. Выполните pip install -r requirements.txt."
        ) from exc

    credentials = get_google_user_credentials()
    sheets_service = build("sheets", "v4", credentials=credentials)
    drive_service = build("drive", "v3", credentials=credentials)

    target_spreadsheet_id = settings.google_target_spreadsheet_id
    if target_spreadsheet_id:
        return _insert_into_existing_spreadsheet(
            sheets_service=sheets_service,
            drive_service=drive_service,
            spreadsheet_id=target_spreadsheet_id,
            sheet_data=sheet_data,
        )

    primary_sheet_name = sheet_data.get("primary_sheet_name") or next(iter(sheet_data["sheets"]))
    spreadsheet_body = {
        "properties": {"title": sheet_data["spreadsheet_name"]},
        "sheets": [
            {"properties": {"title": primary_sheet_name}},
        ],
    }
    spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet_body, fields="spreadsheetId,spreadsheetUrl").execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]
    spreadsheet_url = spreadsheet["spreadsheetUrl"]

    summary_values = sheet_data["sheets"][primary_sheet_name]

    button_result = {
        "installed": False,
        "status": "button_removed",
        "send_page_url": None,
        "message": "Кнопка-ссылка 'Отправить в iiko' на листе 'Накладные' не создаётся.",
    }

    values = [
        {"range": f"{primary_sheet_name}!A1:AL500", "values": summary_values},
    ]
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": values},
    ).execute()
    _format_spreadsheet(sheets_service, spreadsheet_id)

    if settings.google_drive_folder_id:
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=settings.google_drive_folder_id,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "spreadsheet_name": sheet_data["spreadsheet_name"],
        "send_button": button_result,
    }




def _format_spreadsheet(sheets_service, spreadsheet_id: str) -> None:
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in spreadsheet["sheets"]}
    requests = []
    for title, sheet_id in sheet_ids.items():
        header_end_column_index = 38 if title == "Накладные" else (7 if title == "Накладная" else 10)
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            }
        )
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": header_end_column_index,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 53 / 255,
                                "green": 104 / 255,
                                "blue": 84 / 255,
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                            "textFormat": {
                                "bold": True,
                                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                            },
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
                }
            }
        )
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 500,
                        "startColumnIndex": 0,
                        "endColumnIndex": header_end_column_index,
                    },
                    "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP", "verticalAlignment": "MIDDLE"}},
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                }
            }
        )
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": header_end_column_index,
                    },
                    "properties": {"pixelSize": 145},
                    "fields": "pixelSize",
                }
            }
        )
        if title == "Накладные":
            for column_index, pixel_size in INVOICE_REGISTER_COLUMN_WIDTHS.items():
                requests.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": column_index,
                                "endIndex": column_index + 1,
                            },
                            "properties": {"pixelSize": pixel_size},
                            "fields": "pixelSize",
                        }
                    }
                )
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {"pixelSize": 36},
                    "fields": "pixelSize",
                }
            }
        )
        requests.append(
            {
                "setBasicFilter": {
                    "filter": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "startColumnIndex": 0,
                            "endColumnIndex": header_end_column_index,
                        }
                    }
                }
            }
        )
    if requests:
        sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()


def _insert_into_existing_spreadsheet(
    *,
    sheets_service,
    drive_service,
    spreadsheet_id: str,
    sheet_data: dict,
) -> dict[str, Any]:
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="spreadsheetUrl,sheets.properties(sheetId,title,gridProperties.rowCount,columnCount)",
    ).execute()
    spreadsheet_url = spreadsheet["spreadsheetUrl"]
    target_sheet_name = settings.google_target_sheet_name
    target_sheet = None
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == target_sheet_name:
            target_sheet = props
            break
    if target_sheet is None:
        raise GoogleSheetsConfigurationError(
            f"В target spreadsheet не найден лист '{target_sheet_name}'."
        )

    source_sheet_name = sheet_data.get("primary_sheet_name") or next(iter(sheet_data["sheets"]))
    source_rows = sheet_data["sheets"].get(source_sheet_name) or []
    if not source_rows:
        raise GoogleSheetsConfigurationError("Нет данных для записи в target spreadsheet.")

    # In a shared operator sheet the real machine-bound header already exists.
    # New documents are inserted immediately under that header, newest first.
    document_rows = source_rows[1:] if len(source_rows) > 1 else []
    if not document_rows:
        document_rows = [[""] * len(source_rows[0])]
    column_count = max(len(row) for row in source_rows)
    separator_row = [""] * column_count
    rows_to_insert = document_rows + [separator_row]

    header_row_count = max(settings.google_target_header_row_count, 1)
    insert_start_index = header_row_count
    insert_end_index = insert_start_index + len(rows_to_insert)
    first_document_row_number = insert_start_index + 1
    last_document_row_number = first_document_row_number + len(document_rows) - 1

    requests = [
        {
            "insertDimension": {
                "range": {
                    "sheetId": target_sheet["sheetId"],
                    "dimension": "ROWS",
                    "startIndex": insert_start_index,
                    "endIndex": insert_end_index,
                },
                "inheritFromBefore": False,
            }
        }
    ]
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()

    target_range = f"{target_sheet_name}!A{first_document_row_number}:AL{insert_end_index}"
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=target_range,
        valueInputOption="RAW",
        body={"values": rows_to_insert},
    ).execute()

    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "spreadsheet_name": sheet_data["spreadsheet_name"],
        "sheet_name": target_sheet_name,
        "header_row_count": header_row_count,
        "block_start_row": first_document_row_number,
        "block_end_row": last_document_row_number,
        "separator_row": last_document_row_number + 1,
        "mode": "prepend_into_existing_sheet",
        "send_button": {
            "installed": False,
            "status": "button_removed",
            "send_page_url": None,
            "message": "Кнопка-ссылка 'Отправить в iiko' на листе общего реестра не создаётся.",
        },
    }


def serialize_sheet_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
