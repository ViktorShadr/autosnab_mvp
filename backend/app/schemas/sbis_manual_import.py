from pydantic import BaseModel, Field


class SbisManualLoginRequest(BaseModel):
    login: str
    password: str
    account_number: str | None = None


class SbisManualLoginResponse(BaseModel):
    ok: bool = True
    login: str


class SbisManualSessionStatusResponse(BaseModel):
    logged_in: bool
    login: str | None = None


class SbisManualDocumentSummary(BaseModel):
    sbis_document_id: str
    document_type: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    title: str | None = None
    counterparty_name: str | None = None
    counterparty_inn: str | None = None
    recipient_name: str | None = None
    recipient_inn: str | None = None
    amount: str | None = None
    attachment_count: int = 0
    has_target_attachment: bool = False


class SbisManualDocumentListResponse(BaseModel):
    documents: list[SbisManualDocumentSummary] = Field(default_factory=list)
    truncated: bool = False
    pages_fetched: int = 0


class SbisManualImportResultResponse(BaseModel):
    sbis_document_id: str
    success: bool
    stage: str | None = None
    error: str | None = None
    receiving_id: int | None = None
    spreadsheet_url: str | None = None
