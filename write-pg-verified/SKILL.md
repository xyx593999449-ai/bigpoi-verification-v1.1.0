---
name: write-pg-verified
description: 从上游技能生成的本地 JSON 文件中读取大 POI 核实结果并回写 PostgreSQL 成果表。用于执行回库、在仅提供 task_id 和 search_directory 时自动查找索引文件，以及在需要时通过 init 和 verified 参数覆盖原始表与核实成果表名；如果同一 task_id 因调度重试产生多个 index 文件，自动按最新时间戳选择最新结果。
---

# write-pg-verified

将上游核实技能产出的 `index.json`、`decision`、`evidence`、`record` 等文件加载后，写入 PostgreSQL 的核实成果表，并同步更新原始表的 `verify_status` 为“已核实”。

## 工作流

1. 优先接收 `task_id + search_directory`，自动在目录下递归查找匹配的 index 文件。
2. 对每个候选 index 读取文件内容，校验其中的 `task_id` 与入参一致。
3. 如果同一个 `task_id` 命中多个 index 文件，按文件最后修改时间选择最新的一个，避免调度重试后仍误用旧结果。
4. 从选中的 index 加载 `decision`、`evidence`、`record` 等关联文件。
5. 转换字段后写入 `verified` 指定的成果表，并更新 `init` 指定的原始表。

## 输入方式

默认表名：
- `init = "poi_init"`
- `verified = "poi_verified"`

推荐方式：

```python
from SKILL import execute

result = execute(
    {
        "task_id": "TASK_20260227_001",
        "search_directory": "output/results"
    },
    init="poi_init",
    verified="poi_verified"
)
```

也可以直接放进 data：

```python
from SKILL import execute

result = execute({
    "task_id": "TASK_20260227_001",
    "search_directory": "output/results",
    "init": "custom_poi_init",
    "verified": "custom_poi_verified"
})
```

兼容方式：

```python
from SKILL import execute

result = execute({
    "task_id": "TASK_20260227_001",
    "index_file": "output/results/TASK_20260227_001/index.json",
    "init": "poi_init",
    "verified": "poi_verified"
})
```

批量方式：

```python
from SKILL import execute_batch

results = execute_batch(
    ["TASK_001", "TASK_002", "TASK_003"],
    search_directory="output/results",
    init="poi_init",
    verified="poi_verified"
)
```

## 索引文件要求

上游技能应生成类似结构：

```json
{
  "task_id": "TASK_20260227_001",
  "poi_id": "POI_12345",
  "files": {
    "decision": "decision_DEC_20260227_001.json",
    "evidence": "evidence_EVD_20260227_001.json",
    "record": "record_REC_20260227_001.json"
  },
  "poi_data": {
    "id": "POI_12345",
    "name": "北京大学第一医院",
    "poi_type": "090101",
    "address": "北京市西城区西什库大街8号",
    "city": "北京市",
    "city_adcode": "110102",
    "x_coord": 116.3723,
    "y_coord": 39.9342
  }
}
```

必需字段：
- `task_id`
- `poi_id`
- `files.decision`
- `poi_data`

## 多 index 选择规则

当使用 `task_id + search_directory` 模式时：

- 递归匹配可能的 `index*.json`，并覆盖 Linux 下如 `.claude` 这类隐藏目录中的候选文件
- 只保留文件内容里 `task_id` 一致的候选
- 如果有多个候选，按文件最后修改时间降序排序
- 使用最新的那个 index 继续回库

## 表名参数

- `init`：原始表名，默认 `poi_init`
- `verified`：核实成果表名，默认 `poi_verified`
- 允许传裸表名，也允许传带 schema 的形式，例如 `public.poi_init`
- 表名会做标识符校验后再拼入 SQL，避免直接字符串拼接

## 命令行

```bash
python SKILL.py <task_id> <search_directory>
python SKILL.py <index_file_path>
```

## 目录结构

```text
write-pg-verified/
├── SKILL.md
├── SKILL.py
├── config/
│   └── db_config.yaml
└── scripts/
    ├── __init__.py
    ├── file_loader.py
    ├── data_converter.py
    ├── db_writer.py
    └── logger_config.py
```

## 注意事项

- 推荐优先使用 `task_id + search_directory`，让技能自己完成 index 发现与重试结果兜底。
- 如果你已经明确知道要写回哪一份结果，可以直接传 `index_file`，此时不会参与“最新 index”选择。
- 技能保持幂等：`verified` 表已存在相同 `task_id` 时，不重复插入，但仍会更新 `init` 表状态。
- 日志会记录候选 index 数量、最终命中的最新文件，以及本次实际写入的表名，便于排查问题。`Path.rglob(...)` 递归查找可覆盖 Linux 下 `.claude` 等隐藏目录。

## 回库字段来源约束

- `verification_notes` 仅来自 `decision.overall.summary`，要求上游提供稳定的中文摘要。
- `changes_made` 优先使用 `record.verification_result.changes`，不再直接依赖自由格式的 `decision.corrections`。
- 成果表中的 `name`、`x_coord`、`y_coord`、`poi_type`、`address`、`city`、`city_adcode` 均以 `record.verification_result.final_values` 为准。
- 如果 `record.verification_result.final_values` 未正确体现核实后的最终值，应视为上游结果不合格，禁止回库。
