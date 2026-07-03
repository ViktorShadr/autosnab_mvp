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
