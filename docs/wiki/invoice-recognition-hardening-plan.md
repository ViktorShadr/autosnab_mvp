---
title: Invoice Recognition Hardening Plan
source: session
compiled_from:
  - src_af981ad353
  - src_5c7f7149b6
  - src_c408edb166
  - src_6f6622e548
  - src_ec8c54a020
  - src_20260730_pavel_audio
  - src_20260730_pavel_audio_transcript
created: 2026-07-04
updated: 2026-07-31
tags: [invoices, openai, ocr, mineru, multipage, testing, plan]
status: current
---

# Invoice Recognition Hardening Plan

## Goal

Make the real-photo invoice path reliable:

```text
one logical document with one or more files/pages
-> safe image/PDF preparation
-> text and layout evidence
-> OpenAI structured parser with source images when available
-> deterministic validation and normalization
-> deterministic Google Sheets mapper/writer
```

The OpenAI model extracts candidates only. It does not choose sheet columns,
assign business statuses directly, match catalogs authoritatively, or write to
Google Sheets.

## Current blockers

1. **(Fixed 2026-07-09) Docker MinerU model cache.** Originally blocked
   because OpenCV could not load `libxcb.so.1` (fixed earlier by installing
   the missing system libs). Superseded by a second finding the same day: the
   live container's MinerU model cache was missing
   `models/TabRec/UnetStructure/unet.onnx` entirely, so MinerU was skipped on
   every single request via the existing health guard — not a rare failure,
   a permanently disabled provider, leaving Google Drive OCR as the *only*
   evidence provider in production. Repaired via
   `python3 -m mineru.cli.models_download -s huggingface -m pipeline` against
   the persistent `autosnab_hf_cache` volume; hit and fixed a second-order
   issue where an interrupted first download attempt left
   `models/MFR/unimernet_hf_small_2503` corrupted (config files present,
   weights missing) and the downloader's directory-exists check silently
   skipped re-fetching it — `mineru_health()` reported `ready: true` while a
   real document still failed. Deleting that one model directory and
   re-running the downloader fixed it for real, confirmed by an actual
   extraction call returning 3466 characters of structured text. MinerU is
   now a genuine fallback provider again, not just formally "ready" — see
   `docs/wiki/log.md` entry "fix | MinerU model cache repaired, real fallback
   provider restored" for the full trace. `mineru_health()`'s single-file
   check is still shallow relative to the real multi-model surface and could
   mask a future partial-cache corruption the same way; not hardened yet.
2. Google Drive OCR can fail with a TLS handshake timeout and currently leaves
   OpenAI with empty evidence.
3. **(Fixed 2026-07-09) Google Drive OCR export race condition.** Root-caused
   the user's report of identical repeated uploads producing different parsed
   results: `recognize_invoice_with_google_drive_ocr` called `files().export()`
   immediately after `files().create(..., ocrLanguage=...)`, but Drive's OCR
   conversion is asynchronous — the export can return a document that is still
   just a UTF-8 BOM, before the OCR text has actually been written server-side.
   Confirmed directly from production debug logs (`exports/openai_debug/`):
   the same file `file_110.jpg` uploaded three times in a row produced
   `raw_text` of length 1 (BOM only), length 1 again, then length 2351 (real
   text) on the third try — with all three provider attempts logged as
   `status: "success"`, because `"﻿".strip()` is truthy in Python, so the
   near-empty result was never flagged as a failure. Fixed in
   `backend/app/services/ocr_service.py`: `_export_ocr_text_with_retry` now
   polls `export()` (`GOOGLE_DRIVE_OCR_EXPORT_RETRY_ATTEMPTS=4`,
   `GOOGLE_DRIVE_OCR_EXPORT_RETRY_DELAY_SECONDS=2.0` between attempts) until
   the decoded text is at least `GOOGLE_DRIVE_OCR_MIN_TEXT_LENGTH=20`
   characters after stripping the BOM, and the BOM is now stripped from the
   text returned to the rest of the pipeline either way. Covered by
   `backend/tests/test_ocr_provider.py::test_export_ocr_text_retries_past_empty_bom_only_export`
   (replays the exact empty/empty/real sequence from the production logs) and
   `..._gives_up_after_exhausting_retries`. Not yet redeployed to the running
   container — needs a rebuild/restart of `autosnab_backend_mvp4` to take
   effect, then a re-test with the same repeated-upload scenario.
3. **(Resolved, date unclear — found during 2026-07-17 investigation)** This
   blocker text was stale: `_build_openai_input` in
   `openai_invoice_parser_service.py` already sends actual page images
   (`input_image` content blocks, base64, up to `openai_max_image_pages=12`)
   alongside the merged OCR text for every `source_type == "image"` page, not
   just text. `current-status.md`'s 2026-07-04 note that "the current `openai`
   mode does not send source images" is therefore outdated as of at least
   2026-07-17 and should not be relied on — Phase 4's multimodal goal appears
   to already be implemented in code, though it was never explicitly recorded
   as completed in this plan or the log. Worth a live trace check to confirm
   images are actually arriving non-empty/non-truncated in a real request,
   since the fact this was already true wasn't caught by anyone until now.
