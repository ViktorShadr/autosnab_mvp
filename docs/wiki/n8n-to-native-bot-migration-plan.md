---
title: n8n to Native Bot Migration Plan
source: session
created: 2026-07-20
tags: [bot, telegram, n8n, migration, backlog]
status: planned-not-started
---

# n8n → Native Python Telegram Bot — Migration Plan

**Status: decision made 2026-07-20, recorded here as a backlog item — implementation not started.**

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
