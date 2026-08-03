---
title: OCR and Parser Provider Strategy
source: session
created: 2026-07-05
updated: 2026-07-05
tags: [architecture, ocr, llm, providers]
status: current
---

# OCR and Parser Provider Strategy

## Working idea

The next architecture step should keep OCR/layout extraction separate from the
final document parser.

Target shape:

`OCR / layout provider -> normalized evidence -> pluggable parser backend`

This is preferable to binding one OCR provider to one LLM provider or replacing
the whole current path with one monolithic vendor.

## Why this matters for autosnab_mvp

The current pipeline already proved that document quality problems and parsing
problems are not the same problem:

- bad photos, skew, broken runtime dependencies, and OCR transport failures
  damage evidence collection;
- item normalization, duplicate logic, and table field semantics are a separate
  downstream layer;
- one parser backend should be replaceable without rewriting Google Sheets
  mapping or deterministic validation.

So the stable boundary should be:

1. collect text/layout evidence from document pages;
2. normalize it into one internal evidence contract;
3. send that contract to one selected parser backend;
4. keep deterministic normalization and Google Sheets writing unchanged.

## Candidate providers to evaluate

### OCR / layout layer

- `Yandex Vision OCR`
  Strong candidate for image/PDF OCR, table-aware recognition, and async
  document processing.
- current providers remain valid fallback/reference sources:
  `Google OCR`, `MinerU`, and local image preparation.

### Parser layer

- `YandexGPT`
  Strong candidate because of async API shape and structured output for strict
  JSON-oriented document parsing.
- `GigaChat`
  Strong candidate as an alternative parser backend for Russian business
  documents, especially for A/B comparison on receipts and supplier invoices.
- current `OpenAI` path remains the active baseline until another provider is
  proven on the same golden set.

## Recommended evaluation strategy

Do not switch the whole product to a new vendor in one step.

Instead:

1. keep the internal normalized evidence contract;
2. add pluggable OCR providers behind one interface;
3. add pluggable parser backends behind one interface;
4. run the same golden set through:
   - current OpenAI path
   - Yandex Vision OCR + current parser
   - Yandex Vision OCR + YandexGPT
   - Yandex Vision OCR + GigaChat
5. compare:
   - field accuracy
   - table-row accuracy
   - receipt behavior
   - latency
   - operational reliability
   - cost

## Practical conclusion

The idea to use OCR first and LLM second is sound.

The most promising vendor exploration shape is:

- `Yandex Vision OCR` as a likely primary OCR/evidence provider;
- `YandexGPT` as a likely async structured parser candidate;
- `GigaChat` as an alternative parser backend for Russian document quality
  comparison.

For the repository architecture this should mean provider abstraction, not a
hard-coded vendor replacement.

## Update, 2026-08-03: additional OCR-engine candidates from Telegram discussion with Pavel and colleagues

Pavel forwarded a multi-person Telegram thread (August_Raves, Валерий,
Vsevolod Bogodist) into the 1:1 chat with new candidates for the OCR/layout
layer, alongside the existing `Yandex Vision OCR`/`Google OCR`/`MinerU`
options above. User committed in-thread to researching and integrating
these for testing ("Я сегодня изучу их и интегрирую в наш бот и будем
тестить", 19:13) — not yet done as of this note.

- **HunyuanOCR** (August_Raves) — used by them for similar scan-recognition
  work; no further detail shared in this thread.
- **PaddleOCR `rec v5`** (Валерий, Pavel) — favored for balancing cost and
  ease of fine-tuning; has a usable recognition-confidence score to gate
  quality. Their own pipeline pattern: split into stages — document
  cropping, alignment, field extraction — then run PaddleOCR `rec v5`
  recognition, with **YOLO** used upstream for localizing the fields of
  interest before recognition runs. Reference article shared:
  `https://habr.com/ru/articles/1037868/` (fast Paddle-based OCR, CPU-latency
  focus).
- **Docling** (`https://docling.ai/`, `opendatalab/MinerU` was already the
  removed local option — Docling is a separate project) — Vsevolod
  Bogodist's pick for document structuring: handles messy/skewed PDFs better
  than naive text extraction even when the PDF is a "real" document rather
  than a scan; ships with baseline OCR integrated by default and allows
  swapping in a custom OCR engine. Pavel confirmed this reading in-thread.
- Background reading shared in the same thread (not engine-specific):
  `https://habr.com/ru/companies/chestnyznak/articles/1027484/` (OCR
  accuracy evaluation on Russian documents — cautionary piece on trusting
  raw OCR output) and `https://pimenov.ai/knowledge/docling-dokumenty-v-dannye-dlya-ii/`.

None of these have been benchmarked against the golden set yet — this is
still at the "candidates surfaced" stage, same evaluation strategy above
(add behind a pluggable interface, compare on the same documents) applies
before any of these replace or supplement the current path.

## Idea, proposed by Pavel, 2026-08-01 (Saturday): add Langfuse for pipeline observability/metrics

While discussing document-type-aware prompting (see the same-day thread
above — Pavel's suggestion to classify накладная vs. чек and run different
prompts per type), Pavel raised this independently, unprompted: *"Вообще вам
Langfuse по уму ещё нужно бы подключить, чтобы через него метрики
отслеживать. Как идея. Для такого я его ещё не применял. Сергей и Дмитрий
уже используют — проще обсудить с ними."* (roughly: this project should
probably wire up Langfuse to track pipeline metrics; he hasn't used it for
this kind of case himself, but colleagues Сергей and Дмитрий already use it
and would be easier to discuss with directly).

