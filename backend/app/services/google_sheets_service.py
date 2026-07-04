import json
import re
from typing import Any

from app.config import settings
from app.services.google_oauth_service import get_google_user_credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


INVOICE_REGISTER_COLUMN_WIDTHS = {
    0: 160,   # Статус строки
    1: 220,   # Корректировка
    2: 120,   # Дубль
    4: 130,   # Загрузка
    9: 220,   # Грузоотправитель
    14: 220,  # Товар найден в справочнике
    15: 280,  # Наименование товара из документа
    16: 240,  # Наименование товара в УС
    17: 190,  # Ед.изм. в документе
    19: 190,  # Кол-во в документе
    21: 150,  # Цена за ед-цу
    23: 180,  # Стоимость без НДС
    24: 130,  # Ставка НДС
    30: 180,  # Госсистемы
    33: 240,  # Предыдущая дата поставки
    34: 190,  # Предыдущая цена
    35: 230,  # Отклонение от цены прайса
    36: 205,  # Время загрузки документа
    37: 130,  # ID документа
    38: 250,  # Ссылка на исходный документ
}

HEADER_BACKGROUND_COLOR = {
    "red": 53 / 255,
    "green": 104 / 255,
    "blue": 84 / 255,
}

FIRST_BAND_BACKGROUND_COLOR = {"red": 1, "green": 1, "blue": 1}
SECOND_BAND_BACKGROUND_COLOR = {
    "red": 243 / 255,
    "green": 245 / 255,
    "blue": 246 / 255,
}
DOCUMENT_SEPARATOR_BORDER_COLOR = {
    "red": 82 / 255,
    "green": 96 / 255,
    "blue": 105 / 255,
}
INVOICE_REGISTER_COLUMN_COUNT = 39


class GoogleSheetsConfigurationError(RuntimeError):
    pass


