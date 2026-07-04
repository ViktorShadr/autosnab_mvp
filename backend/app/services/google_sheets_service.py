import json
from typing import Any

from app.config import settings
from app.services.google_oauth_service import get_google_user_credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHARED_INVOICE_HEADERS = [
    "Статус загрузки", "Статус строки", "Корректировка", "Дубль", "Форма документа",
    "Загрузка", "Дата документа", "№ Документа", "Поставщик", "ИНН Поставщика",
    "Грузоотправитель", "Получатель", "Торговая точка", "Склад", "Основание",
    "Товар найден в справочнике", "Наименование товара из документа",
    "Наименование товара в УС", "Ед.изм. в документе", "Ед.изм. в УС",
    "Кол-во в документе", "Кол-во в УС", "Цена за ед-цу", "Цена в УС",
    "Стоимость без НДС", "Ставка НДС", "Сумма НДС", "Общая стоимость",
    "Сумма накладной", "Дата приема", "Принял, Ф.И.О.", "Госсистемы",
    "Кол-во в заявке", "Цена по прайсу", "Предыдущая дата поставки",
    "Предыдущая цена", "Отклонение от цены прайса", "Время загрузки документа",
    "ID документа", "Ссылка на исходный документ",
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


def load_invoice_reference_catalogs() -> dict[str, list[dict[str, Any]]]:
    spreadsheet_id = settings.google_target_spreadsheet_id
    if not settings.google_sheets_enabled or not spreadsheet_id:
        raise GoogleSheetsConfigurationError(
            "Для чтения справочников нужны GOOGLE_SHEETS_ENABLED=true и GOOGLE_TARGET_SPREADSHEET_ID."
        )
    sheets_service, _ = _build_google_services()
    ranges = ["'Товары'!A1:D", "'Справочник фасовок'!A1:M"]
    if settings.google_conversion_exceptions_sheet_name:
        escaped_name = settings.google_conversion_exceptions_sheet_name.replace("'", "''")
        ranges.append(f"'{escaped_name}'!A1:Z")
    response = sheets_service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id,
        ranges=ranges,
        majorDimension="ROWS",
    ).execute()
    ranges = response.get("valueRanges") or []
    products_rows = ranges[0].get("values", []) if len(ranges) > 0 else []
    packages_rows = ranges[1].get("values", []) if len(ranges) > 1 else []
    exceptions_rows = ranges[2].get("values", []) if len(ranges) > 2 else []
    return {
        "products": _table_rows_as_dicts(products_rows),
        "packages": _table_rows_as_dicts(packages_rows),
        "conversion_exceptions": _table_rows_as_dicts(exceptions_rows),
    }


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
    sheets_service, drive_service = _build_google_services()

    target_spreadsheet_id = settings.google_target_spreadsheet_id
    if target_spreadsheet_id:
        return _insert_into_existing_spreadsheet(
            receiving=receiving,
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


def _build_google_services():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleSheetsConfigurationError(
            "Не установлены зависимости google-api-python-client/google-auth/google-auth-oauthlib. Выполните pip install -r requirements.txt."
        ) from exc
    credentials = get_google_user_credentials()
    return (
        build("sheets", "v4", credentials=credentials),
        build("drive", "v3", credentials=credentials),
    )


def _table_rows_as_dicts(rows: list[list[Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    headers = [str(value).strip() for value in rows[0]]
    result = []
    for row in rows[1:]:
        mapped = {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(value not in (None, "") for value in mapped.values()):
            result.append(mapped)
    return result




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
    receiving,
    sheets_service,
    drive_service,
    spreadsheet_id: str,
    sheet_data: dict,
) -> dict[str, Any]:
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="spreadsheetUrl,sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))",
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
    target_headers = _read_target_headers(
        sheets_service,
        spreadsheet_id,
        target_sheet_name,
        settings.google_target_header_row_count,
    )
    document_rows = _remap_source_rows_to_shared_sheet(source_rows, receiving, target_headers)
    if not document_rows:
        document_rows = [[""] * len(source_rows[0])]
    column_count = max(len(row) for row in document_rows)
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
    target_column_count = (target_sheet.get("gridProperties") or {}).get("columnCount", 0)
    if target_column_count >= 47:
        template_row_start = insert_end_index
        inserted_rows = {
            "sheetId": target_sheet["sheetId"],
            "startRowIndex": insert_start_index,
            "endRowIndex": insert_end_index,
        }
        template_row = {
            "sheetId": target_sheet["sheetId"],
            "startRowIndex": template_row_start,
            "endRowIndex": template_row_start + 1,
        }
        for paste_type in ("PASTE_FORMAT", "PASTE_DATA_VALIDATION"):
            requests.append(
                {
                    "copyPaste": {
                        "source": {**template_row, "startColumnIndex": 0, "endColumnIndex": 47},
                        "destination": {**inserted_rows, "startColumnIndex": 0, "endColumnIndex": 47},
                        "pasteType": paste_type,
                        "pasteOrientation": "NORMAL",
                    }
                }
            )
        requests.append(
            {
                "copyPaste": {
                    "source": {**template_row, "startColumnIndex": 40, "endColumnIndex": 47},
                    "destination": {**inserted_rows, "startColumnIndex": 40, "endColumnIndex": 47},
                    "pasteType": "PASTE_FORMULA",
                    "pasteOrientation": "NORMAL",
                }
            }
        )
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()

    target_range = f"{target_sheet_name}!A{first_document_row_number}:{_column_index_to_a1(column_count - 1)}{insert_end_index}"
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


def _read_target_headers(
    sheets_service,
    spreadsheet_id: str,
    sheet_name: str,
    header_row_number: int,
) -> list[str]:
    values_resource = sheets_service.spreadsheets().values()
    if not hasattr(values_resource, "get"):
        return SHARED_INVOICE_HEADERS
    response = values_resource.get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A{header_row_number}:AN{header_row_number}",
    ).execute()
    rows = response.get("values") or []
    headers = [str(value).strip() for value in (rows[0] if rows else [])]
    if not headers:
        raise GoogleSheetsConfigurationError(f"Строка заголовков {header_row_number} листа '{sheet_name}' пуста.")
    missing = [header for header in SHARED_INVOICE_HEADERS if header not in headers]
    if missing:
        raise GoogleSheetsConfigurationError(
            "В листе 'Накладная' отсутствуют обязательные заголовки: " + ", ".join(missing)
        )
    return headers


def _remap_source_rows_to_shared_sheet(
    source_rows: list[list[Any]],
    receiving,
    target_headers: list[str] | None = None,
) -> list[list[Any]]:
    if not source_rows:
        return []
    source_headers = [str(cell).strip() for cell in source_rows[0]]
    target_headers = target_headers or SHARED_INVOICE_HEADERS
    target_width = len(target_headers)
    target_indexes = {header: index for index, header in enumerate(target_headers)}
    result: list[list[Any]] = []
    for index, row in enumerate(source_rows[1:], start=1):
        row_map = {
            header: row[column_index] if column_index < len(row) else ""
            for column_index, header in enumerate(source_headers)
            if header
        }
        target_row = [""] * target_width
        mapped_values = {
            "Статус загрузки": row_map.get("Статус загрузки", ""),
            "Статус строки": row_map.get("Статус строки", ""),
            "Корректировка": row_map.get("Причина ручной корректировки", ""),
            "Дубль": row_map.get("Индикатор дубля документа", ""),
            "Форма документа": row_map.get("Форма документа", ""),
            "Загрузка": row_map.get("Загрузить в УС", ""),
            "Дата документа": row_map.get("Дата документа", ""),
            "№ Документа": row_map.get("№ Документа", ""),
            "Поставщик": row_map.get("Поставщик", ""),
            "ИНН Поставщика": row_map.get("ИНН Поставщика", ""),
            "Грузоотправитель": row_map.get("Грузоотправитель", row_map.get("Грузополучатель", "")),
            "Получатель": row_map.get("Получатель", ""),
            "Торговая точка": row_map.get("Торговая точка", ""),
            "Склад": row_map.get("Склад", ""),
            "Основание": row_map.get("Основание", ""),
            "Товар найден в справочнике": row_map.get("Товар найден в справочнике", ""),
            "Наименование товара из документа": row_map.get("Наименование товара из документа", ""),
            "Наименование товара в УС": row_map.get("Наименование товара в УС", ""),
            "Ед.изм. в документе": row_map.get("Ед.изм.", ""),
            "Ед.изм. в УС": row_map.get("Ед.изм. в УС", ""),
            "Кол-во в документе": row_map.get("Кол-во из документа", ""),
            "Кол-во в УС": row_map.get("Кол-во в УС", ""),
            "Цена за ед-цу": row_map.get("Цена за единицу", ""),
            "Цена в УС": row_map.get("Цена в УС", ""),
            "Стоимость без НДС": row_map.get("Стоимость без НДС", ""),
            "Ставка НДС": row_map.get("Ставка НДС %", ""),
            "Сумма НДС": row_map.get("Сумма НДС", ""),
            "Общая стоимость": row_map.get("Общая стоимость", ""),
            "Сумма накладной": row_map.get("Сумма накладной", ""),
            "Дата приема": row_map.get("Дата приема", ""),
            "Принял, Ф.И.О.": row_map.get("Принял, Ф.И.О.", ""),
            "Госсистемы": row_map.get("Госсистемы", ""),
            "Кол-во в заявке": row_map.get("Кол-во в заявке", ""),
            "Цена по прайсу": row_map.get("Цена по прайсу", ""),
            "Предыдущая дата поставки": row_map.get("Последняя дата поставки", ""),
            "Предыдущая цена": row_map.get("Последняя цена", ""),
            "Отклонение от цены прайса": row_map.get("Отклонение от цены прайса", ""),
            "Время загрузки документа": row_map.get("Время загрузки документа", ""),
            "ID документа": row_map.get("ID документа", ""),
            "Ссылка на исходный документ": (
                (getattr(receiving, "documents", None) and getattr(receiving.documents[-1], "file_url", ""))
                or ""
            ),
        }
        first_row_only = {
            "Статус загрузки", "Статус строки", "Дубль", "Форма документа", "Дата документа",
            "№ Документа", "Поставщик", "ИНН Поставщика", "Грузоотправитель", "Получатель",
            "Торговая точка", "Склад", "Основание", "Сумма накладной",
            "Время загрузки документа", "ID документа", "Ссылка на исходный документ",
        }
        for header, value in mapped_values.items():
            if header in target_indexes:
                target_row[target_indexes[header]] = "" if index != 1 and header in first_row_only else value
        result.append(target_row)
    return result


def _column_index_to_a1(column_index: int) -> str:
    if column_index < 0:
        raise ValueError("column_index must be non-negative")
    result = ""
    index = column_index + 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def serialize_sheet_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
