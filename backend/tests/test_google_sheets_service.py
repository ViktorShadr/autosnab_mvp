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


class _FakeDocument:
    def __init__(self, file_url):
        self.file_url = file_url


class _FakeReceiving:
    def __init__(self, file_url):
        self.documents = [_FakeDocument(file_url)]


def test_insert_into_existing_spreadsheet_prepends_block_and_separator():
    fake_service = _FakeSheetsService()
    old_sheet_name = settings.google_target_sheet_name
    old_header_count = settings.google_target_header_row_count
    settings.google_target_sheet_name = "Накладная"
    settings.google_target_header_row_count = 2
    try:
        result = _insert_into_existing_spreadsheet(
            receiving=_FakeReceiving("uploads/invoices/test.jpg"),
            sheets_service=fake_service,
            drive_service=None,
            spreadsheet_id="test-id",
            sheet_data={
                "spreadsheet_name": "АвтоСнаб Накладные",
                "primary_sheet_name": "Накладные",
                "sheets": {
                    "Накладные": [
                        [
                            "Статус загрузки",
                            "Статус строки",
                            "Причина ручной корректировки",
                            "Индикатор дубля документа",
                            "Форма документа",
                            "Загрузить в УС",
                            "Дата документа",
                            "№ Документа",
                            "Поставщик",
                            "ИНН Поставщика",
                            "Получатель",
                            "Торговая точка",
                            "Склад",
                            "Основание",
                            "Товар найден в справочнике",
                            "Наименование товара из документа",
                            "Наименование товара в УС",
                            "Ед.изм.",
                            "Ед.изм. в УС",
                            "Кол-во из документа",
                            "Кол-во в УС",
                            "Цена за единицу",
                            "Цена в УС",
                            "Стоимость без НДС",
                            "Ставка НДС %",
                            "Сумма НДС",
                            "Общая стоимость",
                            "Сумма накладной",
                            "Дата приема",
                            "Принял, Ф.И.О.",
                            "Госсистемы",
                            "Кол-во в заявке",
                            "Цена по прайсу",
                            "Последняя дата поставки",
                            "Последняя цена",
                            "Отклонение от цены прайса",
                            "Время загрузки документа",
                            "ID документа",
                        ],
                        [
                            "loaded",
                            "reviewed",
                            "",
                            "no",
                            "paper",
                            "1",
                            "2026-07-03",
                            "doc-1",
                            "Supplier",
                            "1234567890",
                            "Recipient",
                            "Main point",
                            "Warehouse",
                            "Basis",
                            "yes",
                            "item-1",
                            "item-us-1",
                            "kg",
                            "pcs",
                            "10",
                            "9",
                            "100",
                            "95",
                            "1000",
                            "20",
                            "200",
                            "1200",
                            "1200",
                            "2026-07-03",
                            "Operator",
                            "GS",
                            "11",
                            "105",
                            "2026-07-04",
                            "110",
                            "-5",
                            "2026-07-03T10:00:00",
                            "doc-id-1",
                        ],
                        [
                            "loaded",
                            "reviewed",
                            "",
                            "no",
                            "paper",
                            "1",
                            "2026-07-03",
                            "doc-1",
                            "Supplier",
                            "1234567890",
                            "Recipient",
                            "Main point",
                            "Warehouse",
                            "Basis",
                            "yes",
                            "item-2",
                            "item-us-2",
                            "kg",
                            "pcs",
                            "20",
                            "18",
                            "200",
                            "190",
                            "2000",
                            "20",
                            "400",
                            "2400",
                            "2400",
                            "2026-07-03",
                            "Operator",
                            "GS",
                            "22",
                            "205",
                            "2026-07-05",
                            "210",
                            "-10",
                            "2026-07-03T10:00:00",
                            "doc-id-1",
                        ],
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
    assert value_update["range"] == "Накладная!A3:AN5"
    written = value_update["body"]["values"]
    assert len(written) == 3
    assert len(written[0]) == 40
    assert written[0][16] == "item-1"
    assert written[0][20] == "10"
    assert written[0][37] == "2026-07-03T10:00:00"
    assert written[0][38] == "doc-id-1"
    assert written[0][39] == "uploads/invoices/test.jpg"
    assert written[1][16] == "item-2"
    assert written[1][20] == "20"
    assert written[1][39] == ""
    assert written[2] == [""] * 40
