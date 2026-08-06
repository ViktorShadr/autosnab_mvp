from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import settings


class DocumentArchiveConfigurationError(RuntimeError):
    pass


@dataclass
class ArchiveUploadResult:
    key: str
    url: str


def _build_s3_client():
    import boto3  # local import: optional dependency, only needed when the archive is enabled

    return boto3.client(
        "s3",
        endpoint_url=settings.document_archive_endpoint_url,
        region_name=settings.document_archive_region,
        aws_access_key_id=settings.document_archive_access_key_id,
        aws_secret_access_key=settings.document_archive_secret_access_key,
    )


def _build_archive_key(*, organization_slug: str, upload_dt: datetime, filename: str) -> str:
    return settings.document_archive_key_prefix_template.format(
        organization_slug=organization_slug,
        yyyy=f"{upload_dt.year:04d}",
        mm=f"{upload_dt.month:02d}",
        dd=f"{upload_dt.day:02d}",
        filename=filename,
    )


def upload_to_archive(
    local_path: str | Path,
    *,
    organization_slug: str | None = None,
    upload_dt: datetime | None = None,
    filename: str | None = None,
) -> ArchiveUploadResult:
    """Upload a local file to the configured S3-compatible document archive
    (Yandex Object Storage by default -- see
    docs/wiki/multi-tenant-provisioning-and-document-archive.md for why Drive
    was rejected).

    Raises DocumentArchiveConfigurationError when archiving isn't configured.
    Callers MUST treat this (and any boto3/network error) as non-fatal: local
    disk stays the working copy, and the recognition pipeline must never fail
    just because the archive is unavailable.
    """
    if not settings.document_archive_enabled:
        raise DocumentArchiveConfigurationError(
            "Электронный архив документов отключен (DOCUMENT_ARCHIVE_ENABLED=false)."
        )
    if not settings.document_archive_bucket:
        raise DocumentArchiveConfigurationError("Не задан DOCUMENT_ARCHIVE_BUCKET.")

    path = Path(local_path)
    key = _build_archive_key(
        organization_slug=organization_slug or settings.document_archive_default_organization_slug,
        upload_dt=upload_dt or datetime.utcnow(),
        filename=filename or path.name,
    )

    client = _build_s3_client()
    client.upload_file(str(path), settings.document_archive_bucket, key)
    url = f"{settings.document_archive_endpoint_url.rstrip('/')}/{settings.document_archive_bucket}/{key}"
    return ArchiveUploadResult(key=key, url=url)