4. Upload accepts one file, so a multi-page invoice is split into unrelated
   documents.
5. **(Stale as of 2026-07-29 — Phase 3 is actually implemented.)** This
   blocker said rotated/perspective-distorted photos are not normalized
   before extraction. `document_image_preparation_service.py` already does
   EXIF orientation, perspective crop, quarter-turn correction, deskew,
   autocontrast, and upscale to ≥1800px, plus quality metrics
   (`blur_score`/`glare_ratio`/`dark_ratio`/`clipping_ratio`/`text_coverage_ratio`)
   with `review_reasons`/`stop_reasons`, wired into
   `document_extraction_service.py` and surfaced as `review_flags` on the
   invoice via `openai_invoice_parser_service.py`. Never recorded as done in
   this plan or the log. Remaining real gap (see
   `docs/wiki/current-status.md` 2026-07-29 entry): the quality check only
   fires *after* extraction, producing a soft warning flag on an
   already-created invoice — nothing currently uses `stop_recommended` to
   block a bad photo *before* the OpenAI call, which is the actual complaint
   behind Lilia's new "low-quality photos recognize poorly" feedback.
6. There is no executable golden-set comparison for the five reviewed photos.
7. **(New, found 2026-07-17)** `hybrid`/`mineru`-only extraction is
   consistently non-functional for scanned/rotated table-form documents like
   ТОРГ-12, not just occasionally unreliable. Reproduced by running the
   `УПМК003248` page-1 fixture (`5321471953447098411 (1).jpg`) through
   `extract_invoice_document(..., extraction_method="hybrid")` 8 times in a
   row: every single run returned `supplier: null`, `supplier_inn: null`,
   `items: []`, `invoice_number: "ТОРГ-12"` (the form label, not the real
   document number `УПМК3003248`), and a bogus `total_sum: 1.0`. MinerU itself
   ran successfully and returned 3466 characters of real content (confirmed
   via `pipeline_logs`: `mineru_start` → `mineru_complete`, both `ok`), but its
   `raw_text` is HTML table markup (`<table><tr><td>...`), and the downstream
   parser (`_normalize_mineru_payload` → `extract_invoice_payload_with_fallback`
   in `document_extraction_service.py`) is a legacy regex/heuristic parser
   built for plain OCR text lines, not HTML-escaped table cells — it silently
   finds nothing. The secondary structured path
   (`_extract_mineru_content_list_fields`, meant to read MinerU's
   `content_list.json`) also produced nothing for this run. Unlike the
   `openai`-mode variance found the same day (cosmetic `raw_name` drift only,
   see `docs/wiki/lilia-feedback-2026-07-17-parsing-instability.md`), this is
   not flaky — it is deterministically broken, 8/8 runs, for this document
   shape. Practical implication: `hybrid`/`mineru` cannot currently be trusted
   as a real fallback for rotated/table-form invoices; `openai` is the only
   mode that actually extracts data from this kind of document today. Not
   fixed yet — would need either teaching the legacy regex parser to strip
   HTML table markup first, or making `_extract_mineru_content_list_fields`
   the primary path with the regex parser only as a last-resort fallback.

## Hard pre-recognition quality gate ported from `auto-snab-document-parser` (2026-07-31)

Closes the long-standing gap in blocker #5 above ("nothing currently uses
`stop_recommended` to block a bad photo before the OpenAI call") and directly
targets the 2026-07-29 "low-quality photos recognize poorly" complaint.

**Source**: Andrey Gomzikov's branch `feature/document-image-quality-gate`
(commit `992bc11`, 2026-07-31) in the separate `auto-snab-document-parser`
GitLab repo (`gitlab.testant.online/antipov-backend/auto-snab-document-parser`,
not merged into that repo's `develop` yet). User asked to evaluate and port it
into this repo.

**Conflict assessment before porting**: compared each touched file against
that repo's own `develop` baseline (the common ancestor with this repo's
current files) rather than diffing branch-vs-this-repo directly, since the two
repos have independently diverged (different directory layout: their
domain-driven `app/domains/invoice_pipeline/...` vs this repo's flat
`app/services/...`, plus this repo has its own MinerU integration absent from
that repo entirely). Finding: `document_image_preparation_service.py` was
byte-for-byte functionally identical to that repo's baseline (only ruff
line-wrap differences) — zero conflict, straight replacement. Andrey's
insertions into `document_extraction_service.py`/`_collect_openai_evidence`/
`extract_invoice_document_set` land at points in the function bodies that this
repo's own MinerU additions do not touch — no structural overlap. Same for
`bot_gateway_service.py` (divergence was 100% formatting/import-path noise)
and the router (`retry_recommended_label` dict literal was byte-identical).
This assessment held up in practice — the actual port needed only import-path
edits, not logic reconciliation.

