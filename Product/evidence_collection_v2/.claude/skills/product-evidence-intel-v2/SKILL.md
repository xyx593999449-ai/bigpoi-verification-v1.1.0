---
name: product-evidence-intel-v2
description: 面向 BigPOI 证据收集 v2 的主编排 skill。用于初始化 run context，并通过 `claude -p` 并发启动 web 与图商两个 worker，等待两条 reviewed 分支完成后再调用 merge skill 写出正式 evidence 文件。
argument-hint: [input-poi-json-path]
disable-model-invocation: true
---

# Product Evidence Intel V2

## Goal

唯一正式产物是 `evidence_path`。

主 skill 只负责：

1. 初始化本次 `run_id / task_id / output` 运行上下文。
2. 通过 `claude -p` 同时启动 web 分支与 map 分支两个 worker。
3. 等待两条分支完成并检查标准结果文件是否已落盘。
4. 调用 merge skill 生成正式 `evidence_*.json`。

不要在这里直接输出最终核实结论，也不要跳过 reviewed gate 直接做 merge。

## Runtime assets

优先使用以下本地运行资产：

- skill: `product-evidence-web-v2`
- skill: `product-evidence-map-v2`
- skill: `product-evidence-merge-v2`
- script: `Product/skills-bigpoi-verification/scripts/init_run_context.py`
- script: `Product/evidence_collection_v2/scripts/run_parallel_claude_agents.py`

必要时先阅读：

- [../../README.md](../../README.md)

## Input

`$ARGUMENTS` 是输入 POI JSON 文件路径。

如果未提供输入路径，直接报错，不要猜测。

## Execution steps

1. 先用 `git rev-parse --show-toplevel` 解析仓库根目录，记为 `REPO_ROOT`。
2. 执行：

```bash
python "$REPO_ROOT/Product/skills-bigpoi-verification/scripts/init_run_context.py" \
  -InputPath "$ARGUMENTS" \
  -WorkspaceRoot "$REPO_ROOT"
```

3. 从脚本 stdout 解析并记录：
   - `run_id`
   - `task_id`
   - `workspace_root`
   - `paths.process`
   - `paths.staging`
4. 把初始化结果落盘到：
   - `output/runs/{run_id}/process/intel-runtime.json`
5. 运行以下脚本，通过 `claude -p` 并发启动两个 worker：

```bash
python "$REPO_ROOT/Product/evidence_collection_v2/scripts/run_parallel_claude_agents.py" \
  -InputPath "$ARGUMENTS" \
  -RunId "<run_id>" \
  -TaskId "<task_id>" \
  -WorkspaceRoot "$REPO_ROOT" \
  -OutputPath "$REPO_ROOT/output/runs/<run_id>/process/parallel-agent-runner.json" \
  -LogDirectory "$REPO_ROOT/output/runs/<run_id>/process/agent-logs"
```

6. `run_parallel_claude_agents.py` 内部必须：
   - 用 `claude -p` 启动 `product-evidence-web-v2`
   - 用 `claude -p` 启动 `product-evidence-map-v2`
   - 两个 worker 并发执行
   - 把 stdout/stderr 分别写到 `agent-logs/claude_web_worker.log` 与 `agent-logs/claude_map_worker.log`
7. 主 skill 读取 `parallel-agent-runner.json`，确认两个 worker 的 `status` 都为 `ok`。
8. 两条分支结束后，要求以下文件都存在：
   - `output/runs/{run_id}/process/web-branch-result.json`
   - `output/runs/{run_id}/process/map-branch-result.json`
9. 再调用 `product-evidence-merge-v2`，沿用同一个 `input_poi_path / run_id / task_id / workspace_root`。
10. 最终只返回：
   - `evidence_path`
   - `run_id`
   - `task_id`
   - `output/runs/{run_id}/process/evidence-merge-result.json`

## Return contract

最终回答保持简洁，只返回：

- 正式 `evidence_path`
- 本次 `run_id`
- 如需要排障，再补充两个分支结果文件路径

## Never do

不要做以下事情：

- 不要让任一分支直接写正式 `evidence_*.json`
- 不要再使用运行时 subagent 机制替代 `claude -p` worker
- 不要手工拼装 evidence 数组绕过 `merge_evidence_collection_outputs.py`
- 不要在 merge 前消费有候选但未经 reviewed gate 的 raw 分支结果
