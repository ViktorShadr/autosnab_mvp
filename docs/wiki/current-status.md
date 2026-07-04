---
title: autosnab_mvp Current Status
source: session
created: 2026-07-02
tags: [status]
status: current
---

# autosnab_mvp Current Status

- Wiki bootstrap integrated into this repo on 2026-07-02.
- The knowledge base now lives under `docs/wiki/` in `autosnab_mvp`.
- Local raw-root created at `../autosnab_mvp_raw` for source documents outside Git.
- Next maintenance step: keep wiki writeback in sync with code changes and register any new raw files in `manifests/raw_sources.csv`.
- New SBIS EDO requirements were received on 2026-07-02 and compiled into `docs/wiki/sbis-edo-integration.md`.
- Additional screenshot intake on 2026-07-02 reinforced the centralized OCR/document-flow requirement and pointed to an existing Google Docs table named `АвтоСнаб Кафе Ромашка`.
- Architectural conclusion: SBIS EDO should be implemented as a source adapter over a shared document core, not wired directly into the current invoice-review flow.
- Parallel PDF export development means the shared document contract must be frozen early so the two tracks do not diverge.
- Final execution plan is now recorded in `docs/wiki/sbis-edo-integration.md`: freeze the contract, add SBIS as an adapter, keep the PDF flow unchanged, and validate both sources through one writer.
- New screenshot on 2026-07-03 updates delivery priority: MVP recognition/table placement this week, SBIS EDO next week.
- Meeting notes on 2026-07-03 add a nearer-term focus on multi-page document UX and parsing strategy before SBIS work starts.
- Latest intake on 2026-07-03 adds table-layout constraints: keep header names stable, use the existing Apps Script behavior, and treat the table as a document-level validation layer with a planned `Вернуть на проверку` action.
- Local wiki raw-root was re-initialized on this PC on 2026-07-03 at `../autosnab_mvp_raw`, including the `inbox/` drop zone for new raw attachments.
- Historical raw files already listed in `manifests/raw_sources.csv` are not mounted on this PC yet, so only new inbox intake is ready right now.
- Three new raw files were added to `../autosnab_mvp_raw/inbox/` on 2026-07-03 and registered in the manifest: `АвтоСнаб Кафе Ромашка .xlsx`, `Копия План АвтоСнаб .md`, and `Созвон с Лилией.md`.
- Those three raw files were compiled into wiki conclusions on 2026-07-03: broader supplier-catalog roadmap, a filled project overview, and more explicit validation-table behavior.
- The immediate working priority is now explicit: build an MVP that fills the validation tables from downloaded invoice documents.
- Deeper review of the Lilia walkthrough confirms that the highest-risk MVP areas are document-level status gating, stable table headers, duplicate control, manual reference completion, and recalculation logic.
- A concrete implementation checklist for that MVP is now recorded in `docs/wiki/invoice-table-mvp-checklist.md`.
- The Google Sheets writer now supports a shared-table mode: new invoice blocks can be inserted at the top of an existing sheet with one empty separator row between documents.
- A practical launch/test runbook is now recorded in `docs/wiki/runbook.md`.
- Comparison against the tested spreadsheet copy shows that shared-sheet prepend works structurally, but the inserted values are mapped against the wrong column order for the real `Накладная` sheet.
- The shared-sheet writer has now been rewritten to map rows into the real `Накладная` column order instead of the old `Накладные` register order; live Google retest is still required.
- The shared-sheet writer now computes the Google write range from the actual row width, fixing the `AL` vs `AM` mismatch that blocked the live retest.
- The OCR parser now filters out noisy item rows before they reach `Receiving` or the Google Sheet, reducing accidental garbage rows in the table.
- A local document-extraction service has been added: MinerU can now be enabled as the primary backend, with the current OCR/parser chain kept as fallback.
- The MinerU contract uses the active Python environment: `{python_executable} -m mineru.cli.client -p <input_path> -o <output_path> -b pipeline -l cyrillic`.
- The project installs CPU PyTorch plus `mineru[pipeline]`; the unused `mineru[all]` profile was removed because it pulled Linux CUDA/vLLM dependencies that this backend does not use.
- Today’s implementation track established the full local MVP loop: wiki writeback, raw intake, runbook, shared-sheet prepend mode, diagnosis of the column-contract bug, and a mapper rewrite aligned to the real `Накладная` sheet.

## Today summary

