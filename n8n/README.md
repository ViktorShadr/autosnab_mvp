# n8n Bot MVP

This directory contains the first repository-native scaffold for the Telegram
document-upload bot.

## Files

- `telegram-bot-mvp.workflow.json` - importable n8n workflow scaffold
- `telegram-bot-mvp.env.example` - environment variables expected by the workflow

## Workflow intent

The workflow is intentionally thin:

- Telegram receives commands and files
- n8n stores a lightweight per-chat session
- n8n forwards one logical document to backend
- backend performs OCR/parsing/review-sheet work
- n8n polls backend by `upload_id`
- n8n sends the final short operator result

The workflow must not duplicate parsing or business logic from the backend.

## Expected backend endpoints

- `POST /api/v1/invoice-review/bot/upload-document-live`
- `GET /api/v1/invoice-review/bot/uploads/{upload_id}`

## Current limitations

- The JSON file is a scaffold, not a production-ready full flow.
- Telegram file download and multipart assembly are represented explicitly, but
  credentials, webhook URL, and deployment-specific IDs must be filled in by the operator.
- XML / Excel / QR scenarios still depend on future backend support.
