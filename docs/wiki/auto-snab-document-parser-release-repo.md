---
title: auto-snab-document-parser — release repo status
source: session
created: 2026-07-26
tags: [auto-snab-document-parser, gitlab, deploy, port]
status: current
---

# `auto-snab-document-parser` — release repo status

## What this is

`auto-snab-document-parser` (GitLab: `gitlab.testant.online/antipov-backend/auto-snab-document-parser`,
local clone at `~/PycharmProjects/auto-snab-document-parser`) is the **actual
production push target** for this project — not `autosnab_mvp`. It's a
domain-driven rewrite (`backend/app/domains/{invoice_pipeline,edo_diadoc,
edo_sbis,google_workspace,iiko,accounting_backoffice}` + native
`telegram_bot`), maintained by another engineer (`antipov-backend` on
GitLab), on branch `develop`. `autosnab_mvp` is the working/session repo
where fixes are developed first; durable fixes get deliberately ported over,
adapted to the different file layout.

**This page is the source of truth for that repo's status.** Before
answering "what's pending in `auto-snab-document-parser`", re-verify with
`git -C ~/PycharmProjects/auto-snab-document-parser fetch --all && git log
origin/develop --oneline -20` rather than trusting this snapshot — both
repos keep moving and this page will go stale exactly like the private-memory
version of this note did on 2026-07-26 (see "Correction" below).

## Deploy infra

- Own GitLab CI (`.gitlab-ci.yml`, includes `antipov-devops/ci-templates`:
  build-fastapi / security-scan / docker-build / deploy stages), pushes to
  Yandex Cloud Registry (`YC_REGISTRY_BACK_ID`), deploys via
  `docker/docker-compose.yml` (not the root one, which is a dead leftover
  copied from `autosnab_mvp`) — container `auto-snab-docparser` on external
  Docker network `auto-snab`, `DEPLOY_PORT=8001` → `CONTAINER_PORT=8000`.
  **No Caddy anywhere in this path.**
- Uses Postgres, not SQLite (`PGSSLMODE=require`, cert baked into the image
  at `docker/certs/root.crt`). MinerU is fully removed from the codebase.
- Production domain `avtosnab.testant.online` is shared across multiple
  unrelated microservices, owned/routed by Alexander (controls the
  gateway/pipeline, not this codebase). A path prefix `/docparser` was
  agreed (not a subdomain) — first live attempt 404'd because the gateway
  wasn't stripping the prefix before forwarding to port 8001; nginx/Traefik
  strip-prefix config was sent back. Resolution not yet confirmed.
- **CI currently blocked (2026-07-26):** pipeline `#569` for `develop`
  (commit `8874799`) cannot resolve the external include project
  `antipov-devops/ci-templates`, producing "project not found or access
  denied" before any job is created. The pipeline editor still reports YAML
  syntax as correct; that check does not validate authorization to fetch a
  remote include. DevOps must verify the template project's path/existence,
  its `main` branch and template files, and access for the pipeline trigger
  or consuming project.
  A browser check under the current account confirms the private template
  project, its `main` branch, and all four referenced files exist. Thus the
  most likely cause is that this particular pipeline was triggered under a
  different GitLab identity/token without access, or that the template
  project's CI include authorization is not granted to the consumer project.
  **Resolved by verification:** a fresh manual run `#578`, created by
  `v.viktor.shadrin` for the identical `develop` commit `8874799`, created
  all four jobs successfully. The include is accessible now; no CI YAML or
  DevOps change is required for this incident. Monitor the jobs themselves
  separately for ordinary build/deploy failures.
- `env.prod` convention: a gitignored plaintext `.env` snapshot in both
  repos. Pull the real working one from the VPS
  (`ssh root@78.17.160.248 'cat /opt/autosnab_mvp/.env'`), don't trust
  whatever's sitting locally. When adapting for this repo: keep secrets
  as-is, rewrite `PUBLIC_API_BASE_URL`/`GOOGLE_OAUTH_REDIRECT_URI` to the
  `avtosnab.testant.online/docparser/...` path (re-register the redirect
  URI in Google Cloud Console or it 401s), add
  `DATABASE_URL`/`PGSSLMODE`/`PGSSLCERT` (real `DATABASE_URL` must come from
  Alexander), drop vars this repo doesn't use (`MINERU_*`, `PUBLIC_DOMAIN`,
  `CADDY_HTTPS_HOST_PORT`, `NGROK_AUTHTOKEN`, `BACKEND_MEM_LIMIT`). Never
  paste secret values into chat/tool-call text — use
  `grep -oE '^[A-Z0-9_]+='` for key-name-only comparisons.

