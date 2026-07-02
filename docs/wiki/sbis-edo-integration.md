---
title: SBIS EDO Integration
source: session
created: 2026-07-02
tags: [integration, sbis, edo, raw]
status: draft
---

# SBIS EDO Integration

## Goal

Add a read-only integration with Saby / SBIS EDO that pulls incoming supplier documents into the same document flow as invoice photos/PDFs uploaded through the bot.

## Source documents

- `inbox/ТЗ для разработчика_ интеграция СБИС ЭДО с выгрузкой документов в таблицу.md`
- `inbox/Вставленное изображение.png`
- `inbox/Вставленное изображение (2).png`

## Core requirements

- Read-only only: no signing, rejecting, or modifying documents inside SBIS.
- Pull new incoming documents for active client legal entities.
- Read the full document card: id, type, number, date, amount, supplier, recipient, status, attachments.
- Download all relevant attachments.
- Persist raw files and metadata in local storage or object storage.
- Write one row per document into the working table.
- Prevent duplicates on repeated sync runs.
- Log auth, read, download, duplicate, and save errors.

## Classification

On MVP, do not hard-filter only UPD / TORG-12 / invoice.
Pull all incoming documents that may relate to goods supply, then classify them on our side:

- `goods_document`
- `not_goods_document`
- `unknown`

## Suggested table columns

- upload date
- source
- SBIS document id
- document type
- number
- date
- amount
- supplier name
- supplier INN/KPP
- recipient name
- recipient INN/KPP
- processing status
- classification
- raw file link
- SBIS card link
- error

## Raw storage

Keep raw documents in a structure like:

```text
/sbis-edo/client_{client_id}/YYYY/MM/{sbis_document_id}/
  document.xml
  print_form.pdf
  signature.sig
  metadata.json
```

## Sync model

- Poll every 5-15 minutes
- Fetch active legal entities
- Request new incoming documents by events/changes, not full history
- Download card and attachments
- Save raw files
- Write row to the working table
- Record execution result

## Open implementation questions

- Which SBIS auth method will we use in production credentials?
- Where exactly should the working table live in this repo flow?
- Do we store raw files in local filesystem only, or also in object storage later?
- Do we need a separate DB table for SBIS sync history and dedupe keys?
- There is an additional process hint from screenshots: OCR/document ingestion should stay centralized, not split between isolated per-source flows.
- One screenshot references an existing Google Docs table named `АвтоСнаб Кафе Ромашка` and mentions `@AndrewGF1` as a contact for the OCR/doc flow.
