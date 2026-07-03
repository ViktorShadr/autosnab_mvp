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
- The remaining live task is to retest the Google write flow against the user-owned spreadsheet copy and verify that values now land in the correct business columns.
