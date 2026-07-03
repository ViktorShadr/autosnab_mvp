import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.config import settings  # noqa: E402
from app.services.google_sheets_service import _insert_into_existing_spreadsheet  # noqa: E402


class _FakeValuesResource:
    def __init__(self):
        self.updated = []

    def update(self, **kwargs):
        self.updated.append(kwargs)
        return self

    def execute(self):
        return {}


class _FakeSpreadsheetsResource:
    def __init__(self):
        self.values_resource = _FakeValuesResource()
        self.batch_updates = []
        self.get_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _FakeExecute(
            {
                "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/test-id/edit",
                "sheets": [
                    {
                        "properties": {
                            "sheetId": 321,
                            "title": "Накладная",
                            "gridProperties": {"rowCount": 100, "columnCount": 38},
                        }
                    }
                ],
            }
        )

    def batchUpdate(self, **kwargs):
        self.batch_updates.append(kwargs)
        return _FakeExecute({})

    def values(self):
        return self.values_resource


class _FakeSheetsService:
    def __init__(self):
        self.spreadsheets_resource = _FakeSpreadsheetsResource()

    def spreadsheets(self):
        return self.spreadsheets_resource


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


def test_insert_into_existing_spreadsheet_prepends_block_and_separator():
    fake_service = _FakeSheetsService()
    old_sheet_name = settings.google_target_sheet_name
    old_header_count = settings.google_target_header_row_count
    settings.google_target_sheet_name = "Накладная"
    settings.google_target_header_row_count = 2
    try:
        result = _insert_into_existing_spreadsheet(
            sheets_service=fake_service,
            drive_service=None,
            spreadsheet_id="test-id",
            sheet_data={
                "spreadsheet_name": "АвтоСнаб Накладные",
                "primary_sheet_name": "Накладные",
                "sheets": {
                    "Накладные": [
                        ["H1", "H2", "H3"],
                        ["doc-1", "item-1", "10"],
                        ["", "item-2", "20"],
                    ]
                },
            },
        )
    finally:
        settings.google_target_sheet_name = old_sheet_name
        settings.google_target_header_row_count = old_header_count

    assert result["mode"] == "prepend_into_existing_sheet"
    assert result["sheet_name"] == "Накладная"
    assert result["block_start_row"] == 3
    assert result["block_end_row"] == 4
    assert result["separator_row"] == 5

    batch_update = fake_service.spreadsheets_resource.batch_updates[0]
    requests = batch_update["body"]["requests"]
    assert requests == [
        {
            "insertDimension": {
                "range": {
                    "sheetId": 321,
                    "dimension": "ROWS",
                    "startIndex": 2,
                    "endIndex": 5,
                },
                "inheritFromBefore": False,
            }
        }
    ]

    value_update = fake_service.spreadsheets_resource.values_resource.updated[0]
    assert value_update["range"] == "Накладная!A3:AL5"
    assert value_update["body"]["values"] == [
        ["doc-1", "item-1", "10"],
        ["", "item-2", "20"],
        ["", "", ""],
    ]