## Ported so far (confirmed via direct `git log`, 2026-07-26)

- **`fix/invoice-pipeline-production-bugs` (`5e894e1`) → merged `develop`
  (`1a48422`), then MR `!12`/`!13`**: `telegram_bot_max_poll_attempts` 24→120,
  `document_form` canonicalization `or`-short-circuit fix + widened УПД
  regex, shared-sheet writer switched to name-keyed dict projection instead
  of positional.
- **`fix/bot-ui-inline-buttons-and-progress-edit` (`41fe6a1`) → merged
  `develop` (`1d7002f`)**: poll-loop progress message now edits in place
  per stage instead of sending a new message each time; permanent
  `ReplyKeyboardMarkup` replaced with contextual inline buttons
  (`DRAFT_ACTIONS_KEYBOARD`, `sheet_link_keyboard`) plus `/done`/`/status`/
  `/reset` via `bot.set_my_commands`. **This is already live in `develop`
  with a real CI deploy stage behind it — most likely already in real
  production**, even though `autosnab_mvp`'s own personal-VPS test deploy
  (`78.17.160.248`) never got this update (different, lower-priority target).
- **`fix/quantity-us-passthrough` (`5824f7d`) → MR `!17` → merged `develop`
  (`8874799`)**: `Кол-во в УС`/`Цена в УС` in the shared-sheet row always
  written as the raw document quantity/price, not a `quantity_multiplier`-
  computed value — mirrors the same-day `autosnab_mvp` fix (Apps Script
  alone owns the final number, Lilia's 2026-07-25 decision). Merged
  2026-07-26 via GitLab REST API.
- **`feature/packaging-facts-phase1-schema` (`b1c0f71`)**: Phase 1 of the
  `packaging_facts`/rule-engine port (see
  [auto-snab-document-parser-porting-plan.md](./auto-snab-document-parser-porting-plan.md)).
  **Pushed to GitLab, not merged into `develop`, no MR opened yet.**

## Guiding constraint — do not violate

Do not reintroduce backend-computed authoritative `Кол-во в УС`/`Цена в УС`
anywhere in future ports. That was deliberately simplified to a raw
passthrough in both repos because Google Apps Script alone computes the
final authoritative quantity now.

## Not yet ported

`packaging_facts`/`packaging_risk_flags` and the full Phase 1-3 rule-engine
redesign beyond Phase 1 above — deliberately deferred per user decision
(design was still moving in `autosnab_mvp` itself). Revisit once
`autosnab_mvp`'s own duplicate-rule cleanup and facts-sheet delivery are
fully stable (they are, as of 2026-07-26 — see `current-status.md`).

## Other `develop`-branch state not driven from `autosnab_mvp` (2026-07-26)

`origin/develop`'s tip has moved past all of the above with unrelated infra
work this repo's wiki doesn't track in detail: a `DEVOPS-1` branch (GitLab
CI pipeline, output masking) merged into `develop`, a
`feature/postgresql-migration` branch (`b49af9a` "Migrate database to
PostgreSQL", not yet confirmed merged into `develop`), a ruff lint pass, and
docker persistent-volume/psql-cert fixes. Treat these as informational only
— re-check `git log origin/develop` before relying on specifics.

## Correction, 2026-07-26

Earlier, this repo's status lived only in a private Claude memory file
(`auto-snab-document-parser-release-repo.md`), not in `docs/wiki/`. That
caused a real mistake in a same-day session: `autosnab_mvp`'s own
`n8n-to-native-bot-migration-plan.md` says the bot UI redesign was "not yet
deployed to the VPS", which was read as "not deployed anywhere" — but it was
already merged into `auto-snab-document-parser`'s `develop` (the real
production repo) the day before. This page exists specifically so that
status is git-tracked and available from any workstation after `git pull`,
instead of trapped in one machine's local Claude memory.
