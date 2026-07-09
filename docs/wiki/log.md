# Wiki Log

## [2026-07-02] bootstrap | 初始化知识系统

- 建立 wiki、manifest、检查脚本和 repo 级默认规则。

## [2026-07-02] bootstrap | integrated into autosnab_mvp

- Bootstrapped the LLM Wiki structure into `autosnab_mvp`, created the local raw root, and committed the initial wiki setup.

## [2026-07-02] requirements | SBIS EDO intake

- Registered the new SBIS EDO task files in `manifests/raw_sources.csv` and compiled the read-only integration requirements into `docs/wiki/sbis-edo-integration.md`.

## [2026-07-02] requirements | additional screenshot intake

- Registered `Вставленное изображение (3).png` in `manifests/raw_sources.csv` and captured the centralized OCR/table-flow hint from the new screenshot.

## [2026-07-02] analysis | EDO architecture verdict

- Concluded that a custom SBIS EDO module is feasible, but the right implementation shape is a source-agnostic intake core with SBIS as one adapter.

## [2026-07-02] coordination | parallel PDF work

- Noted that the PDF export path is being developed by another engineer in parallel, so the canonical document contract must be agreed before either branch drifts.

## [2026-07-02] planning | final execution plan

- Recorded the final MVP plan: freeze the shared contract, keep the PDF flow intact, add SBIS as a source adapter, and use one writer for both sources.

## [2026-07-03] coordination | delivery priority update

- Registered the new screenshot intake and captured the updated priority: show the document-recognition/table MVP this week, then move to SBIS EDO next week.

## [2026-07-03] coordination | meeting agenda intake

- Registered the meeting agenda and captured the immediate task split: multi-page upload UX, business-logic coordination with Lilia, contact sharing, and parsing strategy review.

## [2026-07-03] coordination | table logic intake

- Registered the table-logic note, spreadsheet CSV, and screenshot clarifying the Apps Script behavior and the document-level upload status flow.

## [2026-07-03] summary | today's conclusions

- Captured the day's conclusion: the project is a document-processing pipeline, the MVP focus is reliable recognition and table placement, and PDF/SBIS must remain adapters over one shared document core.

## [2026-07-03] setup | local wiki raw-root restored on this PC

- Created the expected sibling raw-root at `../autosnab_mvp_raw`, including `inbox/` for new raw attachments.
- Confirmed that new intake can start from this machine, but older manifest-listed raw files are still absent locally and will need to be restored separately if full manifest validation is required.

## [2026-07-03] intake | new inbox documents registered

- Registered three newly added inbox files in `manifests/raw_sources.csv`: `АвтоСнаб Кафе Ромашка .xlsx`, `Копия План АвтоСнаб .md`, and `Созвон с Лилией.md`.
- Kept the historical manifest rows intact despite the local raw-root still missing older source files from previous sessions.

## [2026-07-03] compile | roadmap and table logic writeback

- Compiled `Копия План АвтоСнаб .md` into a concrete project overview and a new supplier-catalog roadmap page.
- Compiled `Созвон с Лилией.md` and `АвтоСнаб Кафе Ромашка .xlsx` into a dedicated page describing validation-table behavior, status gating, duplicate handling, and conversion logic constraints.

## [2026-07-03] priority | downloaded invoices to validation-table MVP

- Confirmed the immediate task focus: build the MVP that populates the working validation tables from downloaded invoice documents.
- This priority sits ahead of the broader supplier-catalog roadmap and should drive the next implementation steps.

## [2026-07-03] analysis | Lilia walkthrough deepened

- Refined the wiki understanding of `АвтоСнаб Кафе Ромашка`: the table is an operator workflow surface with document-level gating, not just an OCR output sheet.
- Highlighted the concrete MVP risk areas: stable second-row headers, duplicate blocking, correction loop, special document forms, and automatic conversion/recalculation behavior.

## [2026-07-03] planning | invoice-table MVP checklist

- Added a concrete implementation checklist for the downloaded-invoice -> validation-table MVP.
- The checklist defines what to freeze first, what to reuse, what to rewrite, what to postpone, and the smallest 2-3 day delivery cut.

## [2026-07-03] implementation | prepend invoice blocks into shared sheet

- Added a Google Sheets target mode that writes new invoice blocks into an existing shared sheet instead of creating a fresh spreadsheet every time.
- New documents are inserted below the configured header rows, oldest rows are shifted down, and one empty separator row is added between document blocks.
- The created export metadata now stores the inserted row range so later backend reads can target the correct document block.

## [2026-07-03] verification | shared-sheet prepend logic covered by local unit test

- Added a local unit test for the prepend writer logic: new document rows go directly under the configured header rows and a blank separator row is appended after the block.
- Full pytest execution was not possible in the current shell because dev dependencies are missing from the environment.

## [2026-07-03] operations | runbook added

- Added a practical runbook for local start, Docker start, OAuth setup, shared-sheet mode, smoke tests, and local verification commands.

## [2026-07-03] analysis | shared-sheet copy compared against original

- Registered and compared `Копия АвтоСнаб Кафе Ромашка .xlsx` against the original workbook.
- Confirmed that new invoice blocks are inserted at the top and separated by blank rows, but the inserted values follow the old `Накладные` register order instead of the real `Накладная` sheet column order.
- The immediate fix target is therefore the row-to-column mapper, not the prepend mechanics.

## [2026-07-03] implementation | shared-sheet mapper rewritten for real header contract

- Reworked the shared-sheet writer to emit rows in the real `Накладная` column order used by `АвтоСнаб Кафе Ромашка`.
- Updated the reverse sheet parser so send/sync logic can read item rows from the `Накладная` contract as well as the older register-style field names.
- Local syntax checks passed; live Google retest is still needed.

## [2026-07-03] fix | shared-sheet write range widened to match row width

- Fixed the shared-sheet Google write range so it is derived from the actual row width instead of hardcoded to `AL`.
- This removes the `Requested writing within range ... but tried writing to column [AM]` error during live retest.

## [2026-07-03] fix | OCR item-row post-filter added

- Added a post-filter that removes low-quality item rows before they are stored in `Receiving` or written into Google Sheets.
- Added a regression test to ensure noisy item candidates do not become table rows.

## [2026-07-03] implementation | local document extraction layer added

- Added a switchable document-extraction service that can use MinerU as the primary local backend.
- Kept the current Google Drive OCR + deterministic parser chain as the default fallback so the existing flow remains usable.
- Added tests for the MinerU path and the OCR fallback path at the service layer.

## [2026-07-03] implementation | MinerU CLI contract aligned

- Aligned the local extraction adapter with MinerU's documented CLI flow: `mineru -p <input_path> -o <output_path> -b pipeline`.
- Added output-directory readers for structured JSON and markdown/text outputs.
- Added a unit test for MinerU output directory parsing.

## [2026-07-03] implementation | MinerU added to dependency and Docker path

- Added `mineru[all]` to backend Python dependencies so local installs and the Docker image can include the MinerU backend.
- Updated the Docker image notes and runbook to reflect the MinerU-enabled extraction flow and the OCR fallback mode.

## [2026-07-03] summary | day wrap-up

- Restored the wiki-first operating loop on this PC, including raw-root/inbox setup and writeback discipline.
- Registered and compiled new raw sources into project overview, supplier roadmap, validation-table behavior, MVP checklist, and runbook pages.
- Confirmed the immediate delivery focus: downloaded invoices -> validation table MVP.
- Implemented shared-sheet prepend mode for Google Sheets so new invoice blocks go to the top with a blank separator row.
- Diagnosed the real shared-sheet failure as a column-contract mismatch against the live `Накладная` sheet, not an overwrite/prepend bug.
- Reworked the shared-sheet mapper to target the real `АвтоСнаб Кафе Ромашка` sheet contract and updated reverse parsing accordingly.

## [2026-07-04] summary | day wrap-up

