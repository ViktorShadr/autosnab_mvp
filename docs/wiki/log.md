# Wiki Log

## [2026-07-02] bootstrap | 初始化知识系统

- 建立 wiki、manifest、检查脚本和 repo 级默认规则。

## [2026-07-02] bootstrap | integrated into autosnab_mvp

- Bootstrapped the LLM Wiki structure into `autosnab_mvp`, created the local raw root, and committed the initial wiki setup.

## [2026-07-02] requirements | SBIS EDO intake

- Registered the new SBIS EDO task files in `manifests/raw_sources.csv` and compiled the read-only integration requirements into `docs/wiki/sbis-edo-integration.md`.

## [2026-07-02] requirements | additional screenshot intake

- Registered `Вставленное изображение (3).png` in `manifests/raw_sources.csv` and captured the centralized OCR/table-flow hint from the new screenshot.

## [2026-07-02] analysis | EDO architecture verdict

- Concluded that a custom SBIS EDO module is feasible, but the right implementation shape is a source-agnostic intake core with SBIS as one adapter.

## [2026-07-02] coordination | parallel PDF work

- Noted that the PDF export path is being developed by another engineer in parallel, so the canonical document contract must be agreed before either branch drifts.

## [2026-07-02] planning | final execution plan

- Recorded the final MVP plan: freeze the shared contract, keep the PDF flow intact, add SBIS as a source adapter, and use one writer for both sources.

## [2026-07-03] coordination | delivery priority update

- Registered the new screenshot intake and captured the updated priority: show the document-recognition/table MVP this week, then move to SBIS EDO next week.

## [2026-07-03] coordination | meeting agenda intake

- Registered the meeting agenda and captured the immediate task split: multi-page upload UX, business-logic coordination with Lilia, contact sharing, and parsing strategy review.

## [2026-07-03] coordination | table logic intake

- Registered the table-logic note, spreadsheet CSV, and screenshot clarifying the Apps Script behavior and the document-level upload status flow.

## [2026-07-03] summary | today's conclusions

- Captured the day's conclusion: the project is a document-processing pipeline, the MVP focus is reliable recognition and table placement, and PDF/SBIS must remain adapters over one shared document core.

## [2026-07-03] setup | local wiki raw-root restored on this PC

- Created the expected sibling raw-root at `../autosnab_mvp_raw`, including `inbox/` for new raw attachments.
- Confirmed that new intake can start from this machine, but older manifest-listed raw files are still absent locally and will need to be restored separately if full manifest validation is required.

## [2026-07-03] intake | new inbox documents registered

- Registered three newly added inbox files in `manifests/raw_sources.csv`: `АвтоСнаб Кафе Ромашка .xlsx`, `Копия План АвтоСнаб .md`, and `Созвон с Лилией.md`.
- Kept the historical manifest rows intact despite the local raw-root still missing older source files from previous sessions.

## [2026-07-03] compile | roadmap and table logic writeback

- Compiled `Копия План АвтоСнаб .md` into a concrete project overview and a new supplier-catalog roadmap page.
- Compiled `Созвон с Лилией.md` and `АвтоСнаб Кафе Ромашка .xlsx` into a dedicated page describing validation-table behavior, status gating, duplicate handling, and conversion logic constraints.

## [2026-07-03] priority | downloaded invoices to validation-table MVP

- Confirmed the immediate task focus: build the MVP that populates the working validation tables from downloaded invoice documents.
- This priority sits ahead of the broader supplier-catalog roadmap and should drive the next implementation steps.

## [2026-07-03] analysis | Lilia walkthrough deepened

- Refined the wiki understanding of `АвтоСнаб Кафе Ромашка`: the table is an operator workflow surface with document-level gating, not just an OCR output sheet.
- Highlighted the concrete MVP risk areas: stable second-row headers, duplicate blocking, correction loop, special document forms, and automatic conversion/recalculation behavior.

## [2026-07-03] planning | invoice-table MVP checklist

- Added a concrete implementation checklist for the downloaded-invoice -> validation-table MVP.
- The checklist defines what to freeze first, what to reuse, what to rewrite, what to postpone, and the smallest 2-3 day delivery cut.

## [2026-07-03] implementation | prepend invoice blocks into shared sheet

- Added a Google Sheets target mode that writes new invoice blocks into an existing shared sheet instead of creating a fresh spreadsheet every time.
- New documents are inserted below the configured header rows, oldest rows are shifted down, and one empty separator row is added between document blocks.
- The created export metadata now stores the inserted row range so later backend reads can target the correct document block.

## [2026-07-03] verification | shared-sheet prepend logic covered by local unit test

