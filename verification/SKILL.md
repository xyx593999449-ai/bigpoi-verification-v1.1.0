---
name: verification
description: 面向大 POI 核实流程的子技能。用于基于输入 POI 文件和正式 `evidence` 文件给出结构化维度判断，并且必须通过脚本生成稳定的 `decision` 文件。适用于父技能需要一个严格符合 `decision.schema.json` 的核实决策产物时；本技能不得生成最终 `record` 或 `index`。
---

# Verification

## Core rule

本技能的唯一正式输出是 `decision_*.json`。

本技能的正式输入不是内联 evidence 对象，而是证据文件路径。

不要输出：

- `record_*.json`
- `index_*.json`
- 任何“接近 schema 但不完全一致”的自由格式 JSON

## Use bundled script

必须使用：

- `verification/scripts/write_decision_output.py`

禁止行为：

- 直接手写最终 `decision_*.json`
- 输出中文类别名或英文类别名替代内部类型码
- 在脚本失败后用对话里的 JSON 代替文件结果
- 接收父技能临时拼出来的 evidence 对象而不是正式 evidence 文件

## Inputs

本技能只接受两类正式输入：

- 输入 POI 文件：遵循 `skills-bigpoi-verification/schema/input.schema.json`
- 证据文件：路径指向 `evidence-collection` 产出的 `evidence_*.json`

证据文件要求：

- 文件内容必须是证据数组
- 每个 item 遵循 `skills-bigpoi-verification/schema/evidence.schema.json`
- `poi_id` 必须与输入 `id` 一致

分类字段约束：

- 输入 `poi_type` 是公司内部 6 位类型码
- 输出中的分类结论必须继续保持这个类型码
- 类型映射只用于内部核对，不用于改写输出格式

## Workflow

1. 读取输入 POI 文件和 evidence 文件。
2. 按维度形成结构化判断，最少覆盖：
   - `existence`
   - `name`
   - `address`
   - `coordinates`
   - `category`
3. `decision seed.dimensions` 必须显式提供 `address` 与 `coordinates` 两个维度，不允许只写 `location` 由脚本反推。
4. 可选保留 `location` 作为兼容汇总维度，但其结论必须由 `address` 与 `coordinates` 聚合生成，不能再单独作为地址和坐标的唯一判断依据。
5. 只有证据足够时才补充：
   - `administrative`
   - `timeliness`
4. 先写一个精简的 `decision seed` 中间文件，内容只放这些字段：
   - `dimensions`
   - 可选 `overall`
   - 可选 `downgrade_info`
   - 可选 `corrections`
5. 运行脚本生成正式决策文件：

```bash
python verification/scripts/write_decision_output.py -PoiPath <input.json> -EvidencePath <evidence-file.json> -DecisionSeedPath <output/runs/{run_id}/process/decision-seed.json> -OutputDirectory <output/runs/{run_id}/staging> -RunId <run-id> -TaskId <task-id>
```

6. 使用脚本返回的 `decision_path` 作为唯一正式输出路径。

## Decision seed requirements

- `decision seed` 必须包含顶层 `context`，至少包含 `run_id`、`poi_id`、`created_at`，可选 `task_id`
- `decision seed` 必须写入 `output/runs/{run_id}/process/` 下的本次运行独立文件，不允许复用共享固定文件名
- 只有在 `decision seed` 写入成功且内容合法后，才能继续调用 `write_decision_output.py`

`dimensions` 中每个维度至少包含：

- `result`: `pass | fail | uncertain`
- `confidence`: `0.0 ~ 1.0`

可选字段：

- `score`
- `evidence_refs`
- `details`

要求：

- `evidence_refs` 只能引用 evidence 文件中真实存在的 `evidence_id`
- `overall.status` 只能是 `accepted | downgraded | manual_review | rejected`
- 如果不提供 `overall`，脚本会根据维度结果自动推导

## Failure handling

如果脚本报错，说明是 seed 结构、evidence 文件格式、或输入字段不满足约束。

此时必须：

1. 修正 seed，或要求上游重新生成 evidence 文件
2. 重新运行 `write_decision_output.py`
3. 把新的 `decision_path` 返回给父技能

不要：

- 修改脚本已经判定失败的输出文件
- 让父技能猜测你的决策结构
- 省略脚本返回的正式文件路径

## References to load only when needed

仅在需要时读取：

- `skills-bigpoi-verification/schema/decision.schema.json`
- `skills-bigpoi-verification/schema/evidence.schema.json`
- `verification/config/thresholds.yaml`
- `verification/config/downgrade.yaml`
- `verification/config/type_mapping.yaml`

## 回库稳定性约束

- `decision.overall.summary` 必须输出为简体中文短句，供成果表 `verification_notes` 直接复用。
- 如果核实结论包含建议修改、修正、改为等信息，`decision seed` 中必须同步提供结构化 `corrections`。
- `corrections` 仅允许包含 `name`、`address`、`coordinates`、`category`、`city`、`city_adcode`。
- 每个修正项必须包含 `suggested` 与 `reason`，`original` 缺失时也必须由脚本补齐原始值。
- 如果 seed 文本中出现修改信号但没有 `corrections`，`write_decision_output.py` 必须直接失败，不允许生成正式 `decision_*.json`。
- `seed.dimensions.address` 和 `seed.dimensions.coordinates` 必须由上游显式写入，不允许仅提供 `location` 让脚本自动填充。