- Captured today's outcome in wiki: MinerU is now the documented local extraction backend, with OCR remaining as fallback.
- Kept the Google Sheets path aligned to the real `Накладная` column contract and documented the live write-range fix.
- Left `.env`, secret OAuth files, the local database, exports, and uploads out of version control.

## [2026-07-04] security | OAuth credentials moved fully into `.env`

- Replaced OAuth client/token JSON reads with env-only client ID, client secret, access token, refresh token, and expiry settings.
- OAuth callback and token refresh now persist updated token values back into `.env`.
- Removed `.env` and legacy OAuth JSON files from Git tracking while preserving the local ignored files.
- Recorded that the exposed Google credentials must be revoked and reissued because they already exist in Git history.

## [2026-07-04] docs | README aligned with active MVP and runtime

- Rewrote the root `README.md` around the actual current product center: invoice upload, OCR/MinerU extraction, validation-table flow, and iiko send/mock export.
- Removed outdated assumptions about secrets, Google setup, and project scope so the repo entrypoint now matches the active code and wiki status.

## [2026-07-04] ui | upload page now selects extraction backend per document

- Added a dedicated method selector on the invoice upload page for `Google OCR`, `MinerU`, or hybrid mode.
- Wired the selected method through the upload endpoint into the extraction service so one document can force OCR-only, MinerU-only, or `MinerU -> Google OCR fallback` without changing global `.env` settings.

## [2026-07-04] verification | MinerU pipeline works end to end

- Installed CPU PyTorch and the `mineru[pipeline]` dependency profile; added the undeclared MinerU runtime dependency `six`.
- Replaced the missing `mineru` launcher dependency with `python -m mineru.cli.client`, using the backend's active interpreter and Cyrillic OCR.
- Registered the real UPD smoke source and ran MinerU 3.4.2 successfully on it without Google OCR fallback.
- Updated the MinerU adapter for actual 3.4.2 output: Markdown is paired with `*_content_list.json`, while service model JSON is ignored.
- The final backend result contained supplier `ООО "ФРУКТЫ АРИФА"`, INN `3900040690`, invoice `1928`, date `2026-06-23`, and one item totaling `2041`.
- MinerU-focused tests pass; all 35 tests outside `test_receiving.py` pass. The pre-existing `test_receiving.py` hang remains.

## [2026-07-04] operations | one-command Docker startup aligned

- Reworked the Docker image to copy the real backend runtime layout instead of only `backend/app`.
- Added `.dockerignore` so the image build no longer uploads `.venv`, local databases, exports, uploads, and other heavy local artifacts.
- Updated `docker-compose.yml` to support `docker compose up --build` with persistent volumes for SQLite, uploads, exports, and MinerU/HuggingFace cache.
- Updated the README and runbook so Docker startup instructions now match the active runtime contract.

## [2026-07-04] intake | root workbook and updated calculator note reviewed

- Registered the new root copies `MVP Бух калькулятор (2).md` and `АвтоСнаб Кафе Ромашка .xlsx` in `manifests/raw_sources.csv`.
- Compiled their concrete findings into wiki: exact status transitions, first-row-only document statuses, row-specific `Корректировка`, and the current `Накладная` write contract across `A:AN`.
- Noted that the exported `.xlsx` shows some broken named-range validations (`#REF!`), so the live Google Sheet must remain the final source of truth for dropdowns and Apps Script behavior.

## [2026-07-04] planning | OpenAI-first parsing track

- Recorded the new implementation direction: delegate final document parsing to an OpenAI model, keep OCR/MinerU as evidence providers or fallbacks, and preserve deterministic Google Sheets mapping.
- Defined the immediate plan boundary: add an OpenAI parser layer into the existing extraction service, validate/normalize model output, and keep the `Накладная` shared-sheet contract stable.

## [2026-07-04] implementation | OpenAI invoice parser pipeline

- Added a strict Pydantic invoice contract and an OpenAI Responses API parser over PDF, MinerU, or OCR evidence.
- Added deterministic date, INN, amount, VAT, line-total, document-total, duplicate, OCR-error, status, and correction normalization.
- Kept Google Sheets deterministic: the writer reads row-2 headers, writes only the `A:AN` business contract, and limits document-level fields to the first row.
- Added structured per-document debug traces under `exports/openai_debug` and preserved parser metadata in the existing review document metadata.
- Added focused schema, mock-provider, golden-scenario, status-gate, extraction, and mapper tests; 28 targeted tests pass.
- The full suite still hangs in the pre-existing `test_receiving.py` path. Live OpenAI and Google Sheet calls were not run because they require external credentials and the user-owned target sheet.

## [2026-07-04] fix | Docker build unblocked from uvicorn dependency resolution

- Reduced the backend runtime dependency from `uvicorn[standard]==0.34.0` to `uvicorn==0.34.3`.
- This keeps the container command unchanged (`python -m uvicorn ...`) but avoids pulling optional `standard` extras during Docker build, which were not required by the current runtime and were making pip resolution less reliable.

## [2026-07-04] implementation | structured item normalization and reference mapping

- Expanded the strict OpenAI item schema and prompt with cleaned names, descriptors, package data, document quantities, conversion candidates, codes, confidence, and review reasons.
- Added deterministic item cleanup, package extraction, compound conversion, and ambiguity checks after the model response.
- Added fixed-header reads for the Google Sheet tabs `Товары` and `Справочник фасовок`.
- Wired deterministic product/package matches into `Наименование товара в УС`, `Ед.изм. в УС`, and `Кол-во в УС`; unresolved rows receive `Нет в справочнике` or `Сопоставление`.
- Verified 58 backend tests outside the known hanging `test_receiving.py`; no live Google call was made because the current environment still times out during the Google TLS handshake.

## [2026-07-04] ui | upload page preview and inline Google auth

- Added inline preview rendering for selected invoice images and PDFs directly on the upload page before submission.
- Added a Google OAuth status panel and popup-based authorization entrypoint on the same page, with callback postMessage support so the upload screen can refresh auth state without forcing the operator through separate URLs.

## [2026-07-04] ui | upload page pipeline trace and stop rules

- Added explicit `pipeline_logs` from backend extraction stages into the invoice upload response and rendered them on the upload page for operator-visible tracing.
- Added hard stop behavior for empty pre-OpenAI evidence and empty OpenAI structured payloads: the backend now returns a structured error instead of saving an empty review document.

## [2026-07-08] intake | root note and checklist screenshot reviewed

- Reviewed the newly added root note `MVP Бух калькулятор (2).md`; it re-confirmed the contract that document-level statuses are first-row only, `Корректировка` stays row-local, `Проверить выбранные документы` is the gate into `Загрузить`, and `Вернуть на проверку` returns a document to the manual review loop.
- Registered the new root screenshot `img_3.png` in `manifests/raw_sources.csv` before use.
- Captured the screenshot's current delivery checklist: wire the bot/MVP logic around the approved TOR, finish iiko export from the table through script, complete the document-recognition handler, pull SBIS documents into the table, and then run a full system demo for Galina before client onboarding.

## [2026-07-08] source-of-truth | deprecated short BA note

- Marked `MVP Бух калькулятор (2).md` as obsolete after user clarification.
- The active business-analyst baseline is now explicitly `MVP Бух калькулятор.md`; the shorter `(2)` file must not be used as the current source of truth for requirements or workflow decisions.

## [2026-07-08] analysis | bot and SBIS scope checked against real code

- Verified that the repo already contains the central invoice-review backend path: upload UI/API, multi-page document intake, extraction/evidence pipeline, OpenAI normalization, Google Sheets review writer, iiko reference enrichment, and iiko incoming-invoice XML preview/export.
- Verified that the repo does not yet contain a dedicated Telegram bot implementation or any SBIS/Saby adapter, auth client, scheduler, or sync-history persistence.
- The practical integration conclusion is to treat bot and SBIS as source/transport adapters over the existing backend contract, not as separate document-processing implementations.

## [2026-07-08] verification | multi-file upload boundary confirmed

