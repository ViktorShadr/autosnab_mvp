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
