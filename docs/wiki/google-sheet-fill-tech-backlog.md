---
title: Google Sheet Fill Tech Backlog
source: session
compiled_from: [ba-feedback-screenshot-2026-07-05, src_d799d44293]
created: 2026-07-05
updated: 2026-07-05
tags: [backend, backlog, google-sheets, mapping]
status: current
---

# Google Sheet Fill Tech Backlog

## Goal

Turn the analyst remarks and the workbook `Копия АвтоСнаб Кафе Ромашка 3.xlsx`
into an executable backend backlog with concrete module boundaries, code entry
points, and verification targets.

## Current code boundaries

The latest code review points to these modules as the main change surface:

- `backend/app/services/google_sheets_service.py`
  Current shared-sheet remap still contains semantic fallbacks such as
  `Грузоотправитель <- Грузополучатель`.
- `backend/app/services/item_normalization_service.py`
  Owns product match, package match, fallback US name, conversion factor,
  `quantity_us`, and `price_us`.
- `backend/app/services/invoice_normalization_service.py`
  Owns review flags -> `Корректировка` mapping and final document/item review
  statuses.
- `backend/app/routers/invoice_review.py`
  Owns duplicate classification before persistence via `_apply_duplicate_status`.
- `backend/app/services/invoice_review_service.py`
  Owns legacy review payload shaping and read/writeback behavior for old review
  data.

## Priority backlog

### P0. Fix semantic field mapping for document header fields

**Verified 2026-07-27** (live DB + container test):
- `Грузоотправитель`/`Получатель` independence: ✅ FIXED
- `Основание` document-form leak: ⏸ DEFERRED (low priority)
  — `_normalize_basis()` (invoice_normalization_service.py:257) only catches
  "универсальный передаточный документ" / "товарная накладная" patterns;
  "Счет-фактура и документ об отгрузке товаров..." slips through.
  Confirmed via live test in container. Occurred 1/69 docs, non-critical field,
  Lilia hasn't reported it. Fix: add "счет-фактура" to the detection pattern.

Problem proven by workbook:

- `Грузоотправитель` and `Получатель` are filled with buyer-side values in
  rows 3, 8, 19, and 32.
- `Основание` is polluted by UPD/form text in rows 19 and 32.

Code targets:

- `backend/app/services/google_sheets_service.py`
- `backend/app/services/invoice_review_service.py`
- upstream parser/normalization payload fields if they already carry the right
  source values under different keys

Changes:

1. ~~Remove semantic fallback that maps `Грузоотправитель` from
   `Грузополучатель`.~~ ✅ Done
2. ~~Make `Получатель` and `Грузоотправитель` independent write fields.~~ ✅ Done
3. Prevent `Основание` from inheriting document-form text. ⏸ Deferred
4. If shipper/recipient/basis are not confidently extracted, leave them empty
   and attach a review flag instead of fabricating values.

Tests:

- add a shared-sheet mapper test proving shipper is not copied from consignee;
- add a review-payload test proving `Основание` stays empty when only document
  form is known;
- add a parser/normalization test with a TORG-12/UPD sample where shipper,
  recipient, and basis are distinct.

### P0. Make unmatched-product correction deterministic

Problem proven by workbook:

- row 32 shows `Товар найден в справочнике = Нет`, but `Корректировка = Другое`

Code targets:

- `backend/app/services/item_normalization_service.py`
- `backend/app/services/invoice_normalization_service.py`
- `backend/app/services/invoice_review_service.py`

Changes:

1. Treat `product_found = Нет` as the authoritative source for
   `Корректировка = Нет в справочнике`.
2. Keep `Сопоставление` only for ambiguity/incompatible package/unit cases.
3. Ensure writeback/backfill for older stored payloads upgrades stale
   `Другое` into `Нет в справочнике` when the deterministic mapping now knows
   the row is a catalog miss.

Tests:

- extend `test_openai_invoice_pipeline.py` with a stale-payload scenario;
- extend `test_google_sheets_service.py` with a row that has
  `Товар найден в справочнике = Нет` and assert `Корректировка = Нет в справочнике`;
- add a review-sheet rebuild test for old documents.

### P0. Stabilize conversion logic and make `Цена в УС` mandatory when conversion is known

Problem proven by workbook:

- same document `УПМК3003248` appears once with identity conversion and once
  with `3.954 -> 15.634116`
- receipt rows already compute `Кол-во в УС`, but still leave `Цена в УС` empty

Code targets:

- `backend/app/services/item_normalization_service.py`
- any legacy payload adapter that may bypass `price_us`
- `backend/app/services/invoice_review_service.py`

Changes:

1. Audit `_calculate_conversion(...)` and `_extract_package(...)` against the
   `УПМК3003248` OCR text to find why one historical path multiplied by package
   count while another did not.
