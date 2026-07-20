from pydantic import BaseModel, Field


class SbisStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    last_sync_at: str | None = None
    cursor_present: bool = False
    last_error: str | None = None
    scheduler_enabled: bool = False
    sync_interval_seconds: int = 0
    document_types: list[str] = Field(default_factory=list)
    retry_queue_size: int = 0
    delivery_queue_size: int = 0
    dead_letter_count: int = 0
    delivery_dead_letter_count: int = 0


class SbisSyncResponse(BaseModel):
    status: str
    pages_received: int = 0
    events_received: int = 0
    documents_discovered: int = 0
    documents_processed: int = 0
    documents_downloaded: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    documents_retried: int = 0
    documents_recovered: int = 0
    deliveries_retried: int = 0
    deliveries_recovered: int = 0
    deliveries_failed: int = 0
    artifacts_downloaded: int = 0
    review_ids: list[int] = Field(default_factory=list)
    next_cursor_present: bool = False
