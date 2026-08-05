import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.services.error_masking_service import GENERIC_MESSAGE, mask_error_for_user  # noqa: E402


def test_masks_sqlalchemy_operational_error_as_a_database_message():
    """Regression test for the 2026-08-05 live batch test: a Postgres DNS failure
    (`psycopg2.OperationalError`, wrapped by SQLAlchemy as `OperationalError`) was sent
    to a Telegram user as a raw traceback. See docs/wiki/invoice-bot-live-batch-test-2026-08-05.md.
    """
    exc = OperationalError(
        "SELECT 1", {}, Exception("could not translate host name to address")
    )

    message = mask_error_for_user(exc)

    assert "could not translate host name" not in message
    assert "OperationalError" not in message
    assert "psycopg2" not in message
    assert "SELECT 1" not in message


def test_masks_openai_module_exception_as_an_ai_message():
    class _FakeOpenAIError(Exception):
        pass

    _FakeOpenAIError.__module__ = "openai"

    message = mask_error_for_user(_FakeOpenAIError("Error code: 403 - unsupported_country_region_territory"))

    assert "403" not in message
    assert "unsupported_country_region_territory" not in message


def test_masks_unknown_exception_with_the_generic_fallback():
    class _WeirdError(Exception):
        pass

    message = mask_error_for_user(_WeirdError("internal detail: /app/uploads/secret.json"))

    assert message == GENERIC_MESSAGE
    assert "/app/uploads" not in message