- Verified in code that `/invoice-review/upload-document-live` accepts `files: list[UploadFile]`, stores them under one logical upload directory, merges page evidence through `extract_invoice_document_set(...)`, and can continue into the Google Sheets write path when `create_google_sheet=true`.
- Verified the important boundary as well: this is a multi-page path for one logical document, not a batch import of multiple unrelated invoices in one request.
- Verified that multi-file processing currently works only with the OpenAI parser path; non-OpenAI extraction methods are rejected for multi-page documents.

## [2026-07-08] planning | bot and SBIS implementation plan added

- Registered the new root BA source `MVP Бух калькулятор.md` in `manifests/raw_sources.csv` as the active full-scope requirements document used for this planning pass.
- Added `docs/wiki/bot-sbis-implementation-plan.md` as the implementation plan for the user's task scope.
- The plan is code-aware: it assumes the existing invoice-review backend is the canonical processing core, places the bot as a thin upload/status adapter, and places SBIS as a read-only source adapter with raw artifact storage, dedupe, and sync history.

## [2026-07-08] planning | n8n bot plan fixed as latest task

- Added `docs/wiki/n8n-bot-implementation-plan.md` as the concrete delivery plan for the first bot implementation through `n8n`.
- Fixed the architectural boundary: Telegram plus `n8n` are only the session/orchestration layer, while invoice-review backend remains the only OCR/parsing/normalization/review core.
- Fixed the near-term delivery order as well: freeze backend upload/status/result contracts first, then implement `n8n` workflows for Telegram routing, document session collection, finalize/upload, status polling, and result notification.

## [2026-07-08] intake | bot TOR PDF reviewed and compiled

- Registered the new root source `ТЗ бота.pdf` in `manifests/raw_sources.csv` before using it.
- Reviewed the PDF and confirmed it matches the current repo direction: the bot is only an intake/status channel over the existing invoice-review backend, not a second parsing/export pipeline.

## [2026-07-09] fix | n8n 2.3.6 workflow import artifact added

- Added `n8n/telegram-bot-mvp.workflow.hardcoded-fixed.n8n-2.3.6.json` as a separate import artifact for the user's current self-hosted `n8n 2.3.6` runtime.
- Rewrote the `Data Table` nodes from the newer `tableId`/`rowId` export shape to the older runtime's `dataTableId` plus explicit upsert/filter configuration, so session upserts no longer fail with `At least one condition is required`.
- Corrected reply nodes that were reading post-`Data Table` outputs instead of the original workflow state, and reconnected upload polling to branch from the normalized backend response rather than the Telegram `sendMessage` response.

## [2026-07-09] operations | cloud n8n session-table CSV template added

- Added `n8n/telegram_bot_sessions.csv` as a header-only import template for the `telegram_bot_sessions` Data Table used by the Telegram bot workflow.
- Updated the `n8n` setup note so cloud-workspace setup can import the session-table structure instead of creating each column manually.

## [2026-07-09] operations | cloud n8n fixed workflow artifact added

- Added `n8n/telegram-bot-mvp.workflow.fixed.json` as a ready-to-import cloud `n8n` workflow variant.
- Kept the user's current hardcoded Telegram credential/token/backend URL intact while preserving the corrected session-table contract: start/append/finalize/status/reset all key by `chatId -> chat_id`, upserts match on `chat_id`, reset deletes only the current chat row, and post-upload/final-status writes update the specific stored row.

## [2026-07-09] operations | cloud n8n public-backend path added

- Updated `docker-compose.yml` so `PUBLIC_API_BASE_URL` is no longer hardcoded to `http://localhost:8000` inside the backend container; Docker now respects the configured public base URL from `.env`.
- Added `BACKEND_ENV_FILE` support in `docker-compose.yml` so backend startup is no longer blocked by a non-file `.env` path on this workstation; Compose can now mount and load a separate runtime env file when needed.
- Added an optional `ngrok` compose profile that publishes the local backend and exposes the ngrok inspection API on `localhost:4040`.
- Added `scripts/get_ngrok_public_url.py` so the current public HTTPS tunnel URL can be read quickly and pasted into cloud `n8n` workflow config.
- Updated `.env.example`, `README.md`, `docs/wiki/runbook.md`, `n8n/README.md`, `n8n/telegram-bot-node-setup.md`, and the importable workflow JSON so the cloud-`n8n` setup is explicit: the workflow must use a public HTTPS `backendBaseUrl`, while local `host.docker.internal:8000` remains only for same-machine `n8n`.

## [2026-07-09] fix | full n8n workflow binary handoff corrected

- Registered the new Telegram screenshot `codex-clipboard-x2c4Ho.png` in `manifests/raw_sources.csv` before using it.
- Diagnosed the live bot failure as a workflow-level binary access bug, not a backend upload failure: `Store File In Memory` was reading the downloaded Telegram file through `$input.item`, which is not the valid input accessor in the current Code-node runtime.
- Updated `n8n/telegram-bot-full.workflow.json` so the append-file path reads binary from `$input.first().binary` and falls back across available binary keys, matching the current `n8n` runtime behavior and unblocking photo-page accumulation in session memory.

## [2026-07-09] fix | full n8n workflow moved to durable session rows

- Registered the new Telegram screenshot `codex-clipboard-hhh7PL.png` in `manifests/raw_sources.csv` before using it.
- Diagnosed the next live failure as cross-execution state loss: after the bot confirmed `Страница 1 добавлена`, the next `Готово` command could not find the same logical document anymore and returned `Нет активного документа`.
- Reworked `n8n/telegram-bot-full.workflow.json` so the richer full bot flow no longer depends on volatile workflow-static chat state between Telegram updates.
- The full flow now uses the durable `telegram_bot_sessions` Data Table for append/finalize/status/reset: first-file auto-open still works, appended pages are stored as serialized page payloads in `files_json`, `Готово` rebuilds multipart `files[]` from that row, backend upload IDs are written back into the same row, and `Сбросить` deletes the row explicitly.

## [2026-07-09] ui | full n8n workflow now sends Telegram buttons

- Updated `n8n/telegram-bot-full.workflow.json` so all bot replies are sent through direct Telegram Bot API `sendMessage` HTTP calls instead of the previous plain reply nodes.
- Added a persistent reply keyboard with `Новый документ`, `Готово`, `Статус`, and `Сбросить`, generated once in `Normalize Update` and attached to every operator-facing reply as `reply_markup`.
- This removes the earlier UX dependence on typing exact command texts by hand while keeping the same backend contract and multi-page document session logic.
- Compiled the new concrete constraints into wiki: broader first-stage intake types (`jpg/png/pdf/xml/xls/xlsx/QR`), operator-facing upload statuses, explicit upload-journal fields, unsupported-format behavior, and possible organization/point selection before upload finalization.

## [2026-07-08] implementation | first bot backend contract fixed in code

- Added a persistent `ingestion_uploads` journal table for bot-originated uploads, including upload provenance, file path, source user/channel, status, and error text.
- Added bot-facing backend endpoints on top of the existing invoice-review pipeline: async upload entry plus durable status lookup by `upload_id`.
- Fixed the current implementation boundary intentionally: image/PDF uploads go into the live pipeline, while `xml` / `xls` / `xlsx` / QR-specific flows return an explicit `unsupported_format` response instead of crashing.
- Added `docs/wiki/bot-backend-api-contract.md` as the canonical repo writeback for this API shape.

## [2026-07-08] implementation | n8n bot scaffold added

- Added a repo-native `n8n/` directory with a first Telegram bot MVP scaffold.
- Added `telegram-bot-mvp.workflow.json` as an importable workflow skeleton covering session start, file append, finalize/upload, status polling, and reset flow.
- Added `telegram-bot-mvp.env.example` and `n8n/README.md` so the next implementation step can move from planning into actual `n8n` assembly against the new backend contract.

## [2026-07-08] implementation | n8n workflow refined toward real assembly

