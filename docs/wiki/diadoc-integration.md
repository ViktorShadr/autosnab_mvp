---
title: Diadoc (Kontur) EDO Integration
source: session
created: 2026-07-20
updated: 2026-07-20
tags: [integration, diadoc, edo, upstream-main]
status: merged-into-over_version
---

# Diadoc (Kontur) EDO Integration

## Status

Originally found in code on `upstream/main` (colleague Andrey Gomzikov, commits `a2f1ebb`/`8b9b4c1`/`0d0fd63`, dated 2026-07-20 in commit metadata but landed 2026-07-19 through 2026-07-20 per his own `log.md`). `upstream/main`'s git history itself was reset that day (`003b736 Clean main branch` deletes nearly everything, then `a2f1ebb` re-adds a full snapshot in one commit) — `main` is no longer a simple fast-forward of earlier `main` history, and a plain `git merge upstream/main` into `over_version` produces real conflicts in ~10 files (confirmed via `git merge-tree`).

Transplanted onto local branch `diadoc-integration` (branched from `over_version` at `8a1b236`, commit `df70966`): only the Diadoc-specific files were ported (`models/diadoc.py`, `routers/diadoc.py`, `schemas/diadoc.py`, `services/diadoc_*.py`, `scripts/migrate_diadoc_reliability.py`, `tests/test_diadoc_*.py`), plus the minimal additive wiring `main.py`/`config.py`/`models/__init__.py`/`.env.example` needed to register the scheduler and router.

**Correction (2026-07-20, later session):** the two wiki-only commits that followed the transplant (`c33de9a`, `896f263`) described this as done/verified but never actually merged `diadoc-integration` into `over_version` itself — `git cat-file -e HEAD:backend/app/services/diadoc_client.py` confirmed the file was genuinely absent from `over_version`'s tree despite the wiki claim. Caught and fixed in this session: `git merge diadoc-integration` (clean, no conflicts, as the merge-tree check had predicted) is now actually on `over_version`. Re-verified after the real merge: `test_diadoc_*.py` + `test_google_sheets_service.py` = 29/29 passing, full suite = 181 passed / 8 failed (identical pre-existing `test_receiving.py` failures, zero new ones). Diadoc code is now genuinely present and tested on `over_version`, not just documented as such.

## What it does (per Andrey's own wiki page, copied verbatim below with light trimming)

After FastAPI starts, a built-in scheduler polls the Diadoc inbound feed via `V8/GetNewEvents` (interval `DIADOC_SYNC_INTERVAL_SECONDS`, default 300s). Processing chain:

1. Fetch inbound events, persist `afterIndexKey`.
2. Fetch message metadata via `V6/GetMessage`.
3. Download entity content via `V4/GetEntityContent`.
4. Save XML/PDF/images/other attachments under `uploads/diadoc/<message_id>/`.
5. Parse formalized XML directly, or run the general extraction pipeline for PDF/images.
6. Look up an existing order by the basis-document number; if found, run comparison, otherwise create a manual-review card.
7. Queue independent delivery tasks: printable PDF form + Google Sheets write.
8. Retry transient failures with exponential backoff; exhausted attempts go to `dead_letter`.

Reliability: business parsing is decoupled from external delivery (a document can be parsed successfully even if Google Sheets/PDF delivery is temporarily down), a `diadoc_deliveries` table tracks delivery state, `diadoc_leases` prevents concurrent multi-worker sync, late attachments attach to an already-created card, Google Sheets writes are idempotent (`ID документа` check).

OIDC Authorization Code Flow: `GET /api/v1/diadoc/oauth/{authorize,callback,status}`, `POST /api/v1/diadoc/oauth/logout`. Scheduler starts immediately after OAuth callback — no backend restart required. Admin endpoints (`/status`, `/sync`, `/retry`, `/dead-letter/*`, `/organizations`) are gated by header `X-Diadoc-Api-Key` (falls back to `BOT_API_SHARED_SECRET` if unset; open if both unset — local-dev convenience only).

New code: `backend/app/models/diadoc.py`, `backend/app/routers/diadoc.py`, `backend/app/schemas/diadoc.py`, `backend/app/services/diadoc_client.py`, `diadoc_oauth_service.py`, `diadoc_scheduler_service.py`, `diadoc_sync_service.py` (1582 lines), `diadoc_xml_parser_service.py`, plus `backend/scripts/migrate_diadoc_reliability.py`. ~15 new/updated test files including `test_diadoc_*`. Andrey's own log claims a full backend suite run of 187 passed as of 2026-07-20, with the caveat that a real Diadoc mailbox smoke test with live credentials was still outstanding (no live credentials available in his session either).

Full env var list and first-run steps: see the "Environment variables" / "First run" sections this page inherits from `upstream/main:docs/wiki/diadoc-integration.md` — re-fetch that file directly (`git show upstream/main:docs/wiki/diadoc-integration.md`) rather than trusting a stale copy here if planning an actual deployment.

## Known gap found during 2026-07-20 review, resolved by the transplant

`upstream/main`'s `SHARED_INVOICE_HEADERS` in `google_sheets_service.py` was still the **old 41-column contract** (`"Товар найден в справочнике"`, `"Кол-во в упаковке"`, no `"Код товара УС"`/`"ID строки"`), and `_detect_document_form_from_text` still had the `"ТОРГ-12"`/`"Счет-фактура"` regression that `over_version` fixed twice (`e1e07e2`, re-applied as `55c1023` after `d063b31` silently reverted it). If Diadoc's Sheets delivery had been pointed at the real production sheet using `main`'s versions of those functions, it would have hit the same `отсутствуют обязательные заголовки` failure from 2026-07-14.

**Resolved by construction**, not by patching: the `diadoc-integration` branch transplant (see Status above) never touched `google_sheets_service.py` or `invoice_review_service.py` at all. Checked `diadoc_sync_service.py`'s imports from `invoice_review_service` (`create_invoice_review`, `update_invoice_review`, `create_real_google_sheet_for_review`) — it calls these generically and never hardcodes a header name itself, so it runs correctly against `over_version`'s current, already-correct 43-column contract with zero changes. Verified: `test_google_sheets_service.py` (7/7) and all `test_diadoc_*` (22/22) pass on the branch, full suite shows the same pre-existing 8 `test_receiving.py` failures as plain `over_version` — no regression introduced.

## Relationship to SBIS EDO planning

See [[sbis-edo-integration]] — that page's 2026-07-20 effort estimate assumed a from-scratch build. Diadoc (Kontur) and SBIS (Saby/Tensor) are two different, competing Russian EDO providers; this Diadoc work does not replace the SBIS requirement if the business genuinely needs both. Worth confirming with the user/BA whether SBIS is still needed given Diadoc is now built, before spending the estimated 1.5-2.5 dev-weeks on SBIS.
