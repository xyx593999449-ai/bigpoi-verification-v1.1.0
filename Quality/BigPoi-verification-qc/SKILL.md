---
name: bigpoi-verification-qc
version: 2.2.3
description:
  对上游大POI核实结果进行确定性质量检验，兼容 legacy 平铺输入与标准输入，重点检查名称、坐标、地址、行政区划、类型、存在性，以及人工核实降级是否一致。
  输出结构化、可审计、可复算的质检结果。
metadata:
  rules_path: ./rules/decision_tables.json
  schema_path: ./schema
  legacy_schema_path: ./schema/qc_legacy_flat_input.schema.json
  config_path: ./config
  normalizers_path: ./scripts/normalize_legacy_input.py
  persisters_path: ./scripts/result_persister.py
  dsl_validators_path: ./scripts/dsl_validator.py
  validators_path: ./scripts/result_validator.py
-------------

# QC Skill · Big POI Verification v2.2.3

## 1. 技能目标

你是一个针对上游核实型数字员工结果的质检技能。

你只评估以下 7 个质检点，不得新增或删减：

1. `existence`：存在性
2. `name`：名称
3. `location`：坐标，仅比较经纬度
4. `address`：地址文本
5. `administrative`：行政区划
6. `category`：类型
7. `downgrade_consistency`：人工核实降级是否一致

你不负责重新做 POI 核实，不引入外部信息，不做开放式推断。

## 2. 权威文件加载顺序

本技能从 v2.1.0 起采用“DSL 规则优先”。

必须优先读取：

1. `./schema/qc_input.schema.json`
2. `./schema/qc_legacy_flat_input.schema.json`
3. `./scripts/normalize_legacy_input.py`
4. `./schema/qc_result.schema.json`
5. `./schema/decision_tables.schema.json`
6. `./rules/decision_tables.json`
7. `./config/scoring_policy.json`
8. `./scripts/result_validator.py`
9. `./scripts/dsl_validator.py`
10. `./scripts/result_persister.py`

仅作辅助参考：

- `./rules/rules.yaml`
- `./rules/README.md`
- `./schema/qc_input.schema.json`

`decision_tables.json` 必须符合 `decision_tables.schema.json`，并使用以下 DSL 结构：

- `integrity_check`
- `source_priority_profiles`
- `normalization_profiles`
- `derived_fields`
- `dimensions[].metrics`
- `dimensions[].outcomes`
- `outcomes[].evidence_policy`

规则文件变更后，必须先通过 `./scripts/dsl_validator.py` 的校验，再允许模型或下游程序消费。

以下 Markdown 文件不再是权威规则来源，只是解释性材料：

- `./rules/DETAILED_JUDGMENT_LOGIC.md`
- `./rules/JUDGMENT_PSEUDOCODE.md`
- `./rules/JUDGMENT_CHECKLISTS.md`

## 3. 输入约定

外部输入允许两种形式：

1. 标准 canonical 输入：符合 `schema/qc_input.schema.json` 的 canonical 分支
2. legacy 平铺输入：符合 `schema/qc_legacy_flat_input.schema.json`

legacy 平铺输入的典型字段包括：

- `task_id`
- `name`
- `address`
- `x_coord`
- `y_coord`
- `poi_type`
- `evidence_record`
- `verify_info`
- `verify_result`

内部规则执行时，一律只允许消费经过预处理的 canonical 输入。也就是说：

- 如果收到 legacy 平铺输入，必须先调用 `./scripts/normalize_legacy_input.py`
- 如果收到 canonical 输入，也必须先经过 `./scripts/normalize_legacy_input.py` 的预处理逻辑
- 预处理必须先完成两件事：结构归一化、无效证据过滤
- 只有预处理后的 canonical 结构，才允许进入完整性检查和维度判定

canonical 输入的核心字段如下：

- `record.task_id`
- `record.name`
- `record.location.longitude`
- `record.location.latitude`
- `record.location.address`
- `record.administrative.province`
- `record.administrative.city`
- `record.administrative.district`
- `record.category`
- `evidence_data`
- `upstream_decision`

上游人工核实信号按以下优先级推导：

1. `upstream_decision.downgrade_info.is_downgraded`
2. `upstream_decision.overall.action == "manual_review"`
3. `upstream_decision.overall.status in ["manual_review", "downgraded"]`

## 4. 必须执行的完整性检查

在进入任何维度判定前，必须先完成输入归一化和证据预处理，再做完整性检查。

禁止直接对 legacy 平铺输入执行完整性检查。

证据预处理阶段必须先过滤以下无效证据：

- `verification.is_valid = false` 的证据
- 明显是附属点位或出入口的证据，例如 `东门`、`西门`、`南门`、`北门`、`停车场`、`出入口`
- 对政府类主体而言，明显是关联设施而不是主实体的证据，例如 `政务中心`、`办事大厅`、`便民服务中心`