- Added a local unit test for the prepend writer logic: new document rows go directly under the configured header rows and a blank separator row is appended after the block.
- Full pytest execution was not possible in the current shell because dev dependencies are missing from the environment.

## [2026-07-03] operations | runbook added

- Added a practical runbook for local start, Docker start, OAuth setup, shared-sheet mode, smoke tests, and local verification commands.

## [2026-07-03] analysis | shared-sheet copy compared against original

- Registered and compared `Копия АвтоСнаб Кафе Ромашка .xlsx` against the original workbook.
- Confirmed that new invoice blocks are inserted at the top and separated by blank rows, but the inserted values follow the old `Накладные` register order instead of the real `Накладная` sheet column order.
- The immediate fix target is therefore the row-to-column mapper, not the prepend mechanics.

## [2026-07-03] implementation | shared-sheet mapper rewritten for real header contract

- Reworked the shared-sheet writer to emit rows in the real `Накладная` column order used by `АвтоСнаб Кафе Ромашка`.
- Updated the reverse sheet parser so send/sync logic can read item rows from the `Накладная` contract as well as the older register-style field names.
- Local syntax checks passed; live Google retest is still needed.

## [2026-07-03] fix | shared-sheet write range widened to match row width

- Fixed the shared-sheet Google write range so it is derived from the actual row width instead of hardcoded to `AL`.
- This removes the `Requested writing within range ... but tried writing to column [AM]` error during live retest.

## [2026-07-03] fix | OCR item-row post-filter added

- Added a post-filter that removes low-quality item rows before they are stored in `Receiving` or written into Google Sheets.
- Added a regression test to ensure noisy item candidates do not become table rows.

## [2026-07-03] implementation | local document extraction layer added

- Added a switchable document-extraction service that can use MinerU as the primary local backend.
- Kept the current Google Drive OCR + deterministic parser chain as the default fallback so the existing flow remains usable.
- Added tests for the MinerU path and the OCR fallback path at the service layer.

## [2026-07-03] implementation | MinerU CLI contract aligned

- Aligned the local extraction adapter with MinerU's documented CLI flow: `mineru -p <input_path> -o <output_path> -b pipeline`.
- Added output-directory readers for structured JSON and markdown/text outputs.
- Added a unit test for MinerU output directory parsing.

## [2026-07-03] implementation | MinerU added to dependency and Docker path

- Added `mineru[all]` to backend Python dependencies so local installs and the Docker image can include the MinerU backend.
- Updated the Docker image notes and runbook to reflect the MinerU-enabled extraction flow and the OCR fallback mode.

## [2026-07-03] summary | day wrap-up

- Restored the wiki-first operating loop on this PC, including raw-root/inbox setup and writeback discipline.
- Registered and compiled new raw sources into project overview, supplier roadmap, validation-table behavior, MVP checklist, and runbook pages.
- Confirmed the immediate delivery focus: downloaded invoices -> validation table MVP.
- Implemented shared-sheet prepend mode for Google Sheets so new invoice blocks go to the top with a blank separator row.
- Diagnosed the real shared-sheet failure as a column-contract mismatch against the live `Накладная` sheet, not an overwrite/prepend bug.
- Reworked the shared-sheet mapper to target the real `АвтоСнаб Кафе Ромашка` sheet contract and updated reverse parsing accordingly.

## [2026-07-04] summary | day wrap-up

- Captured today's outcome in wiki: MinerU is now the documented local extraction backend, with OCR remaining as fallback.
- Kept the Google Sheets path aligned to the real `Накладная` column contract and documented the live write-range fix.
- Left `.env`, secret OAuth files, the local database, exports, and uploads out of version control.

## [2026-07-04] security | OAuth credentials moved fully into `.env`

- Replaced OAuth client/token JSON reads with env-only client ID, client secret, access token, refresh token, and expiry settings.
- OAuth callback and token refresh now persist updated token values back into `.env`.
- Removed `.env` and legacy OAuth JSON files from Git tracking while preserving the local ignored files.
- Recorded that the exposed Google credentials must be revoked and reissued because they already exist in Git history.

## [2026-07-04] docs | README aligned with active MVP and runtime

- Rewrote the root `README.md` around the actual current product center: invoice upload, OCR/MinerU extraction, validation-table flow, and iiko send/mock export.
- Removed outdated assumptions about secrets, Google setup, and project scope so the repo entrypoint now matches the active code and wiki status.

## [2026-07-04] ui | upload page now selects extraction backend per document

- Added a dedicated method selector on the invoice upload page for `Google OCR`, `MinerU`, or hybrid mode.
- Wired the selected method through the upload endpoint into the extraction service so one document can force OCR-only, MinerU-only, or `MinerU -> Google OCR fallback` without changing global `.env` settings.

