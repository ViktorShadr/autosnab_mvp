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
  strip-prefix config was sent back. Resolution not yet confirmed. **User
  decision, 2026-07-28**: leave the path-prefix/subdomain question alone for
  now — not pursuing it further with Alexander at this time.
- **Caddy scope decision, 2026-07-28**: this repo's production deploy target
  is Pavel's official server, routed by Alexander as above — Caddy is not
  and will not be needed here. `autosnab_mvp`'s own `caddy`
  service/`public-ip` Compose profile exists only for draft/test deploys on
  the user's personal VPS (`78.17.160.248`) and stays there for that
  purpose; it is not a step toward this repo's production path. See
  `docs/wiki/current-status.md` (2026-07-25 entry, "dropping this repo's own
  Caddy") in `autosnab_mvp` for the earlier reverted-removal attempt this
  decision supersedes for the `autosnab_mvp` side.
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
  **Confirmed isolated, not systemic** (checked the full `develop` pipeline
  history in the GitLab UI): `#532` (bot UI redesign merge, `1d7002f`) and
  `#529` (production-bugfixes merge, `1a48422`) both **Passed** all four
  stages a day earlier — so those two ports did deploy successfully. `#569`
  (this incident) is the only pipeline on `develop` that failed on the
  include-access error; an earlier `#525` failure on the same branch was an
  ordinary `ruff` lint failure, unrelated, fixed by the follow-up commits
  that became `1a48422`.
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
  `/reset` via `bot.set_my_commands`. **Confirmed deployed**: pipeline `#532`
  for this merge commit passed all four CI stages (build/lint/scan/deploy) —
  this is live in real production, even though `autosnab_mvp`'s own
  personal-VPS test deploy (`78.17.160.248`) never got this update
  (different, lower-priority target).
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

## Update, 2026-07-26 (later same day): all 3 phases merged into `develop`

Phases 1, 2, and 3 (MRs `!19`/`!20`/`!21`) were all reviewed and merged into
`develop` within about an hour of each other, same day they were opened —
confirmed via `git log origin/develop` (`04d30fe` is the Phase 3 merge
commit) and via GitLab pipeline history (`#595`, all 5 stages incl. deploy,
Passed). The "not yet ported" note below is stale as of this update; the
full packaging_facts/rule-engine port described in this page and in
[auto-snab-document-parser-porting-plan.md](./auto-snab-document-parser-porting-plan.md)
is now on `develop` in full.

## Deploy topology — real production readiness (2026-07-26)

A "is this ready for real users" audit turned up a much bigger structural
finding than the packaging_facts port itself:

- **`main` is a bare "Initial commit"** (`efb7fbc`), 53 commits behind
  `develop`. `.gitlab-ci.yml` was only ever added on `develop` and never
  merged up — `main` currently has **zero pipelines**, ever.
- The shared `deploy.yml` template (`antipov-devops/ci-templates`, owned by
  Aliaksandr Nikifarau) defines two deploy jobs:
  `deploy-dev` (`rules: if $CI_COMMIT_BRANCH == "develop"` — fully
  automatic, tag `dev`, uses the `ENV_DEV` GitLab CI/CD file variable,
  reloads `nginx-proxy-manager-dev`) and `deploy-prod` (`rules: if
  $CI_COMMIT_BRANCH == "main", when: manual` — tag `prod`, `ENV_PROD`,
  `nginx-proxy-manager-prod`).
- **Consequence: every merge to `develop` in this repo's history (SBIS,
  Diadoc, native bot, all bugfixes, the full packaging_facts port, the
  Postgres migration) has only ever automatically deployed to the DEV
  environment.** `deploy-prod` has never been able to run — not skipped,
  structurally impossible, since `main` never had a `.gitlab-ci.yml` to
  even show the manual button.
- **This DEV environment is what real users actually hit** at
  `avtosnab.testant.online/docparser/*` (confirmed: user had the upload
  page open the day before this audit) — despite the "dev" naming, this is
  the de facto production endpoint for real users today. There is no
  separately-verified "real prod" beyond this.
- Project-level GitLab CI/CD Variables (`Settings → CI/CD → Variables`):
  only **`ENV_DEV`** exists (File type). **No `ENV_PROD`**, no group-level
  variables. `YC_SA_KEY`/`YC_REGISTRY_BACK_ID` (used successfully by every
  deploy job) must be GitLab **instance**-level admin variables, invisible
  on this project's own settings page.

