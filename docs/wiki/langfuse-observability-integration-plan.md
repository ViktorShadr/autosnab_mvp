---
title: Langfuse Observability Integration — Plan and Status
source: session
created: 2026-08-03
updated: 2026-08-03
tags: [observability, langfuse, openai, architecture]
status: implemented (code only — off by default, no live account yet)
---

# Langfuse Observability Integration

## Why

Pavel independently suggested Langfuse (2026-08-01) for tracking pipeline
metrics — see `docs/wiki/ocr-parser-provider-strategy.md` → "Idea, proposed
by Pavel, 2026-08-01" and its 2026-08-03 follow-up for the full reasoning
(trace-level debugging instead of manual `exports/openai_debug/` digging,
`SYSTEM_PROMPT` version tracking, metrics for the OCR/parser provider
comparison plan, regression datasets against the existing golden set).

## Decision, 2026-08-03

**Langfuse Cloud**, not self-hosted. Rationale (user decision): fastest to
validate whether this is actually worth the ongoing time cost, zero infra to
stand up or maintain, free tier available, easy to cancel if it doesn't
prove useful. Self-hosting (an extra `docker-compose.yml` service — Langfuse
+ Postgres + ClickHouse + Redis, 4+ containers) was explicitly rejected for
now given the project already carries meaningful ops load (the
`auto-snab-document-parser` OpenAI-egress/Yandex-Cloud geo-block situation
being the freshest example).

**Data-residency note, explicit not implicit**: choosing Cloud means real
invoice text/structured output now also leaves the boundary to Langfuse's
servers (EU/US), in addition to OpenAI. To limit exposure, only text/JSON
already sent to OpenAI is forwarded to Langfuse — **no raw image bytes**
(see "What is NOT sent" below).

## What was implemented (code only, this session)

Single integration point: `parse_invoice_with_openai()` in
`backend/app/services/openai_invoice_parser_service.py` — this is the only
call site that talks to OpenAI in the invoice pipeline.

- **New module**: `backend/app/services/langfuse_tracing_service.py`.
  `start_invoice_generation()` / `finish_invoice_generation()` wrap one
  Langfuse "generation" observation per invoice-parse call using the
  Langfuse Python SDK v4's manual-instrumentation API
  (`client.start_observation(..., as_type="generation")` /
  `generation.update(...)` / `generation.end()`) — **not** the SDK's
  drop-in OpenAI-client wrapper, because this codebase calls the Responses
  API with structured output (`client.responses.parse(text_format=...)`),
  a less common path the auto-instrumented wrapper may not fully cover.
  Manual instrumentation avoids depending on that.
- **Fail-safe by construction**: every Langfuse call is wrapped in
  `try/except Exception` and only logs (`logger.exception(...)`) — a
  Langfuse SDK error, network failure, or bad credentials can never raise
  into the invoice-parsing pipeline. Verified by a dedicated test
  (`test_openai_parser_langfuse_failure_never_breaks_pipeline`) where the
  fake Langfuse client raises on every call and the pipeline still returns
  a normal result.
- **Off by default, safe to leave off**: `settings.langfuse_enabled` defaults
  to `False`; even if `True`, missing `langfuse_public_key`/`langfuse_secret_key`
  also keeps it a no-op. When off, the `langfuse` package is never imported
  at all (deferred import inside `_get_client()`), so it has zero runtime
  cost/risk for any environment that doesn't opt in.
- **What is sent per invoice-parse call**: the same JSON payload already
  built for OpenAI by `_build_evidence_payload()` (filename, source_type,
  ocr_used, extraction_method, page metadata, raw OCR/PDF text, structured
  document) as the trace `input`; the normalized parser output as `output`;
  token usage (`input`/`output`/`total`, mapped from the OpenAI Responses-API
  `usage` object) as `usage_details`; and small metadata (`source_type`,
  `ocr_used`, `review_flags_count`, `needs_review_items`) for filtering.
- **What is NOT sent**: page images. `_build_evidence_payload()` (reused
  as-is for the trace input) never includes the base64-encoded image bytes —
  those are only added later, separately, to the actual OpenAI request by
  `_build_openai_input()`. Confirmed by test assertion
  (`test_openai_parser_records_langfuse_generation_when_enabled`).
- **New settings** (`backend/app/config.py`): `langfuse_enabled` (bool,
  default `False`), `langfuse_public_key`, `langfuse_secret_key`
  (both `str | None`, default `None`), `langfuse_host` (default
  `https://cloud.langfuse.com`). New `.env.example` entries with the same
  defaults plus a comment pointing here.
- **New dependency**: `langfuse>=4.14,<5` in `backend/requirements.txt` —
  pinned against the actual installed/tested version (4.14.2, the latest at
  integration time; SDK v4 is the OpenTelemetry-based rewrite, not the older
  v2/v3 API — this matters if searching Langfuse docs/examples online,
  which mostly still show v2/v3 syntax).
- **Tests**: `backend/tests/test_langfuse_tracing_service.py` (unit tests
  for the tracing module in isolation — disabled/missing-credentials
  no-ops, successful record+close, error-level recording, and that update/end
  failures are swallowed) plus two new tests in
  `backend/tests/test_openai_invoice_pipeline.py` (end-to-end through
  `parse_invoice_with_openai` with a fake Langfuse client: normal recording
  path, and the failure-never-breaks-pipeline path). Full suite: 349 passed
  / 11 pre-existing failures (same baseline as before this change, confirmed
  via `git stash`) — zero regressions.

## Not done yet — explicitly out of scope this session

- **No live Langfuse account exists yet.** Nothing has actually sent a trace
  anywhere — `langfuse_enabled` stays `False` in every real `.env`/`ENV_DEV`
  until the user creates a Langfuse Cloud project and gets real
  `public_key`/`secret_key`.
- **Not deployed anywhere** (personal VPS `78.17.160.248` or
  `auto-snab-document-parser`'s `ENV_DEV`) — this is `autosnab_mvp`
  (session/working repo) only; porting to the release repo is a separate,
  later step per the usual pattern (see
  `docs/wiki/auto-snab-document-parser-release-repo.md`).
- **No prompt-versioning/dataset/eval usage yet** — this session only wires
  up per-call tracing (the foundation). Turning `SYSTEM_PROMPT` into a
  Langfuse-managed prompt object, building a regression dataset from the
  Метро.pdf/Coca-Cola golden set, and comparing OCR/parser candidates
  through Langfuse metrics are all still open follow-ups once real trace
  data exists to justify them.
- **No app-shutdown flush wiring** — Langfuse's client batches/exports
  asynchronously; a clean `client.shutdown()` on FastAPI's lifespan
  shutdown would guarantee no trace is lost on process exit, but this
  wasn't added (low-risk gap: worst case is losing the last few in-flight
  traces on a restart, not a functional break).
- **Talking to Сергей/Дмитрий** (Pavel's own suggestion, per
  `ocr-parser-provider-strategy.md`) still hasn't happened — this plan was
  built from Langfuse's own public API/SDK, not from their real-world
  usage experience.

## Next steps, in order

1. Create a Langfuse Cloud account/project, get `public_key`/`secret_key`.
2. Set `LANGFUSE_ENABLED=true` + the two keys in a real `.env` (local or VPS
   first, not `auto-snab-document-parser`'s `ENV_DEV` yet), run a real
   invoice through the bot, confirm a trace appears in the Langfuse UI with
   the expected input/output/usage.
3. Only after that live check succeeds: decide whether to port this to
   `auto-snab-document-parser` too, and whether to start the
   prompt-versioning/dataset work.
