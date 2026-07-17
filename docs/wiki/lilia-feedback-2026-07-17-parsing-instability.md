---
title: Lilia Feedback (2026-07-17) — Parsing Instability and Multi-Page Failures
source: session
compiled_from:
  - session chat message from Lilia, relayed by user, 2026-07-17
created: 2026-07-17
updated: 2026-07-17
tags: [bugs, openai, multipage, duplicates, quantity, invoice-parsing]
status: open
---

# Lilia Feedback (2026-07-17) — Parsing Instability and Multi-Page Failures

Raw feedback (paraphrased from Lilia, real-world tester): the same ИП Минибаев
invoice was uploaded to the MVP roughly 15 times, and results differed run to
run. Reported symptoms, split into distinct issues below.

## Issue 1 — Quantity digit drift (e.g. `5,000` → `5,001`)

- On repeated uploads of the *same* invoice, some numeric quantity fields
  shift by a small amount (Lilia's example: `5` becomes `5.001`), across
  multiple line items, not just one.
- Comma/decimal-separator instability is also implied ("иногда садится ровно
  запятая иногда в количестве" — sometimes the issue is the separator itself,
  sometimes the quantity value).
- **Status: new, not previously tracked.** This looks like OpenAI-side
  non-determinism in reading/normalizing digits from OCR text, not a
  deterministic-code bug — consistent with
  `invoice-recognition-hardening-plan.md` Phase 4 still being open (the
  `openai` path sends only OCR/MinerU **text**, not source page images, so the
  model is guessing digits from potentially noisy OCR text on every call
  rather than reading the same pixels). Needs investigation: check whether
  `_parse_numeric`/quantity normalization in the OpenAI item pipeline rounds
  or coerces to Decimal deterministically once evidence is fixed, or whether
  variance survives even with identical OCR text as input (i.e. genuinely a
  model-sampling issue, which would argue for stricter decoding
  parameters/temperature or a numeric post-validation cross-check against the
  line amount).

## Issue 2 — Row order scrambles ("верхняя строка может сесть как последняя")

- Item rows are sometimes written to the sheet out of source order — the top
  row of the invoice can end up last.
- **Status: new, not previously tracked.** Not covered by any existing wiki
  page. Needs a code check of where item order is assigned/preserved between
  OpenAI response parsing and `_shared_invoice_item_row`/sheet row building —
  likely either the model isn't instructed to preserve source order, or
  something downstream (dedupe, sort-by-key) reorders items.

## Issue 3 — Wrong document/line totals

- "итоговые суммы неверно определяются" — document or line totals are
  sometimes wrong.
- **Status: partially tracked.** `invoice-recognition-hardening-plan.md`
  Phase 5 ("Recalculate each line and document totals using decimal
  arithmetic and configured tolerances") is designed to catch this but per
  `current-status.md` has not been fully implemented/verified end to end.
  Needs to be checked against this specific ИП Минибаев invoice once
  available as a fixture.

## Issue 4 — Two-page invoices mostly fail, and failure mode is worse than expected

- Two-page invoices loaded correctly (both pages merged into one document)
  only **once** out of many attempts.
- The rest of the time, only page 1's items land — but *also* supplier name,
  INN, date, and document number are **not determined**, even though those
  fields normally live on page 1 and should not depend on page 2 being
  present.
- **Status: contradicts prior wiki claims and needs re-verification.**
  `current-status.md` and `invoice-recognition-hardening-plan.md` both
  describe logical multi-page upload as implemented and working (Phase 2,
  landed ~2026-07-04, plus the UI supports `Многостраничная накладная` mode
  per the 2026-07-09 merge entry). Lilia's report suggests either: (a) the
  multi-page merge path is failing silently and falling back to single-page
  processing of just page 1, or (b) operators are not reliably triggering
  multi-page mode in the Telegram bot / upload UI, so page 2 is being sent as
  a separate document while page 1 alone fails header extraction for an
  unrelated reason. The fact that *header* fields fail even on a
  page-1-only run is the most suspicious detail — worth checking whether
  something about the multi-page code path (even when it degrades) disables
  the normal single-page header-extraction logic, versus a true single-page
  upload of the same page succeeding standalone.

## Issue 5 — Duplicate detection persists after deleting prior uploads

- Re-uploading the same invoice is always flagged `Дубль`, even after all
  previous uploads of it were deleted.
- **Status: expected/by design, explicitly accepted by Lilia** ("если для
  ваших тестов это не мешает, то хорошо"). Duplicate detection is presumably
  keyed by a persistent hash/invoice-number record that isn't rolled back on
  deletion (soft-delete or a separate dedupe-key table). No action needed
  unless this becomes a real operational problem later — flagging here only
  so the behavior is documented as intentional, not a bug.

## Investigation update (2026-07-17, same day) — Issue 4 partially root-caused

Code-level investigation of the two-page path, tracing
`/bot/drafts/pages` → `/bot/drafts/finalize` → `extract_invoice_document_set`
→ `parse_invoice_with_openai` → `normalize_invoice_result`:

- **Ruled out: draft-append race condition.** `append_bot_draft_page` in
  `invoice_review.py` does a check-then-create (`get_active_draft` then
  `create_upload_journal`) with no DB lock or unique constraint, which looked
  like a classic TOCTOU race if two page uploads for the same `chat_id`
  arrived close together (e.g. an operator multi-selecting both photos in
  Telegram's gallery picker, which Telegram can deliver as near-simultaneous
  separate updates). Checked whether this could actually produce two split
  draft rows: the backend runs a single uvicorn worker with no `--workers`
  flag, and `append_bot_draft_page` is `async def` but contains no `await` in
  its body, so once a request's handler starts running it executes to
  completion on the event loop without yielding — a second request's handler
  cannot interleave mid-way through the first's check-then-create sequence.
  This rules the race out for the current single-worker deployment. (Would
  need reconsidering if the deployment ever moves to multiple workers/processes.)
- **Ruled out: multimodal images not sent.** Contrary to the stale
  2026-07-04 note in `current-status.md` and
  `invoice-recognition-hardening-plan.md` Blocker 3, `_build_openai_input` in
  `openai_invoice_parser_service.py` already sends real page images
  (`input_image` base64 blocks) for every image-type page, not just OCR text
  — both pages' images should already reach the model for a 2-page upload.
  Fixed both stale wiki notes as part of this investigation.
- **Confirmed and fixed: missing document-header validation gap.**
  `_payload_validation_errors` in `document_extraction_service.py` only
  requires non-empty item rows to let a document through — it never checked
  whether `supplier_name` or `document_number` came back non-empty.
  Downstream, `normalize_invoice_result` in `invoice_normalization_service.py`
  already flagged empty `document_date` (severity `error`) and empty/invalid
  `supplier_inn` (severity `warning`) for review, but had **no equivalent
  check for `supplier_name` or `document_number`** — exactly two of the four
  fields Lilia listed as failing. A document could therefore be created and
  written to the sheet with a blank supplier name and blank invoice number and
  never get flagged for either reason specifically. **Fixed**: added the same
  `_flag(..., "error")` pattern for both fields, plus two regression tests
  (`test_missing_document_number_requires_review`,
  `test_missing_supplier_name_requires_review` in
  `test_openai_invoice_pipeline.py`). Full non-`test_receiving.py` suite
  (125 tests) passes; `test_receiving.py`'s 8 pre-existing failures are
  identical before/after this change (verified via `git stash`), so nothing
  regressed.
- **Still open: why does extraction actually fail on ~14/15 two-page runs?**
  This fix makes a bad extraction *visible* (forces `Требует проверки`
  instead of a silent blank cell), but does not explain why OpenAI's header
  extraction is unreliable specifically in the merged 2-page case when the
  same page 1 alone reportedly works fine as a single-page upload. Nothing
  else found in the merge code (`_merge_page_evidence`) looks structurally
  wrong: page 1's raw OCR text is placed first in the concatenated
  `raw_text`, well under the `openai_max_evidence_chars=120_000` truncation
  limit, and both pages' images are included, well under
  `openai_max_image_pages=12`. The most likely remaining explanations are (a)
  genuine model-side unreliability when reasoning over two pages/images at
  once (would tie into Issue 1's digit-drift non-determinism as the same
  underlying class of problem), or (b) something page-content-specific to
  this particular ИП Минибаев накладная (e.g. its physical page-1 header
  layout) that doesn't reproduce with other two-page documents. Neither can be resolved
  without a real repro — see next step below, now sharper: capture the
  `exports/openai_debug/` trace for an actual failing two-page run (the
  merged `raw_text` sent to the model, the raw image bytes/count that went
  out, and the model's raw structured JSON response) to see whether the
  request itself was well-formed or the model simply returned an empty
  header despite good input.

## Suggested next step

Get the actual ИП Минибаев source file(s) from Lilia (register under
`manifests/raw_sources.csv` per the session protocol once received) and use
them as a new golden-set fixture alongside the four documents already defined
in `invoice-recognition-hardening-plan.md` Phase 6 — this invoice is a much
better repro case than the existing fixtures for issues 1–3 since it already
has ~15 recorded real runs with variable output. For issue 4, deploy this
session's header-validation fix, then reproduce a two-page upload against the
live VPS bot and pull the `openai_debug` trace for that run — this will show
directly whether page-1 evidence is well-formed at request time (pointing to
a model-reliability issue) or already missing/malformed before the request
(pointing to a remaining bug in evidence collection/merging).