## Real production bug found and root-caused, 2026-07-26: 502 on `/docparser` after the Postgres-migration deploy

User reported the upload page 502'd today after working the day before —
correlates exactly with today's `deploy-dev` runs for the Postgres
migration merge (`#1945`) and the packaging_facts Phase 1-3 merges
(`#1971`). Two plausible code-level hypotheses were floated first (this
session guessed a `docker/docker-compose.yml` `env_file: .env` relative-path
resolution bug; a colleague guessed `DATABASE_URL` falling back to
`config.py`'s hardcoded `localhost:5432` default) — **both were wrong**.
Confirmed via a temporary manual debug CI job (see next section) that
pulled real `docker logs`:

```
psycopg2.OperationalError: connection to server at "c-c9q76fhi8q5o8e3hj2he.rw.mdb.yandexcloud.net" ...
port 6432 failed: certificate present, but not private key file "/app/.postgresql/postgresql.key"
```

**Root cause**: `ENV_DEV` (and the `ci-templates` README's own documented
guidance) sets `PGSSLCERT=/app/certs/root.crt`. `PGSSLCERT` in
libpq/psycopg2 is the **client certificate** parameter (needs a matching
`PGSSLKEY`); the CA root certificate for `verify-full` server verification
belongs in **`PGSSLROOTCERT`**, not `PGSSLCERT`. psycopg2 treated
`root.crt` as an offered client cert, found no matching private key, and
refused to connect. `backend/migrations/env.py` sources `sqlalchemy.url`
from `settings.database_url` (same value `alembic upgrade head` uses at
container start), and `backend/docker-entrypoint.sh` runs that migration
under `set -eu` before starting uvicorn — so the failed connection made the
container exit before ever binding port 8000, which is what OpenResty
reported as 502. Not related to today's merges' own code — a pre-existing
SSL variable-naming bug in the shared Postgres-migration/CI-templates setup
that this was simply the first real deploy to exercise. Reported to
Aliaksandr Nikifarau (owns `ci-templates`) with the fix (`PGSSLCERT` →
`PGSSLROOTCERT`) same day; not yet confirmed fixed.

**Recurrence confirmed, 2026-07-27**: after merging MR `!22` (the
`count_in_package` fix) into `develop`, `deploy-dev` pipeline `#602` showed
all 5 stages **Passed**, but `https://avtosnab.testant.online/docparser/health/runtime`
still returned a live `502 Bad Gateway` (the rest of `avtosnab.testant.online`,
e.g. `/catalog`, loads fine — isolated to the `docparser` service, not a
shared-domain outage). Re-ran the same temporary `debug-logs` technique
(see below) on a throwaway branch off `develop`: identical traceback,
identical root cause — `psycopg2.OperationalError: ... certificate present,
but not private key file "/app/.postgresql/postgresql.key"` from `alembic
upgrade head` at container startup. **Confirms the `PGSSLCERT`/`PGSSLROOTCERT`
fix reported to Aliaksandr on 2026-07-26 was never actually applied to
`ENV_DEV`** — this is not a regression from `!22`'s own code (which never
touches DB/SSL config), just the next deploy to hit the still-broken
variable. The `deploy-dev` CI job itself only verifies `docker run`
succeeded, not that the container stayed up past its entrypoint migration
— a green pipeline does not mean the service is actually reachable. Debug
branch deleted immediately after reading the logs, per the established
cleanup step. **Action needed**: ping Aliaksandr again — the fix was
reported but `ENV_DEV` still has the wrong variable name a day later.

**Aliaksandr replied, 2026-07-27**: asked (via Telegram) why a job was added
to the pipeline and why compose/docker files were changed, wanting
migrations to run in a separate container instead. Answered through the
native Telegram bot (a separate Claude session pointed at `autosnab_mvp`):
the job/compose changes came from the `feature/postgresql-migration` port
itself (`alembic upgrade head` in `docker-entrypoint.sh`,
`postgresql_validation` CI job) — the same change that introduced the
still-open `PGSSLCERT`/`PGSSLROOTCERT` bug above. User confirmed to him that
Alembic migrations are needed and asked him to split them into a separate
container as he suggested. No repo files changed by this exchange. Still
waiting on Aliaksandr for both the separate migration container and the
`ENV_DEV` fix.

