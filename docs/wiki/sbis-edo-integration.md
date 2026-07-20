---
title: SBIS EDO Integration
source: session
created: 2026-07-02
updated: 2026-07-20
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

## Feasibility analysis

Yes, this is realistic in the current project, but only if the EDO flow is implemented as a new source adapter that feeds a shared document core.

### What already helps

- `Receiving`, `ReceivingDocument`, and `ReceivingItem` already give you a common persistence model for incoming documents.
- `invoice_review_service.py` already acts as a central orchestration layer for OCR, parsing, Google Sheets export, and iiko preview/export.
- The project already treats raw files, parsed metadata, and generated table rows as separate layers, which is the right shape for a multi-source pipeline.

### What is missing

- There is no SBIS client, auth layer, sync scheduler, or sync history table yet.
- There is no explicit source registry for "bot upload" vs "SBIS EDO" vs future sources.
- There is no raw-file storage abstraction for attachments and metadata snapshots.
- There is no central dedupe engine keyed by source document identity + attachment identity + content hash.
- The current code path is still mostly invoice-centric; EDO should not be bolted directly into invoice-review handlers.

### Best architecture

Use a shared core with source-specific adapters:

- `source adapters`:
  - bot upload
  - SBIS EDO
- `document core`:
  - normalize header
  - store raw payloads
  - dedupe
  - classify
  - write table row
- `presentation/export`:
  - Google Sheets
  - future export targets

### Recommendation

Do not centralize everything into one giant handler. Centralize the *document model and pipeline*, but keep SBIS as its own adapter. That gives you one place for business rules and multiple ingestion sources without turning the code into a monolith.

### Practical verdict

- For an MVP, yes, you can build your own EDO module.
- For a production-grade version, you should first refactor the project toward a source-agnostic intake pipeline.
- If you skip that refactor and wire SBIS straight into the current invoice-review path, it will work short-term but become fragile quickly.

## Parallel development constraint

Another developer is building the PDF export path in parallel, so we must keep both tracks aligned.

### Rule

- Do not fork the business model into separate PDF and SBIS versions.
- Do not let each developer invent their own document schema.
- Agree on one canonical document contract first, then let each source implement an adapter to that contract.

### Practical boundary

- PDF developer owns the PDF source adapter and PDF-specific extraction.
- SBIS work owns the SBIS source adapter and SBIS-specific extraction.
- Shared code owns the canonical document model, dedupe, raw artifact storage, classification, and table writer.

### Coordination artifact

Create and maintain one short interface spec in the repo:

- canonical document header
- line item shape
- raw artifact shape
- required processing statuses
- table column mapping rules

If this spec changes, both tracks must update together. That is the main guardrail against divergence.

## Final execution plan

1. Freeze the canonical document contract with the PDF developer.
2. Keep the current PDF path unchanged and add SBIS as a separate source adapter.
3. Introduce a shared document core for normalization, dedupe, raw storage, and status tracking.
4. Make both PDF and SBIS write into the same working table through the same writer contract.
5. Validate the result on one PDF document and one SBIS document before expanding the scope.

### MVP boundary

- No separate repo.
- No rewrite of the current OCR flow.
- No duplicated business schema for PDF and SBIS.
- No direct SBIS coupling into invoice-review handlers.

## Delivery priority from latest screenshot

- This week: show a working MVP for document recognition and table placement.
- Next week: move to SBIS EDO work.
- Keep the scope visible and ask for help early if blocked.
- If the line stays stable, the work can continue in this direction on commercial terms.

## Meeting agenda intake

The meeting notes added on 2026-07-03 clarify the immediate task split:

- make multi-page document upload and page visibility comfortable for the user
- coordinate business-logic questions with Lilia
- share Lilia's contacts to keep communication moving
- review parsing options, including whether a service account is needed

### Practical implication

The short-term work is still the same MVP document path, but with a stronger emphasis on multi-page document UX and parsing strategy before SBIS becomes the next-week focus.

## Table structure and Apps Script constraints

The new notes and screenshot on 2026-07-03 clarify the working table behavior:

- the table is an intermediate validation layer between the первичный документ and the accounting system
- columns are grouped conceptually into:
  - fields from the original document
  - fields from the accounting system reference data
  - recalculation fields
  - validation / status fields
  - final fields for the accounting system
- the existing Apps Script looks up column names from the second row, so the current header names must not be renamed casually
- document-level upload/testing currently works through the `Загрузка` column
- if a document already has an error, duplicate, or line under review, it should not be uploaded
- after testing, the row status becomes `Загружено` or `Отправлено в УС`
- a future `Вернуть на проверку` action is planned for cases where a previously uploaded document needs to be corrected

