---
title: Runbook
source: session
created: 2026-07-03
updated: 2026-07-03
tags: [runbook, dev, qa, operations]
status: current
---

# Runbook

## Goal

This runbook covers the shortest practical path to:

- start the backend locally
- authorize Google OAuth
- upload a test invoice
- verify Google Sheets writing
- run local checks/tests

## Prerequisites

- Python `3.12` recommended
- access to the repo root
- Google Cloud OAuth client for Drive + Sheets
- edit access to the target Google Spreadsheet if shared-sheet mode is used

## Required files

OAuth files expected by the app:

```text
backend/secrets/oauth-client.json
backend/secrets/oauth-token.json
```

The token file is created after the OAuth flow and does not need to exist before first launch.

## Minimal `.env`

For local SQLite + OCR + Google Sheets:

```env
DATABASE_URL=sqlite:///./autosnab_mvp.db

GOOGLE_AUTH_MODE=oauth
GOOGLE_OAUTH_CLIENT_SECRETS_FILE=backend/secrets/oauth-client.json
GOOGLE_OAUTH_TOKEN_FILE=backend/secrets/oauth-token.json
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/google-oauth/callback

GOOGLE_DRIVE_OCR_ENABLED=true
GOOGLE_DRIVE_OCR_LANGUAGE=ru
GOOGLE_DRIVE_OCR_DELETE_TEMP_FILES=true
GOOGLE_DRIVE_OCR_FOLDER_ID=

GOOGLE_SHEETS_ENABLED=true
GOOGLE_APPS_SCRIPT_ENABLED=false
GOOGLE_DRIVE_FOLDER_ID=
PUBLIC_API_BASE_URL=http://localhost:8000
UPLOADED_INVOICES_DIR=uploads/invoices

IIKO_INTEGRATION_ENABLED=false
IIKO_BASE_URL=
IIKO_LOGIN=
IIKO_PASSWORD_SHA1=
IIKO_TOKEN=
IIKO_TIMEOUT_SECONDS=30
IIKO_AUTO_MAPPING_ENABLED=true
IIKO_MAPPING_MIN_CONFIDENCE=0.72
```

## Shared-sheet mode

If new invoices must be inserted into one existing operator spreadsheet instead of creating a new spreadsheet per invoice, also set:

```env
GOOGLE_TARGET_SPREADSHEET_ID=<google_spreadsheet_id>
GOOGLE_TARGET_SHEET_NAME=Накладная
GOOGLE_TARGET_HEADER_ROW_COUNT=2
```

Behavior in this mode:

- backend writes into the existing sheet
- the newest invoice block is inserted directly below the header rows
- one empty separator row is inserted after each document block

## Local start

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

Useful URLs:

```text
http://localhost:8000/ping
http://localhost:8000/docs
http://localhost:8000/api/v1/invoice-review/upload-page
```

## Docker start

From the repo root:

```bash
docker compose build --no-cache
docker compose up
```

Notes:

- `docker-compose.yml` mounts `backend/secrets` and `backend/uploads`
- `.env` is loaded into the backend container
- current Docker setup still points one env override at `GOOGLE_SERVICE_ACCOUNT_FILE`, but the active Google flow in code is OAuth-user based

## Google OAuth setup

In Google Cloud:

1. Enable `Google Drive API`
2. Enable `Google Sheets API`
3. Create OAuth client type `Web application`
4. Add redirect URI:

```text
http://localhost:8000/api/v1/google-oauth/callback
```

Save the OAuth client JSON to:

```text
backend/secrets/oauth-client.json
```

Then open:

```text
http://localhost:8000/api/v1/google-oauth/authorize
```

After successful login, the app should create:

```text
backend/secrets/oauth-token.json
```

Quick status check:

```text
http://localhost:8000/api/v1/google-oauth/status
```

## Smoke test: invoice upload

### Browser flow

1. Open `http://localhost:8000/api/v1/invoice-review/upload-page`
2. Upload a JPG, PNG, or PDF invoice
3. Wait for OCR + parser + DB save
4. Confirm that the response shows either:
   - a Google Spreadsheet link
   - or a manual-review fallback with an OCR warning

### Curl flow

```bash
curl -X POST "http://localhost:8000/api/v1/invoice-review/upload-photo" \
  -F "file=@invoice.jpg" \
  -F "create_google_sheet=true" \
  -F "public_api_base_url=http://localhost:8000"
```

Expected response shape:

- `review_id`
- `status`
- `csv_path`
- `google_spreadsheet_id` / `google_spreadsheet_url` when Sheets succeeded
- `parser_provider`
- `parser_notes`

## Smoke test: shared-sheet prepend behavior

Use this only when `GOOGLE_TARGET_SPREADSHEET_ID` is configured.

1. Open the target spreadsheet
2. Confirm the target sheet exists, usually `Накладная`
3. Confirm the first `2` rows are the fixed header area if `GOOGLE_TARGET_HEADER_ROW_COUNT=2`
4. Upload one invoice
5. Check that:
   - the new document block starts directly under the header rows
   - old rows moved down
   - there is one empty row after the new document block
6. Upload a second invoice
7. Check that:
   - the second upload appears above the first one
   - document blocks are visually separated by an empty row

## Smoke test: send flow

1. Open the created review/send page:

```text
http://localhost:8000/api/v1/invoice-review/<review_id>/send-page
```

2. Verify that the backend can read the edited Google Sheet
3. Run send in dry/mock mode first with:

- `IIKO_INTEGRATION_ENABLED=false`

Expected result:

- payload is prepared and saved as an export record
- no real iiko call is required

## Local checks

Wiki checks:

```bash
python3 scripts/wiki_check.py
python3 scripts/raw_manifest_check.py
```

Python syntax spot-check:

```bash
python3 -m py_compile backend/app/config.py backend/app/services/google_sheets_service.py backend/app/services/invoice_review_service.py
```

Unit tests:

```bash
cd backend
python3 -m pytest
```

If `pytest` or other Python packages are missing, reinstall:

```bash
pip install -r backend/requirements.txt
```

## Known pitfalls

- if OAuth is not completed, Google OCR and Google Sheets creation will fail
- if the OAuth token is expired/revoked, re-run `/api/v1/google-oauth/authorize`
- if shared-sheet mode is enabled but the target sheet name is wrong, sheet writing will fail
- if the target spreadsheet is not shared with the authorized Google user, API writes will fail
- if dev dependencies are missing from the shell, `pytest` will not run even when the app code itself is fine

## Current MVP focus

The current priority is not the whole product surface. The runbook is optimized for the downloaded-invoice -> validation-table MVP.
