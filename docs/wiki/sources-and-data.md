---
title: Sources and Data
source: session
created: 2026-07-02
tags: [data, raw]
status: current
---

# autosnab_mvp Sources and Data

原始资料默认放在本地 raw 根目录，不直接进 Git。

raw 根目录建议：

```text
../autosnab_mvp_raw/
```

GitHub 里只保留 manifest 和编译结果。

少量 raw 可以手工登记；新文件一多，直接跑：

```bash
python3 scripts/ingest_raw.py
python3 scripts/stale_report.py
python3 scripts/delta_compile.py --write-drafts
```

前者把本地 raw 编成 manifest + lock + intake report，第二个告诉你哪些 wiki 页面已经 stale，第三个只生成手动草稿，不会偷偷覆盖现有 wiki。

## Local inbox on this PC

On this machine, the wiki raw-root is initialized at:

```text
../autosnab_mvp_raw/
```

New attachments for LLM wiki intake should be dropped into:

```text
../autosnab_mvp_raw/inbox/
```

After adding files, register them with:

```bash
python3 scripts/ingest_raw.py --raw-root ../autosnab_mvp_raw
```

Note: the current manifest references older inbox files that are not present on this PC yet. Until those historical raw files are restored into the same raw-root, `raw_manifest_check.py` will report them as missing.
