# 质检检查清单

本文件只用于快速核对，权威规则请看 `decision_tables.json`。

## 核心维度

- `existence`：是否有足够有效证据支持存在性
- `name`：名称是否高度匹配
- `location`：坐标偏离是否在阈值内
- `address`：地址文本是否直接支持 record.address
- `administrative`：省市区是否一致
- `category`：类型是否匹配

## 降级一致性

- QC 是否需要人工核实
- 上游是否要求人工核实
- 二者是否一致

## 聚合前必须确认

- 所有维度都输出了 `evidence`
- `risk_dims` 只包含 `risk` / `fail` 维度
- `qc_score` 可以由 `scoring_policy.json` 复算
