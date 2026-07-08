# n8n Bot MVP

This directory contains the first repository-native scaffold for the Telegram
document-upload bot.

## Files

- `telegram-bot-mvp.workflow.json` - importable n8n workflow scaffold
- `telegram-bot-mvp.env.example` - environment variables expected by the workflow
- `telegram-bot-workflow-notes.md` - practical assembly notes for the remaining multipart step

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

- The JSON file now freezes the session/status/metadata contract, but the real
  Telegram file download and multipart file attachment still must be wired in n8n.
- Credentials, webhook URL, data-table IDs, and deployment-specific IDs still
  must be filled in by the operator.
- XML / Excel / QR scenarios still depend on future backend support.
