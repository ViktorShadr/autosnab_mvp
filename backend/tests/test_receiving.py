import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import *  # noqa: F401,F403,E402

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _start_receiving() -> int:
    payload = {
        "request_id": "REQ-1",
        "order_number": "01TCPC4P-000001",
        "venue": "Добрая столовая",
        "supplier": "Питер Кельн",
        "delivery_address": "ул. Тверская",
        "chat_id": "123",
        "user_id": "456",
        "order_items": [
            {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 5, "unit": "шт", "price": 250},
            {"name": "Уксус винный белый PONTI 1 л", "quantity": 1, "unit": "шт", "price": 491.6},
        ],
    }
    response = client.post("/api/v1/receiving/start", json=payload)
    assert response.status_code == 200
    return response.json()["id"]


def test_start_receiving():
    receiving_id = _start_receiving()
    assert receiving_id == 1


def test_compare_invoice_detects_quantity_and_price_mismatch():
    receiving_id = _start_receiving()
    response = client.post(
        f"/api/v1/receiving/{receiving_id}/compare-invoice",
        json={
            "invoice_number": "1056",
            "invoice_date": "2026-06-12",
            "supplier_legal_name": "ООО Питер Кельн",
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 4, "unit": "шт", "price": 250},
                {"name": "Уксус винный белый PONTI 1 л", "quantity": 1, "unit": "шт", "price": 515},
                {"name": "Соус BBQ", "quantity": 1, "unit": "шт", "price": 120},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["quantity_mismatch"] == 1
    assert data["price_mismatch"] == 1
    assert data["extra"] == 1


def test_accounting_payload_after_confirm():
    receiving_id = _start_receiving()
    client.post(
        f"/api/v1/receiving/{receiving_id}/documents",
        json={"file_id": "file_1", "file_type": "photo", "raw_text": "Накладная 1056"},
    )
    client.post(
        f"/api/v1/receiving/{receiving_id}/compare-invoice",
        json={
            "invoice_number": "1056",
            "invoice_date": "2026-06-12",
            "supplier_legal_name": "ООО Питер Кельн",
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 5, "unit": "шт", "price": 250},
                {"name": "Уксус винный белый PONTI 1 л", "quantity": 1, "unit": "шт", "price": 491.6},
            ],
        },
    )
    confirm = client.post(
        f"/api/v1/receiving/{receiving_id}/confirm",
        json={"confirmed": True, "partial": False, "comment": "Все принято"},
    )
    assert confirm.status_code == 200
    payload = client.get(f"/api/v1/receiving/{receiving_id}/accounting-payload")
    assert payload.status_code == 200
    data = payload.json()
    assert data["requestId"] == "REQ-1"
    assert data["invoice"]["number"] == "1056"
    assert len(data["items"]) == 2


def test_accounting_mapping():
    response = client.post(
        "/api/v1/accounting/mappings",
        json={
            "venue": "Добрая столовая",
            "supplier_product_name": "Молоко кокосовое Aroy-D 400 мл",
            "normalized_product_name": "молоко кокосовое",
            "accounting_product_id": "iiko-123",
            "accounting_product_name": "Молоко кокосовое",
            "unit": "шт",
        },
    )
    assert response.status_code == 200
    assert response.json()["accounting_product_id"] == "iiko-123"


