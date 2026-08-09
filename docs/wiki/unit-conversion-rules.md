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

### Header-drift risk confirmed live, and a real misalignment bug found and fixed (2026-07-23)

User shared the live spreadsheet URL directly; exported it (`export?format=xlsx`,
publicly link-shared) and inspected it the same way as the local copy. Both
suspicions were confirmed against production, not just the local file:

- The live sheet has **no `Справочник фасовок` tab at all** — only
  `Правила фасовок`, matching the local copy exactly.
- `Накладная` row 2 really does have **45 headers**, not 43: `Количество
  исправлено вручную` (between `Кол-во в УС` and `Цена за ед-цу`) and `ID
  правила фасовки` (before `ID документа`) are both live, not just a local
  draft.

Tracing the actual write path for this drift surfaced a **real, currently-live
production bug**, unrelated to this session's packaging_facts/rule-engine
work: `_read_target_headers()` only checks that the 43 codeexpected headers
are all *present somewhere* in the live row (a subset check) — which passes
fine against a 45-column superset. But the function that turns a built row
into the values actually sent to Google Sheets,
`_align_shared_rows_to_target_headers()`, aligned by **width only**
(pad/truncate a fixed-order 43-value list out to the live column count) —
not by column name. Since `_shared_invoice_item_row()` built each row as a
plain positional list in the old, hardcoded `SHARED_INVOICE_HEADERS` order,
every value from `Цена за ед-цу` onward was landing **one column to the
left** of where the live sheet's real header says it belongs (and two
columns off after `ID правила фасовки`) on every real bot upload — e.g. the
unit price silently writing into the `Количество исправлено вручную` cell.
This is the same class of bug as the 2026-07-14 incident, just not yet
tripped because the missing-header *validation* step doesn't require exact
width, only presence.

**Fixed**: `_shared_invoice_item_row()`/`build_shared_invoice_rows()` (in
`invoice_review_service.py`) now return the row as a dict keyed by column
name instead of a positional list. `google_sheets_service.py`'s
`_align_shared_rows_to_target_headers` was replaced with
`_project_shared_rows_to_target_headers()`, which projects each row dict
onto the actual live header order by name — mirroring the pattern the
legacy `_remap_source_rows_to_shared_sheet()` path already used correctly.
A live column inserted ahead of a code change now just gets written blank
(no matching value), instead of shifting every later value into the wrong
cell. Added a regression test reproducing the exact live drift
(`test_project_shared_rows_to_target_headers_survives_inserted_live_columns`)
plus updated the existing integration test's fixture to the new dict shape.
Full suite: 232 passed (was 231) / 12 pre-existing failures unchanged — zero
regressions.

### Header-drift risk: resolved (confirmed live and fixed, see section above)

Originally flagged here as unverified (no live OAuth token available on this
workstation). The user then shared the live spreadsheet URL directly; both
the tab rename and the 45-column `Накладная` header count were confirmed
against production, and the resulting real write-path misalignment bug was
found and fixed the same session — see "Header-drift risk confirmed live,
and a real misalignment bug found and fixed (2026-07-23)" above.

## `packaging_facts` are currently not durably saved anywhere; new `Факты фасовки AI` sheet spec (2026-07-24, Lilia spec v2)

Lilia asked, before any new sheet gets created, exactly where `packaging_facts`
data lives right now. Traced end to end through code (not from memory):

- `packaging_facts` exists on the Pydantic `NormalizedInvoiceItem` right after
  OpenAI parsing, and `to_legacy_invoice_payload()` (`invoice_normalization_service.py:178`)
  does include it in its output dict.
- But `_item_payload()` (`invoice_review_service.py:1937`), the function that
  actually builds what gets written to `document.recognized_items_json` (the
  durable per-document SQLite column — see `invoice_review_service.py:128`),
  **drops `packaging_facts`/`packaging_risk_flags` entirely**. Only the
  backend-derived `package` view (via `_package_from_facts()`) survives into
  durable storage.
- The only other place the raw facts touch disk is the per-request OpenAI
  debug trace (`_write_debug_log`, `exports/openai_debug/*.json`,
  `openai_invoice_parser_service.py:277`) — a local, unindexed, per-call JSON
  file, not linked to `ID документа`/`ID строки`, not reachable by Apps
  Script, and only present if `openai_debug_log_enabled` is on for that
  environment.
- **Conclusion for Lilia: no, `packaging_facts` are not durably/structurally
  saved anywhere today.** They exist only transiently in memory during one
  request, collapse to a single derived number in `Состав упаковки`, and
  everything else (unit, source fragment, fact type, risk, AI comment) is
  lost the moment the request finishes.
- Live-sheet check (fetched `1UYgYvrWASUenMT8inLOZEwj8gap0TcDODnW01VxpiiY`,
  2026-07-24) confirms this is not theoretical: real row `10ШТ МЕШКИ ДЛЯ
  МУСОРА 120Л METRO PROFESSIONAL 70МКМ` has `Состав упаковки = 10` and
  `Кол-во в УС` correctly left unchanged at 6 (the 2026-07-24 multiplier
  bugfix holds) — but `120Л`, the bag's own volume, is nowhere in the sheet.
  Same for `250ШТ САЛФЕТКИ... 24Х24...`: `Состав упаковки = 250`, `24Х24` is
  gone. These are exactly Lilia's own worked examples, reproduced live.
- Also confirmed live: `Накладная` already carries both `ID документа` (col
  43, first-row-of-block only) and `ID строки` (col 44, populated on every
  item row, e.g. `561`..`578`) as real columns today. A new facts sheet can
  join on these existing IDs directly — no new ID scheme needs inventing.
- No `Факты фасовки AI` (or equivalent) tab exists yet in the live spreadsheet
  (checked sheet list: `Загрузка тест, Накладная, Поставщики, Товары,
  Сопоставление Товаров, Новые товары, Новые товары для УС, Правила фасовок,
  Логика фасовок, Наша фирма, Лист2`).

### Lilia's `Факты фасовки AI` sheet spec (not yet implemented — explicitly withheld pending the above answer)

One row = one semantic fact (not one number). One item can produce 2-3 rows.
Columns:

1. `ID документа` — links to the `Накладная` block.
2. `ID строки` — links to the specific item row.
3. `Наименование товара из документа` — raw source name.
4. `Тип факта` — one of: `артикул/код поставщика`, `количество вложений`,
   `вес`, `объем`, `сухой вес`, `размер`, `характеристика товара`,
   `тип упаковки`, `риск`. (Revised from her first pass: added
   `артикул/код поставщика` and `размер` as distinct types after finding that
   a leading supplier SKU like `12345 Салфетки...` must never be treated as a
   quantity/weight/volume, and that `24х24`-style dimensions are a
   characteristic, not a packaging count.)