- Reworked the workflow scaffold so it now has explicit finalize-contract assembly, upload-outcome mapping, and status-outcome mapping stages instead of one opaque placeholder chain.
- Added `telegram-bot-workflow-notes.md` to isolate the remaining hard step: Telegram file download and multipart `files[]` upload into the bot backend endpoint.
- Extended the env example with backend extraction/sheet options and optional default organization/point values.

## [2026-07-08] diagnosis | current bot upload failure is pre-backend n8n validation

- Reviewed root screenshot `img_4.png`.
- The visible error is not OCR/parsing failure and not a backend upload rejection; `n8n` reports that the workflow itself has issues and cannot be executed.
- Practical meaning: attaching a scan in Telegram currently stops before the bot can call `/api/v1/invoice-review/bot/upload-document-live`, so the immediate fix target is workflow validity/completeness inside `n8n`, not invoice-processing logic.

## [2026-07-08] fix | unknown bot text now has explicit fallback branch

- Reviewed root screenshot `img_5.png`.
- Confirmed that `Normalize Update` emits `intent = unknown` for arbitrary text, while the prior `Route Intent` configuration had no matching branch for that value.
- Updated the `n8n` workflow scaffold so unknown text now routes to a direct Telegram help reply instead of terminating silently.

## [2026-07-08] docs | node-by-node n8n setup guide added

- Added `n8n/telegram-bot-node-setup.md` as an exact UI configuration guide for every node in the current Telegram bot workflow.
- The guide covers Data Table creation, env prerequisites, expressions, code-node contents, and the exact field values to enter in `n8n`.

## [2026-07-08] implementation | fuller self-contained n8n workflow JSON added

- Added `n8n/telegram-bot-full.workflow.json` as a more self-contained workflow variant.
- This version keeps the same bot contract but removes the earlier `Data Table` dependency by storing per-chat bot sessions in `workflow static data`.
- The JSON now includes filled nodes for Telegram file lookup, file download, in-memory session append, finalize payload preparation, backend upload, status polling, reset, and unknown-text fallback.

## [2026-07-08] fix | full n8n workflow aligned to current Code-node static-data API

- Live `n8n` execution screenshot showed `ReferenceError: getWorkflowStaticData is not defined` inside `Prepare File Download`.
- Updated all full-workflow Code nodes to use `$getWorkflowStaticData('global')`, which matches the current runtime helper exposed in this `n8n` editor.

## [2026-07-08] fix | first file can auto-open session in full n8n workflow

- Telegram and `n8n` execution screenshots showed that the full workflow now executes, but photo upload was still rejected at `Prepare File Download` when the operator had not sent `Новый документ` first.
- Updated the full workflow so the first incoming file auto-creates the in-memory session for that chat, then continues through the file-download path instead of replying with a hard session-open error.

## [2026-07-08] ux | bot replies now include a clearer operator menu

- Updated the full workflow so user-facing Telegram replies now carry a consistent text menu with the core actions: `Новый документ`, send file, `Готово`, `Статус`, `Сбросить`.
- Expanded command normalization at the intake step to accept common variants such as `/start`, `/menu`, `/status`, `/reset`, `/done`, and lowercase Russian command text.

## [2026-07-08] ux | bot reply flow cleaned up after Telegram feedback

- Telegram screenshots showed that repeating the full action list after almost every event made the interface feel noisy and misleading.
- Refined the full workflow so start/help/reset paths still show the full instruction block, while file-accepted, upload-submitted, and status replies are now shorter and more contextual.

## [2026-07-08] compatibility | direct Bot API keyboard workaround rolled back on this n8n instance

- Live `n8n` execution showed `access to env vars denied` in reply nodes that built direct Telegram Bot API URLs from `$env.TELEGRAM_BOT_TOKEN`.
- Because that instance policy blocks the workaround, the full workflow was returned to built-in Telegram reply nodes while keeping the cleaner compact text UX.

## [2026-07-08] ux | Telegram bot replies tightened into a cleaner product flow

- Registered the new Telegram screenshot `codex-clipboard-DhOyFN.png`; it showed that the current fallback still looked like an automation dump because of the `Не понял сообщение` opener, the repeated full instruction block, and the `n8n` attribution footer.
- Updated `n8n/telegram-bot-full.workflow.json` so reply nodes now disable attribution, open with a shorter home screen, avoid error-style wording for ordinary unknown text, and keep each step focused on one next action instead of restating the entire menu after every message.

## [2026-07-08] compatibility | full workflow no longer depends on env access inside Code nodes

- Registered the new `n8n` editor screenshot `codex-clipboard-JVqqNR.png`; it showed `Prepare File Download` failing on `$env.DEFAULT_ORGANIZATION_NAME` / `$env.DEFAULT_POINT_NAME` with `access to env vars denied`.
- Updated the full workflow so runtime defaults now live inside `Normalize Update` and flow through item JSON, removing `$env` reads from Code nodes and replacing URL expressions with JSON-backed config values.

## [2026-07-06] intake | original workbook registered as canonical raw source

- Registered `../autosnab_mvp_raw/inbox/АвтоСнаб Кафе Ромашка  (ориг).xlsx` via `scripts/ingest_raw.py` as `src_bd91ee3517`.
- Fixed the project stance that this original workbook is now the canonical offline source for the `Накладная` contract.
- Fixed the contract-reading rule as well: row 1 is the business-annotation layer, row 2 is the machine-binding layer, and Apps Script is the workflow/gating layer.
- Fixed the architectural interpretation that Apps Script constrains sheet behavior and readiness checks, but does not parse invoice contents; OCR/MinerU/OpenAI remain the document-parsing layer.
- Extracted the original `Накладная` mapping into a dedicated wiki page, including the row-1 business instructions, row-2 machine headers, calculation/reference columns, and the first-row-only implications for backend block building.
- Compared the current backend write path against that canonical workbook, then implemented a native shared-sheet row builder: the active `Накладная` write path now uses direct canonical rows instead of depending primarily on the legacy `Накладные` -> remap pipeline.
- Left the legacy register builder in place only as a compatibility layer for the old review output shape.
- Kept `Копия АвтоСнаб Кафе Ромашка ...xlsx` files in the wiki model as diagnostic exports for regression analysis rather than the primary contract authority.
- This narrows the next implementation target: backend row mapping should be checked against the original workbook structure plus the existing Apps Script behavior before comparing against historical generated copies.
- Added retry guidance in the upload UI so empty OCR/MinerU flows can recommend switching to `OpenAI structured parser`.

## [2026-07-07] analysis | branch integration strategy for multi-page invoices

- Compared `main` against `codex/invoice-recognition-hardening` specifically for multi-page invoice handling.
- Confirmed that `main` still carries an older checkbox-based `multipage_invoice` upload path and TORG-12 continuation-page OCR behavior, while the current hardening branch already includes the broader logical multi-page upload/editor flow, merged page evidence, consistency warnings, and one-pass OpenAI parsing over multiple pages.
- Conclusion: do not start with a full `main -> codex/invoice-recognition-hardening` merge for this concern; transplant only the remaining useful OCR/test details from `main` if anything is still missing.

## [2026-07-07] planning | colleague-repo branch merge plan fixed

- Added a durable integration plan to `docs/wiki/github-and-raw-strategy.md` for merging into `AndreyGomzikov/autosnab_mvp`.
- Fixed the recommended path: push `codex/invoice-recognition-hardening` to the author's fork, open a PR into the colleague repo, keep DB/CSV/raw artifacts out of Git, and resolve conflicts manually with the hardening branch as the architectural baseline.

## [2026-07-04] ui | live upload trace polling

- Added a lightweight backend upload-trace store plus `/api/v1/invoice-review/upload-trace/{trace_id}` endpoint.
- The upload page now generates a `trace_id`, starts polling before file submission, and renders live stages while the backend is still processing the document.
- Trace coverage now includes extraction steps, OpenAI request start/finish, deterministic reference mapping, and Google Sheets write attempts.

