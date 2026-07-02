---
title: autosnab_mvp Current Status
source: session
created: 2026-07-02
tags: [status]
status: current
---

# autosnab_mvp Current Status

- Wiki bootstrap integrated into this repo on 2026-07-02.
- The knowledge base now lives under `docs/wiki/` in `autosnab_mvp`.
- Local raw-root created at `../autosnab_mvp_raw` for source documents outside Git.
- Next maintenance step: keep wiki writeback in sync with code changes and register any new raw files in `manifests/raw_sources.csv`.
- New SBIS EDO requirements were received on 2026-07-02 and compiled into `docs/wiki/sbis-edo-integration.md`.
- Additional screenshot intake on 2026-07-02 reinforced the centralized OCR/document-flow requirement and pointed to an existing Google Docs table named `АвтоСнаб Кафе Ромашка`.
- Architectural conclusion: SBIS EDO should be implemented as a source adapter over a shared document core, not wired directly into the current invoice-review flow.
- Parallel PDF export development means the shared document contract must be frozen early so the two tracks do not diverge.
- Final execution plan is now recorded in `docs/wiki/sbis-edo-integration.md`: freeze the contract, add SBIS as an adapter, keep the PDF flow unchanged, and validate both sources through one writer.
- New screenshot on 2026-07-03 updates delivery priority: MVP recognition/table placement this week, SBIS EDO next week.
- Meeting notes on 2026-07-03 add a nearer-term focus on multi-page document UX and parsing strategy before SBIS work starts.
