---
name: evidence-collection-map
description: BigPOI 证据收集图商分支 skill。用于内部图商代理、缺失图商补采、map review 校验与 reviewed 结果落盘。
allowed-tools: Bash Read Write Edit Glob Grep LS
---

# Evidence Collection Map

## Goal

本 skill 只负责图商分支，并把 reviewed 结果稳定落盘到 `output/runs/{run_id}/process/`。

正式分支产物不是 `evidence_*.json`，而是：

- `map-reviewed-internal-proxy.json` 或空候选场景下的 `map-raw-internal-proxy.json`
- `map-reviewed-fallback-<vendor>.json`
- `map-branch-result.json`

## Runtime assets

使用以下脚本：

- `evidence-collection-map/scripts/call_internal_proxy.py`
- `evidence-collection-map/scripts/call_map_vendor.py`
- `evidence-collection-map/scripts/prepare_map_review_input.py`
- `evidence-collection-map/scripts/validate_map_review_seed.py`
- `evidence-collection-map/scripts/write_map_relevance_review.py`
- `evidence-collection-map/scripts/write_map_branch_result.py`

提示词文件：

- `evidence-collection-map/prompts/map_relevance_review.md`

共享模块由以下路径提供：

- `evidence-collection/scripts/evidence_collection_common.py`
- `evidence-collection/scripts/run_context.py`

## Output contract

必须落盘：

- `output/runs/{run_id}/process/map-branch-result.json`

推荐同时落盘 review seed（由 worker 生成，供 review 脚本消费）：

- `output/runs/{run_id}/process/map-review-seed-internal-proxy.json`
- `output/runs/{run_id}/process/map-review-seed-fallback-{vendor}.json`

至少包含：

- `status`
- `branch=map`
- `run_id`
- `task_id`
- `internal_proxy_merge_input_path`
- `vendor_merge_input_paths`
- `missing_vendors`

## Never do

- 不要对未出现在 `missing_vendors` 中的 vendor 执行补采
- 不要把有候选但未经 reviewed gate 的 raw 图商结果直接交给 merge
- 不要把图商分支直接写成正式 `evidence_*.json`
