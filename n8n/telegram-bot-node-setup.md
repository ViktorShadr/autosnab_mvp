# Telegram Bot MVP Setup

This guide matches `n8n/telegram-bot-mvp.workflow.json`.

The workflow is already filled as far as possible for direct import.

## One-time prerequisites

### 1. Create Telegram credential

Create one Telegram credential in `n8n` and attach it to:

- `Telegram Trigger`

The workflow uses direct Bot API HTTP calls for messages and keyboards, so the
credential is only needed on the trigger node.

### 2. Create the Data Table

Create a Data Table named `telegram_bot_sessions`.

Recommended columns:

- `chat_id` - text
- `user_id` - text
- `username` - text
- `status` - text
- `files_json` - text
- `organization_name` - text
- `point_name` - text
- `backend_upload_id` - text
- `backend_trace_id` - text

## Required edits after import

Only one node must be edited for runtime constants:

- `Workflow Config`

Fill these values in that node:

- `telegramBotToken`
- `backendBaseUrl`
- `defaultOrganizationName` if needed
- `defaultPointName` if needed
- `pollIntervalSeconds` if you want slower/faster status polling
- `pollMaxAttempts` if you want a longer/shorter auto-wait window

For cloud `n8n`:

- set `backendBaseUrl` to the public HTTPS URL of the local backend, for example `https://example.ngrok-free.app`
- do not use `http://host.docker.internal:8000` there; that works only for a local `n8n` container on the same machine

## Runtime behavior

The imported workflow already does this:

- accepts photo, scan, or PDF from Telegram
- stores uploaded pages in `telegram_bot_sessions`
- asks the user whether more pages will be added
- uses button `Продолжить` to finalize one logical document
- uploads files to `POST /api/v1/invoice-review/bot/upload-document-live`
- polls `GET /api/v1/invoice-review/bot/uploads/{upload_id}`
- sends the final result back to Telegram automatically

## Bot UX

The keyboard is fixed in the workflow:

- `Продолжить`
- `Статус`
- `Новый документ`
- `Сбросить`

The user is never expected to type confirmation text manually.

## Important boundary

The bot does not choose OCR, MinerU, OpenAI, or any parsing mode.

The workflow sends the document to backend as one logical document and waits
for the backend result. Parser selection remains entirely on backend side.
