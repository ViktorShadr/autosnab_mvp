---
title: GitHub and Raw Strategy
source: session
created: 2026-07-02
tags: [strategy, git]
status: current
---

# GitHub and Raw Strategy

## 结论

- GitHub private repo 放：`code + wiki + manifests + verified_cases`
- 本地 raw 仓放：`pdf/xlsx/xls/rar/图片/客户原件`
- memory repo 放：编译后的长期记忆，不放 raw 本体

## 为什么

把全量 raw 塞进 Git，只会让仓库越来越肥，diff 也基本没用。

真正该版本化的是：

- 结论
- 规则
- 答案表
- 清晰的索引

不是一堆二进制原件。

## Branch Integration Plan For Colleague Repo

Target repo: `AndreyGomzikov/autosnab_mvp`

### Goal

Publish the advanced `codex/invoice-recognition-hardening` work into the
colleague-owned repo without dragging local DB/CSV/raw artifacts into Git and
without starting from a blind full merge into `main`.

### Ground rules

- Work through a branch/PR flow, not direct commits to `main`.
- Keep raw files, local DBs, generated CSV exports, and uploads out of the
  integration commit set.
- Treat `main` as a donor for any still-useful multi-page OCR details, not as
  the architectural source of truth.
- Prefer selective conflict resolution over a large automatic merge.

### Recommended sequence

1. Keep the active implementation branch in the local repo:
   `codex/invoice-recognition-hardening`.
2. Push that branch to the author's fork (`origin`) first.
3. Request collaborator `write` access to
   `AndreyGomzikov/autosnab_mvp` only if direct branch publishing in the
   colleague repo is operationally useful.
4. Open a PR from
   `ViktorShadr:codex/invoice-recognition-hardening` into
   `AndreyGomzikov/autosnab_mvp:main`.
5. In the PR description, state explicitly that:
   - the branch already contains the newer multi-page document model;
   - `main` still has older `multipage_invoice` flow and some TORG-12
     continuation-page heuristics;
   - merge must preserve the newer document-extraction architecture.
6. Resolve conflicts manually in this order:
   - `backend/app/config.py`
   - `backend/app/routers/invoice_review.py`
   - `backend/app/services/document_extraction_service.py`
   - `backend/app/services/ocr_service.py`
   - `backend/app/services/invoice_review_service.py`
   - `backend/app/services/google_sheets_service.py`
   - tests
   - docs / README / env examples
7. During conflict resolution:
   - keep the hardening branch as the default winner for upload flow,
     evidence model, OpenAI parsing, normalization, and sheet writing;
   - inspect `main` only for any continuation-page / OCR details that are still
     absent;
   - do not restore the older checkbox-driven `multipage_invoice` flow if the
     newer logical multi-page upload flow already covers the same business case.
8. Before merge approval, run targeted verification for:
   - multi-page invoice grouping;
   - TORG-12 continuation-page behavior;
   - shared-sheet output invariants;
   - duplicate and normalization regressions.
9. Merge only after the PR branch is clean of local artifacts and all required
   manual conflict decisions are documented in the PR.

### Decision rule

If the PR review shows that `main` contributes no critical behavior missing from
`codex/invoice-recognition-hardening`, then do not perform a second large merge
from `main` into the hardening branch first. Let the PR itself be the
integration point.

## Second Target Repo: GitLab `auto-snab-document-parser`

- Target: `https://gitlab.testant.online/antipov-backend/auto-snab-document-parser`
  (self-hosted GitLab CE).
- Confirmed on 2026-07-20: this is an **empty scaffold repo** — one `Initial
  commit`, only the GitLab-generated default `README.md`, no code, no
  `.gitlab-ci.yml`. `main` and `develop` both point at the same commit. There
  is no existing content to reconcile; the finished project will be pushed
  into it later, not merged against prior work.
- Network access note: SSH is not reachable from this workstation for this
  host — port 22 times out, and port 443 serves plain HTTPS (openresty), not
  SSH-over-443/altssh. HTTPS + a GitLab Personal Access Token
  (`oauth2:<token>@gitlab.testant.online/...`) is therefore the only viable
  access path from here, not SSH keys.
- When the finished project is ready to push here: exclude local artifacts the
  same way as the GitHub plan above (`autosnab_mvp.db`, `.env`, raw
  exports/uploads) and confirm with the user which branch (`main` vs
  `develop`) and which source branch (`over_version` vs a squashed snapshot)
  should be published.
- Push auth is configured on this workstation as of 2026-07-20: global
  `git config credential.helper store` persists the GitLab PAT in
  `~/.git-credentials` (mode 600), verified working for both read
  (`git ls-remote`) and write (`git push --dry-run origin develop` authenticated
  successfully) against this repo. No token re-entry is needed for future
  push/pull on this machine unless the token is rotated or revoked — if the
  user mentioned revoking the token shared in chat earlier, the stored
  credential must be refreshed with the new token afterward.
