---
title: Unit Conversion Rules
source: raw
compiled_from: [src_3b4148378c]
created: 2026-07-04
updated: 2026-07-20
tags: [invoices, normalization, units, conversion, pricing]
status: current
---

# Unit Conversion Rules

## Business requirement

The user must not enter the conversion coefficient manually when package size
and units are known. Backend code must calculate the coefficient, accounting
quantity, and accounting unit price before rows reach the quality-control
sheet.

The model may return package and conversion candidates, but they are evidence
only. The deterministic conversion engine is authoritative.

## Coefficient definition

Use one unambiguous definition throughout the system:

```text
k = quantity in the accounting unit contained in one document unit
```

Examples:

| Document package | Accounting unit | k |
| --- | --- | ---: |
| 250 g | kg | 0.25 |
| 980 ml | l | 0.98 |
| 5 l | l | 5 |
| 0.25 kg | kg | 0.25 |

For a document row:

```text
quantity_us = quantity_document * k
price_us = price_document / k
```

The price formula is valid only when `price_document` is the price for one
`document_unit` and `k > 0`.

The invariant is:

```text
quantity_document * price_document
≈ quantity_us * price_us
```

The comparison must use the same VAT basis as the source price and configured
rounding tolerance.

## Deterministic conversion order

1. Normalize document and accounting units.
2. If both units are the same and no package conversion is needed, use `k=1`.
3. Calculate standard physical conversions from package data:
   - g to kg: `value / 1000`;
   - kg to kg: `value`;
   - ml to l: `value / 1000`;
   - l to l: `value`;
   - pieces to pieces: `value`;
   - compound packages: multiply package size by contained unit count.
4. Use an exact active product exception only when standard conversion cannot
   describe the relation, for example `piece -> kg`.
5. If inputs conflict or no unique conversion exists, do not guess. Leave
   converted numeric values empty and add row correction `Сопоставление`.

## Default behavior when no rule matches (fixed 2026-07-20)

Real tester feedback (Lilia, `Метро.pdf`, 2026-07-20) showed step 5 above was
documented but not actually implemented for the "no reference row at all"
case: any recognized `number + unit` text pattern in the item name (`250 ШТ`,
`0,5Л`, `12 РУЛ`) was silently decomposed into base units whenever no
`Справочник фасовок` row *conflicted* with the computed value — it was never
required that a row *confirm* decomposition should happen. This produced
wrong `Кол-во в УС` for every discrete-package product without a reference
row yet: napkins (`3 пач` became `750`), toilet paper (`2 уп` stayed `2`
instead of becoming `24`), 0.5 л water (`24 бут` became `12`), trash bags
(`6` became `60`), and drinking straws (`2 уп` became `300`).

This is now fixed in `backend/app/services/item_normalization_service.py`
(`_resolve_conversion`): a package-shaped multiplier computed from name text
is only ever a *candidate*. Without an active matching rule row, the
accounting quantity defaults to the document quantity unchanged
(`conversion_method = identity_no_rule`), and a soft (non-blocking) review
note is attached so the gap stays visible without forcing every unconfigured
SKU into manual review. Document-unit identity — the document unit already
*is* the accounting unit, e.g. produce sold by weight in `кг` — remains safe
without a rule, since no package-based guess is involved there.
`backend/tests/test_item_normalization_service.py` encodes all seven of
Lilia's examples as regression tests.

## Exception reference

The source document proposes average weight per piece, for example:

| Product | kg per piece |
| --- | ---: |
| Яйцо С0 | 0.065 |
| Яйцо С1 | 0.055 |
| Яйцо С2 | 0.045 |
| Лимон | 0.120 |
| Лайм | 0.080 |
| Авокадо | 0.350 or 0.400 |

This must be a deterministic reference, not prompt knowledge. A safe exception
record needs at least:

- stable ID;
- normalized product or product ID;
- document unit;
- accounting unit;
- factor value;
- optional package/variant/supplier qualifier;
- active flag;
- effective dates;
- source/comment.

Two active avocado values without a distinguishing qualifier are ambiguous.
The backend must require manual matching instead of choosing one.

## Existing package reference

`Справочник фасовок` identifies package aliases and conversion inputs. Its
existing `Коэффициент пересчета` is retained for compatibility, but the
backend recomputes the factor from package value and units whenever possible
for package-text-matched rows, and flags a mismatch instead of silently
picking one value.

If the stored and computed factors differ:

- use neither value silently;
- add a review flag (`Сопоставление`, both values kept in
  `stored_conversion_factor` / debug trace);
- require correction of the reference data.

