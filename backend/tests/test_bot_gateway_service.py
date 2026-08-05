import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.models import *  # noqa: F401,F403,E402
from app.services import bot_gateway_service  # noqa: E402

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


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def uploads_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "uploaded_invoices_dir", str(tmp_path))
    yield tmp_path


def test_append_draft_page_creates_draft_then_accumulates(db):
    first = bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-1",
        source_user_id="tg-1",
        source_username="operator",
        filename="page-1.jpg",
        content_type="image/jpeg",
        file_bytes=b"first",
    )
    assert first.status == "collecting"
    assert first.pages_count == 1

    second = bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-1",
        source_user_id="tg-1",
        source_username="operator",
        filename="page-2.jpg",
        content_type="image/jpeg",
        file_bytes=b"second",
    )
    assert second.upload_id == first.upload_id
    assert second.pages_count == 2
    assert second.filenames == ["page-1.jpg", "page-2.jpg"]


def test_append_draft_page_rejects_unsupported_format(db):
    result = bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-2",
        source_user_id="tg-1",
        source_username=None,
        filename="invoice.xml",
        content_type="application/xml",
        file_bytes=b"<xml/>",
    )
    assert result.status == "unsupported_format"
    assert result.pages_count == 0
    assert bot_gateway_service.get_draft_status(db, "chat-2").draft is None


def test_append_draft_page_rejects_empty_file(db):
    with pytest.raises(ValueError):
        bot_gateway_service.append_draft_page(
            db,
            chat_id="chat-3",
            source_user_id="tg-1",
            source_username=None,
            filename="page-1.jpg",
            content_type="image/jpeg",
            file_bytes=b"",
        )
    # The draft journal row is created before the per-file size check runs (ported
    # verbatim from the original endpoint), so a rejected first page still leaves
    # behind an open draft with 0 pages rather than no draft at all.
    draft = bot_gateway_service.get_draft_status(db, "chat-3").draft
    assert draft is not None
    assert draft.pages_count == 0


def test_get_draft_status_returns_none_when_no_draft(db):
    assert bot_gateway_service.get_draft_status(db, "chat-missing").draft is None


def test_reset_draft_clears_pages_and_is_a_safe_no_op_when_absent(db):
    bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-4",
        source_user_id="tg-1",
        source_username=None,
        filename="page-1.jpg",
        content_type="image/jpeg",
        file_bytes=b"first",
    )
    result = bot_gateway_service.reset_draft(db, "chat-4")
    assert result.status == "reset"
    assert bot_gateway_service.get_draft_status(db, "chat-4").draft is None

    no_op = bot_gateway_service.reset_draft(db, "chat-4")
    assert no_op.status == "no_active_draft"


def test_finalize_draft_raises_when_no_pages(db):
    with pytest.raises(ValueError):
        bot_gateway_service.finalize_draft(db, "chat-empty")


def test_finalize_draft_starts_background_processing_and_updates_journal(db, monkeypatch):
    captured = {}

    def fake_background(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(bot_gateway_service, "_process_bot_upload_background", fake_background)

    bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-5",
        source_user_id="tg-1",
        source_username=None,
        filename="page-1.jpg",
        content_type="image/jpeg",
        file_bytes=b"first",
    )
    accepted = bot_gateway_service.finalize_draft(db, "chat-5", create_google_sheet=False)

    assert accepted.status == "accepted_for_processing"
    assert accepted.files_count == 1
    assert accepted.trace_id
    assert captured["upload_id"] == accepted.upload_id
    assert captured["file_names"] == ["page-1.jpg"]
    assert bot_gateway_service.get_draft_status(db, "chat-5").draft is None


def test_get_latest_upload_status_returns_none_when_no_history(db):
    assert bot_gateway_service.get_latest_upload_status(db, "chat-never-uploaded") is None


def test_get_upload_status_raises_for_unknown_upload_id(db):
    with pytest.raises(ValueError):
        bot_gateway_service.get_upload_status(db, "bot-upload-does-not-exist")


def test_quality_rejected_status_asks_for_replacement():
    message = bot_gateway_service._bot_status_message("quality_rejected", None)

    assert "После автоматического улучшения" in message
    assert "Замените скан" in message
    assert "перефотографируйте" in message


def test_background_marks_quality_rejection_for_bot(db, monkeypatch):
    from fastapi import HTTPException

    from app.routers import invoice_review

    draft = bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-quality",
        source_user_id="tg-quality",
        source_username=None,
        filename="blurred.jpg",
        content_type="image/jpeg",
        file_bytes=b"image",
    )

    def reject_quality(**_kwargs):
        raise HTTPException(
            status_code=422,
            detail={
                "error_message": (
                    "Качество фотографии недостаточно. "
                    "Замените скан или перефотографируйте документ."
                ),
                "error_code": "image_quality_rejected",
            },
        )

    monkeypatch.setattr(bot_gateway_service, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(invoice_review, "_process_invoice_upload", reject_quality)

    bot_gateway_service._process_bot_upload_background(
        trace_id="trace-quality",
        upload_id=draft.upload_id,
        file_paths=[str(Path(settings.uploaded_invoices_dir) / "unused.jpg")],
        file_names=["blurred.jpg"],
        file_types=["image/jpeg"],
        create_google_sheet=False,
        extraction_method="openai",
        public_api_base_url="http://test",
    )

    db.expire_all()
    status = bot_gateway_service.get_upload_status(db, draft.upload_id)
    assert status.status == "quality_rejected"
    assert status.completed is True
    assert "Замените скан" in status.message


def test_background_masks_raw_exception_and_logs_it_for_bot(db, monkeypatch, caplog):
    """Regression test for the 2026-08-05 live batch test: a Postgres DNS failure
    reached the user as a raw `(psycopg2.OperationalError) could not translate host
    name...` traceback, and nothing was logged server-side to notice it happened.
    See docs/wiki/invoice-bot-live-batch-test-2026-08-05.md.
    """
    from sqlalchemy.exc import OperationalError

    from app.routers import invoice_review

    draft = bot_gateway_service.append_draft_page(
        db,
        chat_id="chat-db-outage",
        source_user_id="tg-db-outage",
        source_username=None,
        filename="invoice.jpg",
        content_type="image/jpeg",
        file_bytes=b"image",
    )

    def raise_db_outage(**_kwargs):
        raise OperationalError(
            "SELECT 1", {}, Exception("could not translate host name to address: Temporary failure in name resolution")
        )

    monkeypatch.setattr(bot_gateway_service, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(invoice_review, "_process_invoice_upload", raise_db_outage)

    import logging

    with caplog.at_level(logging.ERROR, logger="app.services.bot_gateway_service"):
        bot_gateway_service._process_bot_upload_background(
            trace_id="trace-db-outage",
            upload_id=draft.upload_id,
            file_paths=[str(Path(settings.uploaded_invoices_dir) / "unused.jpg")],
            file_names=["invoice.jpg"],
            file_types=["image/jpeg"],
            create_google_sheet=False,
            extraction_method="openai",
            public_api_base_url="http://test",
        )

    db.expire_all()
    status = bot_gateway_service.get_upload_status(db, draft.upload_id)
    assert status.status == "processing_error"
    assert "could not translate host name" not in status.message
    assert "psycopg2" not in status.message
    assert "OperationalError" not in status.message

    assert any("could not translate host name" in record.getMessage() for record in caplog.records) or any(
        record.exc_info for record in caplog.records
    )
