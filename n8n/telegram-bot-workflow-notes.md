# Telegram Bot Workflow Notes

## What changed in the workflow scaffold

The workflow is now structured around four explicit layers:

- session lifecycle
- finalize/upload contract assembly
- upload outcome mapping
- status outcome mapping

That makes the next implementation step narrower: wire Telegram file download
and binary multipart upload into the already fixed contract.

## The main remaining implementation gap

`Upload To Backend Contract` still needs real file binaries.

The current workflow already prepares:

- `source_channel`
- `document_kind`
- `source_user_id`
- `source_username`
- `source_chat_id`
- `organization_name`
- `point_name`
- `create_google_sheet`
- `extraction_method`

What must still be added in the target n8n instance:

1. Call Telegram `getFile` for each stored `fileId`.
2. Download each file as binary.
3. Attach those binaries as repeated `files[]` multipart parts to the backend
   upload request.
4. Preserve page order from `files_json`.

## Recommended next concrete edits in n8n UI

1. Insert a `Split In Batches` loop between `Prepare Finalize` and `Upload To Backend Contract`.
2. For each stored file, call Telegram `getFile`.
3. Download binary from `https://api.telegram.org/file/bot<TOKEN>/<file_path>`.
4. Merge binaries back into one item before the upload node.
5. Configure the HTTP upload node to send repeated `files` form parts plus the
   already prepared metadata fields.

## Why this split is deliberate

The hardest part of n8n assembly here is not business logic. It is the binary
transport shape from Telegram into a multipart backend request. By freezing the
metadata/status/session contract first, that remaining task is isolated.
