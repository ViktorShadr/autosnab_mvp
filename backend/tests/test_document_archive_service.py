import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.config import settings  # noqa: E402
from app.services import document_archive_service  # noqa: E402
from app.services.document_archive_service import (  # noqa: E402
    DocumentArchiveConfigurationError,
    _build_archive_key,
    upload_to_archive,
)


@pytest.fixture(autouse=True)
def _restore_archive_settings():
    original = {
        "document_archive_enabled": settings.document_archive_enabled,
        "document_archive_bucket": settings.document_archive_bucket,
        "document_archive_default_organization_slug": settings.document_archive_default_organization_slug,
    }
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_build_archive_key_matches_year_month_day_template():
    from datetime import datetime

    key = _build_archive_key(
        organization_slug="cafe-romashka",
        upload_dt=datetime(2026, 7, 5, 10, 30, 0),
        filename="накладная.jpg",
    )
    assert key == "cafe-romashka/2026/07/05/накладная.jpg"


def test_upload_to_archive_raises_when_disabled():
    settings.document_archive_enabled = False

    with pytest.raises(DocumentArchiveConfigurationError):
        upload_to_archive("uploads/invoices/test.jpg")


def test_upload_to_archive_raises_when_bucket_missing():
    settings.document_archive_enabled = True
    settings.document_archive_bucket = None

    with pytest.raises(DocumentArchiveConfigurationError):
        upload_to_archive("uploads/invoices/test.jpg")


def test_upload_to_archive_uploads_and_returns_key_and_url(monkeypatch, tmp_path):
    settings.document_archive_enabled = True
    settings.document_archive_bucket = "autosnab-archive"
    settings.document_archive_default_organization_slug = "cafe-romashka"

    local_file = tmp_path / "invoice.jpg"
    local_file.write_bytes(b"fake-image-bytes")

    uploaded = []

    class _FakeS3Client:
        def upload_file(self, filename, bucket, key):
            uploaded.append((filename, bucket, key))

    monkeypatch.setattr(document_archive_service, "_build_s3_client", lambda: _FakeS3Client())

    from datetime import datetime

    result = upload_to_archive(
        local_file,
        organization_slug="cafe-romashka",
        upload_dt=datetime(2026, 7, 5, 10, 30, 0),
        filename="invoice.jpg",
    )

    assert uploaded == [(str(local_file), "autosnab-archive", "cafe-romashka/2026/07/05/invoice.jpg")]
    assert result.key == "cafe-romashka/2026/07/05/invoice.jpg"
    assert result.url == (
        "https://storage.yandexcloud.net/autosnab-archive/cafe-romashka/2026/07/05/invoice.jpg"
    )
