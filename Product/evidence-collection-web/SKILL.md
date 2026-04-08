---
name: evidence-collection-web
description: BigPOI 证据收集 web 分支 skill。用于网页搜索、网页读取、review seed 校验与 reviewed 结果落盘；优先使用内置 WebSearch 与 WebFetch，不可用时回退 Python 代理脚本。
allowed-tools: Bash Read Write Edit Glob Grep LS WebSearch WebFetch
---

# Evidence Collection Web

## Goal

本 skill 只负责 `websearch + webreader` 分支，并把 reviewed 结果稳定落盘到 `output/runs/{run_id}/process/`。

正式分支产物不是 `evidence_*.json`，而是：

- `websearch-reviewed.json`
- `webreader-reviewed.json`（可为空）
- `web-branch-result.json`

本 skill 不是“给模型一组脚本自己发挥”，而是固定执行以下 web 分支流程：

1. 读取运行上下文与输入 POI。
2. 生成 `web-plan.json`。
3. 根据 `web-plan.json` 执行 `websearch` 或直接跳过。
4. 为 `websearch` 结果生成 review input，并写出 `websearch-review-seed.json`。
5. 校验 seed 后写出 `websearch-reviewed.json`。
6. 基于 `web-plan.json` 和 `websearch-reviewed.json` 生成 `webreader-plan.json`。
7. 执行 `webreader` 或直接跳过。
8. 为 `webreader` 结果生成 review input，并写出 `webreader-review-seed.json`。
9. 校验 seed 后写出 `webreader-reviewed.json`。
10. 最后统一写出 `web-branch-result.json`，供 merge skill 使用。

## Input contract

worker 运行时至少要能从输入里拿到以下字段：

- `input_poi_path`
- `run_id`
- `task_id`
- `workspace_root`
- `process_dir`

如上字段存在，应统一把过程文件写入：

- `output/runs/{run_id}/process/`

## Required workflow

必须按以下顺序执行，不要自行重排：

1. 执行 `evidence-collection-web/scripts/build_web_source_plan.py`
   - 输入：`input_poi_path`
   - 输出：`web-plan.json`
   - 目标：得到 `search_queries` 与 `direct_read_sources`

2. 处理 `websearch`
   - 若 `web-plan.json.search_queries` 为空或数量为 0：
     - 跳过 `websearch`
     - 不要伪造 `websearch-reviewed.json`
   - 若 `search_queries` 非空：
     - 优先用内置 `WebSearch`
     - 内置能力不可用时，回退 `evidence-collection-web/scripts/websearch_adapter.py`
     - 原始结果写到 `websearch-raw.json`

3. 处理 `websearch review`
   - 若 `websearch-raw.json` 有候选结果：
     - 执行 `evidence-collection-web/scripts/prepare_websearch_review_input.py`
     - 依据 `evidence-collection-web/prompts/websearch_review_extract.md` 生成 `websearch-review-seed.json`
     - 执行 `evidence-collection-web/scripts/validate_websearch_review_seed.py`
     - 执行 `evidence-collection-web/scripts/write_websearch_review.py`
     - 输出 `websearch-reviewed.json`
   - 若 `websearch` 无候选结果：
     - 可以不生成 `websearch-reviewed.json`
     - 分支最终仍可为 `empty`

4. 执行 `evidence-collection-web/scripts/build_webreader_plan.py`
   - 输入：`web-plan.json`
   - 若存在 `websearch-reviewed.json`，应一并传入
   - 输出：`webreader-plan.json`

5. 处理 `webreader`
   - 若 `webreader-plan.json.read_target_count` 为 0：
     - 跳过 `webreader`
   - 若大于 0：
     - 优先用内置 `WebFetch`
     - 内置能力不可用时，回退 `evidence-collection-web/scripts/webreader_adapter.py`
     - 原始结果写到 `webreader-raw.json`

6. 处理 `webreader review`
   - 若 `webreader-raw.json` 有候选结果：
     - 执行 `evidence-collection-web/scripts/prepare_webreader_review_input.py`
     - 依据 `evidence-collection-web/prompts/webreader_extract.md` 生成 `webreader-review-seed.json`
     - 执行 `evidence-collection-web/scripts/validate_webreader_review_seed.py`
     - 执行 `evidence-collection-web/scripts/write_webreader_review.py`
     - 输出 `webreader-reviewed.json`
   - 若 `webreader` 无候选结果：
     - 可以不生成 `webreader-reviewed.json`

7. 最后执行 `evidence-collection-web/scripts/write_web_branch_result.py`
   - 统一汇总：
     - `websearch-reviewed.json`
     - `webreader-reviewed.json`
     - `websearch-review-seed.json`
     - `webreader-review-seed.json`
   - 输出唯一正式分支结果：`web-branch-result.json`

## Review seed contract

review seed 必须由当前 worker 显式写出，不能只在自然语言里“说明已经 review 完成”。

必须写出的 seed：

- `output/runs/{run_id}/process/websearch-review-seed.json`
- `output/runs/{run_id}/process/webreader-review-seed.json`

若有 review input 但缺 seed：

- 应停止继续写 reviewed 文件
- 应给出可执行错误提示，并指出对应的 `review_input_path`

## Status rules

`web-branch-result.json.status` 只允许以下含义：

- `ok`
  - 至少有一个 mergeable reviewed 文件存在
- `empty`
  - `websearch` 与 `webreader` 都没有可归并结果，但流程本身是正常结束的
- `error`
  - 关键步骤失败，导致无法给 merge 提供可信分支结果

特别约束：

- `webreader` 失败或无结果，不应自动把整个 web 分支判成 `error`
- 只有当 `websearch`、`webreader` 都无法形成合法分支结果，且流程异常中断时，才判 `error`

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

## Success criteria

完成本 skill 时，至少要满足：

1. `web-plan.json` 已生成。
2. `websearch` 和 `webreader` 的跳过/执行原因清楚。
3. 如有候选，review seed 已写出并通过校验。
4. reviewed 文件只包含结构化结果，不包含自由文本总结。
5. `web-branch-result.json` 已落盘，且可被上游 merge skill 直接消费。

## Never do

- 不要把 `websearch-raw.json` 直接交给 merge
- 不要跳过 `prepare_*_review_input.py -> validate_*_review_seed.py -> write_*_review.py` 这条 reviewed gate
- 不要只生成 review seed 而不写 reviewed 文件
- 不要把自然语言分析当作 seed 或 reviewed 文件
- 不要因为 `webreader` 失败就把整个 web 分支判成失败
- 不要输出自由格式网页摘要代替 reviewed JSON