def create_invoice_review_spreadsheet(
    receiving,
    sheet_data: dict,
    apps_script_text: str | None = None,
    public_api_base_url: str | None = None,
    existing_spreadsheet_id: str | None = None,
) -> dict[str, Any]:
    """Create or update the Google Spreadsheet used for invoice review.

    If an invoice-register spreadsheet id is configured/passed, the new invoice
    rows are appended to that single spreadsheet. Otherwise a spreadsheet is
    created once and its id can be reused on the following uploads.
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

    spreadsheet_id = _resolve_spreadsheet_id(existing_spreadsheet_id)
    if spreadsheet_id:
        return _append_invoice_review_to_existing_spreadsheet(
            sheets_service=sheets_service,
            spreadsheet_id=spreadsheet_id,
            sheet_data=sheet_data,
        )

    return _create_invoice_review_spreadsheet(
        sheets_service=sheets_service,
        drive_service=drive_service,
        sheet_data=sheet_data,
    )


def _create_invoice_review_spreadsheet(sheets_service, drive_service, sheet_data: dict) -> dict[str, Any]:
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
    values = [
        {"range": f"{primary_sheet_name}!A1:AM500", "values": summary_values},
    ]
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": values},
    ).execute()
    _format_spreadsheet(sheets_service, spreadsheet_id)
    sheet_id = _sheet_id_by_title(sheets_service, spreadsheet_id, primary_sheet_name)
    _add_invoice_bottom_separator(
        sheets_service=sheets_service,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        end_row=len(summary_values),
    )
    _move_spreadsheet_to_configured_folder(drive_service, spreadsheet_id)

    return _spreadsheet_result(
        spreadsheet_id=spreadsheet_id,
        spreadsheet_url=spreadsheet_url,
        spreadsheet_name=sheet_data["spreadsheet_name"],
        sheet_name=primary_sheet_name,
        data_start_row=2,
        data_end_row=max(2, len(summary_values)),
        mode="created",
    )


def _append_invoice_review_to_existing_spreadsheet(sheets_service, spreadsheet_id: str, sheet_data: dict) -> dict[str, Any]:
    primary_sheet_name = sheet_data.get("primary_sheet_name") or next(iter(sheet_data["sheets"]))
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="spreadsheetId,spreadsheetUrl,properties.title,sheets.properties(sheetId,title,index)",
    ).execute()
    spreadsheet_url = spreadsheet.get("spreadsheetUrl") or _spreadsheet_url(spreadsheet_id)
    sheet_name = _ensure_register_sheet(sheets_service, spreadsheet_id, spreadsheet, primary_sheet_name)
    summary_values = sheet_data["sheets"][primary_sheet_name]
    header_row = summary_values[:1]
    data_rows = summary_values[1:]

    _ensure_header_row(sheets_service, spreadsheet_id, sheet_name, header_row)
    next_document_id = _next_document_id(sheets_service, spreadsheet_id, sheet_name)
    data_rows = _with_document_id(data_rows, next_document_id)

    if data_rows:
        start_row = 2
        end_row = start_row + len(data_rows) - 1
        sheet_id = _sheet_id_by_title(sheets_service, spreadsheet_id, sheet_name)
        _insert_rows_after_header(sheets_service, spreadsheet_id, sheet_id, len(data_rows))
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A{start_row}:AM{end_row}",
            valueInputOption="RAW",
            body={"values": data_rows},
        ).execute()
    else:
        start_row = 2
        end_row = 2

    _format_spreadsheet(sheets_service, spreadsheet_id)
    if data_rows:
        _add_invoice_bottom_separator(
            sheets_service=sheets_service,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
            end_row=end_row,
        )

    return _spreadsheet_result(
        spreadsheet_id=spreadsheet_id,
        spreadsheet_url=spreadsheet_url,
        spreadsheet_name=sheet_data["spreadsheet_name"],
        sheet_name=sheet_name,
        data_start_row=start_row,
        data_end_row=end_row,
        mode="prepended",
    )


def _ensure_register_sheet(sheets_service, spreadsheet_id: str, spreadsheet: dict, sheet_name: str) -> str:
    sheets = spreadsheet.get("sheets", [])
    titles = [sheet["properties"]["title"] for sheet in sheets]
    if sheet_name in titles:
        return sheet_name

    if len(sheets) == 1:
        first_sheet = sheets[0]["properties"]
        first_title = first_sheet["title"]
        first_values = _get_values(sheets_service, spreadsheet_id, f"{first_title}!A1:AM2")
        if not first_values:
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": first_sheet["sheetId"], "title": sheet_name},
                                "fields": "title",
                            }
                        }
                    ]
                },
            ).execute()
            return sheet_name

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
    ).execute()
    return sheet_name


def _ensure_header_row(sheets_service, spreadsheet_id: str, sheet_name: str, header_row: list[list[Any]]) -> None:
    if not header_row:
        return

    existing_header = _get_values(sheets_service, spreadsheet_id, f"{sheet_name}!A1:AM1")
    expected_header = header_row[0]
    current_header = existing_header[0] if existing_header else []
    if current_header[:len(expected_header)] == expected_header:
        return

    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1:AM1",
        valueInputOption="RAW",
        body={"values": header_row},
    ).execute()


def _next_document_id(sheets_service, spreadsheet_id: str, sheet_name: str) -> int:
    # В новой шапке ID документа находится в колонке AL. Колонку B тоже
    # читаем как fallback для таблиц, созданных до переноса служебных полей.
    document_id_values = _get_values(sheets_service, spreadsheet_id, f"{sheet_name}!AL2:AL")
    legacy_document_id_values = _get_values(sheets_service, spreadsheet_id, f"{sheet_name}!B2:B")
    existing_ids = [
        _parse_document_id(row[0])
        for row in document_id_values + legacy_document_id_values
        if row
    ]
    numeric_ids = [document_id for document_id in existing_ids if document_id is not None]
    if numeric_ids:
        return max(numeric_ids) + 1
    return 1


def _parse_document_id(value: Any) -> int | None:
    document_id = None
    if isinstance(value, int):
        document_id = value
    elif isinstance(value, float) and value.is_integer():
        document_id = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d+", text):
            document_id = int(text)
    return document_id


def _with_document_id(data_rows: list[list[Any]], document_id: int) -> list[list[Any]]:
    updated_rows = [list(row) for row in data_rows]
    if updated_rows:
        first_row = updated_rows[0]
        while len(first_row) < 38:
            first_row.append("")
        first_row[37] = document_id
    return updated_rows


def _sheet_id_by_title(sheets_service, spreadsheet_id: str, sheet_name: str) -> int:
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties(sheetId,title)",
    ).execute()
    for sheet in spreadsheet.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == sheet_name:
            return properties["sheetId"]
    raise GoogleSheetsConfigurationError(f"Лист '{sheet_name}' не найден в Google Таблице.")


def _insert_rows_after_header(sheets_service, spreadsheet_id: str, sheet_id: int, row_count: int) -> None:
    if row_count <= 0:
        return
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "insertDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": 1,
                            "endIndex": 1 + row_count,
                        },
                        "inheritFromBefore": False,
                    }
                }
            ]
        },
    ).execute()


def _add_invoice_bottom_separator(
    sheets_service,
    spreadsheet_id: str,
    sheet_id: int,
    end_row: int,
) -> None:
    if end_row < 2:
        return

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "updateBorders": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": end_row - 1,
                            "endRowIndex": end_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": INVOICE_REGISTER_COLUMN_COUNT,
                        },
                        "bottom": {
                            "style": "SOLID_MEDIUM",
                            "color": DOCUMENT_SEPARATOR_BORDER_COLOR,
                        },
                    }
                }
            ]
        },
    ).execute()


def _get_values(sheets_service, spreadsheet_id: str, range_name: str) -> list[list[Any]]:
    result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    return result.get("values", [])


def _move_spreadsheet_to_configured_folder(drive_service, spreadsheet_id: str) -> None:
    if settings.google_drive_folder_id:
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=settings.google_drive_folder_id,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()


def _spreadsheet_result(
    spreadsheet_id: str,
    spreadsheet_url: str,
    spreadsheet_name: str,
    sheet_name: str,
    data_start_row: int,
    data_end_row: int,
    mode: str,
) -> dict[str, Any]:
    button_result = {
        "installed": False,
        "status": "button_removed",
        "send_page_url": None,
        "message": "Кнопка-ссылка 'Отправить в iiko' на листе 'Накладные' не создаётся.",
    }
    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "spreadsheet_name": spreadsheet_name,
        "sheet_name": sheet_name,
        "data_start_row": data_start_row,
        "data_end_row": data_end_row,
        "data_range": f"{sheet_name}!A{data_start_row}:AM{data_end_row}",
        "mode": mode,
        "send_button": button_result,
    }


def _resolve_spreadsheet_id(existing_spreadsheet_id: str | None = None) -> str | None:
    candidates = [
        getattr(settings, "google_invoice_register_spreadsheet_id", None),
        getattr(settings, "google_invoice_register_spreadsheet_url", None),
        existing_spreadsheet_id,
    ]
    for candidate in candidates:
        spreadsheet_id = _extract_spreadsheet_id(candidate)
        if spreadsheet_id:
            return spreadsheet_id
    return None


def _extract_spreadsheet_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", value):
        return value
    return None


def _spreadsheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"



def _format_spreadsheet(sheets_service, spreadsheet_id: str) -> None:
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_ids = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in spreadsheet["sheets"]}
    requests = []
    for title, sheet_id in sheet_ids.items():
        header_end_column_index = INVOICE_REGISTER_COLUMN_COUNT if title == "Накладные" else (7 if title == "Накладная" else 10)
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
        _delete_sheet_bandings(spreadsheet, requests, sheet_id)
        requests.append(
            {
                "addBanding": {
                    "bandedRange": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 500,
                            "startColumnIndex": 0,
                            "endColumnIndex": header_end_column_index,
                        },
                        "rowProperties": {
                            "headerColor": HEADER_BACKGROUND_COLOR,
                            "firstBandColor": FIRST_BAND_BACKGROUND_COLOR,
                            "secondBandColor": SECOND_BAND_BACKGROUND_COLOR,
                        },
                    }
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
                            "backgroundColor": HEADER_BACKGROUND_COLOR,
                            "horizontalAlignment": "LEFT",
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
                        "startRowIndex": 1,
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


def _delete_sheet_bandings(spreadsheet: dict, requests: list[dict[str, Any]], sheet_id: int) -> None:
    for sheet in spreadsheet.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("sheetId") == sheet_id:
            for banded_range in sheet.get("bandedRanges", []):
                banded_range_id = banded_range.get("bandedRangeId")
                if banded_range_id is not None:
                    requests.append({"deleteBanding": {"bandedRangeId": banded_range_id}})


def serialize_sheet_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
