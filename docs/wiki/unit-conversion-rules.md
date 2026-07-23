---
title: Unit Conversion Rules
source: raw
compiled_from: [src_3b4148378c]
created: 2026-07-04
updated: 2026-07-23
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
  `dry_weight_rule`, `coefficient_rule` (2026-07-23: `По коэффициенту` —
  rule's own coefficient only, never a computed fallback),
  `average_weight_rule` (2026-07-23: `По среднему весу штуки` — rule's
  average weight per piece; a real scale-printed weight overriding the
  average is designed but not wired yet, see below), `package_reference` /
  `product_exception` (legacy rows with no explicit `Способ пересчета`), or
  `unresolved`. Any method except `identity`/`identity_document_unit` may
  carry a `_with_units_per_package` suffix;
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

Updated 2026-07-23. Remaining gaps:

- **Resolved 2026-07-23**: rule matching is now specificity-tiered
  (`Код товара УС` > `Склад / назначение` > `ИНН поставщика` /
  `Код товара поставщика` > `Поставщик` > product name > package text), rule
  activity is 3-state (`Активно`/`Неактивно`/`Требует проверки`), and two new
  methods (`По коэффициенту`, `По среднему весу штуки`) are implemented. See
  `item_normalization_service.py`'s `_match_conversion_rule`/
  `_rule_activity_state`/`_resolve_conversion`, test-covered in
  `test_openai_invoice_pipeline.py` with the full pre-existing
  `test_item_normalization_service.py` suite passing unchanged (zero
  regressions, confirmed via `git stash`).
- `Склад / назначение` scoping only ever compares against the
  *document-level* venue/trade-point (one upload = one warehouse value,
  threaded in as `warehouse=` through `apply_reference_mapping_to_payload`)
  — there is no per-item warehouse concept, matching the existing one-upload
  = one document architecture;
- `По среднему весу штуки` uses only the rule's own confirmed average today;
  a real scale-printed weight on the document overriding that average needs
  a new `actual_weight` packaging fact wired through the OpenAI prompt and
  `_package_from_facts` adapter — deliberately deferred, not done yet;
- `package.dry_weight` / `dry_weight_unit` extraction is wired into the
  schema and OpenAI prompt, but has not been exercised against a real olives
  invoice yet (only the regression-test fixture);
- `Комментарий`/`Округление`/`Ручная проверка` (informational rule columns)
  are read but not used by any matcher logic yet;
- **Still unverified against the live Google Sheet**: whether the real
  spreadsheet's rule tab is actually named `Справочник фасовок`,
  `Правила фасовок`, or both, and whether `Накладная`'s real header count
  matches code (see "Header-drift risk flagged" above) — this blocks
  shipping Phase 3 to production, not local development/testing;
- no live retest yet against the real `Метро.pdf` documents through the
  actual OpenAI API — blocked on no `OPENAI_API_KEY`/`.env` on this
  workstation (the fixtures themselves are present at repo root).

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

## AI response restructuring: `packaging_facts` replaces `package`/multiplier fields (2026-07-23, Lilia spec)

Lilia (BA/tester) compared two debug JSON outputs against the current
business logic and identified the actual root cause behind the 2026-07-20
packaging bugs (napkins, water, trash bags, straws, olives, and others): the
AI-produced fields `quantity_multiplier`, `accounting_quantity_candidate`,
`accounting_unit_candidate` are a **business decision made before product
matching**, at a point where the model cannot know the accounting unit. These
fields must stop being trusted/populated as final values — this matches and
sharpens the existing wiki position that "the model may return package and
conversion candidates, but they are evidence only."

Requested restructuring of the AI output contract:

- Replace the single ambiguous `package` object with a `packaging_facts: []`
  array. Each fact carries `type`, `value`, `unit`, `source` (the matched text
  fragment), `confidence`.
- Fact `type` vocabulary: `package_type`, `count_in_package`, `unit_weight`,
  `unit_volume`, `declared_package_mass`, `dry_weight`, `capacity`, `length`,
  `diameter`, `thickness`.
- New `packaging_risk_flags: []`, separate from recognition confidence:
  `in_brine`, `in_syrup`, `in_marinade`, `in_oil`, `dry_weight_unknown`,
  `multiple_ambiguous_values`, `actual_weight_required`.
- `needs_review` (renamed `extraction_needs_review` in her example) is
  reserved **only** for recognition/OCR uncertainty. Business/packaging risk
  must go only into `packaging_risk_flags`, not conflated into the same flag.
- Add a stable `line_id` = `document_id + line_number` (e.g.
  `document-...:9`) so facts survive re-processing without relying on array
  position.
- Do not equate mass with volume; do not invent dry weight, a coefficient, or
  an average weight — those stay downstream deterministic decisions (already
  the architecture's stance, now explicit at the schema level too).
- Keep raw (`raw_name`, `quantity_document`, `document_unit`, requisites,
  sums, `confidence`, `review_flags`) and normalized values separate, as
  today.

Explicit scope limit for this pass (her own words): fix the AI response
structure and resend corrected JSON **for the same two test documents only**.
Do **not** touch the live Google Sheet, do not create new columns/sheets, and
do not wire `packaging_facts` into the real conversion engine yet — this
round is validation-only. Process after the corrected JSON is reviewed: she
and the user approve the final data composition, optionally create a
technical sheet, and partially adapt draft generation — the existing rule
application, manual confirmation, and quantity/price calculation scripts are
explicitly **not** expected to be rewritten.

Items to pay special attention to on the retry (per her list): салфетки,
туалетная бумага, вода, мешки, трубочки, оливки, манго в сиропе, яйца,
булочки 12×89 г, молоко 950 г, чипсы. Note this list only partially overlaps
the seven items from the 2026-07-20 `Метро.pdf` feedback (салфетки/туалетная
бумага/вода/мешки/трубочки/оливки match; манго в сиропе/яйца/булочки/молоко
are new items not seen in that round, so at least one of "the two documents"
is likely not `Метро.pdf` itself) — the actual two source documents/JSONs
have not been provided to this repo/session yet.

She also framed this explicitly as durable target architecture for the
eventual full АвтоСнаб product, not throwaway MVP glue: structured packaging
facts, stable `document_id`/`line_id`, AI-facts-vs-accounting-decision
separation, risk flags, confidence, and source fragment are meant to carry
over into the real service almost unchanged, with the rule/draft/calculation
logic validated in the sheet ported into code once approved and Apps Script
retired.

### Implementation status (2026-07-23)

Phase 1 (this section's schema restructuring) and Phase 2 (reading the new
`Правила фасовок` sheet) from `docs/wiki/n8n-to-native-bot-migration-plan.md`-style
planning are implemented and test-covered on `native-telegram-bot`:

- `InvoiceParsedItem` (AI-facing, `backend/app/schemas/invoice_parser.py`) no
  longer has `package`, `quantity_multiplier`, `accounting_quantity_candidate`,
  or `accounting_unit_candidate` — Pydantic's `extra="forbid"` means OpenAI's
  structured output genuinely cannot populate them anymore, not just "ignored
  downstream." It gained `packaging_facts: list[PackagingFact]` (typed:
  `package_type`, `count_in_package`, `unit_weight`, `unit_volume`,
  `declared_package_mass`, `dry_weight`, `capacity`, `length`, `diameter`,
  `thickness`, `actual_weight`) and `packaging_risk_flags` (`in_brine`,
  `in_syrup`, `in_marinade`, `in_oil`, `dry_weight_unknown`,
  `multiple_ambiguous_values`, `actual_weight_required`).
- A new backend-only `NormalizedInvoiceItem(InvoiceParsedItem)` re-adds
  `package`/`quantity_multiplier`/`accounting_quantity_candidate`/
  `accounting_unit_candidate` plus a new `line_id` field — these only ever
  exist after `item_normalization_service.normalize_item_candidate` runs, never
  on what the model returns. `NormalizedInvoiceResult.items` is now typed as
  `list[NormalizedInvoiceItem]`.
  `line_id` = `f"{document_number}:{line_number}"`, stamped in
  `invoice_normalization_service.normalize_invoice_result`.
- Regex extraction from `raw_name` (`_extract_package`) remains the primary
  packaging source, unchanged. A new adapter, `_package_from_facts()` /
  `_units_per_package_from_facts()` in `item_normalization_service.py`, only
  fires as the fallback (when regex finds nothing) — reading the AI's
  `packaging_facts` instead of the old `package` object. This keeps
  `_calculate_conversion`, `_dry_weight_multiplier`, and
  `apply_reference_mapping_to_payload` byte-for-byte unchanged; they still
  read `item.package`/`item["package"]`, now a backend-derived compatibility
  view instead of an AI-supplied value.
  `packaging_risk_flags` are captured and passed through (into the legacy
  payload / debug traces) but **not yet acted on** by any conversion logic —
  matches Lilia's explicit "don't wire into calc yet" instruction for this
  round.
- `load_invoice_reference_catalogs()` (`google_sheets_service.py`) now also
  reads the `Правила фасовок` tab (`A1:Z`) alongside the older `Справочник
  фасовок`, merging both into one `packages` rule list — additive, not a
  rename, since the live sheet's actual current tab name is still unverified
  (see the header-drift section above).
- SYSTEM_PROMPT (`openai_invoice_parser_service.py`) rewritten to describe
  `packaging_facts`/`packaging_risk_flags` instead of `package`/
  `quantity_multiplier`/`accounting_*_candidate`.
- Full backend test suite: 12 pre-existing failures (all in
  `test_receiving.py`/`test_document_extraction_service.py`, confirmed
  identical with and without this change via `git stash`), 225 passed — zero
  regressions. New/updated tests cover the schema split, the facts-to-package
  adapter, `line_id` format, and reading the new sheet tab.
- **Not done yet**: regenerating the actual debug JSON for the `Метро.pdf`/
  `Метро2.pdf`/`Метро3.pdf` fixtures (the user's confirmed stand-ins for
  Lilia's "two test documents") — blocked on no `OPENAI_API_KEY`/`.env` being
  available on this workstation (confirmed: no `.env` file, no matching env
  var). Needs either a key provided locally or running from the VPS where
  credentials already exist. User explicitly chose to continue with Phase 3
  without this live run rather than wait.
- **Phase 3 implemented 2026-07-23** (same session): specificity-tiered rule
  matching (`_match_conversion_rule` now scores/disqualifies by `Код товара
  УС`/`Склад / назначение`/`ИНН поставщика`/`Код товара поставщика`/
  `Поставщик`/product-name/package-text instead of flat "any 2 matches =
  ambiguous"), 3-state rule activity (`_rule_activity_state`), two new
  recalculation modes (`coefficient_rule`/`average_weight_rule`), a real
  supplier-code-vs-УС-code conflation bug fixed, and column-name aliases for
  the new `Правила фасовок` sheet (`Режим пересчета`/`Коэффициент`/`Ед. изм.
  в УС` alongside the legacy names). `warehouse`/`supplier_inn`/
  `supplier_name` are now threaded from document metadata through
  `apply_reference_mapping_to_payload` → `_resolve_conversion` →
  `_match_conversion_rule`. 6 new tests added, full pre-existing
  `test_item_normalization_service.py` suite passes unchanged (proving the
  new scoring doesn't change no-rule/single-rule behavior); full suite 231
  passed / 12 pre-existing failures — zero regressions.
- **Phase 4 (deferred recalculation across catalog updates) not started** —
  remains as designed in the approved plan, flagged as its own follow-up due
  to unstable per-line SQL PKs and a prepend-only Sheets writer.
- The live-sheet verification gate (tab name, `Накладная` header count) is
  still unverified and blocks shipping Phase 3 to the production spreadsheet
  — local code changes are additive/backward-compatible either way (both old
  and new column names are read), so this is a deploy-time gate, not a
  development blocker.

## New reference sheets found in root workbook copy (2026-07-23, `src_20260723_workbook_pravila`)

A fresh root copy of the workbook (distinct content from the previously
registered `src_239bf1096e` of the same display name) shows the packaging-rule
design has moved well past the "extend `Справочник фасовок` with a `Способ
пересчета` column" plan recorded above. Two new sheets exist:

**`Правила фасовок`** — a 25-column rule table, much richer than planned:
`ID правила`, `Активность правила` (`Активно`/`Неактивно`/`Требует
проверки`), `Приоритет правила`, `Поставщик`, `ИНН поставщика`, `Код товара
поставщика`, `Название из документа`, `Код товара УС`, `Наименование товара в
УС`, `Склад / назначение`, `Ед. изм. документа`, `Тип упаковки`, `Количество
вложений`, `Ед. изм. вложения`, `Вес / объем единицы`, `Ед. изм.
веса/объема`, `Сухой вес единицы`, `Ед. изм. в УС`, `Режим пересчета`
(`Без пересчета` / `По количеству вложений` / `По весу` / `По сухому весу` /
likely also `По среднему весу штуки` / `По коэффициенту` per the sibling
sheet below), `Коэффициент`, `Округление`, `Ручная проверка`, `Комментарий к
правилу`, `Дата подтверждения`, `Кем подтверждено`. Rules are scoped by
product code **and** by `Склад / назначение` (warehouse/destination) —
e.g. the same МЕТРО chips product (`01-00073`-adjacent examples) gets two
different rules depending on whether it's for kitchen use (`По весу`) or
resale (`Без пересчета`), confirming per-destination scoping is now a real
requirement, not just an "informational only" column as previously assumed.
8 rows are `PKG-EX-00x` teaching examples (all `Неактивно`), 10 rows are real
`PKG-MVP-00x` rules (all `Активно`) authored 2026-07-20/22 covering exactly
the packaging items from the 2026-07-20 Lilia feedback plus new ones (масло
для фритюра, подсолнечное масло, манка).

**`Логика фасовок`** — a 16-step narrated process spec ("AI extracts facts,
backend service code applies the accounting rule, Apps Script temporarily
shows/verifies the process in Google Sheets"). Key points not previously
captured in this page:
1. Recalculation must be **deferred** until the item is matched to a УС
   product/code — for a brand-new product, recalculation waits until the
   product is created in УС and a code comes back. Today's code recalculates
   at upload time regardless of match state; this is flagged in the sheet
   itself as "Требуется сделать" (not yet implemented).
2. Rule lookup must go from most-specific to most-general (by УС product
   code, then warehouse/destination, then supplier, then priority) and must
   **not** auto-apply on conflict — multiple equally-specific active rules
   should force manual review, not silently pick one.
3. Only `Активно` rules apply automatically; `Неактивно` and `Требует
   проверки` never do.
4. Recalculation modes enumerated beyond what's implemented today: `Без
   пересчета`, `По вложениям`, `По весу или объему`, `По сухому весу` (falls
   back to manual entry if no reliable value exists — must not be
   invented), and two **not yet in this repo's design**: `По среднему весу
   штуки` (average weight per piece — for avocado/lettuce/microgreens sold
   by count but accounted by weight, with real weighing always overriding
   the average) and `По коэффициенту` (a flat confirmed coefficient when no
   other field is sufficient — AI must never guess it).
5. No matching rule → AI may suggest parameters but the user makes the final
   call; no automatic recalculation until confirmed.

This sheet is effectively the authoritative process spec for implementing
Lilia's separate 2026-07-23 `packaging_facts` JSON restructuring request
(logged in `docs/wiki/log.md`) — steps 3 and 6 there map directly onto this
sheet's step 3 ("AI extracts only explicitly-stated facts, does not choose
the accounting method").

### Header-drift risk flagged, not yet verified live (2026-07-23)

`Накладная` row 2 in this copy has **45 headers**, not the 43 in
`SHARED_INVOICE_HEADERS` (`backend/app/services/google_sheets_service.py`).
Two headers appear that are not in code: `Количество исправлено вручную`
(inserted between `Кол-во в УС` and `Цена за ед-цу`) and `ID правила
фасовки` (inserted between `Время загрузки документа` and `ID документа`).
This is structurally the same class of bug root-caused on 2026-07-14
(silent manual header insertion ahead of a code change) — if the live sheet
already has these two extra columns, every write after `Кол-во в УС` would
land one column off, or the `отсутствуют обязательные заголовки` failure
would recur. **Not yet confirmed against the actual live Google Sheet** —
no live OAuth token is available on this workstation right now (matches the
already-known expired-local-token issue from the 2026-07-20/22 sessions).
Needs a direct Sheets API header read (or asking Lilia/Andrey directly)
before any related code change ships, exactly as was required on 2026-07-14.

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
