# n8n Bot MVP

This directory contains the first repository-native scaffold for the Telegram
document-upload bot.

## Files

- `telegram-bot-mvp.workflow.json` - importable n8n workflow scaffold
- `telegram-bot-full.workflow.json` - fuller importable workflow with compact Telegram UX, persistent Telegram reply-keyboard buttons, real Telegram file download, multipart backend upload, and durable `Data Table` session storage
- `telegram-bot-mvp.env.example` - environment variables expected by the workflow
- `telegram-bot-workflow-notes.md` - practical assembly notes for the remaining multipart step
- `telegram-bot-node-setup.md` - exact node-by-node UI configuration for the current workflow

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
- Create the `telegram_bot_sessions` Data Table before importing the full workflow; it now uses durable row storage for cross-message document assembly.
- In the full workflow, the first uploaded file can auto-open a chat session; the operator does not have to send `Новый документ` first.
- The full workflow now also exposes clearer user-facing guidance, but without repeating the same long command list after every single event.
- The full workflow now uses a compact Telegram conversation pattern as well: a short home screen, step-specific replies, and disabled `n8n` message attribution on reply nodes so the bot reads like a product flow rather than a debug chat.
- The full workflow now sends a persistent Telegram reply keyboard (`Новый документ`, `Готово`, `Статус`, `Сбросить`) through direct Bot API `sendMessage` calls, so the operator can tap actions instead of typing them manually.
- Some `n8n` instances deny `$env` both in HTTP expressions and in Code nodes. The full workflow now keeps its runtime defaults inside `Normalize Update` instead of relying on env access there; after import, fill `telegramBotToken` and `backendBaseUrl` in that node explicitly.
- If the `n8n` instance denies `$env` access inside node expressions, keep the safer built-in Telegram reply nodes enabled instead of the direct Bot API keyboard workaround.
- XML / Excel / QR scenarios still depend on future backend support.