- The project is a document-processing pipeline, not a generic document store.
- The current MVP priority is to show reliable document recognition and placement into the existing validation table.
- Multi-page UX, parsing reliability, and stable table headers are the critical short-term risks.
- SBIS EDO is the next phase, but only after the shared document contract is frozen.
- PDF and SBIS must stay as source adapters over one common document core.
- New raw attachments can now be placed into `../autosnab_mvp_raw/inbox/` and registered from this machine.
- The latest inbox intake is registered and waiting for compile/writeback into wiki pages as needed.
- The repo now has a clearer split between the short-term document-validation MVP and the longer-term supplier-catalog/search roadmap.
- The nearest delivery target is not the broader catalog roadmap but the MVP flow from downloaded invoices into the validation table.
- The current write bug is a column-contract mismatch, not a failure of top insertion or separator-row insertion.
- The immediate blocking bug is now the fixed write-range width on the shared `Накладная` sheet, not the mapper shape itself.
- OCR quality is now constrained by a post-filter on item rows, so the remaining issue should be true recognition limits rather than unfiltered garbage rows.
- The repo now has a switchable local extraction layer, and MinerU is wired in as a documented CLI/output-directory backend that can be enabled from `.env`.
- The local extraction layer now targets MinerU's documented CLI/output-directory flow instead of stdout-only parsing.
- MinerU 3.4.2 is verified end to end on the local CPU environment with a real one-page UPD: provider `mineru`, invoice `1928`, date `2026-06-23`, supplier INN `3900040690`, and item `Еноки вес` (`3.14 кг x 650 = 2041`) were returned without OCR fallback.
- MinerU's first local run downloaded about 2.5 GB of models; cached runs complete in roughly 30 seconds on this machine. The backend timeout is 900 seconds to cover first-run model initialization.
- The MinerU output adapter now consumes Markdown plus `*_content_list.json`, avoiding accidental selection of service `*_model.json` and extracting UPD table rows from MinerU HTML.
- The remaining live task is to retest the Google write flow against the user-owned spreadsheet copy and verify that values now land in the correct business columns.
- The 2026-07-04 wrap-up is now captured in wiki: the local extraction path is MinerU-ready, the Google Sheets writer is documented and fixed at the column-contract level, and only safe docs were prepared for commit.
- Google OAuth now uses env-only credentials: client ID, client secret, access token, refresh token, and token expiry are read from `.env`; runtime no longer reads OAuth or service-account JSON files.
- `.env` and the legacy OAuth JSON files were removed from Git tracking. Because credentials existed in repository history, they must be revoked and reissued.
- The root `README.md` now matches the active product shape: invoice-validation MVP first, MinerU/OCR extraction backends, env-only OAuth, shared-sheet Google flow, and the remaining live retest/testing gaps.
- The upload UI now exposes per-document extraction choice: `Google OCR`, `MinerU`, or `hybrid` (`MinerU -> Google OCR fallback`) instead of relying only on the global `.env` backend switch.
- Docker startup is now aligned to the real backend shape: one `docker compose up --build` command starts FastAPI with mounted `.env` plus persistent volumes for SQLite, uploads, exports, and MinerU model cache.
- New root copies reviewed on 2026-07-04 (`MVP Бух калькулятор (2).md` and `АвтоСнаб Кафе Ромашка .xlsx`) make the current validation-table contract more explicit: document statuses belong only to the first row of each block, `Корректировка` is row-specific, and the live business contract is row 2 of `Накладная` across `A:AN`.
- Team direction has now shifted from regex/MinerU-first parsing to OpenAI-first parsing: OCR and MinerU should remain evidence sources or fallbacks, while the final field extraction should be delegated to an OpenAI model and then normalized deterministically before Google Sheets writing.
- OpenAI structured parsing is now integrated as the default extraction mode: PDF text, MinerU, and Google OCR provide evidence; Pydantic validates the strict result; deterministic code normalizes values and assigns review statuses.
- The shared `Накладная` writer now reads and validates row-2 headers before mapping `A:AN`; document-level fields are first-row-only and `Корректировка` stays item-specific.
- Duplicate outcomes, OCR errors, amount mismatches, debug traces, and the `Загрузить` send gate are covered by focused tests. A live OpenAI + Google Sheet retest remains required with valid external credentials.
- Docker build reliability was improved on 2026-07-04 by simplifying the backend ASGI dependency from `uvicorn[standard]==0.34.0` to plain `uvicorn==0.34.3`; this avoids optional extra-resolution during image build while preserving the runtime server command.
- OpenAI item output now includes cleaned and normalized name candidates, descriptors, package structure, source/document quantities, conversion candidates, codes, confidence, and row-specific review reasons.
- A deterministic `item_normalization_service.py` now rechecks package extraction and conversion, reads `Товары` plus `Справочник фасовок` from the configured Google spreadsheet, and fills the US name/unit/quantity fields only through backend mapping.
- Missing products map to row correction `Нет в справочнике`; ambiguous products, missing packages, and incompatible units map to `Сопоставление`. The Google writer still controls fixed columns and first-row-only document statuses.
- The expanded item pipeline passes all 58 backend tests outside the pre-existing hanging `test_receiving.py`; a live Google retest remains blocked by the environment's Google TLS handshake timeout.
- The upload page now shows an inline preview for selected image/PDF invoices and includes a built-in Google OAuth block with live status polling plus popup-based authorization, so operators can stay on one screen while preparing a document upload.