**What was ported**:
- `document_image_preparation_service.py` replaced wholesale with Andrey's
  version: real orientation detection via **Tesseract OSD** (not just
  heuristics), foreground-contrast checks, edge-touch/cropped-document
  detection, verified deskew, and — the important part — **critical**-severity
  thresholds (`CRITICAL_BLUR_SCORE`, `CRITICAL_GLARE_RATIO`,
  `CRITICAL_DARK_RATIO`, `CRITICAL_LOW_RESOLUTION`, etc.) separate from the
  existing soft warning thresholds. Backward compatible: same
  `prepare_document_page(file_path)` entry point, same output keys
  (`blur_score`, `stop_recommended`, `stop_reasons`, ...), just enriched.
- `document_extraction_service.py`: `extract_invoice_document` now calls
  `_image_quality_rejections(evidence)` right after evidence collection (for
  `backend == "openai"`) and returns a stopped, unwritten result
  (`error_code=image_quality_rejected`, `stop_recommended=True`,
  `replacement_recommended=True`) before ever calling OpenAI when a page's
  quality gate says stop. `extract_invoice_document_set` now breaks out of the
  per-page loop as soon as one page is rejected, instead of preparing every
  page first. `_collect_openai_evidence` checks the gate immediately after
  image preparation (before OCR/MinerU are attempted) and fails closed — if
  `prepare_document_page` itself raises, that's now treated as a rejection
  (`_quality_gate_failure_report`), not silently swallowed with the original
  image kept as fallback like before.
- `bot_gateway_service.py`: new upload-journal status `quality_rejected`
  (distinct from generic `processing_error`), counted as completed, with a
  Telegram-facing message asking the user to reshoot/replace the file.
- `routers/invoice_review.py`: the shared 422 error detail now also carries
  `error_code`/`replacement_recommended`/`quality_rejections` (additive, three
  keys) so the same information reaches both the bot and the web upload page.
- Dependencies: added `pytesseract>=0.3.13,<1` and (new, not merely implicit)
  `opencv-python>=4.10.0,<5` to `backend/requirements.txt`; added
  `tesseract-ocr`/`tesseract-ocr-osd` to the `Dockerfile` apt install plus a
  build-time smoke test (`tesseract --list-langs | grep -qx osd`).