### Source-specific implication

- keep the current header names stable
- avoid table schema drift between the PDF path and the SBIS path
- define only the canonical contract and the writer rules, not a new header set per source

## Real production dump analysis (2026-07-20, `src_20260720_sbis_dump`)

A real `СБИС.СписокИзменений` response (organization ИНН `7604094967`, period
2026-06-30..2026-07-13) was reviewed field-by-field against the task-file's
"confirmed facts" and the plan's classification/attachment logic. Findings:

**Confirmed correct, no change needed:**
- `Документ.Тип` values in real data: `ДокОтгрВх` (УПД/накладные-поступления),
  `СчетВх` (счета), `АктСверВх` (акт сверки), `ДоговорВх` (договор) — exactly
  matches the plan's claimed filter set `{ДокОтгрВх, СчетВх}`. The earlier
  concern (raised when only `sbis_api_test.py`'s keyword-based
  `DOC_TYPE_KEYWORDS` heuristic was visible) is resolved: real documents do
  carry a reliable `Документ.Тип` field, filtering by it is valid and does not
  need the keyword-matching fallback as primary logic.
- Same `Документ.Идентификатор` genuinely repeats 3-5 times across different
  events for one document (confirmed on `019f4bbc-0f62-...` x3,
  `019f5a38-8eb7-...` x5) — dedup by this field is mandatory, as claimed.
- `Вложение.Служебный: "Да"` reliably marks noise (`Извещение о получении`,
  `Подтверждение отправки/получения`, `Технологическая квитанция`) regardless
  of the attachment's own `Направление` (some service attachments are
  `Направление: "Исходящий"` even though the parent `Документ.Направление` is
  `"Входящий"` — filter on `Служебный`, not `Направление`).
- `Файл.Ссылка` expiry: fetched 2026-07-13, `expire_date` fields show
  `2026-08-16T21:52:25Z` — confirms the ~1 month window.

**New findings, not covered by the task file — needed for a correct implementation:**

1. **Two separate `Тип` vocabularies exist, easy to conflate.** `Документ.Тип`
   (top level: `ДокОтгрВх`/`СчетВх`/...) is the classification field. But each
   `Вложение` (attachment) *also* has its own `Тип` field with a completely
   different vocabulary: `УпдДоп`, `УпдДопПокуп`, `УпдСчфДоп`, `ЭДОСч`,
   `АктСвер`, `ИзвПолуч`, `ПодтвДатОтпр`, `ПодтвДатПол`, or empty string. The
   client must filter documents by `Документ.Тип` and select attachments by
   `Служебный` + filename extension — never by `Вложение.Тип`, which is a
   different, attachment-format classifier and not a reliable inclusion/exclusion
   signal on its own.
2. **`Вложение.Файл.Ссылка` can be an empty string even on a real,
   non-служебный attachment.** Both УПД attachments for "Поступление №173"
   (`b1beb6f3-bbd5-...`) and "№172" (`527969ef-8e36-...`) have
   `"Файл": {"Имя": "...xml", "Ссылка": ""}` — populated filename, empty link
   — while the *nested* `Подпись[0].Файл.Ссылка` (the detached `.sgn`
   signature file, not the content itself) is populated. By contrast, the
   larger УПД document (`019f5a38-8eb7-...`, sum 530129.93) has a populated
   top-level `Файл.Ссылка` for its equivalent attachment. This is inconsistent
   between documents in the same dump — **the sync/download code must treat an
   empty `Ссылка` as "not yet downloadable" (log + retry/skip), not assume
   every non-служебный attachment always has one.** Root cause not confirmed
   (timing? a companion event carries the real link instead?) — worth an
   isolated live test once implementation starts.
3. **УПД and Счет attachments use different XML schema versions.** УПД
   attachments show `ВерсияФормата: "5.01"/"5.03"`; Счет (`СчетВх`) attachments
   show `ВерсияФормата: "1.03"`/`"TENSOR_1"` and use a visibly different root
   structure. The plan's proposal to generalize `diadoc_xml_parser_service.py`
   into a shared `fns_upd_xml_parser_service.parse_fns_invoice_xml(...)` should
   **not** be assumed to work for `СчетВх` documents without separate
   verification — a счет is a different ФНС-adjacent document type than
   УПД/счёт-фактура, and Diadoc's existing parser was written against the
   latter's tag names (`СвСчФакт`, `ТаблСчФакт`, `СведТов`). Plan for a real
   `СчетВх` XML sample check before assuming reuse; if the schema doesn't
   match, a separate lightweight счет-parser (or PDF-fallback for счет
   specifically) may be needed.
