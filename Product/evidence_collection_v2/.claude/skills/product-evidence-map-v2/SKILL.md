---
name: product-evidence-map-v2
description: 面向 BigPOI 证据收集 v2 的图商分支 skill。用于执行内部图商代理、缺失图商补采、map review seed 生成与校验，并输出标准 map 分支结果文件。
argument-hint: [input-poi-json-path] [run-id] [task-id] [workspace-root]
disable-model-invocation: true
---

# Product Evidence Map V2

## Goal

本 skill 只负责图商分支，并把 reviewed 结果稳定落盘到 `output/runs/{run_id}/process/`。

本 skill 的正式分支产物不是 `evidence_*.json`，而是：

- `map-reviewed-internal-proxy.json` 或无候选场景下的 `map-raw-internal-proxy.json`
- `map-reviewed-fallback-<vendor>.json`
- `map-branch-result.json`

## Runtime assets

使用以下正式脚本：

- `Product/evidence-collection/scripts/call_internal_proxy.py`
- `Product/evidence-collection/scripts/prepare_map_review_input.py`
- `Product/evidence-collection/scripts/validate_map_review_seed.py`
- `Product/evidence-collection/scripts/write_map_relevance_review.py`
- `Product/evidence-collection/scripts/call_map_vendor.py`

仅在需要生成 review seed 时读取：

- `Product/evidence-collection/prompts/map_relevance_review.md`

## Input

参数顺序固定为：

1. `$0` = `input_poi_path`
2. `$1` = `run_id`
3. `$2` = `task_id`
4. `$3` = `workspace_root`

缺任何一个必要参数都直接报错。

## Execution steps

1. 读取输入 POI，至少拿到：
   - `id`
   - `name`
   - `city`
2. 解析：
   - `REPO_ROOT=$3`
   - `PROCESS_DIR=$REPO_ROOT/output/runs/$1/process`
3. 固定过程文件路径：
   - `map-raw-internal-proxy.json`
   - `map-review-input-internal-proxy.json`
   - `map-review-seed-internal-proxy.json`
   - `map-reviewed-internal-proxy.json`
   - `map-raw-fallback-<vendor>.json`
   - `map-review-input-fallback-<vendor>.json`
   - `map-review-seed-fallback-<vendor>.json`
   - `map-reviewed-fallback-<vendor>.json`
   - `map-branch-result.json`
4. 先运行 `call_internal_proxy.py` 获取内部图商代理原始结果。
5. 如果内部图商代理存在候选：
   - 运行 `prepare_map_review_input.py`
   - 读取 `map-review-input-internal-proxy.json`
   - 参考 `prompts/map_relevance_review.md` 生成 `map-review-seed-internal-proxy.json`
   - review seed 必须逐条覆盖候选，不允许只保留 `keep_candidates`
   - 不允许 `auto_generated` 或全量兜底放行
   - 运行 `validate_map_review_seed.py`
   - 运行 `write_map_relevance_review.py`，产出 `map-reviewed-internal-proxy.json`
6. 检查 `missing_vendors`。
   - 只有 `missing_vendors` 中出现的 vendor 才允许补采
7. 对每个缺失 vendor：
   - 运行 `call_map_vendor.py`
   - 如果补采结果有候选，再执行 `prepare -> seed -> validate -> write reviewed`
   - reviewed 输出文件必须命名为 `map-reviewed-fallback-<vendor>.json`
8. 写 `map-branch-result.json`，至少包含：

```json
{
  "status": "ok",
  "branch": "map",
  "run_id": "<run_id>",
  "task_id": "<task_id>",
  "internal_proxy_raw_path": "<abs path>",
  "internal_proxy_reviewed_path": "<abs path or null>",
  "internal_proxy_merge_input_path": "<abs path>",
  "vendor_reviewed_paths": ["<abs path>"],
  "vendor_merge_input_paths": ["<abs path>"],
  "missing_vendors": ["amap", "bmap", "qmap"]
}
```

9. `internal_proxy_merge_input_path` 规则：
   - 内部图商有候选且 reviewed 成功时，使用 `map-reviewed-internal-proxy.json`
   - 内部图商没有候选时，允许保留 `map-raw-internal-proxy.json` 作为“空候选 merge 输入”
10. 最终只返回 `map-branch-result.json` 中已经落盘的路径与摘要。

## Never do

- 不要对未出现在 `missing_vendors` 中的 vendor 执行补采
- 不要把有候选但未经 reviewed gate 的 raw 图商结果直接交给 merge
- 不要把图商分支直接写成正式 `evidence_*.json`