## [2026-07-04] verification | MinerU pipeline works end to end

- Installed CPU PyTorch and the `mineru[pipeline]` dependency profile; added the undeclared MinerU runtime dependency `six`.
- Replaced the missing `mineru` launcher dependency with `python -m mineru.cli.client`, using the backend's active interpreter and Cyrillic OCR.
- Registered the real UPD smoke source and ran MinerU 3.4.2 successfully on it without Google OCR fallback.
- Updated the MinerU adapter for actual 3.4.2 output: Markdown is paired with `*_content_list.json`, while service model JSON is ignored.
- The final backend result contained supplier `ООО "ФРУКТЫ АРИФА"`, INN `3900040690`, invoice `1928`, date `2026-06-23`, and one item totaling `2041`.
- MinerU-focused tests pass; all 35 tests outside `test_receiving.py` pass. The pre-existing `test_receiving.py` hang remains.

## [2026-07-04] operations | one-command Docker startup aligned

- Reworked the Docker image to copy the real backend runtime layout instead of only `backend/app`.
- Added `.dockerignore` so the image build no longer uploads `.venv`, local databases, exports, uploads, and other heavy local artifacts.
- Updated `docker-compose.yml` to support `docker compose up --build` with persistent volumes for SQLite, uploads, exports, and MinerU/HuggingFace cache.
- Updated the README and runbook so Docker startup instructions now match the active runtime contract.

## [2026-07-04] intake | root workbook and updated calculator note reviewed

- Registered the new root copies `MVP Бух калькулятор (2).md` and `АвтоСнаб Кафе Ромашка .xlsx` in `manifests/raw_sources.csv`.
- Compiled their concrete findings into wiki: exact status transitions, first-row-only document statuses, row-specific `Корректировка`, and the current `Накладная` write contract across `A:AN`.
- Noted that the exported `.xlsx` shows some broken named-range validations (`#REF!`), so the live Google Sheet must remain the final source of truth for dropdowns and Apps Script behavior.

## [2026-07-04] planning | OpenAI-first parsing track

- Recorded the new implementation direction: delegate final document parsing to an OpenAI model, keep OCR/MinerU as evidence providers or fallbacks, and preserve deterministic Google Sheets mapping.
- Defined the immediate plan boundary: add an OpenAI parser layer into the existing extraction service, validate/normalize model output, and keep the `Накладная` shared-sheet contract stable.

## [2026-07-04] implementation | OpenAI invoice parser pipeline

- Added a strict Pydantic invoice contract and an OpenAI Responses API parser over PDF, MinerU, or OCR evidence.
- Added deterministic date, INN, amount, VAT, line-total, document-total, duplicate, OCR-error, status, and correction normalization.
- Kept Google Sheets deterministic: the writer reads row-2 headers, writes only the `A:AN` business contract, and limits document-level fields to the first row.
- Added structured per-document debug traces under `exports/openai_debug` and preserved parser metadata in the existing review document metadata.
- Added focused schema, mock-provider, golden-scenario, status-gate, extraction, and mapper tests; 28 targeted tests pass.
- The full suite still hangs in the pre-existing `test_receiving.py` path. Live OpenAI and Google Sheet calls were not run because they require external credentials and the user-owned target sheet.

## [2026-07-04] fix | Docker build unblocked from uvicorn dependency resolution

- Reduced the backend runtime dependency from `uvicorn[standard]==0.34.0` to `uvicorn==0.34.3`.
- This keeps the container command unchanged (`python -m uvicorn ...`) but avoids pulling optional `standard` extras during Docker build, which were not required by the current runtime and were making pip resolution less reliable.

## [2026-07-04] implementation | structured item normalization and reference mapping

- Expanded the strict OpenAI item schema and prompt with cleaned names, descriptors, package data, document quantities, conversion candidates, codes, confidence, and review reasons.
- Added deterministic item cleanup, package extraction, compound conversion, and ambiguity checks after the model response.
- Added fixed-header reads for the Google Sheet tabs `Товары` and `Справочник фасовок`.
- Wired deterministic product/package matches into `Наименование товара в УС`, `Ед.изм. в УС`, and `Кол-во в УС`; unresolved rows receive `Нет в справочнике` or `Сопоставление`.
- Verified 58 backend tests outside the known hanging `test_receiving.py`; no live Google call was made because the current environment still times out during the Google TLS handshake.

## [2026-07-04] ui | upload page preview and inline Google auth

- Added inline preview rendering for selected invoice images and PDFs directly on the upload page before submission.
- Added a Google OAuth status panel and popup-based authorization entrypoint on the same page, with callback postMessage support so the upload screen can refresh auth state without forcing the operator through separate URLs.
