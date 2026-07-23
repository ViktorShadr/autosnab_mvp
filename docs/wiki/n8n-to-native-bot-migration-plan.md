---
title: n8n to Native Bot Migration Plan
source: session
created: 2026-07-20
tags: [bot, telegram, n8n, migration, backlog]
status: deployed-live
---

# n8n → Native Python Telegram Bot — Migration Plan

**Status: decision made 2026-07-20; code built 2026-07-21 on branch `native-telegram-bot`; deployed live and cut over to production the same day.**

## 2026-07-21 cutover to production

Deployed directly to production (user's explicit choice — skipped the throwaway-bot-token dry run) on VPS `78.17.160.248`:

1. Shipped `native-telegram-bot` (commit `7ae1ae5`) to `/opt/autosnab_mvp` via `git archive` + `scp` + remote `tar -x`, same method as prior deploys (plain directory, not a git clone; all gitignored state — `.env`, `uploads/`, `autosnab_mvp.db` — untouched by the extract).
2. Appended `TELEGRAM_BOT_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_POLL_INTERVAL_SECONDS=5.0`, `TELEGRAM_BOT_MAX_POLL_ATTEMPTS=24` to the server `.env` (piped via SSH stdin heredoc, not as a command-line argument, to avoid the token landing in shell history).
3. User deactivated the n8n workflow in the cloud n8n editor before rebuild/restart, confirmed by `getWebhookInfo` showing `pending_update_count: 0` both before and after — no window where both consumers held the token.
4. `docker compose --profile public-ip build backend` — first attempt failed with `no space left on device` (VPS was at 79% disk / 3.0G free before the build; the `torch`/`mineru`/`transformers` dependency chain plus new `aiogram` needs real headroom during layer export). Retried after disk pressure eased on its own (67% used) and it succeeded; `docker image prune -f` + `docker builder prune -f` afterward reclaimed the build cache (332.9MB) as routine cleanup, same pattern as the 2026-07-20 VPS disk cleanup.
5. `docker compose --profile public-ip up -d --no-deps backend` recreated only the backend container (Caddy/VPN containers untouched). `/health/runtime` returned healthy immediately.
6. **Verification**: `docker logs` showed clean startup with no errors, but also no explicit "bot started" line — expected, since `logging.getLogger(__name__).info(...)` calls in `bot.py`/`poller.py` are below Python's default root log level and nothing in `handlers.py` logs per-message by design. Confirmed the poller was actually alive via `/proc/1/net/tcp` inside the container showing live ESTABLISHED connections to `149.154.166.110` (a real Telegram Bot API IP). Final proof: user sent `/start` in Telegram and received the menu reply with the Готово/Статус/Сбросить keyboard — full end-to-end confirmation.
7. **Not yet done**: no real invoice photo/PDF has been run through the native bot's full draft→finalize→poll→result flow yet — only the `/start` menu round-trip is confirmed live. n8n workflow is deactivated (not deleted) per the plan's rollback window.

## 2026-07-23 real production bug: poll budget too short, bot stops watching before the pipeline finishes (`img_17.png`)

User reported (screenshot `img_17.png`, registered `src_20260723_img17`): uploading `Метро2.pdf` through the live bot, `Готово` at 22:57, then progress messages, then at 22:59 (~120s later) the poller gave up with "Обработка документа занимает необычно долго. Проверьте статус позже кнопкой «Статус»." Checking `Статус` manually a minute later revealed the document *had* actually finished processing (flagged `possible_duplicate` — expected/correct duplicate detection, not itself a bug) — the bot just never delivered that result automatically.

**Root cause, confirmed by code trace**: `poller.py`'s `_poll_loop` gives up permanently (`return`s, popped from `_active_polls`) after `telegram_bot_max_poll_attempts * telegram_bot_poll_interval_seconds` — **24 × 5s = 120s** — regardless of whether the backend is still processing. That 120s budget was never revisited when the OpenAI timeout budget was deliberately *raised* on 2026-07-20 (commit `caeb5ba`, see entry above): `openai_timeout_seconds=180` plus one retry at `openai_timeout_retry_seconds=240` gives a confirmed worst case of **180+240 = 420s** for the OpenAI stage alone, plus the OCR export retry loop (6 attempts × 4s ≈ 20-24s) before it and reference-mapping/Sheets-write after it — realistic worst case ~445-460s. Typical fast runs (~56-101s, per the 2026-07-20 live test of this exact `Метро.pdf`/`2`/`3` set) stay under the 120s poll budget, which is why the bug doesn't fire on every upload — only when a run is slow or actually needs the retry path, both of which are expected to happen periodically on these documents.

A second symptom on the same screenshot — the bot replying "Не понял команду" immediately followed by "Страница 1 добавлена" for what looked like one user action — was investigated and is **not a bug**: it's two independent Telegram updates (a text reply "еще раз", not a recognized command → correctly routed to `handle_unknown`; and a separate literal re-upload of the file → correctly routed to `handle_document`). Confirmed via `aiogram.dispatcher.dispatcher.Dispatcher._polling` source (installed version 3.15.0): `handle_as_tasks=True` is the default, so each incoming update is dispatched as its own concurrent `asyncio.Task` — reply ordering between two near-simultaneous updates is not guaranteed to match send order, which fully explains the apparent interleaving without any handler-routing defect.

**Fix applied** (`backend/app/config.py`, `.env.example`): raised `telegram_bot_max_poll_attempts` default from `24` to `120` (600s total at the unchanged 5s interval), comfortably covering the ~450-460s confirmed worst case with margin. `backend/tests/test_telegram_bot.py` already monkeypatches this setting for its own test, so the default change doesn't affect test behavior. Full non-`test_receiving.py` suite: 200 passed / 2 pre-existing failures unchanged (confirmed via `git stash`), zero regressions.

**Not yet done**: the production VPS `.env` was set explicitly to `TELEGRAM_BOT_MAX_POLL_ATTEMPTS=24` during the 2026-07-21 cutover (see above) — the code-default bump alone does **not** fix the live bot until that VPS `.env` value is also updated (or removed so the new code default applies) and the backend container is rebuilt/restarted. Not deployed this session — needs explicit go-ahead before touching the production VPS again.

## 2026-07-21 real production bug: stage-message spam (`img_14.png`)

The user ran a real document through the freshly cut-over bot and it sent dozens of alternating "🔎 Выгружаем данные из документа..." / "🤖 Обрабатываем через ИИ..." messages over more than a minute (`img_14.png`, registered as `src_285b68038c`) instead of one message per stage.

**Root cause**: `poller.py`'s `_poll_loop` re-scanned the *entire* `pipeline_logs` list (which only ever grows across polls of the same upload) on every 5-second tick, and deduped against a single `last_stage_text` value. Once the log had 2+ distinct stage groups (which is the normal case for any real document — evidence collection then OpenAI then Sheets write), each tick would walk back through *earlier* entries whose text no longer matched whatever `last_stage_text` had most recently been set to inside that same tick's loop, and resend them — every tick, forever, until completion.

**Fix**: track how many log entries have already been scanned (`processed_logs`) and only iterate the new slice (`status.pipeline_logs[processed_logs:]`) each tick, keeping the existing dedup-against-last-sent-text check for genuine consecutive duplicates within/across ticks. Added `test_poll_loop_sends_each_stage_message_once_even_as_pipeline_logs_keeps_growing` in `backend/tests/test_telegram_bot.py`, confirmed to fail against the pre-fix code (produces 8 stage messages including the alternating pattern) and pass against the fix (produces exactly 3, one per stage). Full suite re-verified: 223 passed / 8 pre-existing failures.

Redeployed to `78.17.160.248` the same way as the initial cutover (`git archive`+SFTP, rebuild, `docker compose up -d --no-deps backend`) immediately after the fix, since the bug was live and actively spamming the user's chat.

## 2026-07-21 implementation update

All of "Migration design (not yet built)" below is now real code on branch `native-telegram-bot` (off `packaging-conversion-rules`):

- `backend/app/services/bot_gateway_service.py`: mechanical extraction of the five `/bot/drafts/*` + `/bot/uploads/*` endpoint bodies into plain functions (`append_draft_page`, `get_draft_status`, `reset_draft`, `finalize_draft`, `get_latest_upload_status`, `get_upload_status`), reusing the existing `Bot*` Pydantic response schemas directly instead of inventing new result types. Also holds `start_bot_processing`/`_process_bot_upload_background`/`_build_bot_upload_status_response`/`_bot_status_message`, moved verbatim from the router. `ValueError` replaces `HTTPException` for validation failures so the functions stay usable from both FastAPI and aiogram callers.
- `backend/app/routers/invoice_review.py`: the six `/bot/*` endpoints are now thin wrappers over the gateway (URLs/contracts/`X-Bot-Api-Key` unchanged); the pre-existing bulk `/bot/upload-document-live` endpoint (not one of the six — it predates the draft-based flow) now also calls `bot_gateway_service.start_bot_processing`. `_process_invoice_upload` itself (the ~200-line shared extraction/write engine, also used by the non-bot web-upload endpoint) deliberately stayed in the router; the gateway's background function reaches it via one deferred (function-body) import to avoid a circular import, rather than relocating a function that non-bot code also depends on.
- `backend/app/telegram_bot/`: `bot.py` (Bot/Dispatcher construction, `start_bot`/`stop_bot` as asyncio-task lifecycle hooks), `keyboard.py` (`MAIN_KEYBOARD`: Готово/Статус/Сбросить via aiogram's typed `ReplyKeyboardMarkup`), `messages.py` (ported Russian text + a `STAGE_TEXT` map keyed by the real `pipeline_logs` stage identifiers — `collect_evidence_start`/`ocr_start`/`ocr_fallback_start`/`mineru_start` → "выгружаем данные", `openai_request_start`/`reference_mapping_start` → "обрабатываем через ИИ", `google_sheet_start` → "загружаем в таблицу"), `handlers.py` (aiogram `Router` with photo/document/text handlers, all delegating to `bot_gateway_service` via `asyncio.to_thread`), `poller.py` (per-chat `asyncio.Task` registry; repeated "Готово" cancels and replaces any still-running poll for that chat, matching the plan's stated rollout-safety requirement).
- `backend/app/main.py`: `start_bot()`/`stop_bot()` wired into `lifespan` as asyncio tasks (mirrors the existing `start_diadoc_scheduler`/`stop_diadoc_scheduler` thread pattern); no-ops when `TELEGRAM_BOT_ENABLED` is false, so this ships inert by default.
- `backend/app/config.py` + `.env.example`: new settings `telegram_bot_enabled` (default `false`), `telegram_bot_token`, `telegram_bot_poll_interval_seconds` (5.0), `telegram_bot_max_poll_attempts` (24) — same numbers the n8n workflow already used.
- **Dependency conflict found and resolved**: `aiogram==3.15.0` requires `pydantic<2.10`, which downgraded the environment's resolved `pydantic` from `2.10.4` to `2.9.2`. Re-pinned `backend/requirements.txt`'s `pydantic==2.10.4` down to `pydantic==2.9.2` so a fresh install resolves deterministically instead of leaving pip to pick silently. Full suite re-verified passing after the downgrade.
- **Real regression found and fixed during verification**: `test_receiving.py::test_bot_draft_finalize_starts_processing_and_is_visible_via_latest` monkeypatched `invoice_review_router._process_bot_upload_background`, which no longer exists there post-extraction. Updated the test to monkeypatch `bot_gateway_service._process_bot_upload_background` instead (same object the `Thread(target=...)` call resolves at call time). Confirmed via `git stash` of just the code changes that this was the *only* new failure introduced — baseline is 8 pre-existing `test_receiving.py` failures, branch now reproduces exactly that same 8, zero net regressions.
- New tests: `backend/tests/test_bot_gateway_service.py` (9 tests: draft accumulation, unsupported-format/empty-file rejection incl. the pre-existing quirk that an empty first page still leaves a 0-page draft row behind, reset, finalize-without-pages, finalize-starts-background-processing, latest/by-id status lookups) and `backend/tests/test_telegram_bot.py` (6 tests: the text-matching predicate, keyboard layout, stage-text grouping, result-message formatting). Full suite: 222 passed / 8 pre-existing failures (up from 173/207 non-bot-file baseline + the pre-existing `test_receiving.py` 8).
- **Not done yet**: `aiogram` was `pip install`-ed into the local venv but the Docker image has not been rebuilt with it; no throwaway-BotFather-token dry run has been performed; production cutover (deactivate n8n workflow, set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_BOT_ENABLED=true`, redeploy VPS) has not happened. n8n continues running the live bot unchanged. Aiogram handler code paths (photo/document download, keyboard rendering, poll-loop stage messages against a real Telegram client) have not been exercised end-to-end — only the underlying gateway functions and pure message-formatting logic have real test coverage so far.

## Decision

Replace the cloud-hosted n8n Telegram-bot workflow with a native Python bot module living inside this backend repo. Recommendation accepted by the user; execution deliberately deferred to a future session, not done as part of this decision.

## Why

Two research passes (Explore + Plan agents) established the case:

1. **n8n is used for exactly one thing in this project**: this Telegram invoice-upload bot. No other automation, table sync, or notification flow anywhere in the wiki is attributed to n8n. Replacing it here means dropping n8n from the project entirely, not partially.
2. **The backend already owns essentially all real logic.** Everything behind `/api/v1/invoice-review/bot/*` (`backend/app/routers/invoice_review.py`) — draft accumulation per chat, finalize → background processing, status/result derivation, duplicate detection, Google Sheets link, next-action payload — is backed by DB table `ingestion_uploads` (`backend/app/models/ingestion.py`) and `backend/app/services/bot_ingestion_service.py`. n8n only owns the Telegram transport/UX layer: update routing, the poll-after-finalize loop, reply keyboard, and progress messages built from `pipeline_logs`.
3. **n8n has caused ~10 distinct categories of bugs/friction** across the bot's build history (all in `docs/wiki/log.md`/`docs/wiki/current-status.md`):
   - Docker-bridge-network MTU mismatch breaking multipart file uploads through ngrok (`ERR_NGROK_3004`).
   - Shared-secret (`X-Bot-Api-Key`) credential drift between n8n's stored HTTP-header credential and the backend's actual value.
   - Malformed reply-keyboard JSON, twice — once from a hand-authored guess that n8n rejected on import, once from a wrong nested key (`values` instead of `buttons`) that imported fine but silently didn't work.
   - A cloud-n8n Draft-vs-Publish split silently running the last **published** graph instead of the edited draft during live Telegram-triggered executions — diagnosed only via the Executions tab graph view.
   - Missing `appendAttribution` flag leaving n8n's default footer on every bot reply.
   - A message-ordering race: a "started" reply fanned out in parallel with the poll-loop branch, so the poll branch could finish and deliver the final result before the "started" message actually sent.
   - `getWorkflowStaticData` API mismatch (needed the `'global'` argument).
   - `$env` access denied in this n8n instance, forcing a redesign to put all deployment constants in a `Workflow Config` node instead of environment variables.
   - Volatile in-workflow session-state loss between Telegram updates, motivating two prior redesigns (workflow-static-data → n8n Data Table → finally backend-owned `ingestion_uploads`).
   - Workflow JSON text once found pasted line-by-line into an exported spreadsheet column (local-file-only, but a real hazard of hand-editing/copy-pasting workflow JSON near data).
   - **Freshest, diagnosed this session, not yet in `log.md` before this page**: a loop-stale-data bug — `Format Upload Result Message` reads first-iteration poll data instead of the final one, so the bot's only reply after "Готово" is the premature "Документ обрабатывается..." message even though the backend finishes correctly and the n8n execution reports `Succeeded`. Confirmed via `img_11.png` (Executions graph, 1m44s Succeeded) and `img_12.png` (node input/output showing `status: processing` at a timestamp matching the *finalize* call, not the true completion ~98s later). Root cause not yet fixed in the n8n graph itself.
4. **No Telegram SDK is a dependency yet**; `httpx`/`fastapi`/`uvicorn` already are, and Docker runs a single `backend` process — an in-process native bot adds no new container or deploy complexity.

## Migration design (not yet built)

### Webhook vs. long-polling → **long-polling**

Long-polling (`getUpdates`), not a webhook. This project's public ingress (Caddy + nip.io, or the `ngrok` profile) has directly or indirectly caused multiple incidents already (the MTU bug, credential-header mismatches). Long-polling needs only outbound HTTPS from the `backend` container to `api.telegram.org` — no dependency on Caddy/ngrok/DNS/certs staying up. Single uvicorn worker (no `--workers` flag) means a single long-poll loop is trivially safe, no duplicate-consumer risk.

Cutover note: Telegram allows only one active delivery mode per bot token. Before starting the native poller, must call `deleteWebhook` (or deactivate the n8n workflow, which releases its webhook) — otherwise `getUpdates` returns 409.

### Library choice → **aiogram (3.x)**

Async-native, drops directly into the existing FastAPI/uvicorn asyncio event loop via `asyncio.create_task` from `lifespan` — no extra thread (unlike the Diadoc/SBIS schedulers, which use threads specifically because they're sync/blocking). Typed `ReplyKeyboardMarkup`/`KeyboardButton` builders eliminate the exact bug class that bit n8n twice (hand-authored reply-keyboard JSON). Built-in `bot.download(file_id)` replaces the `Get Telegram File` node. Chosen over `python-telegram-bot` (more boilerplate for a one-dev MVP) and over raw `httpx` (would reintroduce hand-rolled polling/offset/keyboard-JSON risk).

### Module structure

New package `backend/app/telegram_bot/`:
```
backend/app/telegram_bot/
  __init__.py
  bot.py         # Bot/Dispatcher construction, start/stop hooks for lifespan
  keyboard.py    # MAIN_KEYBOARD: Готово/Статус (row 1), Сбросить (row 2)
  messages.py    # Russian text constants + STAGE_TEXT map (ported verbatim from n8n Code nodes)
  handlers.py    # message/command handlers, calling bot_gateway_service
  poller.py      # async poll-after-finalize loop with stage-change messages
```

New service `backend/app/services/bot_gateway_service.py`: a mechanical extraction of the logic currently embedded in the six `bot/*` router endpoint functions, turned into plain async-callable functions taking raw bytes/strings instead of FastAPI `UploadFile`/`Form`/`Query` markers:
- `append_draft_page(db, *, chat_id, source_user_id, source_username, document_kind, organization_name, point_name, filename, content_type, file_bytes) -> DraftPageResult`
- `get_draft_status(db, chat_id) -> DraftStatusResult | None`
- `reset_draft(db, chat_id) -> ResetResult`
- `finalize_draft(db, chat_id, *, create_google_sheet=True) -> UploadAcceptedResult`
- `get_latest_upload_status(db, chat_id) -> UploadStatusResult | None`
- `get_upload_status(db, upload_id) -> UploadStatusResult`

The six `/bot/*` HTTP endpoints in `invoice_review.py` become thin wrappers over these — same URLs, same contracts, same behavior. DB calls from async handlers run via `asyncio.to_thread` (SQLAlchemy/SQLite session is sync).

### n8n node → native handler mapping

| n8n piece | Native replacement |
|---|---|
| `Normalize Update` | aiogram text filters: `{готово,/done,done}`, `{статус,/status,status}`, `{сбросить,/reset,reset}`, `{/start,меню,/menu,menu}`; `F.photo`/`F.document` handlers |
| `Get Telegram File` + `Send Page To Backend` | `await bot.download(file_id)` → `bot_gateway_service.append_draft_page(...)` |
| `If Page Unsupported`/`Reply Unsupported`/`Reply Page Added` | check `DraftPageResult.status`, send matching ported string |
| `Finalize Draft` → `Reply Processing Started` → `Send Started Reply` → `Prepare Poll` | "Готово" handler: `finalize_draft(...)`; send started-reply *and await it* before launching poll task — gets the 2026-07-09 ordering fix for free since aiogram handlers are naturally sequential, not fanned out |
| `Prepare Poll`/`Wait Before Poll`/`Check Upload Status`/`If Poll Done`, `Compute Stage`/`If Stage Changed`/`Set Stage Reply Text`/`Send Stage Update`, `Format Upload Result Message` | `poller.py`: one `asyncio.create_task` per finalize, `while attempt < 24: await asyncio.sleep(5); status = await get_upload_status(...)`; port `mapStage()`/`STAGE_TEXT`/result-formatting as plain Python; last-sent stage tracked in a local coroutine variable (no `$node` self-reference hack needed) |
| `If Is Status` branch | "Статус" handler: `get_draft_status`, fall back to `get_latest_upload_status` with the "Активного черновика нет..." prefix |
| `If Is Reset` branch | "Сбросить" handler: `reset_draft(...)` |
| `Reply Menu` | "/start"/"меню" handler |
| Reply keyboard, `appendAttribution: false` | `MAIN_KEYBOARD` attached to every reply; aiogram sends no attribution footer by default |

Per-chat poll-task registry (`dict[chat_id, asyncio.Task]`) so a repeated "Готово" cancels/replaces any still-running poll for that chat.

`main.py` wiring mirrors the existing scheduler pattern (`start_diadoc_scheduler()`/`stop_diadoc_scheduler()` in `lifespan`) but uses `asyncio.create_task(dispatcher.start_polling(...))` instead of a thread. New settings in `config.py`: `telegram_bot_token: str | None = None`, `telegram_bot_enabled: bool = False`, `telegram_bot_poll_interval_seconds: float = 5.0`, `telegram_bot_max_poll_attempts: int = 24` (same numbers n8n already used).

### What stays unchanged

All `/bot/*` HTTP endpoints (URLs/contracts/`X-Bot-Api-Key` gate), `bot_ingestion_service.py`, `invoice_review_service.py`, the `ingestion_uploads` table, `upload_trace_service.py` (including its known in-memory-only limitation — not being fixed as part of this migration), and the entire processing pipeline (OpenAI extraction, Google Sheets write). This is a transport-layer swap only.

### Rollout — clean cutover, not parallel run

n8n and the native bot must never run against the same bot token simultaneously (`ingestion_uploads` drafts are keyed only by `chat_id` with no per-consumer isolation — two live consumers would race). Given single VPS/single dev/small user base:

1. Build and test against a second, throwaway BotFather test token pointed at the same backend/DB (`bot_gateway_service` is chat_id-scoped and indifferent to which bot delivered the message) — full dry run of every command/error path, no production risk.
2. Cutover in one deploy: deactivate the n8n workflow (releases its webhook), redeploy backend with `telegram_bot_token` = production token, `docker compose up -d`. Single container restart.
3. Immediate smoke test with own account before telling Lilia/BA anything changed.
4. Keep the n8n cloud workflow deactivated-but-not-deleted for ~1 week as rollback; keep `n8n/telegram-bot-mvp.workflow.json` in git history regardless. No feature flag needed at this scale.

### Effort estimate: ~1.5-2 focused developer-days (10-16h)

`bot_gateway_service.py` extraction (~1-2h) + aiogram/settings/skeleton wiring (~1-2h) + handlers (~2-3h) + keyboard/messages (~1h) + poller with stage-progress (~2-3h) + end-to-end testing against throwaway bot (~2-3h) + cutover/smoke test (~1h).

### New/changed files (when this is picked up)

**New**: `backend/app/telegram_bot/{__init__,bot,handlers,keyboard,messages,poller}.py`, `backend/app/services/bot_gateway_service.py`, `backend/tests/test_bot_gateway_service.py`.
**Changed**: `backend/app/main.py` (lifespan), `backend/app/config.py` (new settings), `backend/requirements.txt` (add `aiogram`), `backend/app/routers/invoice_review.py` (six endpoints become thin wrappers).
**Decommissioned, not deleted**: `n8n/telegram-bot-mvp.workflow.json` (deactivate the cloud workflow; keep file as historical reference through the rollback window).