def test_mvp2_text_correction_accepts_partial_quantity():
    receiving_id = _start_receiving()
    client.post(
        f"/api/v1/receiving/{receiving_id}/compare-invoice",
        json={
            "invoice_number": "1056",
            "invoice_date": "2026-06-12",
            "supplier_legal_name": "ООО Питер Кельн",
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 4, "unit": "шт", "price": 250},
                {"name": "Уксус винный белый PONTI 1 л", "quantity": 1, "unit": "шт", "price": 491.6},
            ],
        },
    )
    response = client.post(
        f"/api/v1/receiving/{receiving_id}/corrections/text",
        json={"text": "Молоко кокосовое пришло 4 штуки, подтвердить фактическое количество"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    milk = next(item for item in items if "Молоко" in (item["item_name_from_order"] or ""))
    assert milk["status"] == "accepted"
    assert milk["received_quantity"] == 4


def test_mvp2_crossed_out_and_extra_processing():
    receiving_id = _start_receiving()
    response = client.post(
        f"/api/v1/receiving/{receiving_id}/compare-invoice",
        json={
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 5, "unit": "шт", "price": 250},
                {"name": "Соус BBQ", "quantity": 1, "unit": "шт", "price": 120, "crossed_out": True},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["manual_review"] >= 1
    assert any(item["status"] == "crossed_out" for item in data["items"])


def _prepare_confirmed_receiving() -> int:
    receiving_id = _start_receiving()
    client.post(
        f"/api/v1/receiving/{receiving_id}/documents",
        json={"file_id": "file_1", "file_type": "photo", "raw_text": "Накладная 1056"},
    )
    client.post(
        f"/api/v1/receiving/{receiving_id}/compare-invoice",
        json={
            "invoice_number": "1056",
            "invoice_date": "2026-06-12",
            "supplier_legal_name": "ООО Питер Кельн",
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 5, "unit": "шт", "price": 250},
                {"name": "Уксус винный белый PONTI 1 л", "quantity": 1, "unit": "шт", "price": 491.6},
            ],
        },
    )
    confirm = client.post(
        f"/api/v1/receiving/{receiving_id}/confirm",
        json={"confirmed": True, "partial": False, "comment": "Все принято"},
    )
    assert confirm.status_code == 200
    return receiving_id


def test_mvp2_cannot_send_to_accounting_before_confirm():
    receiving_id = _start_receiving()
    send_response = client.post(
        f"/api/v1/accounting/receivings/{receiving_id}/send",
        json={"target_system": "iiko", "dry_run": False},
    )
    assert send_response.status_code == 400
    assert "после подтверждения" in send_response.json()["detail"]


def test_mvp2_dry_run_does_not_mark_sent_to_accounting():
    receiving_id = _prepare_confirmed_receiving()
    send_response = client.post(
        f"/api/v1/accounting/receivings/{receiving_id}/send",
        json={"target_system": "iiko", "dry_run": True, "comment": "Тестовая подготовка"},
    )
    assert send_response.status_code == 200
    assert send_response.json()["status"] == "prepared"
    receiving = client.get(f"/api/v1/receiving/{receiving_id}")
    assert receiving.status_code == 200
    assert receiving.json()["status"] == "confirmed_full"


def test_mvp2_send_to_accounting_and_export_csv():
    receiving_id = _prepare_confirmed_receiving()
    send_response = client.post(
        f"/api/v1/accounting/receivings/{receiving_id}/send",
        json={"target_system": "iiko", "dry_run": False, "comment": "Передано из MVP-2"},
    )
    assert send_response.status_code == 200
    assert send_response.json()["status"] == "sent_mock"
    exports = client.get("/api/v1/accounting/exports")
    assert exports.status_code == 200
    assert len(exports.json()) == 1
    csv_response = client.post("/api/v1/receiving/export/google-sheets-mvp")
    assert csv_response.status_code == 200
    assert csv_response.json()["items_csv"].endswith("priemka_pozicii.csv")


def test_invoice_history_and_html_view():
    receiving_id = _prepare_confirmed_receiving()
    docs = client.get(f"/api/v1/receiving/{receiving_id}/documents")
    assert docs.status_code == 200
    assert len(docs.json()["documents"]) == 1
    document_id = docs.json()["documents"][0]["id"]

    history = client.get("/api/v1/documents/history")
    assert history.status_code == 200
    assert len(history.json()["documents"]) == 1

    page = client.get(f"/api/v1/documents/{document_id}/view")
    assert page.status_code == 200
    assert "Накладная" in page.text
    assert "Добрая столовая" in page.text


def test_iiko_payload_and_send():
    receiving_id = _prepare_confirmed_receiving()
    payload = client.get(f"/api/v1/iiko/receivings/{receiving_id}/payload")
    assert payload.status_code == 200
    assert payload.json()["externalNumber"] == "01TCPC4P-000001"
    assert payload.json()["source"] == "autosnab_iiko_adapter"

    send = client.post(
        f"/api/v1/iiko/receivings/{receiving_id}/send",
        json={"target_system": "iiko", "dry_run": True},
    )
    assert send.status_code == 200
    assert send.json()["status"] == "iiko_prepared"

    exports = client.get("/api/v1/iiko/exports")
    assert exports.status_code == 200
    assert len(exports.json()["exports"]) == 1


def test_discrepancy_analytics_and_supplier_control():
    receiving_id = _start_receiving()
    response = client.post(
        f"/api/v1/receiving/{receiving_id}/compare-invoice",
        json={
            "invoice_number": "1056",
            "invoice_date": "2026-06-12",
            "supplier_legal_name": "ООО Другой поставщик",
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 4, "unit": "шт", "price": 250},
                {"name": "Соус BBQ", "quantity": 1, "unit": "шт", "price": 120},
            ],
        },
    )
    assert response.status_code == 200

    analytics = client.get("/api/v1/analytics/discrepancies")
    assert analytics.status_code == 200
    assert analytics.json()["totals"]["problem_items"] >= 1

    control = client.get("/api/v1/suppliers/control")
    assert control.status_code == 200
    suppliers = control.json()["suppliers"]
    assert suppliers[0]["supplier"] == "Питер Кельн"
    assert suppliers[0]["control_status"] in {"watch", "control_required"}


