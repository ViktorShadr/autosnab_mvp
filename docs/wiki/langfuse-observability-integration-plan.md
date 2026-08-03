---
title: Langfuse Observability Integration — Plan and Status
source: session
created: 2026-08-03
updated: 2026-08-03
tags: [observability, langfuse, openai, architecture]
status: live on the VPS — real Langfuse Cloud account connected and verified end-to-end
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

## Update, 2026-08-03 (later same day): merged to `develop`, deployed live to the VPS, real Langfuse account connected and verified end-to-end

User merged `feature/langfuse-observability-tracing` into `develop`
(`3c21e4d`, no-ff merge, pushed to GitHub) after both feature commits were
tested clean (351 passed / same 11 pre-existing baseline failures). Deployed
to the personal VPS (`78.17.160.248`, `autosnab_backend_mvp4` — currently the
live production bot, see `auto-snab-document-parser-release-repo.md`'s
2026-08-03 temporary-rollback entry) via the established `git archive` +
`scp` pattern (`/opt/autosnab_mvp` there is a plain directory, not a git
clone). Since `requirements.txt` changed (new `langfuse` dependency), this
needed a full `docker compose build backend` (not just a restart) — image
built clean, `langfuse-4.14.2` installed. Verified the deploy actually took
via `inspect.getsource` inside the running container (per the established
caution from a prior VPS deploy where a `--no-cache`-free rebuild silently
kept a stale file despite correct host source) before trusting it, not just
the build log.

