---
title: Diadoc (Kontur) EDO Integration
source: session
created: 2026-07-20
tags: [integration, diadoc, edo, upstream-main]
status: not-merged-into-over_version
---

# Diadoc (Kontur) EDO Integration

## Status

This integration exists in code on `upstream/main` (colleague Andrey Gomzikov, commits `a2f1ebb`/`8b9b4c1`/`0d0fd63`, dated 2026-07-20 in commit metadata but landed 2026-07-19 through 2026-07-20 per his own `log.md`). It has **not** been merged into `over_version`, which is the branch this project's own sessions have been working from. Do not assume it is live until an explicit merge/review happens.

`upstream/main`'s git history itself was reset on 2026-07-20 (`003b736 Clean main branch` deletes nearly everything, then `a2f1ebb` re-adds a full snapshot in one commit) — `main` is no longer a simple fast-forward of earlier `main` history. Treat `upstream/main` as a fresh snapshot to diff against, not as a branch to `git merge` blindly.

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

## Known gap found during 2026-07-20 review (not yet fixed anywhere)

`upstream/main`'s `SHARED_INVOICE_HEADERS` in `google_sheets_service.py` is still the **old 41-column contract** (`"Товар найден в справочнике"`, `"Кол-во в упаковке"`, no `"Код товара УС"`/`"ID строки"`). `over_version` fixed this to the **live 43-column contract** on 2026-07-14 (see [[current-status]] entries around that date) after the real spreadsheet was found to have been manually renamed/extended. `upstream/main` also still has the `_detect_document_form_from_text` regression ( `"ТОРГ-12"` uppercase + invented `"Счет-фактура"` ) that `over_version` fixed twice (`e1e07e2`, then re-applied as `55c1023` after `d063b31` silently reverted it).

Practical implication: if Diadoc's Google Sheets delivery path in its current `upstream/main` form is pointed at the real production `Накладная` sheet as-is, it will hit the same `отсутствуют обязательные заголовки: Товар найден в справочнике, Кол-во в упаковке` failure that blocked bot uploads on 2026-07-14, and will re-introduce the `Форма документа` dropdown-mismatch bug. This needs to be reconciled (most likely: rebase/cherry-pick Diadoc's diadoc-specific files onto `over_version`'s current `google_sheets_service.py`/`invoice_review_service.py`, not merge `main` wholesale) before Diadoc goes live against the real sheet.

## Relationship to SBIS EDO planning

See [[sbis-edo-integration]] — that page's 2026-07-20 effort estimate assumed a from-scratch build. Diadoc (Kontur) and SBIS (Saby/Tensor) are two different, competing Russian EDO providers; this Diadoc work does not replace the SBIS requirement if the business genuinely needs both. Worth confirming with the user/BA whether SBIS is still needed given Diadoc is now built, before spending the estimated 1.5-2.5 dev-weeks on SBIS.