4. **A single `Документ` can bundle several non-служебный attachments beyond
   the one target file**, not just "XML or one PDF". The ТНС энерго
   `Поступление №761100/79233/01` carries five non-служебный attachments in
   one event: a счет PDF, the target УПД XML, and three more PDFs
   (`ON_SCHETKOMPLEKT_...`, `ON_VEDEHEH_...`, `ON_AKTPOK_...` — a package
   summary, a waybill-like document, and a buyer-side act). The plan's
   "prefer `.xml` over `.pdf` if XML exists" rule correctly resolves this case
   since the XML is present — but if a future document has **only PDFs** and
   several non-служебный ones, naive "pick any PDF" fallback logic will
   sometimes grab the wrong file. Needs a secondary heuristic (match attachment
   `Номер`/`Сумма` against the parent `Документ.Номер`/`Сумма`, or filename
   prefix conventions like `ON_SCHET_`/`ON_NSCHFDOP` vs.
   `ON_SCHETKOMPLEKT_`/`ON_VEDEHEH_`/`ON_AKTPOK_`) before this ships.

## Implementation (2026-07-20, branch `sbis-edo-integration`)

First working implementation of the plan above, on a dedicated branch off
`over_version` (not merged). Mirrors the Diadoc adapter file-by-file as
recommended:

- `backend/app/services/fns_upd_xml_parser_service.py`: `diadoc_xml_parser_service.parse_diadoc_invoice_xml`
  generalized into `parse_fns_invoice_xml(content, *, file_id, file_url=None, provider="diadoc")`.
  `diadoc_xml_parser_service.py` is now a thin wrapper calling it with
  `provider="diadoc"` — existing Diadoc behavior/tests unchanged.
- `backend/app/models/sbis.py`: `SbisSyncState` (cursor = `last_datetime_from`,
  no `box_id` concept — SBIS list already returns everything for the
  authenticated account), `SbisDocument` (dedup key: `sbis_document_id` alone,
  simpler than Diadoc's `message_id`+`entity_id` since one `Документ` already
  bundles all its own attachments across all `Событие[]`), `SbisArtifact`,
  `SbisDelivery` (`google_sheets` only — no `print_form`, out of scope),
  `SbisLease`.
- `backend/app/services/sbis_client.py`: `СБИС.Аутентифицировать` → SID cached
  in a module-level dict keyed by login, reauthenticated once on a
  session-error response (heuristic regex on the JSON `error` field, since
  SBIS returns HTTP 200 with a JSON `error` rather than HTTP 401), plain
  `GET` download with the SID/cookie headers the real test script used,
  raises `SbisAttachmentExpiredError` on HTTP 403 for the sync layer to
  treat as retryable rather than permanent.