This is directly relevant to the "Recommended evaluation strategy" section
above — comparing OCR/parser candidates on field accuracy, table-row
accuracy, latency, reliability, and cost is exactly the kind of per-run
metric tracking Langfuse is built for, rather than ad-hoc logging or manual
comparison.

**Status**: idea only, not scoped or evaluated. User's own response in-thread
was "я для начала узнаю что такое Langfuse" — no investigation done yet, no
code/infra changes. Next step if picked up: talk to Сергей/Дмитрию about
their existing usage before integrating, per Pavel's own suggestion, rather
than evaluating Langfuse cold.

### Follow-up, 2026-08-03: concrete benefits mapped to this pipeline's actual pain points (open for discussion, nothing decided)

Worked through what Langfuse would specifically help with here, tied to
real, already-recorded friction rather than generic tooling appeal — still
just an open idea, not a decision to integrate:

1. **Trace-level debugging instead of manual `exports/openai_debug/` digging.**
   Every Lilia bug report so far (e.g. the 882/616 cell-shift where an item
   code lands in `Количество в документе`, or 743's wrong sums — see
   `unit-conversion-rules.md` → "Other Lilia feedback, 2026-07-31") gets
   diagnosed by grepping raw JSON dumps on disk. Langfuse would give a
   per-document trace (exact prompt + images sent in, exact JSON returned,
   tokens, latency) without that manual step.
2. **Prompt versioning.** `SYSTEM_PROMPT` in
   `openai_invoice_parser_service.py` has already been edited at least 3
   times across recent sessions (the `dry_weight_unknown` narrowing, the
   `count_in_package`/`quantity_document` conflation fix, the Coca-Cola
   negative example). Right now the only history is `git log` on that
   string; Langfuse ties each prompt version to its actual run outcomes, so
   a regression from a prompt edit is visible directly instead of inferred.
3. **Metrics for the provider-comparison plan already in this page.** The
   "Recommended evaluation strategy" section above (field accuracy,
   table-row accuracy, latency, reliability, cost across OpenAI / Yandex
   Vision OCR+YandexGPT / GigaChat / the 2026-08-03 candidates) is exactly
   the kind of per-run metric aggregation Langfuse computes natively,
   instead of hand-building a comparison spreadsheet per test run.
4. **Regression datasets instead of ad-hoc pytest fixtures.** The project
   already has a de facto golden set (Метро.pdf/Метро2.pdf/Метро3.pdf, the
   Coca-Cola case, Lilia's other flagged examples). A Langfuse dataset with
   expected output would surface exactly which fields regressed on a prompt
   change, rather than a bare pytest pass/fail count.

**Cost side, not glossed over**: self-hosted or cloud instance to stand up,
an SDK wrapper around the existing OpenAI call site (small, but real code
change), and ongoing time cost of actually using it. Not free just because
integration is "a few lines" — flagged as a real tradeoff, not just upside.

**Still not decided**: whether to pursue this at all. Per Pavel's own
suggestion, next step (if this idea is picked up) is talking to Сергей and
Дмитрий about their existing Langfuse usage before committing, not
evaluating the tool cold.
