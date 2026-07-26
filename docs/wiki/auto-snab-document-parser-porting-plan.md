---
title: packaging_facts / Phase 1-3 porting plan for auto-snab-document-parser
source: session
created: 2026-07-26
tags: [auto-snab-document-parser, packaging_facts, port, gitlab]
status: current
---

# packaging_facts / Phase 1-3 porting plan for `auto-snab-document-parser`

## Context

`auto-snab-document-parser` (`gitlab.testant.online/antipov-backend/auto-snab-document-parser`,
local clone at `~/PycharmProjects/auto-snab-document-parser`, branch `develop`)
is a domain-driven rewrite of this codebase (`backend/app/domains/invoice_pipeline/`,
`backend/app/domains/google_workspace/`) and the actual push target for the
finished project. It already has three previously-ported production bugfixes
and the `Кол-во в УС`/`Цена в УС` raw-passthrough simplification (MR `!12`,
`!13`, `!17` — all merged as of 2026-07-26, see `current-status.md`). It is
still missing the entire `packaging_facts`/"Phase 1-3" rule-engine redesign
described in [unit-conversion-rules.md](./unit-conversion-rules.md) — this
page is the porting plan for that, produced 2026-07-26 by a planning pass
(Plan agent) that read both repos' actual current code, not just the wiki.

**Guiding constraint — do not violate**: do not reintroduce backend-computed
authoritative `Кол-во в УС`/`Цена в УС` anywhere in this port. That was
deliberately simplified to a raw passthrough in both repos because Google
Apps Script alone computes the final authoritative quantity now (Lilia's
2026-07-25 decision). The rule engine and `packaging_facts` are still worth
porting because they feed durable storage and the hidden facts sheet, which
Apps Script's own draft-rule-suggestion flow can consume — they're just not
allowed to become the source of truth for the sheet's `Кол-во в УС` column.

## Key finding: Repo B's `invoice_pipeline`/`google_workspace` code is a near-mechanical clone of Repo A's *pre-redesign* code

Confirmed line-by-line via diff: only cosmetic differences (import paths,
`ruff format` line-wrapping) beyond exactly the features the redesign added.
This means the port is closer to "replay the same diffs with renamed
imports" than "reimplement from scratch" — but two real, independent bugs
were also found in Repo B's current code along the way (see below), which
should be fixed as part of this port, not left behind.

### Bugs found in Repo B, not yet fixed there (independent of packaging_facts)

1. **`units_per_package` applied unconditionally.** Repo B's
   `apply_reference_mapping_to_payload` folds `units_per_package` into the
   multiplier even when no rule matched — this is the live "3 packs napkins
   × 250 = 750 with no confirming rule" bug Repo A already fixed by gating
   this on `rule_id is not None`. Fix bundled into Phase 3a below.
2. **`Справочник фасовок` read from `A1:Z` instead of `A2:Z`.** Row 1 is
   human-readable descriptions, not machine headers — reading from `A1`
   means the human labels become the dict keys, silently breaking
   `_catalog_value` lookups. Fix bundled into Phase 2 below, but **needs a
   live-sheet check first**: confirm which spreadsheet Repo B's bot actually
   targets and whether it has the same two-row-header convention as Repo A's
   production sheet before assuming this finding transfers directly.
3. **`Код товара УС` and `Код товара поставщика` conflated** into one
   `rule_product_code` lookup in `_match_conversion_rule` — the exact bug
   Repo A's Phase 3 fixed by separating `rule_us_code`/`rule_supplier_code`.
   Fixed as part of Phase 3a's rewrite.

## Phase 1 — Schema restructuring

**Files:**
- `backend/app/domains/invoice_pipeline/schemas/invoice_parser.py` — port
  `PackagingFactType`, `PackagingRiskFlag`, `PackagingFact`; add
  `packaging_facts`/`packaging_risk_flags` to `InvoiceParsedItem`; remove
  `package`/`quantity_multiplier`/`accounting_quantity_candidate`/
  `accounting_unit_candidate` from it; add `NormalizedInvoiceItem
  (InvoiceParsedItem)` carrying those four fields plus `line_id`; retype
  `NormalizedInvoiceResult.items: list[NormalizedInvoiceItem]`.
- `backend/app/domains/invoice_pipeline/schemas/invoice_review.py` — add
  `packaging_facts`/`packaging_risk_flags` to `RecognizedInvoiceItem`
  directly (Repo A had a real bug here — these were silently dropped until
  commit `9a72347` — port it correctly the first time in Repo B).
- `backend/app/domains/invoice_pipeline/services/invoice_normalization_service.py`
  — stamp `line_id` in `normalize_invoice_result`; add the three fields to
  `to_legacy_invoice_payload`.