- `backend/app/services/sbis_sync_service.py`: dedups repeated event records
  for the same `Документ.Идентификатор` via `_group_by_document_id`/`_merge_occurrences`
  before processing (mirrors the real dump's 3-5x repetition), filters by
  `Документ.Тип` against `settings.sbis_document_types`, `_pick_target_attachment`
  implements all four real-dump findings (prefers `.xml`, skips `Служебный`,
  skips attachments with an empty `Файл.Ссылка`, matches PDF-only bundles by
  `Номер` against the parent document when no XML exists), falls back to the
  existing `extract_invoice_document(...)` for PDF-only documents exactly like
  Diadoc's `_parse_unstructured_document`, and feeds parsed documents into the
  existing `create_invoice_review`/`update_invoice_review`/
  `create_real_google_sheet_for_review` — no separate business schema.
  `_normalize_datetime_for_filter` fixes the dots-vs-colons mismatch found in
  the real dump (`ДатаВремяСоздания` uses dots, the `ДатаВремяС` filter needs
  colons) when advancing the sync cursor.
- `backend/app/services/sbis_scheduler_service.py`, `backend/app/schemas/sbis.py`,
  `backend/app/routers/sbis.py`: structural copies of the Diadoc equivalents
  (no OAuth router needed — SBIS uses login/password, not OIDC). Admin gate
  is `X-Sbis-Api-Key`, falling back to `bot_api_shared_secret`.
- `config.py`/`.env.example`: `sbis_*` settings mirroring `diadoc_*` naming.
  `sbis_document_types` defaults to `"ДокОтгрВх,СчетВх"`.
- Wired into `main.py` (router + scheduler start/stop in lifespan), same
  pattern as Diadoc.
- 16 new tests (`test_fns_upd_xml_parser_service.py`, `test_sbis_client_reliability.py`,
  `test_sbis_sync_service.py`, `test_sbis_router_reliability.py`) all pass, all HTTP-mocked.
  Full suite: 197 passed / 8 failed — identical pre-existing `test_receiving.py`
  failure set as the documented baseline (181/8 before this branch), zero
  regressions.

**Not done yet / explicit next steps**: no live smoke test against the real
SBIS account (uses production `sbis_api_test.py` credentials, not run from
this session); no manual DB migration needed since these are brand-new tables
created via `Base.metadata.create_all` (unlike Diadoc's reliability migration,
which altered existing columns); `СчетВх` XML parsing via the shared parser
is unverified against a real Счёт XML sample (see the schema-version caution
above) — should be checked before relying on it in production.

## Test environment / sandbox (confirmed 2026-07-20)

Official Saby documentation (`saby.ru/help/integration/api/techreq_edo`) confirms a
dedicated test stand for the EDO API, separate from production, with the same
method contract and the same request/attachment/auth limits:

- test: `https://fix-online.sbis.ru/auth/service/` (auth) and
  `https://fix-online.sbis.ru/service/?srv=1` (all other commands)
- production: `https://online.sbis.ru/auth/service/` and
  `https://online.sbis.ru/service/?srv=1`

Not documented publicly: whether a separate contract/tariff is required to get
credentials for `fix-online.sbis.ru`, or whether it comes with the normal
`online.sbis.ru` registration. The general integration guide
(`saby.ru/help/integration/api`) only describes the production path (register on
`online.sbis.ru` -> subscribe to a tariff -> configure API calls) and does not
mention the test stand at all. Getting real test credentials requires contacting
Saby support directly; this should be requested in parallel with starting
development, not after, since it's an external dependency outside our control.

## Effort estimate (2026-07-20)

Rough order-of-magnitude estimate for a working MVP (one SBIS document ingested
end to end), assuming one developer and reuse of the existing document core
(normalization, product/package matching, canonical `Накладная` row builder,
Google Sheets writer already exist and are source-agnostic by design):

| Component | Scope | Size | Notes |
|---|---|---|---|
| SBIS auth/client | auth wrapper, list/read/download methods over SBIS API | **Large — main risk** | No prior integration experience with SBIS in this repo; biggest unknown is obtaining `fix-online.sbis.ru` test credentials from Saby support, not the coding itself |
| Document card + attachment parsing | pull XML/print form/signature, extract id/type/number/date/amount/parties | Medium | EDO XML, not photos — no OCR needed, but SBIS may expose multiple document-schema versions |
| Convert to shared document contract | map SBIS payload into the same logical-document shape the bot/upload path already uses | Small | This is exactly what the document core was designed for |
| Raw storage | persist `document.xml` / `print_form.pdf` / `signature.sig` / `metadata.json` under `/sbis-edo/client_{id}/YYYY/MM/{doc_id}/` | Small | Same pattern as existing upload file storage |
| Dedupe + sync history table | new table keyed by SBIS document id + attachment hash, statuses `ingested/skipped/failed` | Small-medium | Structural copy of the existing `ingestion_uploads` journal |
| Scheduler | poll every 5-15 min across active legal entities | Small | Plain background job, nothing architecturally new |
| Classification (`goods_document`/`not_goods_document`/`unknown`) | deterministic rules over already-extracted fields | Small | Not AI-based, simple heuristics/whitelist |
| Smoke test against real SBIS test stand | pull 1 real document, verify repeat sync doesn't duplicate | Medium | Depends on Saby support turnaround for test credentials |

**Total: roughly 1.5-2.5 developer-weeks** to a working MVP (one document
end-to-end), of which an estimated 40-50% is SBIS API/auth discovery rather
than in-repo code, given the sandbox exists but its access process is
undocumented publicly.

Sequencing note (2026-07-20 discussion): starting SBIS now means building an
adapter on top of a document core whose own hardening is not yet done — see
`invoice-recognition-hardening-plan.md` open blockers (multi-page reliability,
`hybrid` mode broken). This is a tradeoff to weigh, not a blocker; SBIS work
itself is architecturally decoupled from those blockers since it does not use
OCR/OpenAI parsing at all (SBIS documents arrive as structured EDO XML, not
photos).

## Plan review: `claude_cli_task_sbis_integration_v2.md` (2026-07-20)

A candidate implementation task file was reviewed against this page and against
`diadoc-integration.md`. Two open questions from this page were resolved directly
by the user in that review session:

- **SBIS API access is confirmed real** by the user, despite `sbis_api_test.py`
  (the reference script the task file cites for real response structure) not
  being present in this repo. The two prior open questions above
  ("Which SBIS auth method..." / test-stand credential access) are effectively
  answered — real production access exists — but the reference script itself
  still needs to be brought into the repo (or its actual response samples
  captured) before implementation starts, since the task file's technical
  claims (JSON-RPC shapes, `СписокИзменений` dedup behavior, `Служебный`
  attachment flag, `expire_date` ~1 month) are only as reliable as that script's
  real output.
- **SBIS is still required alongside Diadoc** — confirmed by the user, not a
  redundant integration. Different counterparties use different EDO providers,
  so both adapters are needed in production, not an either/or choice.

Architecture verdict: the task file's overall shape (JSON-RPC client, poller
with cursor/dedup, XML parser, PDF-fallback, status model, tests) is directionally
correct and matches the source-adapter recommendation above, but it was written
without awareness of the Diadoc adapter that landed in this repo the same day
(see [[diadoc-integration]]). Before implementing, it should be revised to:

