from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.google_sheets_service import (  # noqa: E402
    _build_google_services,
    _ensure_historical_row_groups,
    _read_target_headers,
)


def main() -> None:
    spreadsheet_id = settings.google_target_spreadsheet_id
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_TARGET_SPREADSHEET_ID is not configured.")

    sheets_service, _drive_service = _build_google_services()
    sheet_name = settings.google_target_sheet_name
    header_row_count = max(settings.google_target_header_row_count, 1)

    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties(sheetId,title)",
    ).execute()
    target_sheet = next(
        (
            sheet["properties"]
            for sheet in spreadsheet.get("sheets", [])
            if sheet["properties"].get("title") == sheet_name
        ),
        None,
    )
    if target_sheet is None:
        raise RuntimeError(f"Лист '{sheet_name}' не найден в таблице {spreadsheet_id}.")

    target_headers = _read_target_headers(sheets_service, spreadsheet_id, sheet_name, header_row_count)
    _ensure_historical_row_groups(
        sheets_service,
        spreadsheet_id,
        target_sheet["sheetId"],
        sheet_name,
        header_row_count,
        target_headers,
    )
    print(f"Группировка строк по прошлым месяцам применена: лист '{sheet_name}' таблицы {spreadsheet_id}.")


if __name__ == "__main__":
    main()