- `backend/app/domains/invoice_pipeline/services/openai_invoice_parser_service.py`
  — rewrite `SYSTEM_PROMPT` (copy Repo A's text verbatim, no repo coupling).

**Risks:** `extra="forbid"` makes this a hard breaking schema change — must
land together with the prompt rewrite in one commit. Grep Repo B for any
`.package` access on `InvoiceParsedItem` (as opposed to post-normalization)
before removing the field. Check `NormalizedInvoiceResult` construction
still round-trips with the new subclass.

**Effort:** small–medium.

## Phase 2 — `Правила фасовок` catalog read + facts→package compatibility adapter

**Files:**
- `backend/app/domains/google_workspace/services/google_sheets_service.py`
  — `load_invoice_reference_catalogs()`: read `Правила фасовок!A2:Z`
  alongside `Справочник фасовок` (also fixing its range from `A1:Z` to
  `A2:Z` — see bug #2 above); merge additively into `packages`.
- `backend/app/domains/invoice_pipeline/services/item_normalization_service.py`
  — add `_package_from_facts()`/`_units_per_package_from_facts()`; wire as
  fallback in `normalize_item_candidate` only when regex extraction found
  nothing. Update its type hint to `NormalizedInvoiceItem`.

**Risks:** the `A1`→`A2` change needs a live-sheet sanity check against
whichever spreadsheet Repo B's bot actually targets before shipping.

**Effort:** small.

## Phase 3 — Specificity-tiered rule engine + persistence + hidden facts sheet (largest phase)

**3a. Rule matching/recalculation** —
`services/item_normalization_service.py`: replace flat `_match_conversion_rule`
with specificity-scored version (separate `rule_us_code`/`rule_supplier_code`
lookups — fixes bug #3; disqualify-on-failed-specified-constraint; weights
`Код товара УС`=100, `Склад/назначение`=40, `ИНН поставщика`=20, `Код товара
поставщика`=30, `Поставщик`=10, product-name=5, package-text=3; `Приоритет
правила` tiebreak; 3-state `_rule_activity_state`, unknown → safe review).
Add `coefficient_rule`/`average_weight_rule` recalculation modes. Thread
`warehouse`/`supplier_inn`/`supplier_name` through the call chain. Fix bug
#1 (`units_per_package` gated on `rule_id is not None`).

**3b. Persistence** — `services/invoice_review_service.py`: `_item_payload()`
adds `packaging_facts`/`packaging_risk_flags`; backfill call passes
`warehouse=`.

**3c. Hidden facts sheet** — `invoice_review_service.py` (`build_packaging_facts_rows`,
`_packaging_facts_item_rows`, label dicts) + `google_sheets_service.py`
(`PACKAGING_FACTS_SHEET_HEADERS`, `_write_packaging_facts_rows`) +
`config.py` (`google_packaging_facts_sheet_name`).

**Risks:** 3a is the highest-risk piece — changes matched-rule outcomes for
existing rule data; port test-by-test against the 7 pre-existing
`test_item_normalization_service.py` shape tests to prove zero regression
(same `git stash` method Repo A used throughout). Do 3a→3b→3c in that order
even though they touch different files — 3c needs 3b's data, 3b's field is
trivial but meaningless without 3a producing real facts end-to-end. Check
whether Repo B's live spreadsheet already has a `Правила фасовок` tab with
real data.

**Effort:** large — comparable in size to Phases 1+2 combined.

## Explicitly out of scope (matches Repo A's own stance)

Backend-computed authoritative `Кол-во в УС`/`Цена в УС` (superseded by
passthrough), deferred-recalculation-across-catalog-updates (Repo A's own
unstarted Phase 4), `actual_weight` override for `average_weight_rule`
(deferred in Repo A itself), any Apps Script changes (Lilia's team's scope,
not backend in either repo).

## Test porting (parallel to each phase)

- `test_item_normalization_service.py` — add napkins-with-AI-units-per-package
  fact variant.
- `test_openai_invoice_pipeline.py` — add specificity/priority/inactive/
  coefficient/average-weight tests, `packaging_facts` adapter tests, verify
  the `extra="forbid"` contract test still passes once `package` is removed.
- New `test_packaging_facts_sheet_rows.py` — port verbatim (8 tests, no
  repo-specific coupling beyond import paths).
- `test_google_sheets_service.py` — add hidden-sheet-creation and
  skip-when-no-facts cases.
- After each phase: run Repo B's full suite, diff failures against a
  pre-change baseline via `git stash` — Repo B has its own independent set
  of pre-existing failures (diadoc/ruff-adjacent), don't confuse them with
  real regressions.

## Reconciliation notes

- Repo B's `apply_reference_mapping_to_payload` has no `warehouse` param
  today — audit other Repo B-specific callers (`bot_ingestion_service.py`,
  routers) once it's added.
- No conflicting packaging/units logic found in `reference_catalog_service.py`,
  `iiko_reference_mapping_service.py`, `invoice_golden_evaluation_service.py`
  — safe to leave untouched.
- Confirm which live Google Spreadsheet Repo B's bot actually targets and
  whether its `Правила фасовок`/header-row convention matches Repo A's
  production sheet — affects Phase 2's range fix and whether Phase 3's
  scoring has real rows to exercise on day one.

## Status

**Phase 1 implemented, 2026-07-26** (not yet committed/pushed — sitting as
uncommitted changes in the local clone at `~/PycharmProjects/auto-snab-document-parser`,
branch `develop`). Changes:
- `schemas/invoice_parser.py`: added `PackagingFactType`/`PackagingRiskFlag`/
  `PackagingFact`; `InvoiceParsedItem` gained `packaging_facts`/
  `packaging_risk_flags`, lost `package`/`quantity_multiplier`/
  `accounting_quantity_candidate`/`accounting_unit_candidate`; added
  `NormalizedInvoiceItem(InvoiceParsedItem)` carrying those four plus
  `line_id`; `NormalizedInvoiceResult.items` retyped to
  `list[NormalizedInvoiceItem]`.
- `schemas/invoice_review.py`: `RecognizedInvoiceItem` gained
  `packaging_facts`/`packaging_risk_flags` (ported correctly the first time,
  unlike Repo A which had a real bug here until commit `9a72347`).
- `services/invoice_normalization_service.py`: `line_id` stamped per item;
  `to_legacy_invoice_payload` now includes `packaging_facts`/
  `packaging_risk_flags`/`line_id`.
- `services/openai_invoice_parser_service.py`: `SYSTEM_PROMPT` rewritten
  verbatim to match Repo A's `packaging_facts`-based contract.
- `backend/tests/test_openai_invoice_pipeline.py`: the 7 existing tests that
  construct an item and call `normalize_item_candidate` now construct
  `NormalizedInvoiceItem` instead of `InvoiceParsedItem` (required — those
  fields no longer exist on the AI-facing schema); `test_parser_contract_forbids_unknown_package_fields`
  now targets `packaging_facts` instead of `package`; added
  `test_ai_schema_omits_business_decision_fields`; the existing
  `SYSTEM_PROMPT` content assertion flipped from asserting
  `quantity_multiplier` present to asserting it's absent, plus new
  assertions for `Правила фасовок`/`packaging_facts`/`packaging_risk_flags`.
- `item_normalization_service.py` was deliberately **not touched** — its
  `normalize_item_candidate(item: InvoiceParsedItem)` type hint is stale
  (should read `NormalizedInvoiceItem`) but harmless at runtime since Python
  doesn't enforce type hints and the actual object passed in is always a
  `NormalizedInvoiceItem` once `NormalizedInvoiceResult.items` is retyped.
  Fixing the hint is bundled into Phase 2 per the plan above, alongside the
  `_package_from_facts()` adapter that will actually use the new fields.

**Verification**: `test_openai_invoice_pipeline.py` 44/44 passed. Full
backend suite: 213 passed, the same 8 pre-existing `test_receiving.py`
failures as the unmodified baseline (confirmed via `git stash` — identical
failing test names before and after). `ruff check --fix` + `ruff format` run
on all 5 touched files (one import-order fix only). Needed a fresh venv on
this workstation for this repo (`backend/.venv`, bootstrapped via
`python3 -m venv --without-pip` + cross-install from the `autosnab_mvp` venv's
pip, since `python3-venv`/network `pip` weren't directly usable) — first
time this repo has been test-run from this workstation.

Committed on branch `feature/packaging-facts-phase1-schema` (off `develop`,
commit `b1c0f71`). **MR `!19` opened 2026-07-26** (via GitLab web UI under
`v.viktor.shadrin`, not the API token — see the CI incident note in
`auto-snab-document-parser-release-repo.md`), not yet merged/reviewed.

**Phase 2 implemented and MR opened, 2026-07-26** on branch
`feature/packaging-facts-phase2-catalog` (off Phase 1's branch, commit
`3874621`), **MR `!20`** (depends on `!19`, diff includes Phase 1's commit
until that merges):
- `google_sheets_service.py`: `load_invoice_reference_catalogs()` now also
  reads `Правила фасовок!A2:Z`, merged additively into `packages`; fixed
  `Справочник фасовок`'s own range from `A1:Z` to `A2:Z` (bug #2 from the
  plan above).
- `item_normalization_service.py`: added `_package_from_facts()`/
  `_units_per_package_from_facts()` fallback in `normalize_item_candidate`,
  used only when regex extraction from `raw_name` finds nothing; fixed the
  stale `InvoiceParsedItem` type hint to `NormalizedInvoiceItem`.
- **Pre-check confirmed no live-sheet risk**: direct `.env`/`env.prod`
  comparison showed `GOOGLE_TARGET_SPREADSHEET_ID` is byte-identical between
  `autosnab_mvp` and `auto-snab-document-parser` (both local and deployed)
  — same live spreadsheet, so the two-row-header convention transfers
  directly, no separate verification needed. (Telegram bot tokens differ
  between the two repos' production configs, so no bot-polling conflict —
  only the spreadsheet is shared.)
- 4 tests ported from `autosnab_mvp` (`test_loader_reads_pravila_fasovok_tab_and_merges_into_packages`,
  `test_packaging_facts_adapter_maps_unit_weight_and_dry_weight`,
  `test_packaging_facts_count_in_package_feeds_units_per_package_when_column_empty`,
  plus the existing `A1:Z`→`A2:Z` range assertion fixed). Full suite: 216
  passed, same 8 pre-existing `test_receiving.py` failures as baseline
  (confirmed via `git stash`).

**Not started**: Phase 3 (specificity-tiered rule engine + persistence +
hidden facts sheet — the largest phase).
