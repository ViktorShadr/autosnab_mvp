from __future__ import annotations

from app.schemas.invoice_review import InvoiceReviewCreateRequest
from app.services.fns_upd_xml_parser_service import parse_fns_invoice_xml


def parse_diadoc_invoice_xml(content: bytes, *, file_id: str, file_url: str | None = None) -> InvoiceReviewCreateRequest:
    return parse_fns_invoice_xml(content, file_id=file_id, file_url=file_url, provider="diadoc")