**Fixed, 2026-07-28**: user reports Alexander (Aliaksandr Nikifarau) fixed
the 502. Verified independently, not just taken on report:
`curl -o /dev/null -w '%{http_code}' https://avtosnab.testant.online/docparser/health/runtime`
returns `200`. `ENV_DEV`'s `PGSSLCERT`→`PGSSLROOTCERT` fix is confirmed live.
The separate-migration-container ask (Aliaksandr's own proposal) is a
distinct, still-open item — not confirmed done, not blocking anything right
now since the health check passes.

## Dead `iiko` integration removed, MR `!23` (2026-07-27)

Following the same-day `autosnab_mvp` iiko removal (see that repo's
`docs/wiki/log.md`), user asked to port the change here too. **Important
difference discovered mid-port**: in `autosnab_mvp` iiko was already
unused/parallel code with a confirmed non-overlapping replacement (Marina's
separate iiko project). In this repo — which never went through
`autosnab_mvp`'s later redesign — iiko was still **live and wired into the
core pipeline**: `auto_fill_iiko_fields()` (from
`domains/iiko/services/iiko_reference_mapping_service.py`) ran on every
`create_invoice_review`/`update_invoice_review` call, pulling real supplier/
product/store/unit/tax catalogs from the iiko Server API (when
`IIKO_INTEGRATION_ENABLED=true`) to auto-map header/item fields, and the
confirm/send/preview flow (`build_iiko_preview`, `confirm_and_send_to_iiko`)
built a real iiko incoming-invoice XML payload. This was not dead code by
the same reasoning as `autosnab_mvp` — it was simply never exercised because
the integration flag defaults to `false`. Stopped mid-edit to confirm with
the user before continuing; **user confirmed iiko is definitely unused by
anyone here too**, so the same end-state was applied, function by function
rather than blanket-deleted:

- Deleted `domains/iiko/` (both services) and its dedicated test file
  (`test_incremental_reference_mapping.py`).
- `create_invoice_review`/`update_invoice_review` no longer call
  `auto_fill_iiko_fields`; header/item payloads used as-is (matches
  `autosnab_mvp`'s current shape exactly). `_merge_stored_iiko_metadata` →
  `_merge_stored_item_metadata` (same technical-field preservation across
  updates, iiko-only keys dropped — confirmed those keys were never actually
  set anywhere, i.e. already dead within the dead code).
- `get_iiko_reference_status`/`remap_review_with_iiko_references` and their
  two router endpoints (`/iiko/references/status`,
  `/{review_id}/iiko-auto-map`) removed outright — no other caller existed.
- `build_iiko_preview` → `build_review_preview`, `confirm_and_send_to_iiko` →
  `confirm_and_send`, `send_google_sheet_and_confirm_to_iiko` →
  `send_from_google_sheet`, `sync_sheet_and_confirm_to_iiko` →
  `sync_sheet_and_confirm` — renamed and de-iiko-ified (no more
  `iikoXml`/`iikoProductId`/`iikoSupplierId` in payloads,
  `AccountingExport.target_system` default `"iiko"` → `"review"`), matching
  `autosnab_mvp`'s already-renamed function names exactly.
- Schema: `ConfirmSendToIikoRequest` → `ConfirmSendRequest`; `iiko_*` fields
  dropped from all 4 `invoice_review` schemas. Kept `product_article`,
  `supplier_product`, `amount_unit`, `vat_percent`, `vat_sum`, `store_id`,
  `mapping_status`, `mapping_error` — verified via grep these are actually
  read by live sheet-building code (`_invoice_register_item_row` etc.), not
  iiko-specific despite the old Field descriptions referencing iiko XML tag
  names.
- `validate_review`'s iiko-header/mapping-status hard-block checks removed,
  matching `autosnab_mvp`'s already-live (less strict) validation behavior.
- Send-page HTML, the embedded Apps Script sample, and two Google-Sheets
  status messages de-iiko-ified to the exact wording `autosnab_mvp` uses.

Full suite: 238 passed, same 8 pre-existing `test_receiving.py` failures
(confirmed identical via `git stash` on this repo directly — safe here since
only this session's edits existed in the working tree) plus 2 pre-existing
skips, zero regressions. `pyflakes` clean on every touched file. Committed
(`3a945cc` on branch `fix/remove-dead-iiko-integration`), pushed, and MR
`!23` opened via the GitLab web UI logged in as `v.viktor.shadrin` (per the
2026-07-26 CI-actor-identity lesson). **Not merged** — merging to `develop`
auto-deploys to the real DEV environment, which is already down from the
unrelated `PGSSLCERT` bug above; left open for explicit go-ahead.

## Technique: temporary manual CI job for container logs without SSH (2026-07-26)

No SSH access to the dev host exists in this session (unlike `autosnab_mvp`'s
own VPS). Read-only container logs were obtained instead via a throwaway
GitLab CI job on a dedicated branch:
```yaml
debug-logs:
  extends: .deploy-common   # from the included deploy.yml — reuses existing YC/docker auth
  stage: deploy
  script:
    - docker logs --tail 200 "${CONTAINER_NAME}"
  when: manual
```
Works because the `dev`-tagged runner has the host's Docker socket mounted
(per `ci-templates`' own runner requirements). Purely read-only (`docker
logs`, no restart/stop/config change). Cleanup after use: "Erase job log"
button on the job page, then delete the branch — **GitLab's own
branch-delete-from-UI dropdown silently failed to take effect once in this
session** (page still showed the branch after reload); `git push origin
--delete <branch>` from the CLI worked immediately and is the more reliable
fallback. Reusable pattern for future infra questions on this repo that
don't warrant bothering DevOps first.

## Not yet ported (superseded — see "Update, 2026-07-26" above)

~~`packaging_facts`/`packaging_risk_flags` and the full Phase 1-3 rule-engine
redesign beyond Phase 1 above — deliberately deferred per user decision
(design was still moving in `autosnab_mvp` itself). Revisit once
`autosnab_mvp`'s own duplicate-rule cleanup and facts-sheet delivery are
fully stable (they are, as of 2026-07-26 — see `current-status.md`).~~

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

## Update, 2026-07-27: `count_in_package == quantity_document` fix ported, MR `!22` opened

User asked to bring this repo up to date after the same-day `autosnab_mvp`
fix for Lilia's Метро2.pdf report (Coca-Cola line, "Состав упаковки"
wrongly showing 72 шт — OpenAI misread the invoice table's quantity/unit
column as a `count_in_package` packaging fact). Confirmed via `git fetch` +
`git log` that `develop` here was otherwise fully current (all 3
`packaging_facts` phases already merged, no drift since the last audit) —
this was the only real gap.

Ported the identical fix onto branch `fix/count-in-package-quantity-document-conflation`
(off `develop`, commit `d09c745`): `item_normalization_service.py`'s
`_units_per_package_from_facts()` now takes `quantity_document` and drops a
`count_in_package` fact whose value exactly equals it; `openai_invoice_parser_service.py`'s
`SYSTEM_PROMPT` gained the same tightened instruction + Coca-Cola negative
example; same regression test ported into `test_openai_invoice_pipeline.py`.
Full suite: 246 passed / 2 skipped, same 8 pre-existing `test_receiving.py`
failures confirmed identical via `git stash` (zero regressions) — this
repo's domain-driven file layout differs from `autosnab_mvp`'s flat one but
the function bodies matched closely enough that the port was mechanical.

Pushed and opened MR `!22` **via the GitLab web UI, logged in as
`v.viktor.shadrin`** (not the API token) — deliberately following the
2026-07-26 CI-actor-identity lesson (`[[gitlab-ci-actor-identity-access]]`)
so the merge-request pipeline doesn't hit the same `ci-templates`
access-denied failure an API-token-triggered pipeline hit before. Pipeline
`#599` triggered. **Not merged** — merging `develop` here auto-deploys to
the DEV environment that real users actually hit at
`avtosnab.testant.online/docparser`, so this was left open for explicit
go-ahead rather than auto-merged.

## Update, 2026-07-28: re-verified GitLab CI/CD variables completeness

User asked directly whether all variables needed for the project to fully
function exist on GitLab. Re-checked live via the GitLab UI (not from
memory) rather than trusting the 2026-07-26 snapshot above:

- **Project-level `Settings → CI/CD → Variables`**: still only `ENV_DEV`
  (File, Protected). `ENV_PROD` still does not exist. Group-level
  (inherited) variables: still 0 — confirmed the page itself reports
  `Group variables (inherited): 0`.
- **`antipov-backend` group settings are not accessible** to this account
  (`/antipov-backend/-/settings/ci_cd` → 404) — consistent with `YC_SA_KEY`/
  `YC_REGISTRY_BACK_ID` living at GitLab **instance** admin level, invisible
  from here, same conclusion as 2026-07-26 (still unverifiable directly, but
  functionally proven working since `deploy-dev`/`build-image` keep
  succeeding).
- Read the actual template source to get the authoritative variable list
  instead of re-deriving it from memory: `ci-templates/deploy.yml` needs
  `IMAGE_NAME`/`CONTAINER_NAME` (repo `variables:`, present),
  `DEPLOY_PORT`/`CONTAINER_PORT`/`NETWORK_NAME` (optional, present),
  `NPM_CONTAINER_DEV`/`NPM_CONTAINER_PROD` (optional, unset — falls back to
  `nginx-proxy-manager-dev`/`-prod` defaults), `YC_SA_KEY` (instance-level,
  working), and `ENV_DEV`/`ENV_PROD` (file-type CI/CD vars). `docker-build.yml`
  needs only `IMAGE_NAME` + the same `YC_SA_KEY`. `security-scan.yml`
  (Code Quality/SAST/Secret Detection, MR-only) and `build-fastapi.yml`
  (test/lint) need **no extra GitLab-side variables** — both self-contained
  with in-file defaults.
- **`main` still has no `.gitlab-ci.yml`** — `blob/main/.gitlab-ci.yml`
  redirects to `tree/main`, which only has the bare `README.md`. This means
  `deploy-prod` (manual, `rules: if $CI_COMMIT_BRANCH == "main"`) is not
  just missing its `ENV_PROD` input, it's **structurally unreachable** —
  GitLab has no CI config on `main` to even show the manual job. Same
  finding as 2026-07-26, still true today.
- Re-confirmed the DEV endpoint real users hit is healthy right now:
  `curl https://avtosnab.testant.online/docparser/health/runtime` → `200`.

**Bottom line for "are all variables present": yes for the environment that
actually matters today** (`develop` → dev, the de facto production target) —
`ENV_DEV` + instance-level `YC_SA_KEY`/`YC_REGISTRY_BACK_ID` are all in place
and proven working. **No for a real prod path**: `ENV_PROD` is absent and
`main` has no CI config at all, so prod deploy is two structural steps away
(add `.gitlab-ci.yml` to `main`, add `ENV_PROD`), not a one-variable fix.
This has been a known, accepted gap since 2026-07-26 (`main` deploy was never
pursued) — not a new regression.

## Update, 2026-07-27 (same day): MR `!22` merged into `develop`

User confirmed to merge. Pipeline `#598` on the branch first failed at the
`lint` stage (`ruff format --check`) — this repo runs `ruff format` in CI,
`autosnab_mvp` does not, so the ported code needed two small reformats
(a long boolean condition, one long `PackagingFact(...)` call). Fixed
locally with a temporary `pip install --target ... ruff==0.16.0` (no ruff
installed in this environment otherwise), pushed as `71265eb2`. Re-run
pipelines `#600`/`#601` both passed (build, lint, `postgresql_validation`
test, and the built-in GitLab SAST/code-quality/secret-detection scans —
all slow on this runner's single concurrency slot, ~15 minutes total wall
time, but never actually stuck).

Clicking **Merge** first appeared to hang indefinitely ("Merging! Lift-off
in 5... 4... 3...") with no new commit landing on `develop` and the GitLab
instance itself returning a transient `500` on the MR/commits pages a few
minutes in — a real server-side hiccup on this self-hosted instance, not
something wrong with the MR itself. Reloading showed the MR back in a
"Ready to merge!" state (the stuck attempt had silently reset rather than
completed); clicking **Merge** again succeeded immediately. Merged as
`5a538f4b` into `develop`, source branch deleted. Confirmed via
`git fetch`/`git log origin/develop` from the local clone.

Since `deploy-dev` on `ci-templates` triggers automatically for any push to
`develop`, this merge is expected to auto-deploy to
`avtosnab.testant.online/docparser` (the real DEV environment real users
hit) — not separately verified live after the merge in this session.
