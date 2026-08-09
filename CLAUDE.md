# autosnab_mvp — Claude Rules

## Knowledge System
This project uses a wiki-first knowledge system. Knowledge lives in `docs/wiki/`, not in chat history.

### The knowledge base is now shared (symlink, not a local directory)
`docs/wiki/` and `manifests/` are no longer this repo's own content — they are
symlinks into the sibling directory `../autosnab-memory`
(`github.com/ViktorShadr/autosnab-memory`, private). This repo and
`auto-snab-document-parser` share the exact same knowledge base, so Viktor
(Claude Code) and Andrey (Codex) read/write the same source instead of two
drifting copies.

- **Before starting work**: `cd ../autosnab-memory && git pull` (clone it first
  if it isn't present: `git clone git@github.com:ViktorShadr/autosnab-memory.git ../autosnab-memory`).
- **After any wiki writeback**: commit and push from `../autosnab-memory`, not
  from this repo — this repo no longer tracks `docs/wiki`/`manifests` content at all.
- Every path below (`docs/wiki/index.md`, `manifests/raw_sources.csv`, etc.) is
  still read the normal way from this repo's root — the symlink is transparent
  to scripts and relative paths.

## Session Protocol (mandatory)

### Session Start
0. Run `python3 scripts/version_check.py` — check for LLM-wiki updates (silent if up to date)
1. Read `docs/wiki/index.md` — get the full page list
2. Read `docs/wiki/current-status.md` — know where things stand
3. Read `docs/wiki/log.md` — understand recent session history
4. Read additional wiki pages as needed for the current task

### During Work
- New decision made → update the relevant wiki page immediately
- **Any non-code file mentioned, received, referenced, or saved → check `manifests/raw_sources.csv` first. If not listed, register it before proceeding.** This includes PDFs, spreadsheets, screenshots, customer attachments, chat images, debug captures, CAD files, archives. This is the most commonly skipped step.
- Task completed → update `docs/wiki/current-status.md`

### Session End
1. Append one line to `docs/wiki/log.md`: date, topic, key outcomes
2. Update `docs/wiki/current-status.md` with latest state
3. If context is running low → generate `CONTINUATION-SUMMARY.md`

### Consistency
- If `current-status.md` conflicts with other wiki pages → trust the more specific page, then fix `current-status.md`
- If `log.md` is missing entries from before your session → don't guess, only append your own
- If two wiki pages contradict each other → flag it to the user, resolve before proceeding

### Token Budget
Normal operations are cheap. Full audit/recompilation are disaster recovery, not regular workflow.
- Session start: read 3 files (index, status, log). ~2K tokens. Never read all pages upfront.
- During work: read specific pages one at a time, only when needed.
- Structural checks: Python scripts (`wiki_check.py`, `raw_manifest_check.py`, `untracked_raw_check.py`, `stale_report.py`, `provenance_check.py`, `delta_compile.py`) — zero LLM tokens unless you choose to feed the draft output back into an LLM.
- If every session does incremental writeback, you never need full audit or recompilation.

### Rules
- compile-first: don't just answer, write conclusions into wiki pages
- writeback is mandatory: if you learned something durable, it goes in the wiki
- all non-code files are raw — PDFs, spreadsheets, images, screenshots, customer files, archives
- raw files stay outside Git, only manifests go in
- every wiki page (except index.md and log.md) must have YAML frontmatter with at least: title, source, created