5. `Значение` — the extracted number (`10`, `120`, `0,7`, `250`, `1,3`).
6. `Единица` — `шт`, `г`, `кг`, `мл`, `л`, `рул`, `пач`, `бут`, `бан`.
7. `Исходный фрагмент текста` — the exact substring the fact came from
   (`120 л`, `10 шт`, `сухой вес 260 г`).
8. `Уверенность AI` — recognition confidence only (e.g. `0,95`), not a
   guarantee the resulting calculation will be correct.
9. `Признак риска` — Да/Нет. Да for: `в сиропе`/`в рассоле`/`в маринаде`/
   `в масле`/`в заливке`, multiple ambiguous numbers, or unclear meaning.
10. `Комментарий AI` — short free-text explanation.

Worked example, `10ШТ МЕШКИ ДЛЯ МУСОРА 120Л`: two rows — (характеристика
товара, 120, л, "120 л", "Объём одного мешка, не использовать как количество
для прихода") and (количество вложений, 10, шт, "10 шт", "В рулоне/упаковке
10 мешков").

Ambiguous bare-number patterns (`12/0,5`, `6*1`, `24х0,33`, `1/20` — could
mean count×unit-size, a supplier-internal format code, or nothing
meaningful) must still be captured as a fact, never silently dropped and
never auto-multiplied: type `неполная/неоднозначная фасовка`, risk `Да`,
value/text holds the raw string, comment explains the ambiguity. No script
may compute `12 × 0,5` from this until a human confirms a rule or the target
unit is unambiguous from `Товары`.

Governing principle (her final framing, to keep verbatim): **AI extracts the
maximum number of facts; the code computes only what's safe; anything
ambiguous goes to the user.** Concretely: AI extracts facts → script proposes
only safe drafts → an ambiguous row gets status `Требует проверки` → the
responsible user reviews/confirms the packaging rule. Sheet creation is
explicitly deferred until this persistence-location answer was given (this
section) — no `Факты фасовки AI` tab or code change has been made yet.

## Critical finding: a second, independent packaging-rule engine already exists in Apps Script (2026-07-24)

User pasted the full Apps Script bound to the live spreadsheet (menu "Проверка / Загрузка").
Saved verbatim to `apps_script/invoice_review_menu.gs` in this repo (previously
undocumented — no copy existed anywhere in this project before today). This
substantially changes the picture around Phase 1-3 and the `Факты фасовки AI`
discussion above.

**What it contains that overlaps backend code:**
- A full second packaging-rule matching/calculation engine (`findPackagingRule_`,
  `calculatePackagingQuantity_`, `buildPackagingRules_`), independent from
  `item_normalization_service.py`'s Phase 3 engine, reading the same
  `Правила фасовок` sheet.
- A full second product-matching engine (`applyProductMatching_`,
  alias table `Сопоставление Товаров`), independent from
  `reference_catalog_service.py`.
- A **draft-then-confirm workflow for packaging rules that already implements
  most of what Lilia asked for in the section above**: `suggestPackagingRulesForSelectedDocuments()`
  extracts facts from `Наименование товара из документа` via a hardcoded regex
  (`extractPackagingFactsFromName_`), writes draft rows into `Правила фасовок`
  with `Активность правила = "Требует проверки"`, a human confirms via
  `activateSelectedPackagingRuleDrafts()`, and only then does
  `applyPackagingRulesToSelectedDocuments()`/`checkSelectedDocuments()` compute
  `Кол-во в УС`. This is the same shape as her proposed "AI extracts → human
  confirms → code computes only confirmed" principle — just already built,
  using a blind regex instead of AI understanding.

**Why the existing regex (`extractPackagingFactsFromName_`) validates Lilia's concern:**
It classifies every number+unit pair purely by unit type (кг/г→weight, л/мл→volume,
everything else→count) with no concept of "characteristic vs. quantity", no
handling for a leading supplier SKU (`12345 Салфетки...`), and no risk flag for
ambiguous bare numbers (`12/0,5`). The only semantic awareness it has at all is a
small hardcoded keyword list in `requiresDryWeightReview_` (оливки/маслины/рассол/
заливка/маринад) that blocks a draft outright rather than flagging it as risky data.

**Real architecture risk found, unrelated to Lilia's ask but important:** the
Apps Script engine and the backend Phase 3 engine (`item_normalization_service.py`)
use **different, independently-tuned matching logic** on the same `Правила фасовок`
data:
- Backend: soft-scored specificity — `Код товара УС`=100, `Склад / назначение`=40,
  `ИНН поставщика`=20, `Код товара поставщика`=30, `Поставщик`=10, product-name=5,
  package-text=3.
- Apps Script (`findPackagingRule_`): `Код товара УС` is a **hard filter**, not
  scored; specificity is `ИНН поставщика`=8, `Код товара поставщика`=4 == `Название
  из документа`=4 (tie), `Склад / назначение`=3, `Ед. изм. документа`=1. A rule
  with `Название из документа` filled in is a **hard, exact-match filter** here
  (no soft fallback), unlike the backend's soft weight-5 treatment. `Поставщик`
  (name) is never checked at all — only `ИНН поставщика`.
- `applyPackagingRulesForDocuments_` unconditionally recomputes `Кол-во в УС` and
  `ID правила фасовки` from `Кол-во в документе` every time it runs, with the sole
  exception of `Количество исправлено вручную` being checked. It does not look at
  or preserve whatever the backend already wrote.
- This function is invoked from `checkSelectedDocuments()` ("Проверить выбранные
  документы") and `checkReadinessByStatus()` ("Обновить все статусы") — both
  everyday, expected steps in the operator's normal review workflow per
  `MVP Бух калькулятор.md`.
- **Practical implication, not yet verified live**: in real usage the operator's
  routine "Проверить"/"Обновить все статусы" click likely overwrites the
  backend's Phase 3 `Кол-во в УС` computation with Apps Script's own
  independently-matched result before the document is ever sent onward. If the
  two engines pick different rules or compute different values for the same
  row, Apps Script's value is what actually ships — the backend's Phase 3 work
  this week may not be the source of truth in production it was assumed to be.
  **This needs live verification** (upload a document with a known active rule,
  compare `Кол-во в УС` right after backend write vs. after clicking "Проверить
  выбранные документы") before drawing further conclusions or doing more
  backend rule-engine work.

**Verified against real live rule data (2026-07-24): the divergence is not hypothetical, it's already live.**
Pulled all rows from the real `Правила фасовок` sheet (`1UYgYvrWASUenMT8inLOZEwj8gap0TcDODnW01VxpiiY`). All 39 currently-active rules have both `Код товара УС` and `Название из документа` filled in. 6 product codes already have 2-4 active rules sharing the same `Код товара УС`, differing only in the exact text of `Название из документа` (e.g. `PKG-MVP-008` = `"0,5Л ВОДА BONA AQUA ГАЗ ПЭТ -"` vs `PKG-DRAFT-026` = `"0,5Л ВОДА BONA AQUA ГАЗ ПЭТ"` — differ only by a trailing dash; `01-00087` has 4 active rules, two of which even map genuinely different products — "СОК RICH АНАНАСОВЫЙ" and "СОК RICH ТОМАТНЫЙ" — onto the same УС code, a separate product-matching bug). Read backend's tie-break logic directly (`item_normalization_service.py:760-770`): when top-scoring candidates tie on both score and `Приоритет правила` (all these duplicates share priority 1.0), the function returns `{"status": "ambiguous"}` — a safe block to manual review. Apps Script's `originalName` gate is a hard `return false`, so for any incoming raw_name that doesn't byte-match one of the stored names exactly (near-certain on the next real OCR/AI pass — this project has already documented OpenAI producing different wording for the same document across runs), **all** candidates get excluded, `findPackagingRule_` returns "no rule", and `applyPackagingRulesForDocuments_` then either routes to manual review (if `Ед.изм. в документе !== Ед.изм. в УС`) or **silently carries the document quantity through unconverted with no warning at all** (if the units happen to already match) — a real silent-miscalculation path the backend's tie-to-ambiguous design does not have. Confirmed via direct code read of both engines against the same real rule rows, not simulated or guessed.

**Revised recommendation for the `Факты фасовки AI` question above:** don't
build an isolated audit sheet disconnected from the existing workflow. The
natural integration point is `suggestPackagingRulesForSelectedDocuments()`'s
draft-generation step — feed AI's semantically-aware `packaging_facts` in as a
better fact source than `extractPackagingFactsFromName_`'s blind regex, while
keeping the rest of the already-proven draft→confirm→apply flow unchanged.
This still requires facts to live in the Google Sheet (Apps Script cannot read
the backend DB), so the "must be sheet-based" conclusion from the section above
still holds — it just changes *where* those facts plug in.

## Lilia's answers: source-of-truth, duplicate rules, packaging_facts delivery (2026-07-25)

Lilia (BA/tester) answered the three open questions from the 2026-07-24 entries above.

### 1. Source of truth for `Кол-во в УС` — decided, resolves the dual-engine question

**Google Apps Script (`checkSelectedDocuments()`/`checkReadinessByStatus()`) is and
remains the sole authority for the final `Кол-во в УС`, by explicit design, not
by accident.** The backend must NOT compute a final quantity at all during
upload. Its job at upload time is only to:
1. write the invoice/document data,
2. save the AI-extracted packaging facts (`packaging_facts`/`packaging_risk_flags`),
3. temporarily write the raw source quantity (`Кол-во в документе` passthrough)
   into `Кол-во в УС`.

Lilia's stated reason: having both a backend calculation and a sheet-script
calculation produces two different numbers in the MVP — one calculation only.

**Implemented 2026-07-25**: user chose to simplify backend now rather than
leave the (now out-of-mandate) rule-derived quantity computation in place.
`_shared_invoice_item_row` (`invoice_review_service.py`, the row builder for
the live `Накладная` write path) now always sets `Кол-во в УС`/`Цена в УС` to
the raw `Кол-во в документе`/`Цена за ед-цу` values, regardless of what
`item_normalization_service.py`'s Phase 1-3 rule engine computes. Deliberately
minimal-footprint: only this one function (the shared-sheet row builder) was
touched — `item_normalization_service.py`'s rule-matching/`_resolve_conversion`
logic, product matching, `packaging_facts` extraction/persistence, and the
legacy `_invoice_register_item_row` (inactive "Накладные" register sheet)
were all left untouched, since Lilia's mandate was specifically about the
final number written into the live sheet, not about deleting the rule engine
(which stays available for reference/future use). Full suite: 182 passed
outside `test_receiving.py`/`test_document_extraction_service.py`;
`test_receiving.py` confirmed identical 10 pre-existing failures with and
without the change via `git stash` — zero regressions. Not yet deployed to
the VPS.

### 2. Duplicate `Правила фасовок` rows — cleanup allowed, but gated

- OK to act on, but: **back up first**, **send Lilia the proposed disable
  list before touching anything**, and **set to `Неактивно`, never delete**.
- Explicit exceptions confirmed NOT to touch:
  - `01-00087` (Сок Rich, multiple flavors) — **intentional**, one shared
    product code by design to avoid mis-sorting; only the dash-artifact
    duplicate *copies* of a rule may be deactivated, the multi-flavor sharing
    itself is correct and must stay.
  - Chips (product code not yet re-identified against live data) — the two
    variants (by-pack vs. by-weight) are a **deliberate A/B test**, not a
    duplicate bug; do not touch until she says so.
- The remaining ~4-5 groups flagged 2026-07-24 as `PKG-MVP-*`/`PKG-DRAFT-*`
  trailing-dash duplicates are the actual cleanup candidates, but the list
  needs a fresh live-sheet pull before sending to Lilia (the 2026-07-24 data
  may be stale by now, and the exact product code for "chips" still needs
  confirming so it isn't accidentally included).

### 3. `packaging_facts` delivery to Apps Script — resolved, mechanism still open

- Dedicated user-facing `Факты фасовки AI` sheet is **not required**.
- AI extraction happens exactly once, at backend upload time, and is saved to
  the DB (already implemented 2026-07-25, see the fix above). Apps Script
  must NOT re-invoke AI — it should read the already-saved facts by
  `ID документа` + `ID строки` and use them to build `Правила фасовок` drafts
  the same way `suggestPackagingRulesForSelectedDocuments()` already does
  (Apps Script itself will be edited by Lilia, not the backend engineer).
- Lilia asked backend to propose the concrete delivery mechanism: API call,
  technical (hidden) sheet, or technical field. **Recommendation for this
  repo's shape**: a technical (not user-facing) sheet mirroring Lilia's
  original 10-column spec, written automatically by the backend during the
  same batch write that already produces `Накладная` rows, keyed by
  `ID документа`/`ID строки` (both already exist as real `Накладная`
  columns). Reasons: Apps Script already reads/iterates spreadsheet data
  natively (no new auth/HTTP call needed, unlike an API option), one-row-per-fact
  avoids JSON-parsing in Apps Script, and it doesn't add another column to
  the already header-fragile `Накладная`/`Правила фасовок` contracts.

**Confirmed 2026-07-25 (Lilia's reply)**: go-ahead given for exactly this
recommendation — hidden technical sheet in the same spreadsheet, no API, no
extra `Накладная` field. Backend fills it automatically at upload time.
Apps Script side (reading the sheet and wiring it into rule-draft
generation) will be built by Lilia's team, not this repo. Backend must
notify her when the sheet is live so she can inspect it and connect Apps
Script. **Not yet built.**

Lilia also confirmed the duplicate-rules process exactly as gated above:
backup first, send the candidate list, and deactivate nothing until she
confirms — no changes to that plan.

**Implemented 2026-07-26**: the hidden technical facts sheet is now built in
code. `build_packaging_facts_rows()`/`_packaging_facts_item_rows()`
(`invoice_review_service.py`) turn each item's `packaging_facts`/
`packaging_risk_flags` (already durably saved per the 2026-07-25 fix above)
into one row per fact plus one row per risk flag: `ID документа` (=
`receiving.id`), `ID строки` (= `item.id`), `Наименование товара из
документа`, `Тип факта` (mapped from the AI's English `PackagingFactType`
to a Russian label -- `count_in_package`->"количество вложений",
`unit_weight`/`declared_package_mass`/`actual_weight`->"вес",
`unit_volume`/`capacity`->"объем", `dry_weight`->"сухой вес",
`length`/`diameter`/`thickness`->"размер", `package_type`->"тип упаковки";
risk flags become their own rows with `Тип факта`="риск"), `Значение`,
`Единица`, `Исходный фрагмент текста`, `Уверенность AI`, `Признак риска`
(Да only for risk-flag rows), `Комментарий AI` (Russian-mapped risk
description, e.g. `in_brine` -> "продукт в рассоле — вес может включать
жидкость"). `build_review_sheet()` now returns `packaging_facts_rows`
alongside `shared_sheet_rows`.

`google_sheets_service._write_packaging_facts_rows()` writes them: creates
the sheet `Факты фасовки AI (техн.)` (configurable via
`GOOGLE_PACKAGING_FACTS_SHEET_NAME`) hidden (`addSheet.properties.hidden:
true`) with a header row on first use, then always appends via
`values().append(...insertDataOption=INSERT_ROWS)` -- order-independent by
design, since Apps Script will join on the ID columns, not row position.
Wired into the existing live-sheet write path
(`_insert_into_existing_spreadsheet`, the same function that writes
`Накладная`), so it runs automatically on every real upload with no new
endpoint. 8 new tests (`tests/test_packaging_facts_sheet_rows.py`,
2 new cases in `tests/test_google_sheets_service.py`); full suite 201 passed
outside `test_receiving.py`/`test_telegram_bot.py` (both fail to even
*collect* in this environment -- `ModuleNotFoundError: No module named
'aiogram'`, a pre-existing missing dev dependency on this workstation,
confirmed unrelated to this change by installing nothing and reproducing
the same import error before touching any file); the 2 known pre-existing
`test_document_extraction_service.py` failures confirmed byte-identical via
`git stash`. **Known gap, not fixed here**: the AI schema (`PackagingFact`)
has no per-fact `Комментарий AI`/risk flag of its own and no
`артикул/код поставщика` fact type as Lilia's original spec asked for --
those two columns are populated on a best-effort basis (blank comment for
non-risk facts, `Признак риска` only true for whole-item risk flags, not
per-fact). Revisit if Lilia's Apps Script draft-generation needs richer
per-fact risk/comment data than this provides.

**Deployed live 2026-07-26** to `78.17.160.248` (`autosnab_backend_mvp4`):
backed up the three changed files on the VPS to
`/opt/autosnab_mvp_backup_pre_packaging_facts_sheet/` first, `scp`'d
`config.py`/`google_sheets_service.py`/`invoice_review_service.py` into
`/opt/autosnab_mvp/backend/...`, `docker compose --profile public-ip build
backend` + `up -d --no-deps backend`. Confirmed healthy
(`https://78-17-160-248.nip.io:8443/health/runtime` -> `200`,
`database.ready: true`) and confirmed via `docker exec` +
`inspect.getsource` that the running container actually has
`build_packaging_facts_rows`/`_write_packaging_facts_rows` and that
`_insert_into_existing_spreadsheet` calls the latter; `settings.
google_packaging_facts_sheet_name` reads the new default (`Факты фасовки AI
(техн.)`) since no matching `.env` key exists on the VPS yet (none needed —
the setting has a code-level default).

**2026-07-26, first real upload after deploy found a real, older, still-live
bug**: user uploaded a real invoice and shared the live sheet. The hidden
`Факты фасовки AI (техн.)` sheet was **not created** — direct DB query on
the VPS (`docker exec` + SQLAlchemy) showed the last 3 documents' items all
had `packaging_facts: []` (or `None` for the oldest), even for obvious
candidates like `10ШТ МЕШКИ ДЛЯ МУСОРА 120Л` and `...В РАССОЛЕ`. Root cause:
the 2026-07-25 fix that made `packaging_facts`/`packaging_risk_flags`
survive into `RecognizedInvoiceItem` (commit `9a72347`) had been implemented
and tested locally but **was never actually deployed to the VPS** — the
2026-07-25 session's own log entry said "Not deployed to VPS yet" and this
session's deploy only copied the 3 files for the *new* hidden-sheet feature,
not that earlier prerequisite fix. Confirmed via `docker exec grep` that the
running container's `schemas/invoice_review.py` had no `packaging_facts`
field at all before this fix. **Fixed same session**: `scp`'d
`backend/app/schemas/invoice_review.py` to the VPS, rebuilt, recreated;
confirmed the field is now present in the running container. The 3 already-
uploaded documents (`receiving_id` 61/62/63) have permanently empty
`packaging_facts` in their stored `recognized_items_json` and cannot recover
retroactively — a fresh upload is needed to prove the full path end to end.

**Still not verified end to end** — the schema gap is now closed and
deployed, but no upload has gone through *since* this fix, so the hidden
sheet's actual creation/rows still haven't been observed live. Next steps:
1. Trigger one real bot upload of an invoice with packaging text (e.g. a
   mushroom/napkin-style multi-fact item) and confirm in the live
   spreadsheet that `Факты фасовки AI (техн.)` was created, is actually
   hidden, and has the expected rows.
2. Notify Lilia so she can inspect the sheet and wire Apps Script to it.

### Fresh duplicate-rule candidate list (2026-07-26)

Backed up first: duplicated the live `Правила фасовок` tab in-place as
`Правила фасовок (backup 2026-07-26)` (sheetId `1881719082`) via the Sheets
API `duplicateSheet` request, before reading anything else. **No rule has
been deactivated or edited — read-only analysis below, awaiting Lilia's
confirmation per her gated process.**

Fetched all 47 live data rows (`A1:Z999`) and grouped by `Код товара УС`.
5 codes have more than one active rule; all 5 pairs/groups differ **only**
by a trailing " -" in `Название из документа` (identical recalculation
mode, unit, weight/volume value, rounding, warehouse) — the same
dash-artifact pattern flagged on 2026-07-24, now confirmed fresh:

| Код товара УС | Товар | Keep (recommended) | Deactivate (candidate) | Note |
|---|---|---|---|---|
| `01-00023` | Сахар-песок | `PKG-DRAFT-025` (confirmed by Lilia) | `PKG-MVP-011` (confirmed by "Калькулятор", i.e. auto) | plain duplicate |
| `01-00077` | Вода Bona Aqua 0,5 газ | `PKG-DRAFT-026` (Lilia) | `PKG-MVP-008` (auto) | plain duplicate |
| `01-00081` | Чипсы Delicados 150 г, пачка | `PKG-DRAFT-027` (Lilia) | `PKG-MVP-014` (auto) | **flagged 2026-07-24 as a possible chips by-pack/by-weight A/B test — but both live rows use identical `Без пересчета` config, no by-weight variant exists in current data. Needs Lilia's explicit confirmation before touching, per her standing instruction on chips.** |
| `01-00087` | Сок Rich, ананасовый | `PKG-DRAFT-028` | `PKG-DRAFT-020` | dash-duplicate of the *same* flavor only — the ананасовый/томатный flavor split itself is untouched, per Lilia's explicit exception for this code |
| `01-00087` | Сок Rich, томатный | `PKG-DRAFT-029` | `PKG-DRAFT-021` | same as above |
| `01-00088` | Сок J7 | `PKG-DRAFT-030` | `PKG-DRAFT-022` | plain duplicate |

Rationale for the suggested "keep" side: in the 3 MVP-vs-DRAFT pairs, the
`PKG-DRAFT-*` row is the one personally confirmed by Lilia
(`liliyafidaevna@gmail.com`, `Дата подтверждения` 22.07.2026), while the
`PKG-MVP-*` row was confirmed by an automated actor ("Калькулятор") — the
human-confirmed row is the safer keeper. For the 2 pure DRAFT-vs-DRAFT
pairs (Rich, J7), both sides are equally Lilia-confirmed on the same date;
the no-dash name is suggested only as the cleaner match to current OCR
output, not because of any functional difference — **her call, not a
backend judgment**, if she prefers the other one kept.

Everything else (single-rule product codes, the previously-confirmed
non-duplicates) is untouched and out of scope for this list.

**Done 2026-07-26**: table sent to Lilia; she confirmed all 6 rows exactly as
listed (including the previously-flagged `01-00081` chips pair — she
clarified this is a genuine dash-duplicate, not the by-pack/by-weight A/B
test she'd flagged before; that separate weight-based rule is `PKG-MVP-013`,
code `01-00080`, and stays untouched/active). Deactivated live on the VPS
(read/write both went through the running container's Google OAuth
credentials, since local credentials on this workstation are stale): set
column B (`Активность правила`) to `Неактивно` for `PKG-MVP-008` (row 18),
`PKG-MVP-011` (row 21), `PKG-MVP-014` (row 24), `PKG-DRAFT-020` (row 30),
`PKG-DRAFT-021` (row 31), `PKG-DRAFT-022` (row 32) — verified by reading
each row back after the write. No rows deleted; the `Правила фасовок
(backup 2026-07-26)` tab from before still holds the pre-change state.
Confirmed untouched: `PKG-MVP-013` (`01-00080`, chips by weight) and all 6
"keep" counterparts (`PKG-DRAFT-025/026/027/028/029/030`), all still
`Активно`. **Next**: notify Lilia that both this cleanup and the hidden
`Факты фасовки AI (техн.)` sheet (she independently confirmed it's working
correctly, and confirmed the `30X40СМ`-style dimension text is a
non-computable product-size fact the script won't use, so no AI schema
changes needed there) are done, so her team can wire up Apps Script.

## `dry_weight_unknown` was firing for ordinary products, not just brine/syrup items (2026-07-31, Lilia feedback via Max)

Lilia reported (Max chat, not a raw file — no attachment, compiled directly):
starting around row 83 of the live `Факты фасовки AI (техн.)` sheet, ordinary
products with no brine/syrup/marinade content were coming back with a "risk"
that asked for a dry weight the product never has, and this blocked packaging
rule draft creation / document processing in her Apps Script workflow. Manual
edits to the sheet didn't stick — whatever script re-derives the risk kept
re-flagging it, so she reverted her manual changes rather than fight it.

Root cause: the `dry_weight_unknown` value in `packaging_risk_flags` was
described in `SYSTEM_PROMPT` (`backend/app/services/openai_invoice_parser_service.py`)
as "сухой вес не подтвержден документом" with no scope restriction — the model
could set it for any product lacking an explicit dry weight, including plain
items like kefir or napkins where the concept doesn't apply at all.

**Agreed split of responsibility (Max chat, 2026-07-31, user confirmed "Да.
давай так")**:
1. Backend (this repo): narrow the AI prompt so `dry_weight_unknown` is only
   ever set alongside one of `in_brine`/`in_syrup`/`in_marinade`/`in_oil` —
   i.e. only for products actually packed in liquid (olives, marinades,
   brined items and similar), never for an ordinary product with a normal
   declared weight/volume.
2. Apps Script (Lilia's own side, not this repo): when a row's only signal is
   `dry_weight_unknown` with no brine/syrup/marinade/oil/olive keyword in the
   product name, treat it as a non-blocking warning instead of a stopper, so
   the normal-weight packaging rule draft can still be created. This part is
   explicitly hers to implement — the live Apps Script bound to the
   spreadsheet is not this repo's `apps_script/invoice_review_menu.gs` copy
   (that copy has no reference to the `Факты фасовки AI (техн.)` sheet at
   all, confirmed by grep — her team's live script has since diverged from
   the last saved copy here).

**Implemented 2026-07-31 (backend part only)**: `SYSTEM_PROMPT` now states
`dry_weight_unknown` must only accompany a liquid-packaging risk flag, added
an explicit "don't set it for ordinary products" instruction, and added two
worked examples (`МАСЛИНЫ Б/К 300Г` without a separate drained weight → sets
`in_brine`+`dry_weight_unknown`; `КЕФИР ФЕРМЕРСКИЙ 800Г` → no risk flags at
all). Prompt-only change, no schema/code logic touched (nothing in this repo
currently acts on `packaging_risk_flags` for blocking, per the "not yet acted
on by any conversion logic" note above). `test_openai_invoice_pipeline.py`'s
existing `SYSTEM_PROMPT` content assertions plus the full
`test_packaging_facts_sheet_rows.py` suite pass unchanged (60 passed). Not
yet deployed to the VPS; not yet re-tested against a real upload since a
prompt-only change can't be verified from unit tests alone — needs a real
document with an ordinary weighed product to confirm the flag no longer
fires, ideally paired with Lilia's own Apps Script-side warning-vs-stopper
change so the full loop closes.

## Other Lilia feedback, 2026-07-31 (Max chat, same conversation)

Compiled directly from the chat, not yet actioned except where noted:

- **UI ask**: make the separator row between invoice blocks in `Накладная`
  grey (not default) and shorter, since even an empty separator row is hard
  to visually distinguish from "still loading" — Viktor acknowledged
  ("Хорошо)"), not yet implemented.
- **UI ask**: collapsible rows per document number in the first column (`+`
  collapses all, `−` expands all) so the sheet isn't "one wall of rows" —
  Viktor's assessment: "должно быть реально... потом можно сделать" (backlog,
  not scoped/scheduled).
- **Bug, накл 882 and 616**: table-parsing cell shift — item column-2 product
  code `166` lands in `Количество в документе` instead of the actual
  quantity. Reproduced twice on 882 even after a manual fix and re-upload.
  Not yet traced to a specific function.
- **Bug, накл 882 and 743**: supplier name/document number/date failed to
  recognize on 2 of 3 uploaded invoices in one batch. 882's photo quality was
  reported normal; 743 is a "new form" layout that a similar document (745)
  parsed correctly but 743 itself did not.
- **Bug, накл 743**: line/document sums computed incorrectly.
- **Bug, накл 3688**: `Ставка НДС` column has a percentage number format;
  the value `Без НДС` is text, so writing it into a %-formatted column causes
  a format conflict in Sheets (whole-column format change warning when edited
  manually). Lilia asked whether the write path can set text format
  specifically for non-numeric VAT values. Not investigated yet.
- **Resolved, no action needed**: Lilia considered deleting invoices stuck
  after repeated failed re-uploads; Viktor asked her to export/send the sheet
  first. She then chose not to delete anything, left as-is.

None of the bug reports above (882/616/743/3688 cell-shift/sum/VAT-format
issues) have been traced to root cause yet — recorded here as open items for
the next session, cross-reference from `docs/wiki/current-status.md`.

## Follow-up, 2026-08-07 (Max chat with Lilia, read directly in browser, not a raw file)

- **Explained: why the 2026-07-31 `dry_weight_unknown` fix looked like it
  "didn't stick".** Lilia re-sent the exact same 2026-07-31 instruction
  ("не должен ставить риск 'сухой вес не указан' для обычных товаров...")
  and asked "Вот эту мою просьбу сделал да? что-т снова на эти грабли
  наступила". Checked both repos directly (not memory): `autosnab_mvp`'s
  `openai_invoice_parser_service.py` has the narrowed prompt (lines 81/85/132
  — `dry_weight_unknown` only with `in_brine`/`in_syrup`/`in_marinade`/
  `in_oil`), but `auto-snab-document-parser`'s copy of the same prompt (line
  87) still has the old unscoped wording — the 2026-07-31 fix was never
  ported there. Per the 2026-08-04 log entry the live bot Lilia actually uses
  has been running on `auto-snab-document-parser`'s GitLab dev environment
  since the proxy fix, not `autosnab_mvp`'s VPS — so she has never actually
  been running the fixed prompt. **Task**: port the same prompt narrowing
  (plus the two worked examples) into `auto-snab-document-parser`, deploy,
  then ask Lilia to re-verify.
  - Lilia herself later concluded today's specific recurrence was **not**
    this issue at all (see next item) and said "не смотри пока если делал" —
    but the underlying deploy gap above is real and independent of that,
    confirmed by direct repo comparison, not by her report.
- **New bug found by Lilia: a packaging rule created for one product got
  applied to a completely different product after a manual product-code
  rename.** Her account: after uploading a document she manually reassigned
  one item's product code to a different product with unrelated packaging
  ("мидии" → later a rule for that row started firing on "пепперони"). Her
  hypothesis: the packaging-rule draft is keyed off `id строки`/`id
  документа` rather than the (possibly-changed) product code, so a rename
  after rule-draft creation leaves the rule pointing at the wrong product.
  Not investigated in code yet — needs tracing through the Apps Script
  rule-draft/product-matching path (same area as the 2026-07-24/25 dual
  packaging-rule-engine findings). **Lilia's own workaround, worth keeping in
  mind for any future synthetic/test invoices**: vary only invoice number and
  date, never rename a product on an uploaded document — renaming is what
  triggers this.
- **Recurrence of the untraced cell-shift bug (see "Bug, накл 882 and 616"
  above), same failure class, new example**: накл `114551` (ООО «КОМПАНИЯ
  ЦЕФЕЙ», мясо мидии, rows 26 and 63 on the live `Накладная` sheet) — unit
  code `796` (ОКЕИ, likely "кг") lands in the quantity column instead of the
  real quantity. First upload was manually corrected; two later re-uploads of
  the same document reproduced the same shift both times. Same open item as
  882/616, still not traced to a specific function — this is now the third
  reported instance of the same bug class.
  - Context: this document is part of the 24-invoice batch the assistant
    pushed through the bot on 2026-08-05 for the live test
    (`invoice-bot-live-batch-test-2026-08-05.md`); Lilia is cleaning up that
    batch's leftovers today (also flagged: several invoices in that batch have
    incompletely-loaded supplier data, marked red on the sheet — no separate
    root cause given yet, she said "буду сейчас разбираться").
- **Process change, not code**: per Pavel, action items should be tracked in
  Bitrix task checklists going forward, not just decided in chat. Lilia
  agreed reluctantly ("не нравится битрикс, но придется"). Doesn't change
  this project's wiki-writeback workflow, but chat-only task tracking may
  become less complete over time — Bitrix should be checked too if it's
  accessible.
- **Later same evening (22:01), confirms the dry_weight_unknown port above
  was exactly the right call**: Viktor told Lilia directly "да. это было
  сделано. я просто из своего чернового кода не перенес в боевой бот. сейчас
  портировать буду" — matches the `auto-snab-document-parser` port done this
  session (branch `fix/dry-weight-unknown-prompt-scope`, MR `!34`).
- **Fourth reported instance of the same untraced cell-shift bug class**
  (see 882/616 and 114551 above): счет-фактура/УПД № `2054` от `28.07.2026`,
  поставщик ИП Погосян Артур Борисович, item «Бедро Б/К 12 кг Аврора»,
  live `Накладная` row 73. Lilia's photo of the row shows two adjacent "1"
  and two adjacent "2,000" values where document unit/quantity should be —
  same symptom shape (a code/count value landing in the wrong column) as the
  796-in-quantity cases, though the exact source value wasn't legible in the
  photo this time. She said she'd fix it manually and asked whether anything
  further is needed from her side ("надо мне далее делать" — message is
  slightly cut off/ambiguous, worth confirming with her directly). This is
  now the fourth independent report of this bug class — strong signal to
  prioritize root-causing it over the other open items.
- **Follow-up request (22:22): Lilia asked Viktor to re-upload накл `114551`
  again** ("попробуй еще раз загрузить") to see if the unit/quantity shift
  still reproduces — not yet done, needs the source file (should already be
  in the 2026-08-05 batch-test source set, `~/Загрузки/Накладные`, per that
  session's dedup list) or a fresh copy from Lilia.
- Yesterday's (2026-08-06) multi-tenant table-cloning conversation continued
  slightly (06:51-07:30 today's chat's "Вчера" section): confirmed one
  reference table per organization (not per user), Lilia will make the clean
  reference copy while Viktor wires the bot's spreadsheet-target setting to
  it — same open template-sync question as already recorded in
  `multi-tenant-provisioning-and-document-archive.md`, no new resolution.

## Root cause found and fixed, 2026-08-07: ОКЕИ unit-code/quantity column confusion

Traced the untraced cell-shift bug from the "Bug, накл 882 and 616" and
"Follow-up, 2026-08-07" entries above, now reported four times (882/616,
114551, and счёт-фактура № `2054`).

**Trace**: `document_unit`/`quantity_document`/`unit`/`quantity` are direct
fields on the AI-facing schema (`InvoiceParsedItem`,
`app/schemas/invoice_parser.py:77-82`) with no per-field
`Field(description=...)` — all semantic guidance comes only from the
free-text `SYSTEM_PROMPT`. Following these fields end to end:
`item_normalization_service.normalize_item_candidate` (lines 81-86) copies
`item.quantity_document` straight into `item.quantity` and
`item.document_unit` straight into `item.unit`, with no recomputation from
anything else; `invoice_normalization_service.to_legacy_invoice_payload`
(lines 180-189) passes the same values through unchanged;
`invoice_review_service.create_invoice_review`/`update_invoice_review`
(lines 131/184) write them straight into
`ReceivingItem.received_quantity`/`.unit`; `_shared_invoice_item_row` (lines
807/810) reads those same DB fields with no further transformation. **No
positional/index-based logic touches these two fields anywhere in the
backend** — whatever lands in the sheet's "Кол-во в документе"/"Ед.изм. в
документе" columns is exactly what the AI model returned in JSON, verbatim.

**Conclusion**: this is not a backend bug. The standard УПД/счет-фактура/
ТОРГ-12 table layout (confirmed directly from Lilia's photo of накл `2054`)
puts the "Единица измерения" column's ОКЕИ numeric code (e.g. 796=штука,
166=килограмм) immediately next to the "Количество (объем)" column — two
short adjacent numbers, a classic vision-model confusion source on a
blurry/skewed photo. All four reported instances show exactly this pattern:
a small OKEI-code-like number landing in the quantity field.

**Fix, branch `fix/okei-code-quantity-column-confusion`** (off `develop`,
not yet pushed):
1. `SYSTEM_PROMPT` (`openai_invoice_parser_service.py`) now explicitly
   describes this column layout and instructs the model never to take
   `quantity_document` from the ОКЕИ code column, with a self-check
   instruction: if the extracted quantity numerically equals the adjacent
   unit code, re-read the row and take quantity from the actual
   "Количество"/"Кол-во"/"Объем" column, or flag `needs_review` if still
   unsure.
2. **Defense-in-depth in code**: `normalize_item_candidate`
   (`item_normalization_service.py`) now flags `needs_review=true` whenever
   `document_unit` is a bare numeric string equal to `quantity_document` —
   catches the case even if the prompt fix doesn't fully prevent it,
   instead of silently writing the wrong number.

**Tests**: 4 new tests in `test_openai_invoice_pipeline.py` (one confirms
the guard fires on the exact 796/796 pattern, two confirm it doesn't
false-positive on normal unit/quantity pairs or on a numeric-unit-but-
different-value case, one asserts "ОКЕИ" appears in `SYSTEM_PROMPT`). Full
backend suite unchanged elsewhere: 1 already-known pre-existing failure in
`test_document_extraction_service.py`, 10 already-known in
`test_receiving.py` — both confirmed identical via `git stash`, zero
regressions.

This repo's own branch (`fix/okei-code-quantity-column-confusion`) is pushed
to `origin` on GitHub; no PR opened yet (not asked for).

**Ported to `auto-snab-document-parser`, same session**: identical diff
applied on branch `fix/okei-code-quantity-column-confusion` (off `develop`,
that repo's dry_weight_unknown fix — MR `!34` — already merged there first).
4 matching tests, `ruff format`/`check` clean, 323 passed / 2 skipped, same 8
pre-existing `test_receiving.py` failures — zero regressions. Pushed, MR
`!35` opened
(`https://gitlab.testant.online/antipov-backend/auto-snab-document-parser/-/merge_requests/35`).
Full detail: `docs/wiki/auto-snab-document-parser-release-repo.md`.

**Not done yet**: neither PR/MR merged, neither repo deployed. Also still
open: Lilia's 2026-08-07 22:22 request to re-upload накл `114551` to see if
it reproduces.

## Follow-up, 2026-08-09: Andrey's `feature/invoice-parser-fixes`, deploy-blocking lint bug, ketchup and calibre fixes

Read yesterday's (08-08) and today's Max/Bitrix conversation with Lilia and
Andrey Gomzikov directly (not from memory) before doing anything. Yesterday's
critical report: the `ID документа`/`ID строки` counters had restarted from
1 after a DB reset, so a new "Агротрэйд ООО" document got IDs (82/893)
already used by an earlier "ИП Полуян" document — since packaging-rule and
product-catalog mappings are keyed on these IDs, this risked silently
applying the wrong supplier's rules to the new document. Lilia explicitly
said to stop uploading until fixed. Same batch of messages also had a large
QA dump on the `Факты фасовки AI (техн.)` sheet: OKEI codes 166/796/756
leaking into quantity, seafood calibre ranges ("200/300" mussels, "61/70"
shrimp) misread as counts/weight, a real 61kg-vs-12kg quantity error, a
ketchup wrongly flagged `dry_weight_unknown`, and a unit-type mismatch on
invoice 616. Viktor had delegated part of this to intern Andrey Gomzikov.

**Andrey's branch reviewed and merged**: `feature/invoice-parser-fixes`
(pushed 2026-08-09 01:16, MR `!36`) was already built on the latest `develop`
(no conflicts). Read the full diff directly rather than trusting his summary
message: it adds a real `sheet_document_id`/`sheet_row_id` system (new
DB columns with **unique indexes**, allocated from the live sheet's actual
max at write time via `_assign_stable_sheet_technical_ids`, guarded by an
in-process lock) — this is a materially better fix for the ID-collision bug
than a simple DB counter, since it self-heals from a DB reset by reading the
sheet itself. Also extends the OKEI-code map (166/796/112) with a
line-amount-based quantity repair, fixes invoices 114551 and 2854
specifically, and hardens supplier/header/second-page/ТТН-МЕТРО extraction.
Full test suite: 377 passed / 2 skipped, same 8 pre-existing
`test_receiving.py` failures confirmed via direct comparison against
`develop` HEAD (not `git stash`, since this was a different branch) — zero
regressions. Checked the deployment's actual worker config
(`docker-entrypoint.sh`: plain `uvicorn` with no `--workers` flag, single
container, no compose `replicas`) — the in-process lock's residual
multi-worker race risk flagged in planning turned out to be moot, not a real
gap. Merged via a real browser click (`945df594`).

**Real bug found: the merge itself broke deploy.** The post-merge pipeline
(`#964` on `develop`) failed at the `lint` stage — Andrey's branch left the
new `ocr_service` import out of alphabetical order in
`openai_invoice_parser_service.py` (`ruff` `I001`), which is `allow_failure:
false` and gates `build-image`/`deploy-dev` entirely. **This meant `develop`
had not actually redeployed since the merge**, despite the merge itself
succeeding — caught by reading the actual pipeline job list, not just
"pipeline passed" on the MR page (that MR pipeline only ran security-scan
jobs, a separate job set from the branch-push pipeline that does
build/lint/build-image/deploy). Fixed with a one-line `ruff check --fix
backend/app/` on a new branch (`fix/develop-lint-import-order`, MR `!38`),
verified against the pre-existing `tests/` lint debt (22 errors, unrelated,
confirmed CI only lints `backend/app/` not `tests/`) to make sure this was
the *only* real blocker. Merged (`8aa0b068`); pipeline `#974` on `develop`
tracked live for `build-image`/`deploy-dev` to actually go green this time.

**Ketchup / `dry_weight_unknown` fixed** (`fix/dry-weight-unknown-liquid-
products`, MR `!37`): the 2026-07-31 narrowing only excluded plain
weighed/volumed products, but never distinguished "a solid product packed in
a liquid" (olives, brine-packed meat — flags correctly apply) from "a
product that is itself a liquid" (ketchup, sauces, mayonnaise, oil/syrup/
honey sold as the product — flags never apply, `declared_package_mass`/
`unit_volume` already equal the product's own mass/volume, "dry weight" is a
meaningless concept for them). Added that distinction plus a worked ketchup
example to `SYSTEM_PROMPT`. 1 new test, full suite unaffected.

**Seafood calibre-ratio misread fixed** (`fix/seafood-calibre-ratio-
misread`, MR `!40`): prompt now explicitly describes seafood calibre
notation (`NNN/NNN`, e.g. "200/300", "61/70" — pieces-per-kg size grading,
not a packaging_fact) with the mussel/shrimp examples from Lilia's report,
and forbids turning it into any packaging_fact or quantity. Added a
deterministic guard in `item_normalization_service.py`
(`_calibre_range`/`_CALIBRE_RATIO_RE`), mirroring the existing OKEI-code
guard: if `quantity_document` equals either half of a calibre ratio found in
`raw_name`, attempt the same price×line-amount repair already used for the
OKEI case; if that fails, flag `needs_review` instead of silently keeping
the wrong number. 3 new tests (unrepairable-flags, repaired-via-line-amount,
does-not-false-positive-on-unrelated-quantity). Full suite: 380 passed / 2
skipped, same 8 known `test_receiving.py` failures — zero regressions.

**Duplicate-sheet-ID audit script added** (`chore/audit-duplicate-sheet-
ids`, MR `!39`): read-only script (`scripts/audit_duplicate_sheet_ids.py`)
that reads the live `Накладная` sheet's `ID документа`/`ID строки` columns
and reports every value that already appears more than once, with supplier/
invoice-number/date context per occurrence — for Lilia's team to see the
full extent of data already corrupted before the counter fix shipped
(the fix only prevents *new* collisions, e.g. the Агротрэйд/Полуян case
already in the sheet is not retroactively repaired by it). Verified
structurally (imports/logic resolve correctly, fails only on missing local
Google OAuth session, which is expected on this workstation with no `.env`)
but **not run against the live sheet** — no credentials available here;
needs to be run wherever the backend's real Google credentials are
reachable (VPS, or a temporary CI debug job per
`[[temporary-ci-debug-job-technique]]`).

**Second deploy-blocking bug found on the same merge**: pipeline `#974`
(the real develop deploy attempt, after the import-order fix) failed lint
again — `ruff format --check` flagged 6 files as unformatted. Root cause:
the lint job runs `ruff check` before `ruff format --check`, and the
import-order failure had aborted the job before format-check ever got a
chance to run on `#964`, hiding this second issue. Fixed with a pure
`ruff format` (no logic changes) on `fix/develop-ruff-format`, MR `!41`,
full suite re-confirmed clean (377/2/8, zero regressions).

**GitLab CI runner became unresponsive while waiting for `!41`'s pipeline**
(`#977`/`#976` stuck `Pending`, `#975` stuck `Canceling` after an explicit
cancel) — this matches a previously-documented incident on this exact
GitLab instance (2026-08-05 live-batch-test entry: "перестал отвечать на
15+ минут без автовосстановления"), not something fixable from this side.
Stopped active polling after ~25 minutes; the runner recovered on the next
check, `!41`'s pipeline (`#977`) finished, merged (`c0b5860e`).

**Deploy confirmed green**: the resulting `develop` pipeline (`#981`) passed
all 4 stages — `build`, `lint`, `build-image`, and critically `deploy-dev`
— for the first time since Andrey's original merge. `develop` is now
actually deployed with the ID-counter fix, both lint/format fixes, in the
real dev environment, not just merged in git.

**Not done this session** (explicitly deferred by the user): moving the
"Загрузка" select-all checkbox to the top of the `Накладная` sheet
(Apps Script UI, Lilia's own team's territory) — Lilia's other minor asks
(multi-page upload combining, historical row cleanup) also untouched.
**Still needed after this session**: merge MRs `!37`/`!39`/`!40` (open,
reviewed code but not self-merged), then a real live re-upload test through
the Telegram bot of накл 114551/2854/616 and the ТТН 9610429080689 case
(confirming the deployed fix, not just the code), and running the audit
script for real — before telling Lilia anything is closed out. Full session
detail also in `docs/wiki/auto-snab-document-parser-release-repo.md`.

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