**Real Langfuse Cloud credentials added** (user provided
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_BASE_URL` in chat,
EU region — matches this repo's `LANGFUSE_HOST` default). Appended to the
VPS `.env` via a temp file over `scp` rather than as inline SSH command
arguments (avoids the secret sitting in `ps aux` output or shell history on
the VPS during transfer); the local temp file was deleted immediately after.
Set `LANGFUSE_ENABLED=true` at the same time — inferred intent (there is no
reason to add real keys otherwise), not separately asked, but flagged to the
user. Container recreated (`docker compose up -d backend`, no rebuild needed
this time — only `.env` changed) — healthy immediately, clean logs.

**Live verification (closes the skill's own required step 3 — "execute
end-to-end, fetch and audit the real trace", not skippable per its own
instructions)**:

1. `client.auth_check()` inside the container → `True` — keys are valid
   against Langfuse Cloud.
2. Ran the real `start_invoice_generation`/`finish_invoice_generation`
   functions directly inside the container with a clearly-tagged synthetic
   call (`source_channel="deployment_smoke_test"`,
   `user_id="claude-deploy-check"`) so it's unambiguously identifiable as a
   verification trace, not real user data. Flushed explicitly.
3. Queried the Langfuse public API directly (`GET /api/public/traces`,
   basic-auth with the same keys) and fetched the created trace
   (`78dee092aef7030a2318084fd600d629`) by ID — **confirmed live and correct**:
   trace name `parse-invoice` (verb-first, as fixed in the self-audit above),
   one `GENERATION` observation with `model: gpt-5-mini`, clean `input`
   (just the evidence text, no raw blob), `output`, `usage` (mapped
   correctly: `{unit: TOKENS, input: 1, output: 1, total: 2}`), `tags:
   ['deployment_smoke_test']`, and `userId: claude-deploy-check` — every
   best-practice fix from the self-audit confirmed working end-to-end
   against the real service, not just unit-tested against fakes.

**Current live state**: `LANGFUSE_ENABLED=true` on the VPS, real invoice
uploads through the Telegram bot now produce real `parse-invoice` traces in
Langfuse Cloud. Not yet done: looking at a real (non-synthetic) invoice
trace with the user in the Langfuse UI (the skill's step 4, "Explore Traces
With the User") — next time a real document is uploaded, worth pointing the
user at the Traces view to see what real data looks like there.

## Not done yet — explicitly out of scope this session

- **Not deployed to `auto-snab-document-parser`'s `ENV_DEV`** — this is
  `autosnab_mvp` (session/working repo) only; porting to the release repo is
  a separate, later step per the usual pattern (see
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

## Self-audit against Langfuse best practices (2026-08-03, later same day)

User asked to install the official Langfuse Claude Code skill
(`github.com/langfuse/skills`, official `langfuse` GitHub org — inspected
before installing: `SKILL.md` + `references/*.md`, scoped `allowed-tools`
restricted to `langfuse.com`/`langfuse-cli`, nothing suspicious) and use it
to audit/improve the tracing added earlier today. Installed at
`.claude/skills/langfuse/` (project-level, committed — available to anyone
using Claude Code on this repo).

Per the skill's "Documentation First" principle, fetched current docs fresh
rather than relying on memory:
`https://langfuse.com/integrations/model-providers/openai-py` (confirmed:
the OpenAI Python drop-in wrapper's structured-output support only
documents `client.chat.completions.parse(...)`, nothing about the Responses
API this repo actually uses — validates the earlier decision to
hand-instrument rather than use the auto-wrapper) and
`https://langfuse.com/docs/observability/best-practices` (fetched fresh per
the skill's explicit instruction to never audit from memory). Findings and
fixes:

- **Observation name was noun-first (`invoice-parse`).** Best practices:
  "Use active language... verb first." Renamed to **`parse-invoice`**.
- **Trace `input` was the entire evidence payload** (filename, source_type,
  page metadata, provider_attempts, evidence_errors, raw_text, etc.) — a
  direct violation of "Set [input] to what a reviewer needs at a glance...
  not a raw JSON blob of function arguments. If you need the raw payload
  for debugging, put it in metadata." **Split**: `input` is now just
  `{"raw_text": ..., "structured_document": ...}` (the actual evidence text
  being parsed — the doc's own classification-task example: "the text being
  classified"); everything else moved to `metadata`.
- **No trace-level `tags`/`user_id`.** Traced 3 real call sites of
  `extract_invoice_document`/`extract_invoice_document_set`
  (`document_extraction_service.py`) back through the codebase:
  `invoice_review.py` (Telegram bot / web upload), `sbis_sync_service.py`,
  `diadoc_sync_service.py` — matching the instrumentation guide's own
  "Multiple distinct endpoints/features → feature tag" row, not a
  speculative addition. Reused the codebase's own existing
  `source_channel` concept (`"telegram_bot"`/`"sbis"`/`"diadoc"`, already a
  first-class value on the `IngestionUpload.source_channel` DB column and
  used elsewhere in `parser_metadata`) as the tag, and the `user_id` already
  flowing through `_process_invoice_upload`'s existing `user_id` parameter
  (from `bot_gateway_service.py`'s `upload.user_id`) as the trace's user ID.
  New optional keyword-only params on `extract_invoice_document`/
  `extract_invoice_document_set` (`source_channel`, `user_id`), purely
  additive — every existing caller that doesn't pass them keeps working
  identically. Wired via `evidence["source_channel"]`/`evidence["user_id"]`
  before the `parse_invoice_with_openai(evidence)` call, then via
  `from langfuse import propagate_attributes` (the correct SDK v4 API for
  trace-level `user_id`/`tags` — confirmed via
  `https://langfuse.com/docs/observability/features/users.md` and
  `.../tags.md`; `start_observation()` itself has no `user_id`/`tags`
  params, those are trace-level not observation-level).
- **Model name / token usage / good names beyond this** were already correct
  from the first pass (model passed, `usage_details` mapped from the OpenAI
  Responses-API `usage` object, static non-dynamic name).
- **Not changed**: `environment` attribute (`propagate_attributes` supports
  it, but this codebase has no existing prod/dev/staging distinction to
  source it from — flagged as a possible future addition, not fabricated
  here) and `session_id` (no multi-turn/multi-trace conversation concept
  exists for one invoice upload — a single trace per document is already
  the correct scope per the best-practices doc's own guidance on trace
  scope).

**Regression check**: `extract_invoice_document`/`_set`'s new kwargs broke 3
test fakes in `test_receiving.py` that didn't accept `**kwargs`
(`TypeError: got an unexpected keyword argument 'source_channel'`) — fixed
by adding `**_kwargs` to those 4 fake stubs (same fix applies to a 4th test
that was already in the pre-existing-failure baseline for an unrelated
reason). Full suite after all fixes: **351 passed / same 11 pre-existing
failures as the documented baseline** (confirmed against the baseline
established earlier this session), zero regressions.

**Not done — explicit limitation**: the skill's workflow step 3 ("Run and
Self-Audit the Traces") requires executing the instrumented path end-to-end
and fetching a real trace from Langfuse to verify the fixes above actually
render correctly in the UI. **This cannot be done yet** — no live Langfuse
account/keys exist (see "Not done yet" section above, unchanged). This
audit is a code-level review against the documented best practices, not a
live-trace-verified one. Once real credentials exist (see "Setup
instructions" below), re-run this audit step live and confirm.

## Setup instructions (2026-08-03)

Written for `autosnab_mvp` (this repo) first — local/VPS `.env`, not
`auto-snab-document-parser`'s `ENV_DEV` yet, per "Next steps" below.

### 1. Create a Langfuse Cloud account and project

Go to `https://cloud.langfuse.com` (**EU** region — matches this repo's
`langfuse_host` default) or `https://us.cloud.langfuse.com` (**US** region,
if chosen at signup) → sign up → create a new project (e.g.
`autosnab-mvp`). **The region picked at signup matters**: if the project
ends up on the US region, `LANGFUSE_HOST` must be changed to
`https://us.cloud.langfuse.com` or the keys won't authenticate against the
default EU host.

### 2. Get API keys

In the project: **Settings → API Keys → Create new API key**. This gives a
`Public Key` (`pk-lf-...`) and a `Secret Key` (`sk-lf-...`) — the secret is
shown once, save it immediately.

### 3. Set them in `.env`

The root `.env` (same file `docker-compose.yml` mounts into the container —
see its `env_file`/volume config) is what matters for a real deploy. If it
doesn't exist yet:
```bash
cp .env.example .env
```
(if it already exists, edit it directly — don't overwrite other secrets).
Fill in the block already present from `.env.example`:
```
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

### 4. Rebuild and restart the backend

`langfuse` is a new dependency in `backend/requirements.txt`, so this needs
an **image rebuild**, not just a restart:
```bash
docker compose build backend
docker compose up -d backend
```
If testing on the personal VPS (`78.17.160.248`), deploy the
`feature/langfuse-observability-tracing` branch specifically first — it
isn't merged into `develop` yet.

### 5. Verify a real trace appears

Upload a real invoice through the bot or the web-upload page, then check
the Langfuse UI → **Traces**. A record named `invoice-parse` should appear
with the model, input (the same payload sent to OpenAI, no images), output
(normalized JSON), and token usage (`input`/`output`/`total`).

If no trace shows up, check `docker logs autosnab_backend_mvp4` — every
Langfuse failure is logged (bad key, unreachable host, etc.) but never
blocks the invoice pipeline, so the document still processes normally
either way; the log line is the only signal something's wrong on the
tracing side.

### 6. Rollback

Set `LANGFUSE_ENABLED=false` and restart — no image rebuild needed, this is
a pure feature flag.

## Next steps, in order

1. Follow "Setup instructions" above to get one real trace flowing.
2. Only after that live check succeeds: decide whether to port this to
   `auto-snab-document-parser` too, and whether to start the
   prompt-versioning/dataset work.
