# n8n Bot MVP

This directory now contains one importable Telegram bot workflow for the MVP.

## Files

- `telegram-bot-mvp.workflow.json` - importable workflow with config node, Telegram file download, multipart backend upload, durable `Data Table` session storage, and automatic backend status polling
- `telegram-bot-node-setup.md` - minimal setup notes for import and one-time prerequisites

## Workflow intent

The workflow is intentionally thin:

- Telegram accepts pages of one document
- `n8n` stores a lightweight per-chat draft in `telegram_bot_sessions`
- the user finishes the logical document with button `Продолжить`
- `n8n` forwards the document to backend
- backend decides how to parse and process it
- `n8n` only relays processing state and final result back to Telegram

The bot must not duplicate OCR, parser, or review business logic from backend.

## Expected backend endpoints

- `POST /api/v1/invoice-review/bot/upload-document-live`
- `GET /api/v1/invoice-review/bot/uploads/{upload_id}`

## Current import assumptions

- Create the `telegram_bot_sessions` Data Table before import.
- Attach a Telegram credential to `Telegram Trigger`.
- Fill runtime constants in the `Workflow Config` node.
- The workflow does not use `$env`; all deployment-specific values live in the config node itself.
- For cloud `n8n`, `backendBaseUrl` must be a public HTTPS URL of your local backend, for example an `ngrok` tunnel.

## User-facing behavior

- The first file can start a new document automatically.
- After each page, the bot asks whether more pages will follow.
- The user finishes the document with button `Продолжить`, not by typing free-form confirmation.
- While backend is working, the bot sends a processing message and then polls the backend automatically.
- On success, the bot sends a short parsed summary plus the Google Sheets link returned by backend.
- On backend failure, the bot sends the backend error text to the user.

## Remaining product boundary

XML / Excel / QR scenarios still depend on future backend support and are not
handled in this MVP workflow.
