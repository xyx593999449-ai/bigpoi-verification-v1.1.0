---
name: write-pg-verified
version: 1.5.0
description: 从上游技能生成的本地JSON文件读取大POI核实结果，回写到PostgreSQL成果表
---

# 大POI核实结果回库技能 v1.5.0

## 概述

本技能从上游大POI核实技能本地化存储的JSON文件中读取核实结果，批量回写到PostgreSQL数据库的 `poi_verified` 成果表，同时更新 `poi_init` 原始表状态为'已核实'。

### 主要特性

- **通用输入模式**：支持 task_id + search_directory 自动查找索引文件，也支持直接指定索引文件路径
- **JSONB支持**：使用 `psycopg2.extras.Json` 正确处理复杂的JSON字段
- **原子性事务**：确保成果表插入和原始表更新的原子性
- **幂等性保证**：重复执行不会产生重复记录
- **状态同步**：即使成果表已存在记录，也会确保原始表状态更新为'已核实'
- **完整证据记录**：支持包含多个证据文件的完整证据链

---

## 功能说明

### 输入格式

上游技能应生成以下结构的索引文件（`index.json`）：

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

**必需字段**：
- `task_id`: 任务唯一标识
- `poi_id`: POI唯一标识
- `files.decision`: 决策文件路径（必需）
- `files.evidence`: 证据文件路径（可选）
- `files.record`: 记录文件路径（可选）
- `poi_data`: POI基础信息

### 调用方式

```python
from SKILL import execute, execute_batch

# 模式1：使用 task_id + search_directory（推荐）
result = execute({
    'task_id': 'TASK_20260227_001',
    'search_directory': 'output/results'
})

# 模式2：直接指定索引文件路径（兼容）
result = execute({
    'task_id': 'TASK_20260227_001',
    'index_file': 'output/results/TASK_20260227_001/index.json'
})

# 批量写入 - 使用任务ID列表
results = execute_batch(
    ['TASK_001', 'TASK_002', 'TASK_003'],
    search_directory='output/results'
)

# 批量写入 - 使用完整数据列表
results = execute_batch([
    {'task_id': 'TASK_001', 'search_directory': 'output/results'},
    {'task_id': 'TASK_002', 'index_file': 'path/to/index2.json'}
])
```

### 输出格式

成功响应：
```json
{
  "success": true,
  "task_id": "TASK_20260227_001",
  "poi_id": "POI_123",
  "message": "POI 核实结果已成功写入成果表",
  "tables_updated": ["poi_verified", "poi_init"],
  "verify_time": "2026-03-04T12:00:00"
}
```

已存在记录（仅更新原始表状态）：
```json
{
  "success": true,
  "task_id": "TASK_20260227_001",
  "poi_id": "POI_123",
  "message": "POI 核实结果已存在，原始表状态已更新",
  "tables_updated": ["poi_init"],
  "verify_time": "2026-03-04T12:00:00",
  "skipped": true
}
```

---

## 数据转换映射

| 上游字段 | 数据库字段 | 转换规则 |
|---------|-----------|---------|
| `task_id` | `task_id`, `original_task_id` | 直接映射 |
| `poi_id` | `id`, `original_id` | 直接映射 |
| `poi_data.name` | `name` | 直接映射 |
| `poi_data.x_coord` | `x_coord` | 直接映射 |
| `poi_data.y_coord` | `y_coord` | 直接映射 |
| `poi_data.poi_type` | `poi_type` | 直接映射 |
| `poi_data.address` | `address` | 直接映射 |
| `poi_data.city` | `city` | 直接映射 |
| `poi_data.city_adcode` | `city_adcode` | 直接映射 |
| `overall.status` | `verify_result` | accepted→核实通过, 其他→需人工核实 |
| `overall.confidence` | `overall_confidence` | 直接映射 |
| `dimensions.existence.result` | `poi_status` | pass→1, uncertain→4, fail→5 |
| `dimensions` | `verify_info` | JSONB 存储 |
| `evidence` 数组 | `evidence_record` | JSONB 存储数组 |
| `corrections` | `changes_made` | JSONB 存储 |
| `overall.summary` | `verification_notes` | 直接映射 |

---

## 目录结构

```
write-pg-verified/
├── SKILL.md                    # 本文档
├── SKILL.py                    # 入口文件
├── config/
│   └── db_config.yaml         # 数据库配置
└── scripts/
    ├── __init__.py            # 包初始化文件
    ├── file_loader.py          # JSON文件加载器
    ├── data_converter.py       # 数据格式转换器
    ├── db_writer.py            # 数据库写入器
    └── logger_config.py        # 日志配置
```

---

## 依赖项

- Python >= 3.8
- psycopg2 (数据库驱动)
- PyYAML (配置文件解析)

---

## 命令行测试

```bash
# 模式1（推荐）：使用 task_id + search_directory
python SKILL.py <task_id> <search_directory>

# 示例
python SKILL.py TASK_20260227_001 output/results

# 模式2（兼容）：直接传入索引文件路径
python SKILL.py <index_file_path>

# 示例
python SKILL.py output/results/TASK_20260227_001/index.json
```

---

## 数据库操作

### 插入成果表

```sql
INSERT INTO public.poi_verified (
    task_id, id, name, x_coord, y_coord, poi_type, address, city, city_adcode,
    verify_status, verify_result, overall_confidence, poi_status,
    original_task_id, original_id,
    verify_info, evidence_record, changes_made, verification_notes,
    verify_time, updatetime, verified_by, verification_version
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s
)
```

### 更新原始表

```sql
UPDATE public.poi_init
SET verify_status = '已核实', updatetime = %s
WHERE task_id = %s
```

---

## 验证命令

```bash
# 验证成果表记录
psql -h 10.82.232.122 -U appdeploy -d big_poi -c \
    "SELECT task_id, verify_result, verify_time FROM poi_verified ORDER BY verify_time DESC LIMIT 5;"

# 验证原始表状态
psql -h 10.82.232.122 -U appdeploy -d big_poi -c \
    "SELECT task_id, verify_status FROM poi_init WHERE task_id = 'TASK_20260227_001';"
```

---

## 错误处理

| 错误码 | 说明 | 处理方式 |
|-------|------|---------|
| `VALUE_ERROR` | 输入数据验证失败 | 检查 task_id 和 search_directory/index_file 字段是否存在 |
| `FILE_NOT_FOUND` | 索引文件或相关文件不存在 | 检查搜索目录是否正确，或索引文件路径是否正确 |
| `JSON_DECODE_ERROR` | JSON文件格式错误 | 检查JSON文件格式 |
| `DB_ERROR` | 数据库操作失败 | 检查数据库连接和权限 |

---

## 注意事项

1. **输入方式**：推荐使用 `task_id` + `search_directory` 模式，技能会自动在搜索目录下查找匹配的索引文件
2. **索引文件命名**：索引文件命名建议为 `index_<task_id>.json` 或包含 task_id 的名称
3. **幂等性**：重复执行相同 `task_id` 的数据不会产生重复记录
4. **状态同步**：即使成果表已存在记录，也会更新原始表状态为'已核实'
5. **事务一致性**：写入失败时会自动回滚，确保两表数据一致
6. **JSONB处理**：使用 `psycopg2.extras.Json` 包装JSON字段，确保正确编码
7. **日志记录**：所有操作都会记录详细日志，便于问题排查

---