- **Mirror the Diadoc adapter's structure** instead of designing a parallel one:
  `diadoc_scheduler_service.py` (polling), `diadoc_sync_service.py` (event fetch
  → download → parse → match → deliver, with `diadoc_leases` for
  single-worker-at-a-time sync and `diadoc_deliveries`/`dead_letter` for
  retryable, idempotent Google Sheets delivery) is a near-exact structural
  template for what SBIS needs (`СБИС.СписокИзменений` poll, attachment
  download, XML parse, dedupe, delivery).
- **Reuse the existing PDF/OCR/OpenAI extraction pipeline for the PDF-fallback
  path** (`document_extraction_service.py`, `openai_invoice_parser_service.py`,
  `invoice_normalization_service.py`) instead of introducing a separate
  `opendataloader-pdf` + custom-LLM-call path with its own status vocabulary
  (`ready_for_review`/`needs_manual_check`/`manual_entry_required`) — the repo
  already has a working status model (`needs_review` / `Требует проверки`) that
  should be extended, not duplicated, per this page's standing "no duplicated
  business schema per source" rule.

### Plan rewritten (2026-07-20) to mirror the Diadoc adapter file-by-file

`claude_cli_task_sbis_integration_v2.md` was rewritten in place with a concrete
Diadoc→SBIS file mapping table (`models/diadoc.py`→`models/sbis.py`,
`diadoc_client.py`→`sbis_client.py`, `diadoc_sync_service.py`→`sbis_sync_service.py`,
`diadoc_scheduler_service.py`→`sbis_scheduler_service.py`, `routers/diadoc.py`→
`routers/sbis.py`, `schemas/diadoc.py`→`schemas/sbis.py`, `diadoc_*` config settings
→ `sbis_*`), plus per-item notes on where the SBIS protocol actually diverges
(SID login/password auth instead of OIDC, no `sbis_oauth_service.py` needed,
single-call `СписокИзменений` instead of Diadoc's `GetNewEvents`+`GetMessage`+
`GetEntityContent` chain, dedupe key is `Документ.Идентификатор` instead of
`message_id`+`entity_id`).

**Key finding from reading `diadoc_xml_parser_service.py` directly**: its
`parse_diadoc_invoice_xml` is already a generic ФНС УПД/счёт-фактура XML parser
(tag names like `СвСчФакт`/`ТаблСчФакт`/`СведТов` are the government schema, not
anything Diadoc-specific) — only `document_form`, `parser_metadata.provider`, and
the `request_id` prefix are Diadoc-specific literals. The rewritten plan calls for
generalizing this into `fns_upd_xml_parser_service.parse_fns_invoice_xml(..., provider=...)`
and reusing it for SBIS's XML attachments (still needs verification against one real
SBIS XML file, since ФНС schema versions can differ in field details), instead of
writing a second XML parser from scratch as the original task file proposed.
`diadoc_sync_service._parse_unstructured_document` is called out as the concrete
pattern to copy for the PDF-fallback path (`extract_invoice_document(..., extraction_method=...)`),
and `_transfer_to_verification`/`create_invoice_review`/`update_invoice_review`/
`create_real_google_sheet_for_review` as the pattern for feeding parsed documents into
the shared document core instead of writing directly to `Receiving`/`ReceivingDocument`.
