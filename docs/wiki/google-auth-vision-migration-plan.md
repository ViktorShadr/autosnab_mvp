---
title: Google Auth Migration Plan — Service Account for Sheets, Cloud Vision for OCR
source: session
compiled_from:
  - docs/wiki/google-oauth-production-readiness.md (2026-07-22 audit + service-account test)
  - live web research this session (Google IAM best practices, Sheets/Vision API quotas and pricing, Workspace pricing)
  - Explore-agent code trace of live Sheets/Drive/OCR call paths this session
created: 2026-07-22
updated: 2026-07-22
tags: [google, oauth, service-account, vision-api, production, migration-plan]
status: planned
---

# Google Auth Migration Plan — Service Account for Sheets, Cloud Vision for OCR

## Context

The bot is moving to real production use by many end users, and reliability/
simplicity now matters more than during MVP development. The
2026-07-22 audit (`docs/wiki/google-oauth-production-readiness.md`) found the
current mechanism fragile in ways that will bite in production:

- Every Google call (Drive OCR + Sheets) runs through one OAuth2 credential
  authorized against the developer's personal Gmail. If that account's
  password/2FA changes or access is revoked, the whole bot stops working for
  every user at once.
- The OAuth consent screen's publish status (Testing vs. In production) is
  unverified. If it's still "Testing," Google forces refresh-token expiry
  after 7 days regardless of use — a silent production outage waiting to
  happen.
- Two separate, undocumented OAuth Client IDs already exist for dev vs. prod
  under the same GCP project — this drift already caused one dead credential
  this session.
- The team lead supplied a service account
  (`id-698@personal-453020.iam.gserviceaccount.com`). Live-tested: works for
  Sheets, but cannot replace the current Drive-based OCR mechanism — bare
  service accounts have zero Drive storage quota, confirmed live with
  `403 storageQuotaExceeded` when reproducing the real OCR upload call. This
  is structural on a non-Workspace GCP project.
- The standard Google workarounds (Shared Drive, domain-wide delegation) both
  require a paid Workspace **and owning/verifying a custom domain** — a real
  procurement step, not just a subscription toggle.

Team lead is willing to pay for infrastructure. Given that, the simplest and
most reliable direction is to stop depending on Drive entirely: move Sheets
to the service account (confirmed safe by code trace, see below), and move
OCR off the Drive-conversion trick onto the Cloud Vision API — Google's
actual documented OCR product (published quota, published pricing,
synchronous call, no async-conversion race condition), rather than a side
effect of Drive's upload-and-convert feature not intended for bulk
automation. No Workspace subscription needed anywhere.

Only the team lead has Google Cloud Console access to `personal-453020`
(to enable Billing + Vision API, adjust quotas) — hard dependency for the
OCR half of this plan, must be requested from him before Phase 4.

