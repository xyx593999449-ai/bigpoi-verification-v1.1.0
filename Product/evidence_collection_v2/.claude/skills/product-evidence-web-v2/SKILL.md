---
name: product-evidence-web-v2
description: 面向 BigPOI 证据收集 v2 的 web 分支 skill。用于执行 websearch、webreader、review seed 生成、seed 校验与 reviewed 文件落盘，并输出标准 web 分支结果文件。
argument-hint: [input-poi-json-path] [run-id] [task-id] [workspace-root]
disable-model-invocation: true
---

# Product Evidence Web V2

## Goal

本 skill 只负责 `websearch + webreader` 分支，并把 reviewed 结果稳定落盘到 `output/runs/{run_id}/process/`。

本 skill 的正式分支产物不是 `evidence_*.json`，而是：

- `websearch-reviewed.json`
- `webreader-reviewed.json`（可为空）
- `web-branch-result.json`

## Runtime assets

使用以下正式脚本：

- `Product/evidence-collection/scripts/build_web_source_plan.py`
- `Product/evidence-collection/scripts/websearch_adapter.py`
- `Product/evidence-collection/scripts/prepare_websearch_review_input.py`
- `Product/evidence-collection/scripts/validate_websearch_review_seed.py`
- `Product/evidence-collection/scripts/write_websearch_review.py`
- `Product/evidence-collection/scripts/build_webreader_plan.py`
- `Product/evidence-collection/scripts/webreader_adapter.py`
- `Product/evidence-collection/scripts/prepare_webreader_review_input.py`
- `Product/evidence-collection/scripts/validate_webreader_review_seed.py`
- `Product/evidence-collection/scripts/write_webreader_review.py`

仅在需要生成 review seed 时读取：

- `Product/evidence-collection/prompts/websearch_review_extract.md`
- `Product/evidence-collection/prompts/webreader_extract.md`

## Input

参数顺序固定为：

1. `$0` = `input_poi_path`
2. `$1` = `run_id`
3. `$2` = `task_id`
4. `$3` = `workspace_root`

缺任何一个必要参数都直接报错。

## Execution steps

1. 解析：
   - `REPO_ROOT=$3`
   - `PROCESS_DIR=$REPO_ROOT/output/runs/$1/process`
2. 固定过程文件路径：
   - `web-plan.json`
   - `websearch-raw.json`
   - `websearch-debug.json`
   - `websearch-review-input.json`
   - `websearch-review-seed.json`
   - `websearch-reviewed.json`
   - `webreader-plan.json`
   - `webreader-raw.json`
   - `webreader-debug.json`
   - `webreader-review-input.json`
   - `webreader-review-seed.json`
   - `webreader-reviewed.json`
   - `web-branch-result.json`
3. 先运行 `build_web_source_plan.py` 生成 `web-plan.json`。
4. 运行 `websearch_adapter.py` 生成 `websearch-raw.json` 与 `websearch-debug.json`。
5. 如果 `websearch` 没有 query 或结果为空：
   - 跳过 websearch review
   - 继续尝试执行 `webreader plan`
6. 如果 `websearch` 有候选：
   - 运行 `prepare_websearch_review_input.py`
   - 读取 `websearch-review-input.json`
   - 参考 `prompts/websearch_review_extract.md` 生成 `websearch-review-seed.json`
   - review seed 必须逐条覆盖候选，不能用 `auto_generated`，`is_relevant=true` 时必须给出 `entity_relation` 与 `extracted.name`
   - 运行 `validate_websearch_review_seed.py`
   - 运行 `write_websearch_review.py`，产出 `websearch-reviewed.json`
7. 再运行 `build_webreader_plan.py`。
   - 如果已经有 `websearch-reviewed.json`，优先把它作为 `-WebSearchReviewedPath` 传入
8. 如果 `webreader plan` 的 `read_target_count=0`：
   - 跳过 `webreader`
9. 如果 `webreader` 需要执行：
   - 运行 `webreader_adapter.py`
   - 运行 `prepare_webreader_review_input.py`
   - 读取 `webreader-review-input.json`
   - 参考 `prompts/webreader_extract.md` 生成 `webreader-review-seed.json`
   - 运行 `validate_webreader_review_seed.py`
   - 运行 `write_webreader_review.py`，产出 `webreader-reviewed.json`
10. `webreader` 失败、超时或不可用时：
   - 不要阻断本分支
   - 继续保留 `websearch-reviewed.json` 作为 merge 输入
11. 最后写 `web-branch-result.json`，至少包含：

```json
{
  "status": "ok",
  "branch": "web",
  "run_id": "<run_id>",
  "task_id": "<task_id>",
  "web_plan_path": "<abs path>",
  "websearch_raw_path": "<abs path>",
  "websearch_reviewed_path": "<abs path or null>",
  "webreader_reviewed_path": "<abs path or null>",
  "websearch_merge_input_path": "<abs path or null>",
  "webreader_merge_input_path": "<abs path or null>"
}
```

12. 最终只返回 `web-branch-result.json` 中已经落盘的路径与摘要。

## Never do

- 不要把 `websearch-raw.json` 直接交给 merge
- 不要因为 `webreader` 失败就把整个 web 分支判成失败
- 不要输出自由格式网页摘要代替 reviewed JSON
