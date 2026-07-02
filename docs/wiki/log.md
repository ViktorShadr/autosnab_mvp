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