## [2026-07-04] fix | backfill invoice reference mapping for older review payloads

- Reviewed `Копия АвтоСнаб Кафе Ромашка  (2).xlsx` and confirmed that empty `Наименование товара в УС` values came from older stored `recognized_items_json` records where `us_product_name/product_found` had never been persisted.
- Verified that the current deterministic matcher can map representative rows from that workbook against the current `Товары` sheet, so the gap was not in the similarity rules themselves.
- Added a review-sheet backfill path: when `Накладная` is rebuilt and item US fields are missing, backend now re-merges parser item metadata and re-runs deterministic reference mapping against current Google catalogs before composing output rows.

## [2026-07-04] fix | fallback US product name and supplier INN cleanup in shared sheet

- Reviewed `img.png` and confirmed that the shared sheet still exposed two UX-visible defects on older review rows: empty `Наименование товара в УС` and overlong `ИНН Поставщика` values that actually contained merged `ИНН/КПП`.
- Updated deterministic mapping so `Наименование товара в УС` is always populated from the normalized item candidate when no exact catalog match exists; exact matches still overwrite it with the catalog name.
- Added reusable supplier-INN cleanup that extracts the real 10/12-digit INN from merged OCR strings such as `3900040690390001001` and reused it during review-sheet header build, not only during the initial OpenAI normalization step.

## [2026-07-04] ui | live upload job split from HTTP request

- Added a separate `upload-photo-live` endpoint that returns a `trace_id` immediately and runs the document processing in a background thread.
- Kept the existing sync upload route for compatibility, but both paths now write to the same trace store so the upload page can show logs as they are produced.
- Updated the upload page to poll the trace endpoint while the background job is still running, then render the final result once the trace is marked complete.

## [2026-07-04] summary | day wrap-up

- Captured the day’s end state in wiki: the upload flow is now live-trace driven, not just a final-result screen.
- Preserved the deterministic rule that `Наименование товара в УС` should never stay blank when the parser can provide a normalized candidate.
- Preserved the deterministic rule that supplier INN must be normalized again during review-sheet build so merged `ИНН/КПП` OCR values do not leak into the visible column.

## [2026-07-04] analysis | five real invoice photos assessed

- Registered and reviewed five root JPEGs representing four documents: UPD `1928`, UPD `УТ-35634`, both pages of товарная накладная `УПМК003248`, and one retail receipt.
- Confirmed that the model contract covers the visible document headers, amounts, VAT, item rows, package candidates, and normalized product names, but the current OpenAI service receives text evidence only and never sees the source image.
- Confirmed a multi-page gap: the upload UI and API accept one file, so the two pages of `УПМК003248` cannot currently be parsed as one document.
- Ran an isolated `openai` extraction test without database or Google Sheets writes. The request stopped before OpenAI because Docker MinerU cannot import OpenCV without `libxcb.so.1`, then Google Drive OCR timed out during TLS handshake.
- Conclusion: `gpt-5-mini` remains appropriate as the structured parser, but the current end-to-end runtime is not yet reliable enough for quality production recognition. Required next work is Docker OCR repair, direct-image AI fallback, multi-page grouping, image preprocessing, and expected-JSON golden tests for these photos.

## [2026-07-04] fix | SQLite runtime health and readonly diagnosis

- Added a dedicated database health service so startup now performs a real SQLite write probe instead of relying on `/ping`.
- Added `/health/runtime` and pointed Docker healthcheck at it, so a read-only `/data` mount stops being reported as healthy.
- Background upload traces now rewrite `attempt to write a readonly database` into a direct operator hint to check permissions on `/data/autosnab_mvp.db` and its parent volume.

## [2026-07-04] planning | invoice recognition hardening plan fixed

- Added `docs/wiki/invoice-recognition-hardening-plan.md` as the execution plan for the failures exposed by the five real photos.
- Ordered work into observable contracts, runtime evidence repair, multi-page intake, deterministic image preparation, multimodal OpenAI parsing, deterministic validation, executable golden tests, and final live Google Sheets verification.
- Kept the current strict Pydantic and deterministic writer boundaries. Model replacement is explicitly gated by golden-set accuracy, latency, and cost rather than assumed to be necessary.
- Defined the final release gate: five photos become four logical documents, critical fields and numeric rows match expected fixtures, normalized product names are always present, and stopped pipelines cannot write to Google Sheets.

## [2026-07-04] analysis | deterministic conversion rules compiled

- Registered and analyzed `Расчет коэфф.md`.
- Fixed one coefficient definition: accounting units contained in one document unit.
- Added formulas for accounting quantity and price plus the line-amount preservation invariant.
- Confirmed the current implementation gap: quantity conversion exists partially, but `Цена в УС` is always empty and no product exception reference exists.
- Added `docs/wiki/unit-conversion-rules.md` and integrated its implementation and acceptance gates into the recognition hardening plan.
- Recorded that piece-to-weight values for eggs, citrus, and avocado are deterministic reference data, not model knowledge; ambiguous active values must require `Сопоставление`.

## [2026-07-04] implementation | hardening plan phases 0-6 closed in code

- Extended live upload tracing with a versioned trace contract and explicit metadata fields for `logical_document_id`, `evidence_version`, selected method, and source files.
- Upgraded the upload UI into a logical multi-page editor: operators can reorder selected pages, remove mistakes before submit, and the wording now consistently describes the OpenAI mode as a vision parser receiving text plus images.
- Strengthened deterministic image preparation with deskew, clipping/text-coverage quality metrics, and page-level review/stop warnings that are carried into the evidence contract.
- Added OCR-based continuation-page marker checks during multi-page merge so missing pages are surfaced as consistency warnings before persistence or sheet writing.
- Expanded the real-photo golden fixtures with expected shared-sheet rows, added replay evaluation plus compact provider/model reporting, and introduced a no-write live evaluation helper that always forces `create_google_sheet=False`.
- Added `scripts/docker_runtime_smoke.py` for Docker/provider smoke runs and `scripts/run_invoice_golden_eval.py` for replay-driven golden reports.

## [2026-07-04] fix | MinerU unhealthy runtime is skipped early

- Tightened provider health so MinerU is marked unready when the HuggingFace model cache is incomplete, not only when Python imports fail.
- Added an extraction-service guard: OpenAI evidence collection and `hybrid` mode now skip MinerU immediately when health is red and continue to OCR fallback without spending several minutes inside a doomed MinerU run.
- Added regression tests covering incomplete MinerU cache reporting and unhealthy MinerU short-circuit before OCR fallback.

## [2026-07-04] analysis | workbook export after two parsed invoices explained

- Registered and analyzed `Копия АвтоСнаб Кафе Ромашка 2.xlsx`, a workbook export containing two newly parsed document blocks.
- Confirmed that the kefir receipt block stores `normalized_name_candidate = Кефир Фермерский` for all six kefir rows, while `us_product_name` and `product_found` remain null in `recognized_items_json`; the blank `Наименование товара в УС` cells therefore come from stale unmapped stored payload, not from an inability of the current matcher to map `Кефир Фермерский` to catalog item `Кефир`.
- Confirmed that duplicate indicators are driven by historical SQLite documents: the new UPD `1928` is marked `Да` because document `ID 9` already stores the same supplier and invoice number from the same source image, while the kefir receipt `0245` is marked `?` because older documents `ID 4` and `ID 10` share the same supplier/date/total but store the invoice number as `ЧЕК 0245` instead of `0245`.

## [2026-07-04] fix | review sheet no longer leaves US product name blank on stale payloads

- Updated review-sheet build so each row first rehydrates parser metadata and then falls back to `normalized_name_candidate`, `clean_name`, or raw item name when `us_product_name` is still absent in stored payload.
- This keeps `Наименование товара в УС` visible for old documents even before a full deterministic remap runs; when Google reference catalogs are reachable, the normal exact mapped name still overrides the fallback.
- Added regression coverage for both cases: exact backfill through Google reference catalogs and local fallback rendering without mapped fields.

