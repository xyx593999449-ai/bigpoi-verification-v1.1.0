# 规则说明

从 v2.1.0 起，本目录采用“DSL 规则优先”。

## 权威文件

1. `decision_tables.json`
2. `../schema/decision_tables.schema.json`
3. `rules.yaml`
4. `../config/scoring_policy.json`
5. `../scripts/dsl_validator.py`

`decision_tables.json` 是唯一权威规则来源，定义了：

- 7 个固定质检维度
- `integrity_check`
- `source_priority_profiles`
- `normalization_profiles`
- `derived_fields`
- 每个维度的 `metrics`
- 每个维度的 `outcomes`
- `evidence_policy`

DSL 的目标是把规则表达成可校验的结构，而不是只保留条件名字。

规则修改后，先执行：

```bash
python3 ../scripts/dsl_validator.py decision_tables.json --schema ../schema/decision_tables.schema.json
```

通过后，才允许将 DSL 作为模型提示或执行输入。

## DSL 结构

每个维度都由以下块组成：

- `record_selector`：被检 record 字段
- `metrics`：先计算的统计量或匹配等级
- `outcomes`：按顺序评估的结果分支
- `evidence_policy`：命中结果后应回填哪些证据

条件表达式统一使用：

- `all`
- `any`
- `not`
- `left / op / right`

## 非权威辅助文档

以下 Markdown 文件只用于解释和培训，不可替代结构化规则：

- `DETAILED_JUDGMENT_LOGIC.md`
- `JUDGMENT_PSEUDOCODE.md`
- `JUDGMENT_CHECKLISTS.md`

## 规则设计原则

- 坐标和地址拆分成两个独立维度
- 不再保留单独的 `downgrade` 维度
- `downgrade_consistency` 直接比较 QC 与上游是否都需要人工核实
- 所有评分必须服从 `config/scoring_policy.json`
- LLM 只能按 DSL 中定义的 selector、metric、outcome 和 explanation template 进行判断
