---
name: evidence-collection
description: BigPOI 证据收集主调度 skill。用于初始化运行上下文，并发调用 evidence-collection-web 与 evidence-collection-map，等待分支结果后再调用 evidence-collection-merge 写出正式 evidence 文件。
allowed-tools: Bash Read Write Edit Glob Grep LS
---

# Evidence Collection

## Goal

本 skill 是 Product 域证据收集的唯一主入口。

它只负责：

1. 初始化本次 `run_id / task_id / process_dir / staging_dir`。
2. 调用 `scripts/run_parallel_claude_agents.py`，并发启动两个 worker：
   - `evidence-collection-web`
   - `evidence-collection-map`
3. 等待以下分支结果文件落盘：
   - `output/runs/{run_id}/process/web-branch-result.json`
   - `output/runs/{run_id}/process/map-branch-result.json`
4. 调用 `evidence-collection-merge` 完成 reviewed-only merge 与正式 evidence 写出。
5. 最终只返回 `evidence_path`。

## Runtime assets

使用以下脚本：

- `evidence-collection/scripts/run_evidence_collection.py`
- `evidence-collection/scripts/run_parallel_claude_agents.py`
- `skills-bigpoi-verification/scripts/init_run_context.py`

共享模块放在：

- `evidence-collection/scripts/evidence_collection_common.py`
- `evidence-collection/scripts/run_context.py`

如需查看旧版长流程说明，可读取：

- `evidence-collection/references/legacy-evidence-collection-skill-20260407.md`

## Input

输入必须是符合 `skills-bigpoi-verification/schema/input.schema.json` 核心约束的 POI JSON 文件路径。

至少需要：

- `id`
- `name`
- `poi_type`
- `city`

## Output

唯一正式输出是：

- `evidence_path`

过程产物包括：

- `output/runs/{run_id}/process/parallel-agent-runner.json`
- `output/runs/{run_id}/process/web-branch-result.json`
- `output/runs/{run_id}/process/map-branch-result.json`
- `output/runs/{run_id}/process/evidence-merge-result.json`

## Seed 约定

并行 worker 需要在 `output/runs/{run_id}/process/` 下写出 review seed；主调度脚本默认自动发现以下文件，不再强制手动参数注入：

- `map-review-seed-internal-proxy.json`
- `map-review-seed-fallback-{vendor}.json`
- `websearch-review-seed.json`
- `webreader-review-seed.json`

## Child skills

本 skill 内部编排以下子技能：

- `evidence-collection-web`
- `evidence-collection-map`
- `evidence-collection-merge`

父技能 `skills-bigpoi-verification` 不直接调用这三个子技能。

## Never do

- 不要直接输出 `decision_*.json`、`record_*.json`、`index_*.json`
- 不要手工拼接 evidence 数组绕过 merge 脚本
- 不要在主 skill 中直接执行 web/map 原始采集细节