- Tests: ported the full `test_document_image_preparation.py` (34 tests,
  replacing this repo's 3 pre-existing ones which are a strict subset) and the
  new quality-gate-specific tests from `test_document_extraction_service.py`
  (7) and `test_bot_gateway_service.py` (2), with only import-path edits
  (`app.domains.invoice_pipeline.services...` → `app.services...`).

**Real, unanticipated issue found during porting (not a code conflict — a
dependency-resolution one)**: this repo's `requirements.txt` never pinned
`opencv-python` directly; it was pulled in transitively and unpinned by
`mineru`, and on this workstation resolved to `opencv-python 5.0.0.93` — a
major version whose `cv2.HoughLinesP` return shape broke Andrey's line-angle
skew-estimation code (`lines[:, 0]` unpacking `TypeError`). The
`auto-snab-document-parser` repo avoids this by pinning
`opencv-python-headless>=4.10.0,<5` explicitly. Fixed here by adding the same
upper-bound pin (`opencv-python>=4.10.0,<5`, matching the existing
non-headless package name already in use) and reinstalling; confirmed
`mineru`'s own requirement (`opencv-python>=4.11.0.86`, no upper bound) is
compatible with the pin. All 34 image-preparation tests pass after the pin.
**Anyone reinstalling this repo's venv from a clean `pip install` should get
opencv 4.x automatically now that it's pinned** — before this fix a fresh
install could have silently picked up 5.x and broken skew estimation exactly
like this.

**Verification**: full backend suite outside the two known-quirky files
(`test_receiving.py` hangs/has 10 pre-existing failures,
`test_telegram_bot.py` can't collect — missing `aiogram` dev dependency, both
pre-existing and unrelated) — **299 passed, 1 failed**. The 1 failure
(`test_collect_openai_evidence_falls_back_to_mineru_after_empty_ocr`) is
pre-existing, confirmed identical before and after this change via
`git stash`. `test_receiving.py`'s 10 failures also confirmed byte-identical
before/after via the same method. **Zero regressions.**

**Deliberate scope decision, not yet resolved**: the quality gate as ported
only naturally covers `backend == "openai"` (the only backend that exists in
`auto-snab-document-parser`, where Andrey wrote this). This repo also has
`mineru`/`hybrid` backends with their own code paths in
`extract_invoice_document` that do not currently call
`_image_quality_rejections` — a bad photo run through `mineru`/`hybrid` mode
is not gated by this change. Whether to extend the gate there is an open
product decision, not done in this port.

**Deployed live 2026-07-31/08-01** to `78.17.160.248` (`autosnab_backend_mvp4`,
the developer's personal/draft VPS, also running an unrelated Amnezia
WireGuard/Xray VPN service on the same box). SSH access re-authorized for
this session (not durable across sessions, per established pattern — user
added this session's key to `authorized_keys`). Backed up the 7 changed files
to `/opt/autosnab_mvp_backups/2026-07-31-quality-gate-port/` first. Compared
each target file against the VPS's actual current content before touching
anything: 6 of 7 were byte-identical to this repo's pre-port `HEAD`
(`document_image_preparation_service.py`, `document_extraction_service.py`,
`bot_gateway_service.py`, `routers/invoice_review.py`,
`openai_invoice_parser_service.py`, `Dockerfile`) — no drift for these
specific files despite the VPS's known general drift from `develop` (see the
2026-07-31 header-whitespace deploy entry) — and `requirements.txt` differed
by exactly one pre-existing missing line (`pypdfium2`) that this port's own
version already carries. Given near-zero drift, deployed via direct `scp` of
the 7 files rather than the heavier full-tree `git archive` method.

**Real deploy-process bug hit and caught before declaring success**: the
first `docker compose --profile public-ip build backend` produced an image
whose `document_extraction_service.py` had **zero** occurrences of the new
code — the file on the VPS host itself was confirmed correct (byte-identical
to local, `image_quality_rejected` present) both before and after that build,
but the built image (verified via `docker run --rm ... md5sum` on a
throwaway container, bypassing any doubt about the running container)
contained an older version, timestamped (per the VPS's own clock) hours
before the scp. Root cause not conclusively identified — the VPS reports
`System clock synchronized: no`, so a clock event during the session is one
plausible explanation, but this was not chased further since a reliable fix
existed regardless of cause. **Caught by verifying the actual running
container's source via `inspect.getsource` before declaring the deploy done,
not by trusting the build/health-check output** — this is the same discipline
prior deploy log entries in this file already established (e.g. the
2026-07-26 "confirmed via `docker exec`/`inspect.getsource`" pattern) and it
paid off directly this time. Fixed by rebuilding with `docker compose build
--no-cache backend` (new image `69bb5fb51a31`, ~27 min build — apt+full pip
resync with no layer reuse, plus an unusually slow ~26min layer-export/unpack
step observed only on this rebuild, cause not investigated) and verifying the
new image's file contents via a disposable `docker run --rm ... grep`
**before** recreating the container.
- Post-deploy verification, all confirmed live via `docker exec` inside the
  actually-running container (not just the image): `image_quality_rejected`
  wired into `extract_invoice_document`, `_image_quality_rejections` present,
  `quality_rejected` wired into `_bot_status_message`, `CRITICAL_BLUR_SCORE`
  and `_tesseract_orientation` present in the preparation service,
  `dry_weight_unknown`/`in_brine` present in `SYSTEM_PROMPT` (confirms the
  same-day packaging-facts prompt fix — see `unit-conversion-rules.md` — rode
  along in this deploy too, since it touched the same file). `pytesseract`
  reports a live `tesseract 5.5.0` binary. Container recreated with
  `--force-recreate`, confirmed `docker inspect` shows `status=running
  health=healthy` and `/health/runtime` returns
  `{"status":"ok","database":{"ready":true}}`.
- **Not done yet**: no live end-to-end test of an actual bad photo being
  rejected through the real bot/upload flow (only static source-level
  verification so far); the `mineru`/`hybrid`-backend scope gap noted above
  is still open; no notification sent to Lilia about this change yet.

**Not done yet** (superseded notes, kept for history — see the deployed
entry above for current status):
- Docker image build not fully verified locally: tried twice. Both times the
  `apt-get install` layer (including the new `tesseract-ocr`/`tesseract-ocr-osd`
  packages this port added) built and cached cleanly. Both times `pip install
  -r requirements.txt` inside the container failed on a network read timeout
  to `pypi.org`/`files.pythonhosted.org` (different package each time —
  `fastapi` then `sqlalchemy`, both pre-existing pins unrelated to this port).
  Direct `curl` from the same host to the same URLs succeeded instantly
  (200, <2s), so this is very likely container-network flakiness specific to
  this local sandbox's legacy (non-buildx) Docker builder, not a real pypi
  outage or a defect introduced by this change. **The one part of the
  Dockerfile this port actually changed (the apt layer) is confirmed working;
  the full image build (including whether `pip install pytesseract` and the
  final `tesseract --list-langs | grep -qx osd` smoke test succeed) is still
  unverified** — needs either a retry in a more stable network environment or
  verification directly at VPS deploy time. First attempt's exit-code check
  was itself wrong (piped through `tee | tail`, which reports `tail`'s exit
  code, not `docker build`'s) — the second attempt used `pipefail` to get an
  accurate result.
- No system `tesseract` binary is installed
  on this dev workstation either, so `pytesseract` calls locally fall back
  gracefully to their "OSD unavailable" branch (by design — `_tesseract_orientation`
  catches `ImportError`/any exception and returns a null result) rather than
  exercising the real OSD path; local test runs did not need real OCR
  orientation detection to pass, but that specific behavior is unverified
  outside Docker/VPS.
- Not deployed anywhere. Needs the same full-tree sync method noted in the
  2026-07-31 header-whitespace deploy entry (VPS `78.17.160.248` is known to
  have drifted from `develop`) rather than a single-file `scp`, since this
  touches the Dockerfile/requirements.txt themselves.
- The `mineru`/`hybrid`-backend scope gap above.
- No live end-to-end test yet of an actual bad photo being rejected before
  reaching OpenAI.

## Diagnostic findings, 2026-07-31: what's actually causing poor recognition (real DB data, not guesses)

User asked to identify, directly from the live server, which invoices recognize poorly and why — instead of continuing to wait for Lilia's promised concrete failing examples (still not sent as of this writing). Scanned all 93 `receiving_documents` ever created on `78.17.160.248` and categorized every stored `review_flags` entry from each document's `recognized_items_json`.

**Headline finding: the built-in photo-quality gate (`blur_score`/`glare_ratio`/`dark_ratio`/`clipping_ratio`/`text_coverage_ratio`, see blocker #5 above) has never fired, not once, across all 93 documents.** By the pipeline's own measurements, no uploaded photo has ever been too blurry, glary, dark, clipped, or text-sparse. This reframes Lilia's 2026-07-29 "low-quality photos recognize poorly" report: it is very unlikely to be classic lens/lighting photo quality, since that's exactly what this gate measures and it has never once tripped.

**What the flags actually show, by volume (across all 93 documents' `review_flags`):**
- 599× `Товар не найден в справочнике` (product not in the `Товары` catalog) — a catalog-completeness gap, not a recognition failure; the text was read correctly, it just doesn't match anything on file.
- 553× `Фасовка не найдена в справочнике` (no matching `Правила фасовок` rule) — same category, packaging/conversion side.
- 217× line-amount-vs-quantity×price mismatches — the closest thing to a genuine misread (wrong digit) in the whole dataset, but could equally be legitimate rounding/discount lines; not isolated further this session.

**The real, concrete "poor recognition" signal — 8 page-structure problems, all with a specific identifiable pattern:**
1. **Накладная №43958, ИП Полуян Денис Дмитриевич** — uploaded twice (2026-07-30 10:53 and 14:14), **both times missing page 1** (`"В маркерах страниц пропущены страницы: 1"`). Confirmed by listing the actual uploaded files on disk: both drafts contain exactly 2 photos, never 3. Systematic, not a one-off — whoever photographs this specific invoice consistently skips its first page.
2. **МЕТРО накладные (4 separate uploads: receiving ids 4, 26, 27, 32)** — each one's own page markers declare ≥3 pages, but only 2 were ever uploaded (`"Маркер страниц документа указывает минимум на 3 стр., но загружено только 2"`). Also systematic across 4 independent uploads, not one mistake.
3. **Receiving id 91 (БАЛТСМАК ПЛЮС, №26745), 2026-07-31 ~14:32** — the 2 photos in this one draft turned out to belong to **two different invoices** (`"На страницах найдены разные значения номера документа: 14882, 26745"`). Cross-checked file timestamps on disk: the draft's first photo has the exact same modification time as when the *previous* invoice (id 90, №14882) was finalized ("Готово"). This looks less like a user mistake and more like a possible draft-state carryover bug (a leftover page from the prior draft not fully cleared before the next one started collecting pages) — **not confirmed, just flagged**; needs either a code trace of the draft-reset path (`bot_ingestion_service.py`/`handlers.py`) or direct confirmation from Lilia on whether she intentionally photographed two different накладные in one sitting.

**Practical conclusion**: the actual, evidenced "poor recognition" complaint is about **incomplete or mixed page capture** during upload, not photo sharpness/lighting/blur as the 2026-07-29 assumption had it. Recommended next step (not yet done): investigate the draft-carryover hypothesis for finding #3 in the bot code, since it's the only one of the three that looks like a possible bug rather than a user capture habit.

**Not done this session**: recomputing actual numeric `blur_score`/`glare_ratio` values against the raw stored photos (the DB only ever stores the pass/fail text flags, never the underlying numbers, so no historical trail of real quality scores exists — only a fresh recomputation against files still on disk under `/app/uploads/invoices/` could produce them).

## First real-world example of the "Низкое разрешение" warning band causing actual recognition damage (2026-08-03)

The first real Telegram-bot upload traced through the new Langfuse integration (see `docs/wiki/langfuse-observability-integration-plan.md`) happened to be a low-resolution photo — surfaced the exact cost of the warning-not-block resolution band from the 2026-07-31 hard-gate port above, concretely for the first time.

Photo's short side: **1224px** — inside the `LOW_RESOLUTION_SHORT_SIDE` (900px) to `MIN_QUALITY_SHORT_SIDE` (1500px) band in `document_image_preparation_service.py`, i.e. exactly the "Низкое разрешение... рекомендуется от 1500px" **warning**, not the `CRITICAL_QUALITY_SHORT_SIDE` (650px) hard stop. Confirms the gate behaved exactly as designed for this band (warn, don't block) — not a bug.

**Downstream effect, visible end-to-end in the Langfuse trace**: `document_number`, `document_date`, and `supplier_name` all failed recognition outright (`severity: error`), `supplier_inn` failed validation, and `total_with_vat` didn't reconcile — while the main item table (larger text) still recognized fine (2 items, correct name/unit/quantity/price). This is a plausible mechanism for at least part of the 2026-07-29 "low-quality photos recognize poorly" complaint that the 2026-07-31 diagnostic above concluded was *not* about blur/glare (those never fired) — resolution-band photos in the 900-1500px warning zone can still cause real header/footer recognition loss even when the old blur/glare/dark/clipping metrics all pass clean, since those measure different things than raw pixel resolution.

**Not done / not decided**: whether the 900-1500px band should be tightened toward a harder stop, given this first concrete evidence that it does cause real damage — flagged for a decision, not acted on unilaterally (would need more than one example before tuning a threshold that affects every upload).

## Delivery order

### Phase 0: freeze observable contracts

- Keep the existing Pydantic parser result as the model-output boundary.
- Add a versioned evidence contract containing:
  - logical document ID;
  - ordered pages;
  - original file metadata;
  - prepared image paths;
  - OCR/MinerU text and structured blocks;
  - extraction errors per provider;
  - provider timing and attempt count.
- Add a version field to debug traces and normalized payloads.
- Ensure every provider attempt is visible in live logs.
- Treat empty evidence, empty model JSON, invalid schema, and zero item rows as
  explicit stop conditions unless the document type legitimately has no items.
- Never create a Google Sheet block after a stopped pipeline.

Acceptance:

- one trace explains which providers ran, what they returned, and why the
  pipeline continued or stopped;
- no failed provider is silently converted into a successful empty payload.

### Phase 1: repair the runtime evidence path

- Fix MinerU/OpenCV in Docker:
  - prefer a headless OpenCV-compatible dependency if MinerU supports it;
  - otherwise install the minimal required Debian runtime libraries, including
    the package providing `libxcb.so.1`;
  - add a container smoke test that imports `cv2` and starts the MinerU CLI.
- Diagnose Google TLS failures separately from parser failures:
  - verify DNS, CA certificates, OAuth refresh, and outbound connectivity;
  - add bounded retries with exponential backoff for transient handshake and
    timeout errors;
  - log the failing Google operation without exposing tokens;
  - return a typed provider error after retries are exhausted.
- Add health checks for `mineru`, `google_ocr`, and `openai` readiness.

Acceptance:

- a clean `docker compose up --build` passes the MinerU import/CLI smoke test;
- one sample image produces non-empty evidence in Docker;
- a Google OCR outage is reported as a provider outage, not as an empty invoice;
- OpenAI invocation count is visible in the trace.

### Phase 2: add logical multi-page upload

- Change the upload UI to accept multiple images and PDFs for one document.
- Show ordered page previews with reorder and remove controls.
- Add a logical upload/document ID distinct from individual page/file IDs.
- Persist page order and original filenames.
- Preserve the current single-file endpoint as a compatibility adapter.
- Pass all pages through one extraction and one OpenAI parse request.
- Reject or flag pages whose document number/supplier conflicts with page 1.

Acceptance:

- photos `...8411` and `...8412` are parsed as one invoice
  `УПМК003248`;
- document-level fields come from the complete page set;
- item rows from all pages are retained in source order;
- only one document block and one document ID are created.

### Phase 3: deterministic document preparation

- Preserve originals and generate separate prepared derivatives.
- Apply EXIF orientation and deterministic 90-degree rotation detection.
- Add deskew, perspective correction, border crop, contrast normalization, and
  conservative upscale for small text.
- Record every transformation in `source_trace`.
- Calculate basic quality signals: resolution, blur, clipping, glare, and
  estimated text coverage.
- Stop or require review when the image is too damaged for reliable extraction.

Acceptance:

- both rotated UPD photos enter OCR and vision upright;
- prepared derivatives remain traceable to their originals;
- transformations never overwrite uploaded source files.

### Phase 4: make OpenAI parsing genuinely multimodal

- Extend `openai_invoice_parser_service.py` to send:
  - OCR/MinerU text as textual evidence;
  - ordered prepared page images as image inputs;
  - page labels so `source_fragment` can identify the source page.
- For image documents, use text plus images together rather than waiting for
  OCR to become empty. Non-empty OCR may still contain wrong digits.
- Keep strict Pydantic Structured Outputs and the current deterministic
  normalization after the model.
- Add configurable limits for page count, image size, timeout, and retries.
- Keep `gpt-5-mini` as the baseline. Benchmark it against the selected newer
  mini candidate; change the default only if golden-set accuracy improves
  enough to justify latency and cost.
- Rename UI wording so “OpenAI parser” and “OpenAI vision parser” accurately
  describe whether images are sent.

Acceptance:

- debug evidence proves that OpenAI received each intended page;
- the model can recover a field from the image when OCR text omitted it;
- malformed or empty structured output stops before persistence/writing;
- the model still has no Google Sheets access or column-selection authority.

### Phase 5: strengthen deterministic validation

- Validate INN length and checksum and detect merged `ИНН/КПП`.
- Cross-check document number, date, supplier, totals, and VAT across pages.
- Recalculate each line and document totals using decimal arithmetic and
  configured tolerances.
- Detect missing continuation pages from page markers and inconsistent totals.
- Classify supported forms deterministically: UPD, TORG-12/товарная накладная,
  receipt, and unknown.
- Preserve repeated receipt lines exactly as source rows during parsing.
- If aggregation is required for accounting, perform it as a separate
  deterministic post-processing step with an audit link to original lines.
- Guarantee non-empty `Наименование товара в УС` from the normalized candidate
  even when catalog matching fails.
- Implement the deterministic conversion contract from
  `unit-conversion-rules.md`:
  - define the coefficient as accounting units per one document unit;
  - calculate both `Кол-во в УС` and `Цена в УС`;
  - use `Decimal` and verify that conversion preserves the line amount;
  - recompute standard coefficients from package value and units instead of
    trusting model output or manual user input;
  - add a deterministic product-exception reference for relations such as
    `шт -> кг`;
  - flag ambiguous or conflicting exceptions as `Сопоставление`;
  - retain conversion method, inputs, source reference, and unrounded results
    in debug metadata.

Acceptance:

- wrong or ambiguous INN cannot silently become `Распознано`;
- totals and VAT discrepancies produce item/document review flags;
- first-row-only document fields and row-specific corrections remain intact.
- `Цена в УС` is no longer left empty when conversion inputs are valid;
- `quantity_document * price_document` equals
  `quantity_us * price_us` within the configured tolerance;
- no ambiguous product exception is selected automatically.

**Update (2026-08-05/06): "recalculate document totals" line item was already done, not just planned.** `invoice_normalization_service.py` has summed line items with `Decimal` arithmetic and flagged mismatches against `document.total_with_vat` (tolerance `MONEY_TOLERANCE = Decimal("0.02")`) for a while before this note was written — this page was stale relative to the code. Triggered by the 2026-08-05 live batch test (`docs/wiki/invoice-bot-live-batch-test-2026-08-05.md`), the same cross-check was extended to `total_without_vat` and `vat_total` (previously normalized to `Decimal` but never independently reconciled against summed line values) — same `_flag`/`_close` pattern, same tolerance. Line-level `amount_without_vat`/`amount_with_vat` recalculation (qty×price, net+vat) was also already present. Still open from this Phase: INN checksum/merged-ИНН/КПП detection status unverified against this note, continuation-page/missing-page detection, deterministic form classification, and the full unit-conversion contract.

### Phase 6: turn the photos into an executable golden set

- Store expected fixtures outside production code:
  - source document identity;
  - page grouping and order;
  - expected header fields;
  - expected source item rows;
- expected normalized names and units;
- expected conversion factor, method, accounting quantity, and accounting
  price;
- expected totals and review flags;
  - expected `Накладная` rows.
- Cover the four logical documents:
  - UPD `1928`;
  - UPD `УТ-35634`;
  - two-page invoice `УПМК003248`;
  - retail receipt with repeated kefir lines and one bag line.
- Add three test levels:
  - deterministic unit tests with mocked provider responses;
  - replay tests from saved evidence/model JSON;
  - opt-in live provider evaluation that never writes to Google Sheets.
- Produce a compact evaluation report per model/provider configuration.

Required metrics:

- exact match for document number, date, supplier INN, line quantities, prices,
  VAT, and totals;
- item row precision/recall;
- non-empty normalized product name rate;
- correct page grouping;
- correct review/stop decision;
- exact sheet-column mapping.

Release gate for this set:

- all four documents grouped correctly;
- 100% exact match on document number/date/INN and numeric line fields;
- 100% non-empty normalized product names;
- 100% correct deterministic conversions for rows with complete inputs;
- no sheet write from a stopped or schema-invalid pipeline.

### Phase 7: live Google Sheets retest

- Run the complete chain against the user-owned test sheet only after phases
  1–6 pass.
- Upload each logical document once.
- Compare written rows with the golden expected rows by row-2 header names.
- Verify formulas, validations, separator rows, and first-row-only fields.
- Verify duplicate behavior by uploading one confirmed duplicate.
- Record sheet ID, inserted range, trace ID, model, and evidence version in the
  test report.

Acceptance:

- values land under the exact existing headers;
- formulas and validations are unchanged;
- document statuses appear only in the first row;
- corrections appear only in affected item rows;
- document IDs are unique and stable.

## Suggested implementation batches

### Batch A: unblock and measure

- Phase 0 trace contract
- Phase 1 Docker/Google fixes
- golden fixtures and a no-write live evaluator

This batch must come first because model quality cannot be measured while no
evidence reaches OpenAI.

### Batch B: improve real-photo quality

- Phase 2 multi-page intake
- Phase 3 preparation
- Phase 4 multimodal OpenAI input

### Batch C: production gate

- Phase 5 validation
- Phase 6 full golden evaluation
- Phase 7 Google Sheets retest

## Idea (proposed by Pavel, 2026-07-30, not yet approved or scoped): piecewise/puzzle-style recapture

Pavel sent a voice message (`src_20260730_pavel_audio`, transcript
`src_20260730_pavel_audio_transcript`) proposing an alternative to a flat
"retake the whole photo" quality gate (see the 2026-07-29 low-quality-photos
open item in `docs/wiki/current-status.md`): instead of rejecting a bad photo
outright, let the agent extract whatever fields it can read from the current
shot, then ask the user to photograph specific missing/unreadable pieces of
the same invoice, and assemble the final document from all the partial shots
like a puzzle. He suggested the pieces could be tied back to the same
in-progress document by invoice number (or some other identifier exchanged
with the user) and offered to help design that identification logic further.

This is a genuinely different shape from Phase 2's multi-page upload (which
assumes each page is a full page of the same document supplied together, all
at once) and from the 2026-07-29 pre-upload quality gate (which assumes a
binary accept/retake decision on one shot). Piecewise recapture would need,
at minimum: a per-field/per-region confidence or "missing" signal from the
extraction step (not just a whole-document quality score), a way to tell the
user in plain language which part of the invoice to reshoot (e.g. "сфотографируй
шапку документа" / "сфотографируй строки товаров снизу таблицы"), and a
session/identifier mechanism so a follow-up photo merges into the same
in-progress document instead of starting a new one — the Telegram bot already
has a draft/session concept (`_finalize_and_start_poll`,
`DRAFT_ACTIONS_KEYBOARD`) that this could potentially reuse rather than
inventing a new one.

**Not designed, not scoped, no code written.** Open questions before this can
become a phase: how per-region confidence would actually be computed (OpenAI
has no notion of "this field wasn't visible" vs. "this field is genuinely
absent from the invoice"), whether recapture should be scoped to the existing
draft/session flow, and whether Pavel's offered help on the identification
logic should be taken up before or after Lilia's concrete failing examples
(still pending, per the 2026-07-29 entry) are available to validate that
photo quality is really the dominant failure mode worth solving this way.

**Feasibility assessment, 2026-07-30 (assistant opinion, not yet validated against real data):**
technically buildable — the Telegram bot's existing draft/session concept
already gives per-chat correlation for follow-up photos, so Pavel's proposed
invoice-number matching is likely unnecessary complexity for the single-active-draft
case (it would only matter for a batch/no-session import path, which this
isn't). GPT-5-mini vision is plausibly capable of describing "table cut off
at the bottom" or "header not visible" in plain language, which is the core
per-region signal the idea needs.

The real risk is whether it targets the actual failure mode. Piecewise recapture
only helps when content is genuinely out of frame (a long invoice that doesn't
fit one shot). It does nothing for whole-image blur or glare — reshooting a
crop of the same document under the same lighting/focus conditions reproduces
the same defect. Recommendation: do not design this further until Lilia's
concrete failing examples (still pending) show that "missing region" rather
than "uniformly bad capture" is the dominant failure — otherwise this risks
solving a problem the real complaints don't actually have.

## Non-goals

- model-controlled Google Sheets operations;
- dynamic column naming or mapping;
- automatic catalog creation from model output;
- silent aggregation of source item rows;
- broad SBIS changes before the photo pipeline passes its release gate.

## Definition of done

The work is complete when the five source photos are processed as four logical
documents, all golden metrics pass, every provider and model step is visible in
live logs, failed pipelines cannot write to Google Sheets, and a live test
places normalized rows under the unchanged `Накладная` headers.
