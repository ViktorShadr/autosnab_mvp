---
title: Validation Table Behavior
source: inbox/Созвон с Лилией.md
source_hash: ffd34f080314822f
compiled_at: 2026-07-03T14:39:13+00:00
compiled_from: [src_ffd34f0803, src_137b730e1a]
created: 2026-07-03
updated: 2026-07-03
tags: [table, validation, workflow, spreadsheet]
status: current
---

# Validation Table Behavior

## Role of the table

The working Google Sheet is an intermediate validation layer between the primary document and the accounting system.

The user does not upload directly into accounting. They first review the recognized document in the table, fix issues, and only then trigger loading.

The call with Lilia makes one more thing explicit: she demonstrated the intended operator workflow in the table itself, not just field definitions. For MVP purposes, the table behavior is as important as OCR quality.

## Header and script constraints

- the second row contains the effective column names used by the Apps Script and integration logic
- those names must stay stable
- warning/blocking around header renames is desirable because both script logic and code are name-bound
- the upper explanatory row can change, but the actual machine-bound header row should be treated as frozen contract

## Source document fields

The document flow is expected to populate, at minimum, fields like:

- document date
- document number
- supplier
- supplier INN
- recipient
- basis / contract
- line item name
- unit
- quantity
- price
- totals

Trade point and warehouse may sometimes come from the source document, but often need user selection from reference data.

## Status logic

The source call and workbook show document-level gating through statuses:

- normal recognized document -> user review -> ready for loading
- hard duplicate -> not ready
- possible duplicate -> requires manual check
- OCR/read failure -> not ready, stop further automation

The `Загрузка` / upload state should act at document level, not just line level.

The demonstrated operator logic was roughly:

- file is loaded from paper photo, scan, or EDO export
- document fields and rows are placed into the table
- the document receives an initial status
- the user checks recognition, duplicate markers, supplier mapping, and product mapping
- only documents that satisfy the status conditions are allowed into the test/accounting upload step

This means your MVP should optimize for controllable review states, not just for producing rows.

## Duplicate handling

- exact duplicate should be blocked automatically
- possible duplicate can be marked with a question mark or equivalent review signal
- the user can clear the ambiguity and move the document back into the normal review path

Important nuance from the call: duplicate handling is based on document requisites, and the decision to load is made at document level. A duplicate document should not partially slip through because some individual rows look valid.

## Accounting-system export boundary

Only a subset of columns should go to the accounting system. The table itself contains more operator-facing and validation-oriented fields than the final accounting payload.

Important reference dimensions visible in the workbook:

- supplier directory
- own-company / trade-point / warehouse directory
- product directory
- pack-size / conversion rules

In practice, Lilia showed that the table is doing three jobs at once:

- capture recognized values from the source document
- let the user finish missing business mappings from references
- compute/export the final fields that should go further into the accounting path

So the table is not just a dump of OCR output. It is a transformation and approval surface.

## Special document forms

The call notes explicitly distinguish cases like cash receipts and purchase acts:

- supplier and supplier INN may stay empty there
- those forms follow a different accounting path
- they should not be forced through the same assumptions as standard UPD / TORG-12 supplier documents

This is a real MVP scope trap. If you hard-code one strict supplier-document contract, you will break on these forms early.

## Recheck / correction loop

The future `Вернуть на проверку` action is part of the intended workflow:

- a previously uploaded document may need correction
- the row/document returns to review
- user edits the data
- the document is checked and loaded again
- downstream accounting integration should treat this as a correction/rewrite, not just a blind duplicate insert

This means you need stable document identity and a way to tell "new upload" from "correction of an already loaded document."

## Packing and conversion logic

The workbook also makes one design point explicit: conversion factors should be computed by the program when pack size and unit are known, not entered manually by the user.

This affects:

- normalized quantity
- unit price in accounting units
- transparency of recalculation during review

The workbook also hints at an exception dictionary for piece-based products like eggs, lemons, limes, avocado, etc. So a naive generic converter will not be enough for all rows later.

## Practical MVP attention points

For the nearest MVP, the main things to watch are:

- build around document-level status transitions, not row-only transitions
- keep the target header contract stable and tied to the real sheet, not to ad hoc renamed columns
- separate three layers clearly: raw OCR fields, operator mapping fields, final export fields
- treat duplicate detection as a gate before upload
- support manual completion of trade point and warehouse from references
- allow OCR failure to still produce a reviewable document shell instead of hard-failing the flow
- do not assume every document has supplier and INN
- keep room for a future `Вернуть на проверку` / correction cycle
- avoid manual entry of conversion coefficients when they can be computed
