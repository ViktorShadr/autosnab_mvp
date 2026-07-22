---
title: Google OAuth Production Readiness Audit (2026-07-22)
source: session
compiled_from:
  - live check against local .env (dev/ngrok OAuth client)
  - live SSH check against VPS 78.17.160.248 /opt/autosnab_mvp/.env (production OAuth client)
  - live test call against team-lead-provided service account key (personal-453020-285299f6b7b6.json)
created: 2026-07-22
updated: 2026-07-22
tags: [google, oauth, service-account, security, production, risk]
status: open
---

# Google OAuth Production Readiness Audit (2026-07-22)

## Question asked
User asked whether the authorization mechanism needs to change before treating
this project as production-ready, specifically for Google Drive OCR and
Google Sheets access (both go through one shared user-OAuth credential — see
`backend/app/services/google_oauth_service.py`).

## Method
- Read `GOOGLE_OAUTH_*` values from the local repo's `.env` (dev machine).
- Attempted a live `refresh_token` grant against `https://oauth2.googleapis.com/token`
  using the local values.
- SSH'd into the production VPS (`78.17.160.248`, granted this session) and
  read the non-secret `GOOGLE_OAUTH_*` fields from `/opt/autosnab_mvp/.env`.
- Attempted a live `refresh_token` grant using the VPS's values, then called
  `https://www.googleapis.com/drive/v3/about?fields=user` with the resulting
  access token to identify the authorized account (the granted scopes are
  `drive` + `spreadsheets` only — no `openid`/`email`/`profile` scope, so the
  standard `oauth2/v3/userinfo` endpoint returns `401` here; `drive/v3/about`
  works instead since it only needs the already-granted `drive` scope).

## Findings

### 1. Two different OAuth Client IDs exist under the same GCP project, undocumented
Both share GCP project number `78170315728`, but are registered as separate
OAuth clients with separate redirect URIs and separate refresh tokens:

| Environment | Client ID (prefix) | Redirect URI | Refresh token status (2026-07-22) |
|---|---|---|---|
| Local dev machine | `78170315728-f3mta4111...` | `https://frequent-scope-scallion.ngrok-free.dev/...` | **Dead** — `invalid_grant: Token has been expired or revoked` |
| Production VPS | `78170315728-ujd06n6ffnvo4t0qai4lu84ciq6nsie4` | `https://78-17-160-248.nip.io:8443/...` | **Alive** — refreshed successfully, `expires_in: 3599`, correct scope |

This split was not previously recorded anywhere in the wiki or runbook. It
explains why the local `.env` copy silently went stale (last touched
2026-07-09) while the VPS kept working independently — there is no single
source of truth for "the" OAuth credential; there are two, and only one is
live and load-bearing.

### 2. Production token is live and correctly scoped
Refreshing the VPS's `GOOGLE_OAUTH_REFRESH_TOKEN` succeeded and returned
scope `https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets`,
matching `GOOGLE_OAUTH_SCOPES` in code. **Production is not currently broken.**

### 3. Authorized account is a personal Gmail account, not a service/org account
`drive/v3/about?fields=user` on the production token resolved to:
- `displayName: Виктор Шадрин`
- `emailAddress: vitek19852007@gmail.com`

This is the developer's own personal Google account, not a dedicated
service account or a company-owned account. Every Drive file created for
OCR and every Sheets write is attributed to this personal identity. Risk:
if this account's password changes, 2FA changes, the app's access is
manually revoked from `myaccount.google.com/permissions`, or the account
is otherwise unavailable, both OCR and Sheets writing break at once for
every user of the bot, not just this one person.

### 4. OAuth consent screen publish status (Testing vs. In production) — not verified
Could not check this from either machine; it requires Google Cloud Console
UI access for the production client
(`78170315728-ujd06n6ffnvo4t0qai4lu84ciq6nsie4`). This matters because Google
caps refresh-token validity at **7 days from issuance** for apps left in
"Testing" publish status, regardless of usage — a real risk if it applies
here, since `drive` (full Drive access) is a sensitive/restricted scope
that normally requires verification to move to "In production" status.
The production token has clearly lived longer than 7 days at some point
(script/session gaps in the wiki log span weeks), which weakly suggests
either the app is already published, or the refresh token has been getting
re-issued periodically in a way that resets the clock — not confirmed
either way. **Open item, needs Cloud Console access to resolve.**

