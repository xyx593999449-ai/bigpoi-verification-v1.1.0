---
name: evidence-collection-web
description: BigPOI 证据收集 web 分支 skill。用于网页搜索、网页读取、review seed 校验与 reviewed 结果落盘；优先使用内置 WebSearch 与 WebFetch，不可用时回退 Python 代理脚本。
disable-model-invocation: true
allowed-tools: Bash Read Write Edit Glob Grep LS WebSearch WebFetch
---

# Evidence Collection Web

## Goal

本 skill 只负责 `websearch + webreader` 分支，并把 reviewed 结果稳定落盘到 `output/runs/{run_id}/process/`。

正式分支产物不是 `evidence_*.json`，而是：

- `websearch-reviewed.json`
- `webreader-reviewed.json`（可为空）
- `web-branch-result.json`

## Runtime assets

优先使用内置联网工具：

- `WebSearch`
- `WebFetch`

不可用时回退以下脚本：

- `evidence-collection-web/scripts/build_web_source_plan.py`
- `evidence-collection-web/scripts/websearch_adapter.py`
- `evidence-collection-web/scripts/build_webreader_plan.py`
- `evidence-collection-web/scripts/webreader_adapter.py`
- `evidence-collection-web/scripts/prepare_websearch_review_input.py`
- `evidence-collection-web/scripts/validate_websearch_review_seed.py`
- `evidence-collection-web/scripts/write_websearch_review.py`
- `evidence-collection-web/scripts/prepare_webreader_review_input.py`
- `evidence-collection-web/scripts/validate_webreader_review_seed.py`
- `evidence-collection-web/scripts/write_webreader_review.py`
- `evidence-collection-web/scripts/write_web_branch_result.py`

提示词文件：

- `evidence-collection-web/prompts/websearch_review_extract.md`
- `evidence-collection-web/prompts/webreader_extract.md`

共享模块由以下路径提供：

- `evidence-collection/scripts/evidence_collection_common.py`
- `evidence-collection/scripts/run_context.py`

## Output contract

必须落盘：

- `output/runs/{run_id}/process/web-branch-result.json`

推荐同时落盘 review seed（由 worker 生成，供 review 脚本消费）：

- `output/runs/{run_id}/process/websearch-review-seed.json`
- `output/runs/{run_id}/process/webreader-review-seed.json`

至少包含：

- `status`
- `branch=web`
- `run_id`
- `task_id`
- `websearch_reviewed_path`
- `webreader_reviewed_path`
- `websearch_merge_input_path`
- `webreader_merge_input_path`

## Never do

- 不要把 `websearch-raw.json` 直接交给 merge
- 不要因为 `webreader` 失败就把整个 web 分支判成失败
- 不要输出自由格式网页摘要代替 reviewed JSON
