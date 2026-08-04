"""Push the invoice parser's SYSTEM_PROMPT to Langfuse Prompt Management.

Run this manually whenever SYSTEM_PROMPT changes in
app/services/openai_invoice_parser_service.py, so the "production"-labeled
prompt in Langfuse stays in sync with the code (code remains the source of
truth; Langfuse mirrors it for versioning/observability -- see
get_system_prompt() in app/services/langfuse_tracing_service.py).

Requires LANGFUSE_ENABLED=true and real LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY
in the environment/.env -- this is a one-off maintenance action, not something
the app runs itself.
"""

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.langfuse_tracing_service import LANGFUSE_SYSTEM_PROMPT_NAME  # noqa: E402
from app.services.openai_invoice_parser_service import SYSTEM_PROMPT  # noqa: E402


def main() -> None:
    if not settings.langfuse_enabled or not settings.langfuse_public_key or not settings.langfuse_secret_key:
        raise RuntimeError(
            "Langfuse is not configured (LANGFUSE_ENABLED/LANGFUSE_PUBLIC_KEY/"
            "LANGFUSE_SECRET_KEY) -- set real credentials before pushing a prompt version."
        )

    from langfuse import Langfuse

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    prompt = client.create_prompt(
        name=LANGFUSE_SYSTEM_PROMPT_NAME,
        type="text",
        prompt=SYSTEM_PROMPT,
        labels=["production"],
    )
    print(f"Pushed {LANGFUSE_SYSTEM_PROMPT_NAME!r} version {prompt.version} (label: production).")


if __name__ == "__main__":
    main()