## Recommendation (not yet actioned)
Not an immediate blocker — the mechanism does not need to change to keep
running as-is. Before calling this durable for real client production use:
1. Check the OAuth consent screen publish status in Cloud Console for the
   production client ID above.
2. Consider moving authorization off the developer's personal Gmail onto a
   dedicated Google account (Workspace service account or at minimum a
   separate "bot" Google account) so the integration doesn't depend on one
   person's personal account.
3. Decide whether the dead local/dev OAuth client should be cleaned up or
   re-authorized, and document which client ID is authoritative for which
   environment in `runbook.md` so this doesn't have to be re-discovered.
4. `.env`-as-token-store (plaintext refresh token on disk, rewritten on
   every refresh) is functionally fine for a single-instance deployment but
   is not a secret-management story that scales past one VPS.

## Team-lead-provided service account (2026-07-22) — tested, partial fit

The team lead supplied a Google service account,
`id-698@personal-453020.iam.gserviceaccount.com`, as a candidate to replace
the personal-Gmail OAuth dependency flagged above (finding #3). Verified and
tested live with the JSON key the team lead holds
(`personal-453020-285299f6b7b6.json`, kept local-only, added to `.gitignore`
via `personal-*.json` / `*-service-account*.json` patterns — never committed).

**Identity confirmed by construction, not inference:** any address on the
`*.iam.gserviceaccount.com` domain is guaranteed by Google Cloud IAM to be a
machine service account, never a human-owned account — that domain is not
assignable to personal or Workspace user logins. `personal-453020` is the
owning GCP project ID, distinct from project number `78170315728` that both
existing OAuth clients (finding #1) live under — i.e. this is a separate GCP
project with no inherited access to the target spreadsheet or Drive folder;
sharing has to be set up explicitly regardless of which part of the pipeline
adopts it.

**Google Sheets — fits.** The Sheets write path only edits an existing,
already-shared spreadsheet; it never creates a new file, so the service
account's storage quota (confirmed `0` via `drive.about.get`) is irrelevant
there. Once `google_target_spreadsheet_id` is shared with the service
account email as Editor, `google_sheets_service.py` can authenticate with it
directly.

**Google Drive OCR — does not fit as currently implemented.** Reproduced the
exact call `recognize_invoice_with_google_drive_ocr()` makes
(`ocr_service.py`): `drive.files().create()` with real image bytes as
`media_body`, converting to `application/vnd.google-apps.document`, no
parent folder (matches the live config — `GOOGLE_DRIVE_OCR_FOLDER_ID` is
unset). Result, live and reproducible:

```
403 storageQuotaExceeded:
"The user's Drive storage quota has been exceeded."
```

This is not fixable by pointing at a shared folder: on a non-Workspace
("personal") GCP project like `personal-453020`, a file created via the API
is always owned by the service account that created it, so it's always
charged against the SA's own (zero) quota regardless of whose folder it
lands in. The two standard workarounds — uploading into a **Shared Drive**,
or **domain-wide delegation** to impersonate a real Workspace user — both
require a Google Workspace organization, which a personal-account GCP
project does not have.

**Conclusion:** this service account is usable for Sheets right now, not
for Drive OCR as the OCR mechanism is currently built (upload-and-convert
through Drive). Migrating OCR off the personal Gmail account would require
either a different service account living in a Workspace org, or replacing
the Drive-conversion OCR mechanism itself with something that doesn't need
Drive file ownership — e.g. calling the Vision API directly instead of
uploading through Drive.

**Planned next step (not yet implemented):** split auth by responsibility —
move Google Sheets reads/writes onto the service account, leave Google
Drive OCR on the existing personal-Gmail OAuth credential for now.