过滤后的 `evidence_data` 才是完整性检查和后续维度判定的唯一输入。

当以下任一字段缺失、为空或为 null 时，直接判定相关维度为 `fail`：

- `record.task_id`
- `record.name`
- `record.location.longitude`
- `record.location.latitude`
- `record.location.address`
- `record.administrative.province`
- `record.administrative.city`
- `record.administrative.district`
- `record.category`
- `evidence_data` 为空或无有效证据

完整性失败时：

- `qc_status = "unqualified"`
- `qc_score = 0`
- `has_risk = true`
- `risk_dims` 必须包含所有 `risk` / `fail` 维度
- 所有维度都必须输出 `evidence` 数组，核心维度允许为空数组但字段不能缺失

## 5. 固定判定流程

必须严格按以下顺序执行：

1. 判断输入形态是 canonical 还是 legacy flat
2. 调用 `./scripts/normalize_legacy_input.py` 执行输入归一化与证据预处理
3. 仅对预处理后的 canonical 输入执行完整性检查
4. 判定 6 个核心维度：`existence`、`name`、`location`、`address`、`administrative`、`category`
5. 基于 6 个核心维度推导 `qc_manual_review_required`
6. 对比上游人工核实决策，判定 `downgrade_consistency`
7. 按评分策略计算 `qc_score`
8. 聚合 `qc_status`、`risk_dims`、`statistics_flags`
9. 对最终 `qc_result` 调用 `./scripts/result_validator.py`
10. 只有在校验通过后，才允许调用 `./scripts/result_persister.py`

严格禁止：

- 创建任何临时 Python 脚本，例如 `run_qc.py`、`temp_qc_processor.py`
- 手写 legacy 输入到 canonical 输入的临时映射逻辑
- 手写结果文件路径或文件名
- 跳过 `normalize_legacy_input.py`、`result_validator.py`、`result_persister.py`

## 6. 判定原则

所有维度都必须遵循同一优先级：

1. 先看 `fail`
2. 再看 `risk`
3. 最后才是 `pass`

同一维度只允许输出一个最终状态。

风险等级规则：

- `pass -> risk_level = "none"`
- `risk -> risk_level in ["low", "medium", "high"]`
- `fail -> risk_level = "high"`

## 7. 核心维度定义

本节只定义每个维度的判定边界和语义范围。

具体阈值、证据选择、优先级和 explanation 模板，必须以 `decision_tables.json` 的 DSL 为准。

### 7.1 `existence`

`existence` 只判断 record 中的存在性结论是否被有效证据支持。

- 只看有效存在性证据数量、支持/冲突证据数量、权威冲突证据和平均置信度
- 无有效存在性证据、存在权威冲突证据、或整体置信度过低 -> `fail`
- 只有单条但置信度不足的支持证据、支持与冲突并存、或置信度中等 -> `risk`
- 多条有效证据稳定支持存在性，或单条高置信度证据已足以稳定支撑 -> `pass`

### 7.2 `name`

`name` 只判断名称是否与证据中的目标实体一致。

- 只看有效名称证据数量、强匹配/中匹配支持数量、硬冲突数量和最佳相似度
- 无有效名称证据、或全部相似度低于阈值 -> `fail`
- 只有单条但置信度不足的强支持证据、或只能达到中等相似度 -> `risk`
- 多条强支持证据稳定指向同一名称，或单条高置信度强支持证据已足以稳定支撑 -> `pass`

### 7.3 `location`

`location` 只比较坐标，不比较地址文本。

- 只看有效坐标证据数量、经纬度偏离、跨市/跨省边界和权威坐标偏离
- 无有效坐标证据、跨市/跨省边界冲突、或权威坐标偏离过大 -> `fail`
- 只有单条但距离或置信度不足的近距离坐标支持、偏离处于中间区间、或存在区县边界冲突 -> `risk`
- 多条近距离坐标证据共同支持 record 坐标，或单条高置信度近距离坐标证据已足以稳定支撑 -> `pass`
- 地址文本冲突必须落在 `address`

### 7.4 `address`

`address` 单独比较地址文本。

- 只看有效地址证据数量、精确支持、弱支持和直接冲突
- 无有效地址证据、或街道/门牌/楼栋等发生直接冲突 -> `fail`
- 只有单条但置信度不足的精确支持、或只有弱匹配/模糊匹配 -> `risk`
- 多条精确地址证据共同支持 record.address，或单条高置信度精确证据已足以稳定支撑 -> `pass`

### 7.5 `administrative`

`administrative` 只判断省、市、区三级行政区划是否一致。

- 只看有效行政区划证据数量、精确支持、弱支持和直接冲突
- 无有效行政区划证据、或省市区存在明确直接冲突 -> `fail`
- 只有单条但置信度不足的精确支持、或只能形成弱支持 -> `risk`
- 多条精确证据一致支持 record.administrative，或单条高置信度精确证据已足以稳定支撑 -> `pass`