### One merged rule sheet, not two (per 2026-07-20 tester feedback)

Rather than a second `Исключения`/product-exception sheet, `Справочник
фасовок` is the single rules table for both package-shaped and
product-identity conversions (`backend/app/services/item_normalization_service.py`,
`_resolve_conversion` / `_match_conversion_rule`). A row is matched either by
package text (`Фасовка в документе` / `Состав упаковки` / `Варианты`) or by
the matched УС product (`Наименование товара УС` / `Код товара УС`), plus an
optional `Активна`, `Ед.изм. в документе`, and free-text `Вариант`/
`Квалификатор` qualifier.

Recommended extended columns (existing ones unchanged: `ID`, `Фасовка в
документе`, `Основная фасовка`, `Варианты`, `Коэффициент пересчета`,
`Единица учета в УС`, `Активна`):

| Column | Purpose |
| --- | --- |
| `Способ пересчета` | `Без пересчета` / `По количеству вложений` / `По весу/объему` / `По сухому весу` / `Ручная проверка` — see below |
| `Поставщик`, `ИНН поставщика`, `Код товара поставщика` | scope a rule to one supplier/SKU |
| `Наименование из документа` | free-text reference for whoever authors the rule |
| `Код товара УС`, `Наименование товара УС` | match by the matched catalog product instead of package text |
| `Склад/назначение` | informational only, not read by the matcher yet |
| `Комментарий` | informational only |

`google_sheets_service.load_invoice_reference_catalogs()` reads
`'Справочник фасовок'!A1:Z` (widened from the historical `A1:M`) so these
columns are picked up automatically once added to the live sheet —
`_table_rows_as_dicts` keys rows by whatever header text is present, so this
is a no-op until the sheet itself is extended. **The live sheet has not been
extended yet** — per the tester's explicit request, the column structure
should be reviewed with her/the AI-specialist before anyone adds rows.

`Способ пересчета` dispatch (`_resolve_conversion`):

- `Без пересчета` → multiplier `1`, keep the document quantity as-is.
- `По количеству вложений` → multiplier = `Коэффициент пересчета` (or the
  computed package multiplier as a fallback).
- `По весу/объему` → standard physical conversion (g→kg, ml→l, ...).
- `По сухому весу` → uses the new `package.dry_weight` / `dry_weight_unit`
  fact instead of the gross package weight.
- `Ручная проверка` → always routes to `Сопоставление`, regardless of any
  computed value.
- Rows with a blank `Способ пересчета` (all rows today) keep the pre-existing
  behavior: package-text matches confirm/override the computed value, and
  product-identity matches (weight exceptions) always trust the row's own
  `Коэффициент пересчета` / `Вес 1 шт`.

## Result contract

Each normalized item should carry:

- `conversion_factor`;
- `conversion_method`: `identity`, `identity_document_unit`, `standard`,
  `compound_package`, `identity_no_rule` (no confirming rule found),
  `no_recalculation_rule`, `package_units_rule`, `weight_volume_rule`,
  `dry_weight_rule`, `package_reference` / `product_exception` (legacy rows
  with no explicit `Способ пересчета`), or `unresolved`. Any method except
  `identity`/`identity_document_unit` may carry a `_with_units_per_package`
  suffix;
- `conversion_source_id`, when a reference row was used;
- `document_unit`;
- `accounting_unit`;
- `quantity_document`;
- `quantity_us`;
- `price_document`;
- `price_us`;
- `conversion_review_reason`;
- calculation inputs and unrounded values in debug metadata.

Use `Decimal` internally. Round only at the explicit output boundary according
to the accounting system's quantity and price precision.

## Current implementation gap

Updated 2026-07-20. Remaining gaps:

- `Способ пересчета` is a supported column but not yet present on the live
  `Справочник фасовок` sheet — every existing row still uses the legacy
  (blank-method) dispatch path;
- `package.dry_weight` / `dry_weight_unit` extraction is wired into the
  schema and OpenAI prompt, but has not been exercised against a real olives
  invoice yet (only the regression-test fixture);
- `Склад/назначение` and `Комментарий` are read but not used by any matcher
  logic — informational only for now;
- no live retest yet against the real `Метро.pdf` (not available as a file
  in this session — needs registering in `manifests/raw_sources.csv` once
  provided, then a dry-run diff against Lilia's expected values before any
  live sheet write).

## Rule authorship handoff (2026-07-20)

