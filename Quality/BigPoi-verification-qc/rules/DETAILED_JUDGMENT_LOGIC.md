# 质检逻辑说明

本文件从 v2.0.0 起仅作解释用途。

## 权威来源

请以以下文件为准：

1. `decision_tables.json`
2. `../config/scoring_policy.json`
3. `../schema/qc_result.schema.json`

## v2.0.0 的核心变化

- 维度固定为：`existence`、`name`、`location`、`address`、`administrative`、`category`、`downgrade_consistency`
- `location` 只评坐标
- `address` 单独评地址文本
- `downgrade_consistency` 直接比较是否需要人工核实，不再引入独立 `downgrade` 维度
- 评分采用固定 100 分权重制，不再做比例换算

## 判定优先级

每个维度都必须按下面顺序处理：

1. 先判断是否满足 `fail`
2. 不满足时再判断 `risk`
3. 都不满足才判 `pass`

## 结果聚合

- 任一核心维度 `fail` -> `unqualified`
- 否则只要任一维度 `risk`，或 `downgrade_consistency = fail` -> `risky`
- 否则 -> `qualified`