def test_mvp4_invoice_review_sheet_preview_and_send():
    response = client.post(
        "/api/v1/invoice-review/upload",
        json={
            "file_id": "photo_123",
            "file_type": "photo",
            "file_url": "https://example.test/invoice.jpg",
            "raw_text": "Накладная 777 от 2026-06-19 ООО Питер Кельн",
            "supplier": "Питер Кельн",
            "supplier_legal_name": "ООО Питер Кельн",
            "invoice_date": "2026-06-19",
            "invoice_number": "777",
            "venue": "Добрая столовая",
            "delivery_address": "ул. Тверская",
            "iiko_default_store_id": "STORE-001",
            "iiko_supplier_id": "SUP-001",
            "document_number": "777",
            "incoming_date": "2026-06-19",
            "items": [
                {"name": "Молоко кокосовое Aroy-D 400 мл", "quantity": 5, "unit": "шт", "price": 250, "sum": 1250, "vat": "20%", "product_article": "MILK-001", "amount_unit": "шт", "line_number": 1},
                {"name": "Уксус винный белый PONTI 1 л", "quantity": 1, "unit": "шт", "price": 491.6, "sum": 491.6, "product_article": "VINEGAR-001", "amount_unit": "шт", "line_number": 2},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    review_id = data["review_id"]

    sheet = client.get(f"/api/v1/invoice-review/{review_id}/sheet")
    assert sheet.status_code == 200
    assert sheet.json()["action"]["button_label"] == "Подтвердить и отправить в iiko"
    assert "Товарные позиции" in sheet.json()["sheets"]

    csv_response = client.get(f"/api/v1/invoice-review/{review_id}/sheet.csv")
    assert csv_response.status_code == 200
    assert "Проверка накладной" in csv_response.text

    preview = client.get(f"/api/v1/invoice-review/{review_id}/preview?target_organization=Добрая%20столовая&target_warehouse=Основной%20склад")
    assert preview.status_code == 200
    assert preview.json()["target_system"] == "iiko"
    assert preview.json()["invoice"]["totalSum"] == 1741.6

    send = client.post(
        f"/api/v1/invoice-review/{review_id}/confirm-send",
        json={
            "approved": True,
            "dry_run": False,
            "target_organization": "Добрая столовая",
            "target_warehouse": "Основной склад",
            "target_warehouse_id": "STORE-001",
            "approved_by": "tester@example.test",
            "comment": "Проверено вручную",
        },
    )
    assert send.status_code == 200
    assert send.json()["status"] == "iiko_sent_mock"
    assert send.json()["payload"]["preview"]["target"]["organization"] == "Добрая столовая"
    assert "<document>" in send.json()["payload"]["iikoXml"]


def test_mvp4_requires_manual_approval_before_send():
    response = client.post(
        "/api/v1/invoice-review/upload",
        json={
            "supplier": "Питер Кельн",
            "invoice_date": "2026-06-19",
            "invoice_number": "778",
            "venue": "Добрая столовая",
            "items": [{"name": "Сахар", "quantity": 1, "unit": "шт", "price": 100}],
        },
    )
    assert response.status_code == 200
    review_id = response.json()["review_id"]
    send = client.post(f"/api/v1/invoice-review/{review_id}/confirm-send", json={"approved": False})
    assert send.status_code == 400
    assert "подтвердить" in send.json()["detail"]


def test_mvp4_real_ocr_endpoint_requires_google_vision_credentials():
    response = client.post(
        "/api/v1/invoice-review/upload-photo",
        files={"file": ("invoice.jpg", b"fake image bytes", "image/jpeg")},
        data={"venue": "Добрая столовая", "create_google_sheet": "false"},
    )
    assert response.status_code == 503
    assert "Google Vision OCR" in response.json()["detail"]


def test_mvp4_sync_sheet_corrections_before_iiko_send():
    response = client.post(
        "/api/v1/invoice-review/upload",
        json={
            "supplier": "Питер Кельн",
            "invoice_date": "2026-06-19",
            "invoice_number": "779",
            "venue": "Добрая столовая",
            "items": [{"name": "Сахар", "quantity": 1, "unit": "шт", "price": 100}],
        },
    )
    assert response.status_code == 200
    review_id = response.json()["review_id"]
    send = client.post(
        f"/api/v1/invoice-review/{review_id}/sync-sheet-and-confirm-send",
        json={
            "approved": True,
            "dry_run": False,
            "target_organization": "Добрая столовая",
            "target_warehouse": "Основной склад",
            "target_warehouse_id": "STORE-001",
            "approved_by": "sheet-user@example.test",
            "supplier": "ООО Питер Кельн",
            "supplier_legal_name": "ООО Питер Кельн",
            "invoice_date": "2026-06-19",
            "invoice_number": "779",
            "venue": "Добрая столовая",
            "iiko_default_store_id": "STORE-001",
            "iiko_supplier_id": "SUP-001",
            "items": [
                {"name": "Сахар ванильный", "quantity": 2, "unit": "шт", "price": 110, "sum": 220, "vat": "20%", "product_article": "SUGAR-001", "amount_unit": "шт", "line_number": 1}
            ],
        },
    )
    assert send.status_code == 200
    data = send.json()
    assert data["status"] == "iiko_sent_mock"
    assert data["payload"]["preview"]["items"][0]["name"] == "Сахар ванильный"
    assert data["payload"]["preview"]["items"][0]["quantity"] == 2


def test_mvp4_ai_agent_disabled_falls_back_to_deterministic_parser():
    from app.services.ai_invoice_agent_service import extract_invoice_payload_with_fallback

    raw_text = """
    ООО Питер Кельн
    Накладная №12345 от 19.06.2026
    Молоко кокосовое Aroy-D 400 мл 5 шт 250 1250
    """
    payload = extract_invoice_payload_with_fallback(raw_text, "invoice.jpg")
    assert payload["parser_provider"] == "deterministic_fallback"
    assert payload["supplier"] == "ООО Питер Кельн"
    assert payload["invoice_number"] == "12345"
    assert payload["invoice_date"] == "2026-06-19"
    assert payload["items"][0]["name"] == "Молоко кокосовое Aroy-D 400 мл"


def test_mvp4_ai_agent_upload_photo_response_can_include_parser_metadata(monkeypatch):
    from app.services import ai_invoice_agent_service, ocr_service
    from app.routers import invoice_review as invoice_review_router

    def fake_ocr(_file_path):
        return {
            "provider": "fake_google_vision",
            "raw_text": "ООО Питер Кельн\nНакладная №555 от 19.06.2026\nСахар 2 шт 100 200",
            "pages": 1,
            "confidence": None,
        }

    def fake_ai(raw_text, fallback_filename=None):
        return {
            "parser_provider": "ai_agent",
            "supplier": "ООО Питер Кельн",
            "supplier_legal_name": "ООО Питер Кельн",
            "invoice_number": "555",
            "invoice_date": "2026-06-19",
            "venue": None,
            "delivery_address": None,
            "raw_text": raw_text,
            "items": [
                {
                    "name": "Сахар",
                    "quantity": 2,
                    "unit": "шт",
                    "price": 100,
                    "sum": 200,
                    "vat": None,
                    "comment": "AI Agent parsed",
                    "confidence": 0.91,
                }
            ],
            "parser_notes": ["AI Agent test"],
        }

    monkeypatch.setattr(ocr_service, "recognize_invoice_image", fake_ocr)
    monkeypatch.setattr(invoice_review_router, "recognize_invoice_image", fake_ocr)
    monkeypatch.setattr(ai_invoice_agent_service, "extract_invoice_payload_with_fallback", fake_ai)
    monkeypatch.setattr(invoice_review_router, "extract_invoice_payload_with_fallback", fake_ai)

    response = client.post(
        "/api/v1/invoice-review/upload-photo",
        files={"file": ("invoice.jpg", b"fake image bytes", "image/jpeg")},
        data={"venue": "Добрая столовая", "create_google_sheet": "false"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["parser_provider"] == "ai_agent"
    assert data["ocr"]["provider"] == "fake_google_vision"
    assert data["parser_notes"] == ["AI Agent test"]


def test_mvp4_auto_fills_iiko_fields_from_references(monkeypatch):
    from app.services import iiko_reference_mapping_service

    def fake_context(force_refresh=False):
        return {
            "status": "ready",
            "context": {
                "suppliers": [{"id": "SUP-001", "name": "ООО Питер Кельн", "code": "PK"}],
                "stores": [{"id": "STORE-001", "name": "Добрая столовая"}],
                "products": [{"id": "PROD-001", "name": "Сахар ванильный", "num": "SUGAR-001", "taxCategory": "TAX-20"}],
                "units": [{"id": "шт", "name": "шт", "code": "шт"}],
                "taxes": [{"id": "TAX-20", "name": "НДС 20%", "vatPercent": 20}],
            },
        }

    monkeypatch.setattr(iiko_reference_mapping_service, "get_iiko_reference_context", fake_context)

    response = client.post(
        "/api/v1/invoice-review/upload",
        json={
            "supplier": "Питер Кельн",
            "invoice_date": "2026-06-19",
            "invoice_number": "780",
            "venue": "Добрая столовая",
            "items": [{"name": "Сахар ванильный", "quantity": 2, "unit": "шт", "price": 110}],
        },
    )
    assert response.status_code == 200
    review_id = response.json()["review_id"]
    sheet = client.get(f"/api/v1/invoice-review/{review_id}/sheet")
    assert sheet.status_code == 200
    summary = sheet.json()["sheets"]["Проверка накладной"]
    items = sheet.json()["sheets"]["Товарные позиции"]
    assert "Служебные поля iiko" not in sheet.json()["sheets"]
    assert any(row[0] == "Поставщик" and row[1] == "Питер Кельн" for row in summary)
    assert items[1][1] == "Готово"
    assert items[1][3] == "Сахар ванильный"

    preview = client.get(f"/api/v1/invoice-review/{review_id}/preview")
    assert preview.status_code == 200
    data = preview.json()
    assert data["supplier"]["iikoSupplierId"] == "SUP-001"
    assert data["items"][0]["iikoProductId"] == "PROD-001"
    assert data["items"][0]["productArticle"] == "SUGAR-001"
    assert data["items"][0]["mappingStatus"] == "ready"