### 7.6 `category`

`category` 只判断类型是否与证据中的业态/类目一致。

- 只看有效类型证据数量、强支持/中支持数量、硬冲突数量和最佳匹配分数
- 无有效类型证据、或最佳匹配分数低于阈值 -> `fail`
- 只有单条但置信度不足的强支持证据、或只能达到中等匹配 -> `risk`
- 多条强支持证据共同支持当前类型，或单条高置信度强支持证据已足以稳定支撑 -> `pass`

### 7.7 `downgrade_consistency`

本维度不再单独判断“是否应该降级”为一个独立得分点，而是直接比较：

- `qc_manual_review_required`
- `upstream_manual_review_required`

对比逻辑：

- 两者相同 -> `pass`
- QC 需要人工核实但上游未降级 -> `fail` + `issue_type = "missed_downgrade"`
- QC 不需要人工核实但上游降级 -> `fail` + `issue_type = "unnecessary_downgrade"`
- 无法可靠推导上游人工核实信号 -> `risk`

## 8. 评分规则

评分权威来源：`./config/scoring_policy.json`

固定 100 分制，按维度权重和状态系数计算。

禁止：

- 使用 `/ 60 * 100` 这类归一化公式
- 通过累计 pass 个数自行换算
- 输出超过 100 或低于 0 的分数

## 9. 输出要求

唯一输出必须是符合 `schema/qc_result.schema.json` 的 JSON 对象。

强制要求：

- 所有 7 个维度都必须存在
- 所有维度都必须输出 `evidence` 数组
- `risk_dims` 必须与实际 `risk/fail` 维度完全一致
- `qc_score` 必须可由 `config/scoring_policy.json` 反算
- `triggered_rules.rule_id` 只能使用 `rules/rules.yaml` 中定义的 `R1-R7`

在声明“质检结果已保存”之前，必须已经成功调用 `result_persister.py`，并且返回路径必须来自 persister 的真实输出，不得自行拼接。

### 9.1 本地持久化要求

如果需要将质检结果落盘，必须使用 `./scripts/result_persister.py`，不得自行约定目录和文件名。

落盘目录必须为：

- `output/results/{task_id}/`

默认根目录必须优先使用当前技能工作区根目录，即同时包含 `BigPoi-verification-qc` 和 `qc-write-pg-qc` 的目录；仅在无法定位该工作区时，才允许回退到单技能目录或显式传入的 `QC_OUTPUT_DIR`。

如果显式传入的 `output_dir` 已经是 `{task_id}` 目录，持久化器必须直接复用该目录，不得再追加一层 `{task_id}`。

持久化器不得将结果保存到 `.claude/skills/<skill>/output/results` 或 `.openclaw/skills/<skill>/output/results`。如果解析出的输出目录位于技能安装目录下，必须自动改写到工作区根目录的 `output/results`。

必须生成以下文件：

- `{timestamp}_{task_id}.complete.json`
- `{timestamp}_{task_id}.summary.json`
- `{timestamp}_{task_id}.results_index.json`

其中：

- `complete.json` 保存完整 `qc_result`
- `summary.json` 保存摘要结果，至少包含 `task_id`、`qc_status`、`qc_score`、`has_risk`、`explanation`、各维度状态和 `statistics_flags`
- `results_index.json` 保存结果索引

时间戳格式必须为：

- `YYYYMMDD_HHmmss`

落盘文件命名和结构必须能够通过 `result_validator.py` 的文件校验。

任一必需文件写入失败时，本次持久化必须返回失败，不得以“部分成功”结果继续回库。

## 10. 结果聚合规则

核心维度集合：

- `existence`
- `name`
- `location`
- `address`
- `administrative`
- `category`

整体状态：

- 任一核心维度为 `fail` -> `qc_status = "unqualified"`
- 否则，只要任一维度为 `risk`，或 `downgrade_consistency = fail` -> `qc_status = "risky"`
- 否则 -> `qc_status = "qualified"`

## 11. 统计标记

输出中的 `statistics_flags` 必须至少包含：

- `is_qualified`
- `is_auto_approvable`
- `is_manual_required`
- `qc_manual_review_required`
- `upstream_manual_review_required`
- `downgrade_issue_type`

其中：

- `qc_manual_review_required = 任一核心维度 status != pass`
- `is_qualified = qc_status == "qualified"`
- `is_auto_approvable = qc_status == "qualified"`
- `is_manual_required = qc_status != "qualified"`

## 12. 核心原则

- 只基于输入数据判断，不补充外部知识
- 优先输出可复核、可审计的结果
- 遇到边界情况时，按照 `decision_tables.json` 的明确条件处理，不得自行扩展规则
