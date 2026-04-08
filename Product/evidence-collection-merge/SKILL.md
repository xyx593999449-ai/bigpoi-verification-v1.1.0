---
name: evidence-collection-merge
description: BigPOI 证据收集合并 skill。用于读取 web 和 map 分支结果，执行 reviewed-only merge，并写出正式 evidence 文件。
allowed-tools: Bash Read Write Edit Glob Grep LS
---

# Evidence Collection Merge

## Goal

本 skill 只负责：

1. 读取 `web-branch-result.json` 与 `map-branch-result.json`
2. 调用 reviewed-only merge 脚本
3. 调用正式 evidence 写出脚本
4. 返回 `evidence_path`

## Runtime assets

使用以下脚本：

- `evidence-collection-merge/scripts/merge_evidence_collection_outputs.py`
- `evidence-collection-merge/scripts/write_evidence_output.py`

共享模块由以下路径提供：

- `evidence-collection/scripts/evidence_collection_common.py`
- `evidence-collection/scripts/run_context.py`

## Output contract

必须落盘：

- `output/runs/{run_id}/process/evidence-merge-result.json`

至少包含：

- `status`
- `run_id`
- `task_id`
- `collector_merged_path`
- `evidence_path`

## Never do

- 不要绕过 `merge_evidence_collection_outputs.py` 手工拼 evidence
- 不要让 merge skill 自己重新执行 web 或 map 采集
- 不要把 `collector-merged.json` 当成正式 evidence 对外返回