User decision: roll out in phases, not one shot — Sheets migration first
(low risk, proven safe), Vision OCR migration second, only after
side-by-side accuracy validation against real hard documents (the
`Метро.pdf` series from Lilia's feedback rounds).

## Recommended approach

### Two independent toggles, not one auth-mode flip

```python
# backend/app/config.py
google_sheets_auth_mode: str = "oauth"          # "oauth" | "service_account"
google_ocr_provider: str = "google_drive_ocr"   # "google_drive_ocr" | "google_cloud_vision"
google_service_account_json_b64: str | None = None
google_vision_pdf_render_scale: float = 2.0
```

Base64-encoded key in `.env` (not a loose JSON file) — avoids
`python-dotenv`'s handling of a multi-line PEM private key, stays inside the
project's existing "all secrets in `.env`" convention. The existing
`google_auth_mode` field in `config.py` is vestigial (nothing branches on it
today) — left alone; these two new settings supersede it in meaning.

Add `validate_google_auth_configuration()`, called once from `app/main.py`
startup, that fails fast if `google_ocr_provider == "google_cloud_vision"`
without a service-account key configured (or vice versa).

### New files

**`backend/app/services/google_service_account_service.py`**
- `get_google_service_account_credentials(scopes: list[str])`: base64-decode
  + `json.loads` the key, build via
  `google.oauth2.service_account.Credentials.from_service_account_info(...)`.
- `GoogleServiceAccountConfigurationError(RuntimeError)`.

**`backend/app/services/google_credentials_service.py`** (thin dispatcher)
- `get_sheets_credentials()`: branches on `settings.google_sheets_auth_mode`.
  `"oauth"` → existing `google_oauth_service.get_google_user_credentials()`.
  `"service_account"` → new module, scope
  `https://www.googleapis.com/auth/spreadsheets` only (confirmed safe, see
  below).

**`backend/app/services/google_api_retry_service.py`**
- Extract `_execute_google_operation` / `_is_retryable_google_error` out of
  `ocr_service.py` so both the (temporarily kept) Drive path and the new
  Vision path share one retry implementation.

**`backend/app/services/google_vision_ocr_service.py`**
- `recognize_invoice_with_google_vision_ocr(file_path: str) -> dict`, same
  return shape as today's `recognize_invoice_with_google_drive_ocr`.
- Credentials via `google_service_account_service`, scope
  `https://www.googleapis.com/auth/cloud-vision`.
- Call Vision through `googleapiclient.discovery.build("vision", "v1", ...)`
  rather than the separate `google-cloud-vision` SDK — matches how
  `ocr_service.py`/`google_sheets_service.py` already talk to Google, avoids
  a new grpc/protobuf dependency.
- Images: one `images().annotate(...)` call with `DOCUMENT_TEXT_DETECTION`.
- PDFs without a text layer: rasterize each page locally with `pypdfium2`
  (pure-Python wheel, no system Poppler needed), run Vision per page,
  concatenate with a page-break marker so existing sequential regex parsers
  still see page boundaries.

### Modified files

- **`ocr_service.py`**: `recognize_invoice_image()` becomes the dispatcher
  (Drive vs. Vision based on `settings.google_ocr_provider`);
  `document_extraction_service.py` needs zero changes. `OcrProviderError`'s
  hardcoded `provider = "google_drive_ocr"` becomes a constructor parameter.
- **`google_sheets_service.py`**: `_build_google_services()` calls
  `google_credentials_service.get_sheets_credentials()`. Add a guard in the
  dead `_create_invoice_review_spreadsheet` branch for a clear error if
  reactivated under `service_account` mode.
- **`invoice_review_service.py`**: `_read_google_sheet_values()` (~lines
  1265-1272) swaps its inline `get_google_user_credentials()` call for
  `google_credentials_service.get_sheets_credentials()` — this is the iiko
  sync/confirm read-back path; missing this would silently leave that
  traffic on the personal Gmail account.
- **`requirements.txt`**: add `pypdfium2>=4,<5` only (no new heavy SDK).

## Why Sheets-on-service-account is safe (verified, not assumed)

Traced the live call chain: with the confirmed production config
(`GOOGLE_SHEETS_ENABLED=true`, `GOOGLE_TARGET_SPREADSHEET_ID` set),
`create_invoice_review_spreadsheet()` always takes the
`_insert_into_existing_spreadsheet` branch — the new-spreadsheet-creation
branch that touches Drive (`_move_spreadsheet_to_configured_folder`) is dead
code under this config. `_insert_into_existing_spreadsheet` receives a
`drive_service` parameter but never calls anything on it (confirmed by
grep). `load_invoice_reference_catalogs()` and
`sync_incremental_reference_catalogs()` are Sheets-API-only. The only live
Drive-file-creation call in the entire backend is `ocr_service.py`'s
Drive-OCR upload.

## Rollout (phased, matches the existing git-archive + SFTP deploy pattern)

1. Dev, no behavior change — defaults keep current behavior byte-identical. Full `pytest`.
2. Dev smoke test, Sheets only — share dev spreadsheet with the service account, confirm write + iiko read-back.
3. Deploy Sheets-only cutover to prod — share the live target spreadsheet + reference-catalog sheet, verify, let it run a few days before touching OCR.
4. Vision accuracy validation — **blocked on team lead enabling Billing + Vision API on `personal-453020`.** Run known-hard real samples (`Метро.pdf` series, photographed JPGs) through Drive OCR and Vision side by side; compare actual parsed fields, not just "returned text." Only proceed if Vision matches or beats current accuracy.
5. Deploy OCR cutover to prod — flip `GOOGLE_OCR_PROVIDER=google_cloud_vision`, monitor a few days. Keep `GOOGLE_DRIVE_OCR_*`/`GOOGLE_OAUTH_*` env vars in place — rollback is a one-line `.env` edit.
6. Cleanup, 2-4 weeks after step 5 looks stable — remove Drive-OCR code, the async-race-condition retry workarounds, the OAuth flow/router and its upload-page status widget.

## Cost

- Sheets migration: $0 (free API, quota far above realistic bot volume).
- Vision API: first 1,000 units/month free, then $1.50/1,000 up to 5M/month. Real monthly cost unknown — get an actual count of OCR-triggering uploads before quoting the team lead a number, rather than guessing.
- No Workspace subscription needed anywhere in this plan.
- Team lead must enable Cloud Billing + Vision API on `personal-453020` before Phase 4 — only he has console access there.

## Verification

- `pytest backend/tests` after each phase. `test_document_extraction_service.py` needs no changes (monkeypatches `recognize_invoice_image` at the fixture level). `test_ocr_provider.py` stays valid until cleanup. Add `test_google_vision_ocr_service.py`. Add a test asserting `_build_google_services()` calls `get_sheets_credentials()`.
- Manual: one real invoice through the Telegram bot at each deploy step.

## Status

Plan approved by user on 2026-07-22. **Not yet implemented** — explicitly
saved as a plan first, per user request, before any code changes begin.

## Update, 2026-07-28: implemented in full, both Sheets and OCR, on branch `feature/google-service-account-dual-mode`

User found the actual service-account key Pavel had given previously
(`personal-453020-285299f6b7b6.json`, sitting in the repo root, never
registered in `manifests/raw_sources.csv` until this session), and asked to
go further than this plan's original cautious Sheets-only-first phasing:
migrate **both** Sheets and OCR fully onto the service account, since Pavel
confirmed he can enable Cloud Billing for the Vision API (this plan's
stated hard blocker). Implemented with two deliberate deviations from the
design above:

- **Field names differ from this doc's sketch**: `google_sheets_auth_mode`/
  `google_ocr_provider`/`google_service_account_json_b64` (as designed here)
  — implemented exactly as named. The vestigial `google_auth_mode` field is
  left in place, commented as superseded, not removed.
- **No cleanup phase, ever** (deviates from this doc's rollout step 6): the
  user explicitly wants the OAuth+Drive-OCR path to stay permanently
  switchable, not deleted after a stabilization period. Both auth paths are
  designed to coexist in the codebase indefinitely.
- **`google_credentials_service.py`'s `get_sheets_auth_status()`** additionally
  replaced `diadoc_sync_service.py`'s preflight check (previously hardcoded
  to OAuth-user status regardless of which mode Sheets actually used) — a
  gap this design doc didn't originally cover, found via this session's code
  trace.

New/modified files: `google_service_account_service.py`,
`google_api_retry_service.py` (extracted from `ocr_service.py`),
`google_credentials_service.py`, `google_vision_ocr_service.py`;
`ocr_service.py` (provider dispatcher, `OcrProviderError.provider` now a
constructor param), `google_sheets_service.py` (credentials dispatch +
dead-code guard on the Drive-touching new-spreadsheet branch),
`invoice_review_service.py` (`_read_google_sheet_values` credentials swap),
`routers/google_oauth.py` (`/status` now mode-aware), `provider_health_service.py`,
`diadoc_sync_service.py`, `main.py` (fail-fast `validate_google_auth_configuration()`
at startup), `requirements.txt` (+`pypdfium2`). 27 new/updated tests added.
Full suite: 257 passed outside `test_receiving.py`, same 5 pre-existing
failures (`test_document_extraction_service.py` ×3, `test_document_image_preparation.py`
×2) confirmed unrelated. Both new toggles default to today's behavior
(`oauth`/`google_drive_ocr`) — zero behavior change until explicitly flipped
in `.env`.

**Not yet done** (manual steps, deliberately left to the user — never
handled by the assistant, since they involve the actual secret key
material): base64-encoding the key, setting `GOOGLE_SERVICE_ACCOUNT_JSON_B64`
in `.env` (local and VPS), sharing the target/reference Google Sheets with
`id-698@personal-453020.iam.gserviceaccount.com`, Pavel enabling Cloud
Billing + the Vision API on `personal-453020`, the side-by-side OCR
accuracy validation against the `Метро.pdf` series before any production
cutover, and the actual `.env` toggle flips in dev then prod. Branch pushed
locally, not merged, not deployed anywhere yet.