2. Enforce one invariant: if `quantity_us` is computed deterministically, then
   `price_us` must also be computed unless the row is marked unresolved.
3. Persist conversion evidence explicitly:
   `conversion_factor`, `conversion_method`, `package_reference_id`,
   `conversion_amount_delta`, `conversion_review_reason`.
4. During writeback/backfill, do not keep old rows with derived `quantity_us`
   and blank `price_us`.

Tests:

- add a regression fixture for `УПМК3003248` proving `3.954 кг` stays identity;
- add receipt tests proving `0.8 кг` implies a non-empty `Цена в УС`;
- assert amount preservation within tolerance;
- add a backfill test for old rows missing `price_us`.

### P1. Add a receipt-specific normalization branch

Problem proven by workbook:

- rows 11-16 and 21-26 keep receipt item names and quantities, but VAT columns
  and `Цена в УС` stay empty
- receipt identity is unstable: `0245` vs `ЧЕК 0245`

Code targets:

- `backend/app/services/openai_invoice_parser_service.py`
- `backend/app/services/invoice_normalization_service.py`
- `backend/app/services/item_normalization_service.py`

Changes:

1. Add an explicit receipt document-form branch.
2. Normalize receipt document numbers to one canonical shape before dedupe.
3. Extract VAT from receipt evidence when present; otherwise mark as unknown in
   a receipt-specific way rather than pretending the invoice path applies.
4. Keep supplier-related fields optional for receipt flows.

Tests:

- add a receipt golden case covering `0245` and `ЧЕК 0245`;
- add item-level receipt VAT tests;
- add a normalization test proving receipt numbers are canonicalized before
  duplicate check.

### P1. Normalize document identity before duplicate classification

Problem proven by workbook:

- `УПМК3003248` vs `UPMK3003248`
- `0245` vs `ЧЕК 0245`

Code targets:

- `backend/app/routers/invoice_review.py`
- optionally a new helper in `backend/app/services/normalization.py`

Changes:

1. Introduce canonical document-number normalization before `_apply_duplicate_status`.
2. Normalize mixed Cyrillic/Latin lookalikes where safe.
3. Strip superficial prefixes such as `ЧЕК` for receipt-specific duplicate keys.
4. Keep raw source number for display, but dedupe on canonical identity.

Tests:

- add duplicate tests for `УПМК` vs `UPMK`;
- add duplicate tests for `0245` vs `ЧЕК 0245`;
- assert exact duplicates become `Да`, near duplicates remain `?`.

### P2. Tighten fallback `Наименование товара в УС`

Problem proven by workbook:

- rows 17 and 27 use `Пакет-майка Виктория`, while the analyst expects a
  cleaner catalog-facing name

Code targets:

- `backend/app/services/item_normalization_service.py`

Changes:

1. Improve `_clean_product_name(...)` so packaging/promotional tails do not
   dominate the fallback name.
2. Separate brand/descriptor noise from core product noun more aggressively.
3. Keep fallback visible, but closer to a catalog candidate.

Tests:

- add a regression test for `ПАКЕТ-МАЙКА ВИКТОРИЯ 65*40СМ`;
- assert fallback selection order:
  exact match -> normalized candidate -> cleaned source -> raw source.

### P2. Diagnose live `Проверить` gate mismatch

Problem proven by analyst feedback:

- some rows visually satisfy ready conditions but still cannot pass `Проверить`

Code targets:

- `backend/app/services/invoice_review_service.py`
- sheet/App Script contract verification

Changes:

1. Compare backend-written first-row-only fields with the actual cells the live
   script reads.
2. Check whether stale `Корректировка`, `Дубль`, or helper columns `AO:AU`
   remain blocking after rebuild.
3. Encode one backend-side readiness predicate matching the live script.

Tests:

- integration-level no-send test for a row that looks ready but should still be
  blocked;
- once the live rule is known, add a regression fixture mirroring it.

## Suggested execution order

1. P0 semantic header mapping
2. P0 unmatched-product correction
3. P0 conversion stability and `Цена в УС`
4. P1 receipt-specific branch
5. P1 duplicate normalization
6. P2 fallback name cleanup
7. P2 `Проверить` gate diagnosis

## Definition of done

The backlog is complete when all of the following are true:

- `Грузоотправитель`, `Получатель`, and `Основание` are never filled by the
  wrong semantic source
- `Товар найден в справочнике = Нет` always yields `Нет в справочнике`
- deterministic conversion never produces `quantity_us` without `price_us`
- the `УПМК3003248` regression no longer flips between identity and multiplied
  conversion
- receipt blocks write consistent document identity and a receipt-specific VAT
  result
- duplicate classification is stable across `УПМК`/`UPMK` and `0245`/`ЧЕК 0245`
- shared-sheet rows that visually satisfy the ready state also satisfy the real
  `Проверить` gate
