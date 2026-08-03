import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client: Any | None = None
_client_init_attempted = False


def _get_client() -> Any | None:
    """Lazily create the Langfuse client. Returns None (and stays None for the
    rest of the process) if tracing is disabled, credentials are missing, or
    the SDK fails to initialize -- callers must treat None as "tracing is a
    no-op", never as an error to surface to the invoice-parsing pipeline."""
    global _client, _client_init_attempted
    if not settings.langfuse_enabled:
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    if _client_init_attempted:
        return _client
    _client_init_attempted = True
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:  # noqa: BLE001 - tracing must never break invoice parsing
        logger.exception("Failed to initialize Langfuse client; tracing disabled for this process.")
        _client = None
    return _client


def start_invoice_generation(*, trace_input: dict[str, Any], model: str) -> Any | None:
    """Start a Langfuse "generation" observation for one invoice-parse call.
    Returns None if tracing is off/unavailable; the returned handle (or None)
    must be passed to finish_invoice_generation regardless."""
    client = _get_client()
    if client is None:
        return None
    try:
        return client.start_observation(name="invoice-parse", as_type="generation", input=trace_input, model=model)
    except Exception:  # noqa: BLE001 - tracing must never break invoice parsing
        logger.exception("Langfuse tracing failed while starting the invoice-parse observation.")
        return None


def finish_invoice_generation(
    generation: Any | None,
    *,
    output: Any | None = None,
    usage: dict[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Record the result of an invoice-parse call and close the observation.
    A no-op if generation is None (tracing was off/unavailable at start)."""
    if generation is None:
        return
    try:
        if error is not None:
            generation.update(level="ERROR", status_message=error)
        else:
            generation.update(output=output, usage_details=usage, metadata=metadata)
    except Exception:  # noqa: BLE001 - tracing must never break invoice parsing
        logger.exception("Langfuse tracing failed while recording the invoice-parse result.")
    finally:
        try:
            generation.end()
        except Exception:  # noqa: BLE001 - tracing must never break invoice parsing
            logger.exception("Langfuse tracing failed while closing the invoice-parse observation.")


def usage_details_from_openai_response(response: Any) -> dict[str, int] | None:
    """Map an OpenAI Responses-API usage object to Langfuse's usage_details shape."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "input": getattr(usage, "input_tokens", 0) or 0,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "total": getattr(usage, "total_tokens", 0) or 0,
    }
