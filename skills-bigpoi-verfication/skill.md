---
name: bigpoi-verification
description: 面向大 POI 核实任务的父技能。用于编排 `evidence-collection` 与 `verification` 子技能，整合 input/evidence-file/decision 生成最终 `record` 与 `index` 输出包，并在流程末尾执行目录、文件名、文件内容的硬性校验。遇到最终规格校验失败时，必须根据 `failed_stage` 打回到对应环节重新执行，而不是手改结果文件。
---

# Big POI Verification

## Core rule

必须把最终输出稳定性收敛到脚本，不要只靠自然语言约束结果格式。

父技能只负责三件事：

1. 校验输入是否进入核实范围。
2. 串联 `evidence-collection` 和 `verification` 子技能。
3. 生成最终结果包并执行最终验收。

## Use bundled scripts

必须使用以下脚本：

- `skills-bigpoi-verfication/scripts/write_result_bundle.py`
- `skills-bigpoi-verfication/scripts/validate_result_bundle.py`

禁止行为：

- 手写最终 `record_*.json` 或 `index_*.json`
- 只在对话中展示 JSON 而不落盘
- 跳过最终校验直接宣布完成
- 在校验失败后直接修改生成文件绕过失败原因

## Inputs

输入 POI 必须满足 `skills-bigpoi-verfication/schema/input.schema.json` 的核心约束：

- 必须有 `id`、`name`、`poi_type`、`city`
- `poi_type` 必须保持公司内部 6 位类型码
- 若只有遗留字段 `poi_id`，先规范化为 `id` 再继续

子技能交接要求：

- `evidence-collection` 必须交付正式 `evidence_path`
- `evidence-collection` 内部可以并行跑图商代理、`websearch`、`webfetch` 和缺失图商补采，但这些都只能作为中间 JSON 工件存在
- `verification` 必须读取这个 `evidence_path`，不得接收模糊的内联 evidence
- `verification` 必须交付正式 `decision_path`

## Workflow

1. 读取输入并检查是否属于大 POI 范围。
2. 调用 `evidence-collection`，让其先完成并行采集、缺失图商补采、归并规范化，再通过 `write_evidence_output.py` 生成正式 `evidence_*.json` 文件。
3. 调用 `verification`，输入是 `input 文件 + evidence_path`，产出唯一正式产物 `decision_*.json`。
4. 运行以下脚本生成最终输出包：

```bash
python skills-bigpoi-verfication/scripts/write_result_bundle.py -InputPath <input.json> -EvidencePath <evidence-file.json> -DecisionPath <decision.json> -WorkspaceRoot <repo-root>
```

5. 对脚本生成的任务目录执行最终规格校验：

```bash
python skills-bigpoi-verfication/scripts/validate_result_bundle.py -TaskDir <output/results/{task_id}>
```

6. 只有在校验脚本返回 `status = passed` 时，才能把任务标记为完成，并向下游暴露 `index` 文件路径。

## Final output contract

最终目录必须为：

- `output/results/{task_id}/`

最终目录内的正式结果文件必须满足：

- `decision_<timestamp>.json`
- `evidence_<timestamp>.json`
- `record_<timestamp>.json`
- `index_<timestamp>.json`

约束：

- `timestamp` 格式必须为 `yyyyMMddTHHmmssZ`
- `index.files` 中必须是绝对路径
- `index.task_dir` 必须是 `output/results/{task_id}`
- 对用户的最终说明里必须明确给出 `index` 文件路径

## Retry gate

最终校验失败时，必须依据 `failed_stage` 处理：

- `evidence_collection`：重新执行证据收集分支 JSON、归并脚本与 `write_evidence_output.py`，然后重跑父技能打包与校验
- `verification`：使用正式 `evidence_path` 重新执行子技能决策输出，然后重跑父技能打包与校验
- `parent_integration`：只重跑父技能的打包脚本与最终校验

不要做的事：

- 不要手工补字段来“修”失败文件
- 不要把子技能失败伪装成父技能完成
- 不要忽略 `warnings` 之外的任何 `reasons`

## References to load only when needed

仅在需要时读取以下文件，不要一次性把所有内容都塞进上下文：

- `skills-bigpoi-verfication/schema/input.schema.json`
- `skills-bigpoi-verfication/schema/evidence.schema.json`
- `skills-bigpoi-verfication/schema/decision.schema.json`
- `skills-bigpoi-verfication/schema/record.schema.json`



