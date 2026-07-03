---
title: Invoice Table MVP Checklist
source: session
compiled_from: [src_ffd34f0803, src_137b730e1a]
created: 2026-07-03
updated: 2026-07-03
tags: [mvp, checklist, invoices, table, implementation]
status: current
---

# Invoice Table MVP Checklist

## MVP goal

Build the shortest reliable flow from downloaded invoice documents to the working validation table.

Target flow:

```text
downloaded invoice
-> file intake
-> OCR / text extraction
-> document + line parsing
-> validation table row set
-> user review
-> gated upload action
```

## Do first

### 1. Freeze the target table contract

- take the real `АвтоСнаб Кафе Ромашка` sheet as the source of truth
- lock the effective machine-bound header row
- define the minimum MVP columns you must write
- separately mark:
  - source document fields
  - manual operator fields
  - computed/export fields

Without this, backend work will drift immediately.

### 2. Define a document-level status model

Minimum states for MVP:

- `ocr_failed`
- `recognized_needs_review`
- `possible_duplicate`
- `blocked_duplicate`
- `ready_for_upload`
- `uploaded`
- `returned_for_review`

The status decision must be document-level, even if rows are stored line-by-line.

### 3. Build a dedicated table writer

Do not rely on ad hoc row shaping inside old invoice-review logic.

Create one explicit mapping layer:

- normalized document -> table header fields
- normalized item -> table line fields
- computed fields -> final target columns

This is the safest reuse boundary if existing ingestion code stays.

### 4. Keep OCR failure non-fatal

Even when OCR/parser quality is poor:

- create the document shell
- create a reviewable table entry
- set blocking status
- let the operator fix manually

### 5. Add duplicate gating before upload

At MVP level, use simple document identity heuristics:

- document number
- document date
- supplier
- amount, if available

You do not need perfect dedupe first. You do need a hard stop for obvious duplicates.

## Reuse from current code

Reuse:

- upload endpoint
- file persistence
- OCR integration / fallback
- base DB persistence for review entities

Likely rewrite or isolate:

- sheet row builder
- target headers
- status mapping
- duplicate logic
- manual/computed/export field separation

## Backend implementation order

### Step 1

Introduce a new target contract module for the validation table:

- header constants
- allowed statuses
- field groups

### Step 2

Introduce a new builder/service:

- `document_to_validation_table(...)`
- `item_to_validation_row(...)`
- `compute_export_fields(...)`

### Step 3

Make current upload flow write through that builder instead of directly through old register assumptions.

### Step 4

Store enough metadata to support:

- duplicate checks
- manual recheck
- future `Вернуть на проверку`

### Step 5

Only after table writing is stable, refine parser quality and extra business rules.

## Explicitly postpone

Do not pull these into the first MVP unless they block table creation:

- full SBIS EDO integration
- broad supplier-catalog work
- multimodal search
- perfect product matching
- advanced unit-conversion exception engine
- full accounting upload automation for all edge cases

## Must-not-miss risks

- treating row status as primary and forgetting document-level gating
- coding against renamed headers instead of the real sheet contract
- mixing OCR output with user-entered mapping fields in one opaque layer
- assuming every document has supplier + INN
- letting duplicate documents upload because individual rows looked valid
- making conversion coefficients manual-only

## Practical 2-3 day cut

If speed matters, the smallest sensible cut is:

1. freeze the real target columns
2. create a new table writer
3. map recognized document + items into those columns
4. add simple document statuses
5. add simple duplicate blocking
6. allow manual review when OCR is weak

That is enough for a real MVP. Everything else can follow after the table flow is trustworthy.