`Метро.pdf` was live-retested this session (registered `src_2f8d118756`,
plus two more scans of the same supplier: `Метро2.pdf`/`src_3e21489c9e`,
`Метро3.pdf`/`src_e69285ed7e`). With no `Способ пересчета` column or rule
rows on the live sheet yet, every item across all three documents correctly
fell through to `identity_no_rule` (or plain `identity` when the document
unit already was the accounting unit) — confirming the fix behaves as
designed: it never guesses, it just waits for a rule.

Lilia separately forwarded a second round of feedback, restating the same
seven `Метро.pdf` examples as corrections against the *old* (pre-fix)
decomposed values, and asking whether a script/AI could ever reliably decide
*when* to decompose a package vs. keep it as-is. Answer given to relay back:
no, and not as a limitation — the engine deliberately does not infer this
from invoice text (it can't know if a product is food, or how a specific
kitchen actually uses it). It requires a one-time human-authored rule per
product via `Способ пересчета`, then applies it automatically on every
future delivery of that item. Mapping of her seven examples to the method
they need (for reference — not pre-filled sheet rows):

| Item | `Способ пересчета` | Expected result |
|---|---|---|
| Салфетки (250 шт/пач × 3 пач) | `Без пересчета` | keep `3` |
| Туалетная бумага (12 рул/уп × 2 уп) | `По количеству вложений`, factor 12 | `24` рул |
| Оливки (строки 1 и 5) | `По сухому весу` | dry/drained weight |
| Вода 0,5Л × 24 бут | `Без пересчета` | keep `24` бут |
| Мешки для мусора (10 шт/рул × 6 рул) | `Без пересчета` | keep `6` рул |
| Чипсы 150г × 15 шт | context-dependent — `Ручная проверка`, or `По весу/объему` if this kitchen always cooks with it | Lilia's call per actual usage |
| Трубочки (150 шт/уп × 2 уп) | `Без пересчета` | keep `2` уп |

**Decision**: Lilia will author the `Способ пересчета` column and the rule
rows herself directly on the live `Справочник фасовок` sheet on 2026-07-21.
No rule rows or rule-authoring tool are being built in this repo for that —
`load_invoice_reference_catalogs()` already reads `A1:Z` and the matcher
already resolves the extended column names via alias lookup
(`_catalog_value`), so nothing on the code side blocks her from adding the
column/rows directly.

Separately, Lilia asked whether mixed food + хозтовары invoices, or invoices
spanning multiple warehouses/departments, should be split into separate
documents, and whether that's supported today. Confirmed it is not — one
uploaded file/page-set is always exactly one logical document with one
document-level `Склад`/`Торговая точка` (`Receiving.venue`, `_invoice_...`
row builders in `invoice_review_service.py` blank the value on every row
after the first). Building this would be a real, separate feature
(product-category taxonomy, one-upload-to-N-documents support, multi-block
Sheets writes). Explicitly postponed — not scoped into this session's work.

## Required tests

- `250 g -> 0.25 kg`;
- `980 ml -> 0.98 l`;
- `5 l -> 5 l`;
- `0.25 kg -> 0.25 kg`;
- identity conversion;
- compound package such as `0.5 l x 12 -> 6 l`;
- egg `С1`, document quantity in pieces, accounting quantity in kg;
- ambiguous avocado exception;
- stored package coefficient conflicting with computed coefficient;
- zero/negative factor rejection;
- quantity/price amount invariant;
- correct `Кол-во в УС` and `Цена в УС` sheet mapping;
- unresolved conversion produces `Сопоставление` only on the affected row;
- **(2026-07-20)** no confirming rule → identity default, not silent
  decomposition (napkins/water/trash-bags/straws shape);
- **(2026-07-20)** `По количеству вложений` rule confirms decomposition
  (toilet-paper shape);
- **(2026-07-20)** `По сухому весу` rule uses `dry_weight`, not gross package
  weight (olives shape);
- **(2026-07-20)** identical evidence resolves to different results purely by
  which rule/method is configured (chips shape) — covered in
  `backend/tests/test_item_normalization_service.py`.

## Open questions before production rollout

- Required quantity and price precision in the target accounting system.
- Whether `Цена в УС` must be calculated from document unit price or from the
  line amount divided by `quantity_us` when source rounding differs.
- Which qualifiers distinguish multiple valid weights for one product, such as
  avocado size, variety, supplier, or package.
- ~~Where the product exception reference will live: a new Google Sheet tab
  or a versioned backend table~~ **Resolved 2026-07-20**: merged into the
  existing `Справочник фасовок` sheet as one extended rules table, per
  explicit tester request not to split it into two sheets. A future move to
  a versioned backend table (mirroring `reference_catalog_service.py`'s
  SQLite-backed product/supplier cache) remains a reasonable next step once
  rule volume grows, but is out of scope for this fix.