## [2026-07-05] intake | analyst screenshot on shared-sheet fill logic

- Registered `img_2.png` in `manifests/raw_sources.csv` as a new raw source with business-analyst feedback on the `Накладная` sheet output.
- Extracted new business constraints from the screenshot: `Грузоотправитель/Получатель` should not be guessed from the wrong company, unmatched products must set `Нет в справочнике`, `Основание` must not mirror `Форма документа`, and `Госсистема` / `Дата приема` remain later-stage fields.
- Captured additional open logic gaps: noisy fallback `Наименование товара в УС`, incomplete deterministic fill of `Цена в УС`, receipt-specific VAT handling, and a mismatch between backend assumptions and the live `Проверить` gate.

## [2026-07-05] planning | shared-sheet fill change plan

- Added `docs/wiki/google-sheet-fill-change-plan.md` with an ordered implementation plan for the next table-writing pass.
- Set the recommended sequence to semantic field mapping first, then row-level correction/fallback cleanup, then deterministic conversion completion, then receipt-specific handling, then live `Проверить`-gate diagnosis.

## [2026-07-05] analysis | workbook export 3 tied analyst remarks to concrete rows

- Registered `Копия АвтоСнаб Кафе Ромашка 3.xlsx` in `manifests/raw_sources.csv` and analyzed the latest `Накладная` export block-by-block.
- Confirmed that Lilia's remarks are visible directly in the workbook output: supplier-side documents still write buyer-like values into `Грузоотправитель/Получатель`, the UPD path sometimes copies document-form text into `Основание`, and receipt rows still leave `Цена в УС` and VAT columns empty.
- Found a concrete conversion inconsistency on the same `ТОРГ-12` document: one historical block keeps `3.954 кг -> 3.954 кг`, while another expands the same row to `15.634116` in `Кол-во в УС` and lowers `Цена в УС` accordingly.
- Confirmed that unmatched-product signaling is still inconsistent: at least one row shows `Товар найден в справочнике = Нет` while `Корректировка` remains `Другое` instead of `Нет в справочнике`.

## [2026-07-05] planning | code-level backlog for shared-sheet fix path

- Added `docs/wiki/google-sheet-fill-tech-backlog.md` as the executable backend backlog derived from the analyst screenshot plus workbook export 3.
- Bound the next implementation wave to concrete modules: `google_sheets_service.py`, `item_normalization_service.py`, `invoice_normalization_service.py`, `invoice_review_service.py`, and duplicate handling in `invoice_review.py`.
- Set P0 to semantic header mapping, deterministic `Нет в справочнике`, and stable `quantity_us`/`price_us`; P1 to receipt-specific logic and duplicate-key normalization; P2 to fallback-name cleanup and live `Проверить`-gate diagnosis.

## [2026-07-05] implementation | first backlog pass for shared-sheet correctness

- Added `shipper` to the review payload flow, taught OCR/MinerU normalization to carry it forward, and changed shared-sheet output so `Грузоотправитель` no longer falls back to `Грузополучатель`.
- Tightened shared-sheet and review-sheet correction normalization: rows with `product_found = Нет` now render `Нет в справочнике`, while ambiguous rows no longer silently degrade into `Другое`.
- Hardened document normalization: basis values that only repeat `УПД`/`ТОРГ-12` document-form text are cleared, receipt-like documents receive deterministic VAT defaults (`Без НДС`, `0`) when evidence is absent, and fallback product-name cleanup now strips more packaging/promo noise.
- Stabilized key parts of conversion and dedupe logic: weight-unit rows no longer auto-multiply themselves from OCR numbers embedded in the product text, and duplicate classification now canonicalizes invoice-number variants such as `UPMK...`/`УПМК...` and `ЧЕК 0245`/`0245`.
- Added focused regression coverage in `test_openai_invoice_pipeline.py`, `test_google_sheets_service.py`, and selected `test_receiving.py` cases; targeted suites now pass.

## [2026-07-05] planning | provider strategy for OCR and parser layers

- Added `docs/wiki/ocr-parser-provider-strategy.md` to capture the next architecture hypothesis for provider evolution.
- Fixed the target shape as `OCR / layout provider -> normalized evidence -> pluggable parser backend`, instead of binding one OCR stack to one LLM stack.
- Recorded `Yandex Vision OCR` as the strongest OCR candidate to evaluate next, with `YandexGPT` and `GigaChat` as parser-backend candidates to compare against the current OpenAI baseline on the same golden set.

## [2026-07-06] implementation | direct canonical `Накладная` builder for shared Google Sheets

- Replaced the primary shared-sheet write path with a native canonical `Накладная` row builder: shared Google Sheets output no longer depends primarily on the legacy `Накладные -> remap -> Накладная` translation route.
- Added `build_shared_invoice_rows(...)` and direct canonical row emission from normalized header/item review data while keeping the old register builder only as a compatibility layer for legacy review-sheet output.
- Updated shared-sheet insertion logic so `google_sheets_service.py` prefers already-built canonical shared rows when available and only falls back to the old remap path for compatibility.
- Added focused regression coverage for the new path in `backend/tests/test_google_sheets_service.py`, then re-ran targeted `test_receiving.py` cases covering supplier-INN safety and TORG-12 continuation-page cleanup.
- Fixed wiki status/gap-analysis pages so they now reflect the post-rewrite state: the main remaining issues are contract-centralization and field ownership, not the existence of a mandatory legacy remap stage.

## [2026-07-07] integration | over_version aligned to hardening branch

- Merged `codex/invoice-recognition-hardening` into the colleague-facing `over_version` line in an isolated worktree so the current local dirty tree was not disturbed.
- Resolved the only semantic conflicts in favor of the newer env-only credential model by keeping `.env` and `backend/secrets/oauth-token.json` out of Git on the merged branch.
- Added a small compatibility fix in the first-row header helper so missing newer keys such as `consignor` from older payload shapes now yield empty sheet values instead of `KeyError`.
- Verified the merged branch with targeted backend tests: `backend/tests/test_google_oauth_service.py`, `backend/tests/test_document_extraction_service.py`, and `backend/tests/test_google_sheets_service.py` all pass.

## [2026-07-09] integration | upstream over_version merged into active bot branch

- Merged `upstream/over_version` into `codex/bot-sbis-plan` with a single manual conflict resolution in `backend/app/routers/invoice_review.py`.
- Kept both change lines in the resolved upload flow: the bot ingestion/journal endpoints stay intact, and the newer colleague upload behavior also stays intact, including explicit `multipage_invoice` gating, client timezone propagation, compact selected-file UI, and upload polling UX changes.
- Explicitly dropped the tracked `autosnab_mvp.db` file from the merge result so branch-local SQLite contents were not inherited as if they were source code.
- Re-ran targeted verification after the merge: `pytest backend/tests/test_google_sheets_service.py -q` passed with 7 tests, and `python3 -m py_compile` succeeded for `backend/app/routers/invoice_review.py`, `backend/app/services/google_sheets_service.py`, and `backend/app/services/invoice_review_service.py`.

## [2026-07-09] bot | telegram workflow rebuilt around merged upload contract

- Deleted the earlier parallel bot workflow JSON artifacts and rebuilt the Telegram MVP around one import target: `n8n/telegram-bot-mvp.workflow.json`.
- Removed workflow dependence on `$env`: deployment-specific values now live in the opening `Workflow Config` node because the target `n8n` instance does not allow env reads in expressions or Code nodes.
- Kept the bot deliberately thin: it accumulates pages of one logical document, asks whether more pages will follow, finalizes with button `Продолжить`, uploads through `POST /api/v1/invoice-review/bot/upload-document-live`, polls `GET /api/v1/invoice-review/bot/uploads/{upload_id}`, and relays the backend result back to Telegram.
- Extended the bot status API contract so Telegram can stay thin at the finish step too: `BotUploadStatusResponse` now includes `document_summary`, `google_spreadsheet_url`, and `google_spreadsheet_error`.
- Added focused regression coverage for the new bot-summary backend helper in `backend/tests/test_bot_ingestion_service.py`.

