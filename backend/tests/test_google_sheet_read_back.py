import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.services import invoice_review_service  # noqa: E402
from app.services import google_credentials_service  # noqa: E402


class _FakeValuesGetCall:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeValuesResource:
    def __init__(self, response):
        self._response = response
        self.get_calls = []

    def get(self, spreadsheetId, range):  # noqa: N803, A002 - matches googleapiclient signature
        self.get_calls.append({"spreadsheetId": spreadsheetId, "range": range})
        return _FakeValuesGetCall(self._response)


class _FakeSpreadsheetsResource:
    def __init__(self, response):
        self.values_resource = _FakeValuesResource(response)

    def values(self):
        return self.values_resource


class _FakeSheetsService:
    def __init__(self, response):
        self.spreadsheets_resource = _FakeSpreadsheetsResource(response)

    def spreadsheets(self):
        return self.spreadsheets_resource


def test_read_google_sheet_values_uses_credentials_dispatcher(monkeypatch):
    sentinel_credentials = SimpleNamespace(name="dispatched-credentials")
    fake_service = _FakeSheetsService({"values": [["row1"]]})
    captured_credentials = []

    monkeypatch.setattr(
        google_credentials_service, "get_sheets_credentials", lambda: sentinel_credentials
    )
    monkeypatch.setattr(
        "googleapiclient.discovery.build",
        lambda *args, credentials=None, **kwargs: captured_credentials.append(credentials)
        or fake_service,
    )

    result = invoice_review_service._read_google_sheet_values(
        "sheet-id",
        sheet_name="Накладная",
        header_row_count=2,
        block_start_row=3,
        block_end_row=5,
    )

    assert captured_credentials == [sentinel_credentials]
    assert result["invoices"] == [["row1"]]
    assert fake_service.spreadsheets_resource.values_resource.get_calls == [
        {"spreadsheetId": "sheet-id", "range": "Накладная!A2:AL5"}
    ]