## [2026-07-09] operations | local n8n workspace raised for direct workflow editing

- Started a persistent local `n8n` editor on `http://localhost:5678` in Docker container `autosnab_n8n_local`, mounted to the existing `~/.n8n` home so workflows and credentials survive restarts.
- Filled the local `n8n` Data Table layer directly in SQLite: table `telegram_bot_sessions` now exists with the expected bot-session columns and its backing storage table, so the MVP workflow can run without manual table creation in the UI.
- Imported the rebuilt Telegram MVP workflow into the same local `n8n` instance as draft `autosnab telegram bot mvp`, which means the next task can continue by editing the live workflow in the editor rather than only the JSON file in Git.
- Confirmed runtime connectivity across the intended local topology: the backend is reachable at `http://host.docker.internal:8000` from inside the `n8n` container and returns healthy status for the bot-facing endpoints.

## [2026-07-09] review | backend and bot coupling checked against real code

- Reviewed the actual backend/bot boundary in code instead of relying on the planning docs: `invoice_review.py`, `bot_ingestion_service.py`, `upload_trace_service.py`, and `n8n/telegram-bot-mvp.workflow.json`.
- Confirmed the main reason the structure feels too complex: one logical bot upload currently lives in three overlapping state stores at once, namely `ingestion_uploads`, the RAM-only upload trace, and `telegram_bot_sessions`.
- Confirmed that the "durable bot contract" is still only partial in runtime terms because final status enrichment depends on a daemon thread plus the in-memory trace store, while `n8n` also keeps full page binaries in its own Data Table row before finalize.
- Captured the concrete simplification target in `docs/wiki/backend-bot-integration-review.md`: move draft assembly and durable progress into backend, keep `n8n` as a thin Telegram transport/session router, and extract shared upload orchestration away from the monolithic router.

## [2026-07-09] cleanup | all n8n workflow artifacts deleted for a fresh rebuild

- Deleted the entire `n8n/` directory at the user's request: all workflow JSON variants, `README.md`, `telegram-bot-node-setup.md`, and `telegram_bot_sessions.csv`. Three of the JSON variants and the CSV were untracked, so this removal is not recoverable through Git history.
- Confirmed via `git log -- n8n/` that the tracked files' history remains available if needed, but the working tree now has no bot workflow at all.

## [2026-07-09] planning | fresh cloud-n8n bot plan with backend-owned draft state

- Added `docs/wiki/telegram-bot-cloud-n8n-plan.md` as the concrete plan for today's priority: a Telegram bot that replaces the web upload page for single/multi-page invoice scans, with all business logic staying in the FastAPI backend.
- Key architectural change from the deleted workflows: session/draft state is no longer stored in an `n8n` Data Table. It reuses the existing `ingestion_uploads` table with a new `collecting` status, so `n8n` needs zero business state and becomes a stateless Telegram router.
- Planned new backend endpoints: `POST /bot/drafts/pages`, `GET /bot/drafts/status`, `POST /bot/drafts/reset`, `POST /bot/drafts/finalize`, `GET /bot/uploads/latest`, all built on the existing `bot_ingestion_service.py` helpers and the existing `_process_bot_upload_background` pipeline.
- Flagged a real gap to close before going live: `/bot/*` endpoints have no auth today, and the deployment plan requires exposing them through a public `ngrok` tunnel; the plan adds a shared-secret header check.
- Marked `docs/wiki/n8n-bot-implementation-plan.md` as superseded for its session-storage design while keeping its UX/format sections as valid reference.
- This session produced a plan only; no backend code, tests, or `n8n` workflow were implemented yet.

## [2026-07-09] implementation | backend draft-session endpoints for the bot rebuild

- Implemented the backend half of `docs/wiki/telegram-bot-cloud-n8n-plan.md`: reused `ingestion_uploads` with a new `collecting` status instead of adding a new table.
- Added `backend/app/services/bot_ingestion_service.py` helpers `get_active_draft`, `list_draft_files`, `draft_display_name`, `append_draft_file`, `delete_draft`, `get_latest_upload_for_chat`.
- Added five router endpoints in `backend/app/routers/invoice_review.py` under `/bot/`: `POST drafts/pages`, `GET drafts/status`, `POST drafts/reset`, `POST drafts/finalize`, `GET uploads/latest`. Refactored shared logic out of the existing bulk endpoint into `_start_bot_processing(...)` and `_build_bot_upload_status_response(...)` so both old and new endpoints share one code path.
- Added `settings.bot_api_shared_secret` plus a `require_bot_api_key` dependency applied to all `/bot/*` routes (including the two pre-existing ones); documented the new `BOT_API_SHARED_SECRET` env var in `.env.example`. This closes the previously-flagged no-auth gap before exposing the backend through `ngrok`.
- Added an index on `IngestionUpload.chat_id` since it is now queried on every bot interaction.
- Added 8 new tests in `backend/tests/test_receiving.py` covering draft accumulation, per-chat isolation, reset, empty-finalize rejection, finalize-then-visible-via-`latest`, unsupported format, and 404-with-no-history. All pass. Confirmed via `git stash` that the file's pre-existing 10 failures are unchanged and unrelated to this work.
- Updated `docs/wiki/bot-backend-api-contract.md` with the new endpoint contracts and auth section.
- Not done yet: the actual cloud `n8n` workflow, local Docker + `ngrok` bring-up, and the smoke tests from the plan page.

## [2026-07-09] implementation | fresh stateless n8n workflow built against the draft-session backend contract

- Recreated `n8n/` and added `n8n/telegram-bot-mvp.workflow.json`: a single 29-node importable cloud-n8n workflow, hand-authored directly against the new `/bot/drafts/pages|status|reset|finalize` and `/bot/uploads/latest` endpoints.
- Design choices made for robustness across n8n versions, since this could not be test-imported live: every `IF` node uses one boolean-expression condition compared to `true` instead of relying on specific string/exists operator names; every text-reply step is a small `Code` node instead of a `Set` node, to avoid guessing at Set/Edit-Fields schema differences; `Finalize Draft` and `Check Latest Upload` use `onError: continueErrorOutput` for their error branch instead of a separate `IF` node; a single `Workflow Config` Code node is the only place the `ngrok` backend URL is hardcoded, referenced everywhere else via `$('Workflow Config').item.json.backendBaseUrl`.
- The workflow holds no session state itself: page uploads, the finalize step, and the bounded ~2-minute poll loop (`Prepare Poll` → `Wait Before Poll` → `Check Upload Status` → `If Poll Done`) all key off `chat_id` against the backend, matching the plan's "n8n as stateless router" goal.
- Added `n8n/telegram-bot-node-setup.md` (import steps, the two credentials to create — `Telegram Bot` and `Bot API Key` header-auth — and a checklist of parameters to verify after import) and a short `n8n/README.md` pointing back to the wiki plan/contract pages.
- Verified only what's checkable without a live n8n instance: valid JSON, 29 unique node names, and every `connections` edge resolves to an existing node. Real import/credential-wiring/execution has not been tested from this environment.
- Confirmed via `scripts/untracked_raw_check.py` that these new `n8n/*` files are correctly treated as code artifacts, not raw sources requiring manifest registration.

## [2026-07-09] verification | bot confirmed working end to end on cloud n8n

- The user brought up `docker compose --profile public-tunnel up --build`, retrieved the `ngrok` URL, imported `n8n/telegram-bot-mvp.workflow.json` into cloud `n8n`, and ran a real two-page invoice upload through Telegram.
- Backend logs and a direct `/bot/uploads/{upload_id}` check confirmed a clean run: 2 pages merged into 1 logical document, `google_drive_ocr` evidence collected (MinerU cleanly skipped due to incomplete local model cache, not an error), OpenAI structured parsing succeeded, reference mapping ran, and the Google Sheet was updated with a real spreadsheet URL. `completed: true`, `result_code: requires_review`.
- This is the first live confirmation that the backend draft/finalize/poll contract and the hand-authored n8n workflow work together correctly outside this environment.

## [2026-07-09] ux | stage-progress messages and a no-typing reply keyboard added to the bot

- User feedback: the bot should not require the operator to type anything, and should show intermediate processing status so a long-running upload doesn't look stuck.
- Added a persistent Telegram reply keyboard (`Готово` / `Статус` / `Сбросить`) to the workflow's shared **Send Reply** node — every bot reply now carries it, so the operator only ever taps buttons; typed text still works identically as a fallback.
- Added a 4-node stage-tracking sub-loop inside the existing poll (`Compute Stage` → `If Stage Changed` → `Set Stage Reply Text` → `Send Stage Update`, now 33 nodes total in `n8n/telegram-bot-mvp.workflow.json`) that turns the backend's existing `pipeline_logs` into one extra Telegram message whenever the coarse stage changes: принят в обработку → выгружаем данные → обрабатываем через ИИ → загружаем в таблицу → final result. No new backend state was needed; this reads the same `/bot/uploads/{id}` payload already used for polling, and the "last stage sent" is carried across loop iterations via `$('Set Stage Reply Text')` self-reference, the same n8n technique already used for the poll-attempt counter.
- Updated `n8n/telegram-bot-node-setup.md` with the new credential attachment (`Send Stage Update` also needs the `Telegram Bot` credential), an explanation of the stage-message sequence, and a flagged manual-fallback path for the reply-keyboard node, since its exact parameter schema is the one part of this change not yet confirmed against a live n8n import.

## [2026-07-09] fix | hand-authored reply-keyboard JSON removed after failed import

- Re-importing the updated workflow failed with `Could not find property option`, confirming the risk already flagged when the reply keyboard was added: the Telegram node's `replyMarkup`/`replyKeyboard` fields were placed as top-level node parameters in the JSON, which is not where that node type actually exposes them.
- Removed the guessed `replyMarkup`/`replyKeyboard` block from **Send Reply** in `n8n/telegram-bot-mvp.workflow.json` entirely rather than re-guessing the correct nesting; the workflow now imports clean (33 nodes, same stage-tracking sub-loop from the previous entry untouched).
- Updated `n8n/telegram-bot-node-setup.md` with exact manual steps to add the reply keyboard through the n8n editor UI (Additional Fields → Reply Markup → Reply Keyboard → two rows: `Готово`/`Статус`, then `Сбросить`), since the editor UI cannot produce invalid parameter JSON the way hand-authoring blind can.

## [2026-07-09] fix | Статус after Сбросить no longer reads as live news about the reset

- Registered root screenshot `img_4.png` in `manifests/raw_sources.csv` as `src_20260709_img4` before using it for diagnosis.
- Live test showed: `Сбросить` clears the draft correctly, but a following `Статус` then displayed the last *finished* upload's full result (supplier/invoice/sum/link) with no indication it was old news — reading as if it answered the just-cleared draft.
- Root cause was intentional fallback behavior (`Статус` with no open draft → `GET /bot/uploads/latest`), just missing a distinguishing label. Added a `Mark As Status Command` code node on that branch (`Check Latest Upload` success → `Mark As Status Command` → `Format Upload Result Message`, workflow now 34 nodes in `n8n/telegram-bot-mvp.workflow.json`) and prefixed the shared result-formatting message with `Активного черновика нет. Последний обработанный документ:` only on that path.
- Updated `n8n/telegram-bot-node-setup.md` with a section explaining this is expected fallback behavior, now clearly labeled.

## [2026-07-09] fix | workflow rebuilt from the user's own live n8n export, reply-keyboard bug root-caused

- The user pasted back their own current cloud-n8n export after manually configuring the reply keyboard through the editor UI (real credential IDs `buTTuJt7v20jFjXE`/`1inRkYns5Mj1ovhO`, real `backendBaseUrl`, real `webhookId`s) and asked for the `Mark As Status Command` fix to be layered onto that exact file without touching hardcoded values or structure.
- `n8n/telegram-bot-mvp.workflow.json` was rewritten from that pasted export plus the `Check Latest Upload` → `Mark As Status Command` → `Format Upload Result Message` rewiring and the `from_status_command` prefix in `Format Upload Result Message`'s `jsCode`. 34 nodes total; internal connection graph re-verified.
- This also resolved the earlier reply-keyboard mystery: the working export shows `replyMarkup: "replyKeyboard"` as a valid top-level parameter after all — the actual bug in the first hand-authored attempt was the nested key name (`values` instead of the correct **`buttons`**), plus a sibling `replyKeyboardOptions: {}`. Recorded the corrected shape in memory (`feedback_n8n_hand_authoring.md`) and removed the now-obsolete "add the keyboard manually" instructions from `n8n/telegram-bot-node-setup.md`.
- Established a working process for the remainder of this bot's iteration: the user tests live and pastes back their current export/screenshots when something looks off; fixes are layered onto that exact file rather than regenerated independently.

## [2026-07-09] docs | root README gets a full bot onboarding section

- Rewrote the "Публичный backend для cloud n8n" section of the root `README.md` into a full "Telegram-бот через облачный n8n" section aimed at a colleague setting this up cold: what to prepare (Docker, ngrok account/authtoken, Telegram bot token from `@BotFather`, cloud n8n account, OpenAI key, Google Cloud access), 8 numbered steps from `.env` prep through activation/smoke-tests, and a troubleshooting list (import errors, 401s, dead webhook after an `ngrok` restart).
- Cross-linked the deeper docs from there instead of duplicating them: `docs/wiki/telegram-bot-cloud-n8n-plan.md` for architecture rationale, `docs/wiki/bot-backend-api-contract.md` for the endpoint contract, `n8n/telegram-bot-node-setup.md` for node-by-node detail.

## [2026-07-09] bot | separate hardcoded fixed workflow artifact saved

- Registered the new Telegram screenshot `codex-clipboard-jumBaw.png` in `manifests/raw_sources.csv` before using it for diagnosis.
- Confirmed from that screenshot that the current editor workflow had imported broken Data Table settings: `Persist Session Row` lost its `chat_id` upsert match and failed with `At least one condition is required`.
- Saved a separate handoff artifact `n8n/telegram-bot-mvp.workflow.hardcoded-fixed.json` as a copy of the validated fixed workflow so the user can import a known-good bot JSON without losing the current hardcoded Telegram token, backend URL, or Telegram credential binding.

## [2026-07-09] operations | ngrok secrets filled and Docker MTU bug fixed

- Filled in `NGROK_AUTHTOKEN` and `BOT_API_SHARED_SECRET` in this workstation's `.env`, which were previously absent (only documented in `.env.example`), and brought up `docker compose --profile public-tunnel up`.
- Diagnosed a live `ERR_NGROK_3004` failure on **Send Page To Backend**: reproduced it independently with raw `curl` (small POST bodies succeeded, a multipart file upload failed identically to the n8n error), ruling out n8n/backend application code.
- Root cause: Docker's default bridge network MTU (1500) exceeded this machine's actual outbound path MTU (1376, from active VPN interface `amn0`), so larger multipart packets were silently dropped instead of fragmented. Fixed by adding a `networks.default` block to `docker-compose.yml` with `driver_opts: com.docker.network.driver.mtu: 1376`, then recreating the stack. Verified fixed with the same raw `curl` reproduction (`200 OK`, page accepted) before touching n8n again.
- Separately hit and fixed a `401 Неверный или отсутствующий X-Bot-Api-Key` on the same node: confirmed via `sha256sum` that the backend-side secret matched the value already given to the user, so the mismatch was in the n8n `Backend URL` HTTP Header Auth credential not being saved with the current value. Fixed by having the user re-enter and explicitly save it.
- User confirmed the bot works end to end again after both fixes.
