---
name: qc-write-pg-qc
description: 从本地化JSON文件读取大POI质检结果，回写到PostgreSQL指定表（v1.2.4 新增候选优先级；优先使用正式工作区输出，避免误选技能安装目录结果）
metadata:
  version: "1.2.4"
  category: "quality-control"
  tags: ["qc", "database", "persistence"]
---

# 大POI质检结果回库技能 v1.2.4

## 概述

本技能从上游大POI质检技能本地化存储的JSON文件中读取质检结果，批量回写到PostgreSQL数据库的指定质检表，同时更新该表的质检相关字段（质检结论、评分、风险标识、统计标记）和状态为'已质检'。

**v1.2.4 当前特性**：
- 支持灵活指定目标表名，可向不同的表写入数据，默认表名为 `poi_qc_zk`
- 保留索引缺失时的递归恢复能力，但恢复范围收敛到 `task_id` 目录
- 多个合法候选并存时拒绝自动猜测，直接返回歧义错误
- 回库字段映射已对齐当前质检结果中的 `downgrade_consistency`
- 回库前强制执行 `BigPoi-verification-qc/scripts/result_validator.py` 校验，拒绝无效 `qc_result`
- 当同时发现正式工作区输出和 `.claude/skills` 下的技能安装目录输出时，优先使用正式工作区结果

### 主要特性

- **文件驱动输入**：仅从本地化 `.complete.json` 文件读取数据
- **灵活表名配置** ✨：支持指定目标表名参数，默认为 `poi_qc_zk`
- **JSONB支持**：使用 `psycopg2.extras.Json` 正确处理复杂的JSON字段
- **原子性事务**：确保质检相关字段在单一事务中原子性更新
- **幂等性保证**：重复执行不会产生重复记录
- **完整质检记录**：支持完整的质检结果和统计字段
- **SQL注入防护**：表名参数进行正则验证，防止注入攻击

### 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.2.4 | 2026-03-17 | 恢复搜索时优先使用正式工作区输出目录中的结果文件；仅当全部候选都位于技能安装目录下时，才回退到 `.claude/skills` 下的结果 |
| 1.2.3 | 2026-03-16 | 新增回库前 `qc_result` 校验；结果不通过 `ResultValidator` 时直接拒绝写库 |
| 1.2.2 | 2026-03-16 | 修复 `downgrade_status` 仍读取旧字段 `dimension_results.downgrade.status` 的问题；默认结果目录不再依赖兄弟 skill 的动态导入 |
| 1.2.1 | 2026-03-16 | 将递归恢复改为受约束模式；仅接受 `task_id` 目录下的索引/complete 候选；多个合法候选时报歧义错误 |
| 1.2.0 | 2026-03-06 | 增强文件查找容错机制，支持多级别降级策略；完善索引缺失时的目录扫描能力；支持递归搜索目录树 |
| 1.1.0 | 2026-03-05 | 新增表名参数支持，可指定目标表名；增加SQL注入防护 |
| 1.0.0 | 2026-03-04 | 初始版本，支持本地化JSON文件读取，质检结果写入poi_qc表 |

---

## 功能说明

### 1. 输入参数

本技能支持以下输入参数：

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `task_id` | string | ✅ 必需 | 质检任务唯一标识 |
| `result_file` | string | ❌ 可选 | 结果文件完整路径，与 result_dir 二选一 |
| `result_dir` | string | ❌ 可选 | 结果目录路径，与 result_file 二选一，推荐使用 |
| `table_name` | string | ❌ 可选 | 目标表名，默认为 `poi_qc_zk`；**v1.1.0 新增** |

### 2. 文件读取模式

#### 方式1：直接指定文件路径（不推荐）

```python
SKILL.execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_file': 'output/results/219A8C6D8C334629A7E1F164D514C381/20260304_103000_219A8C6D8C334629A7E1F164D514C381.complete.json'
})
```

#### 方式2：通过索引文件自动定位（推荐）✅

```python
SKILL.execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_dir': 'output/results'  # 自动从 results_index.json 读取文件路径
})
```

#### 方式3：指定目标表名（v1.1.0 新增）✨

```python
# 写入自定义表
SKILL.execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_dir': 'output/results',
    'table_name': 'poi_qc_custom'  # 自定义表名
})

# 使用默认表名（poi_qc_zk）
SKILL.execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_dir': 'output/results'
    # 不指定 table_name，默认写入 poi_qc_zk
})
```

当提供 `result_dir` 时，技能会：
1. 优先从 `output/results/{task_id}/results_index.json` 索引文件读取最新质检记录
2. 若索引文件不存在或损坏，先在标准 `task_id` 目录内选择时间戳最新的合法 `complete.json`
3. 标准目录仍失败时，自动进入**受约束递归恢复**：只在名为 `{task_id}` 的目录中搜索索引文件和 `complete.json`
4. 每个恢复候选都必须通过 `task_id` 一致性和 JSON 结构校验
5. 如果只找到 1 个合法候选，就读取并返回完整的质检结果
6. 如果同时存在正式工作区候选和技能安装目录候选，优先使用正式工作区候选
7. 若仍存在多个同级合法候选，不自动猜测，直接返回歧义错误
8. 对加载出的 `qc_result` 执行结果校验，确保结构、评分和统计标记自洽
9. 写入到指定的表（默认 poi_qc_zk，或自定义表）

**容错机制说明**（v1.2.1）：
- ✅ **正常情况**：从索引文件快速获取文件路径
- ✅ **索引缺失**：先回退到标准 `task_id` 目录内的合法 `complete.json`
- ✅ **标准目录失败**：进入受约束递归恢复
- ✅ **索引损坏**：忽略损坏的索引，继续尝试其他合法候选
- ✅ **技能安装目录隔离**：当正式工作区结果存在时，自动忽略 `.claude/skills` 下的同 task_id 候选
- ✅ **结果自校验**：回库前先校验 `qc_result`，不允许将无效质检结果写入数据库
- ❌ **多个合法候选**：拒绝自动猜测，返回歧义错误
- ❌ **都找不到**：抛出 FileNotFoundError

### 3. 数据转换映射

| 来源字段（qc_result） | 数据库字段 | 转换规则 |
|---------|-----------|---------|
| `task_id` | `task_id` | 直接映射 |
| `qc_status` | `qc_status` | 直接映射：qualified / risky / unqualified |
| `qc_score` | `qc_score` | 直接映射：0-100 |
| `has_risk` | `has_risk` | 布尔转整型：True→1, False→0 |
| `statistics_flags.is_qualified` | `is_qualified` | 布尔转整型：True→1, False→0 |
| `statistics_flags.is_auto_approvable` | `is_auto_approvable` | 布尔转整型：True→1, False→0 |
| `statistics_flags.is_manual_required` | `is_manual_required` | 布尔转整型：True→1, False→0 |
| `statistics_flags.downgrade_issue_type` | `downgrade_issue_type` | 直接映射：consistent / missed_downgrade / unnecessary_downgrade |
| `dimension_results.downgrade_consistency.status` | `downgrade_status` | 直接映射：pass / risk / fail；旧结构 `dimension_results.downgrade.status` 仅作兼容回退 |
| `dimension_results.downgrade_consistency.is_consistent` | `is_downgrade_consistent` | 布尔转整型：True→1, False→0 |
| 完整 `qc_result` 对象 | `qc_result` | JSONB 存储 |

### 4. 输出格式

**成功时返回**：

```json
{
  "success": true,
  "task_id": "219A8C6D8C334629A7E1F164D514C381",
  "message": "质检结果已成功更新到 poi_qc_custom 表",
  "table_updated": "poi_qc_custom",
  "updated_records": 1,
  "qc_time": "2026-03-04T10:30:00Z"
}
```

**失败时返回**：

```json
{
  "success": false,
  "task_id": "219A8C6D8C334629A7E1F164D514C381",
  "error": "未找到要更新的质检记录：Task ID = xxx",
  "error_type": "ValueError"
}
```

**表名验证失败**：

```json
{
  "success": false,
  "task_id": "219A8C6D8C334629A7E1F164D514C381",
  "error": "无效的表名：table-name-with-dash",
  "error_type": "ValueError"
}
```

---

## 目录结构

```
qc-write-pg-qc-v2/
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

## 使用示例

### Python 调用

```python
from SKILL import execute, execute_batch

# ========== 基础用法 ==========

# 1. 单条写入（自动查找文件，使用默认表名 poi_qc_zk）
result = execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_dir': 'output/results'
})

# 2. 单条写入（指定文件路径，使用默认表名）
result = execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_file': 'output/results/219A8C6D8C334629A7E1F164D514C381/20260304_103000_219A8C6D8C334629A7E1F164D514C381.complete.json'
})

# ========== 新增功能：灵活表名 (v1.1.0) ✨ ==========

# 3. 单条写入（指定自定义表名）
result = execute({
    'task_id': '219A8C6D8C334629A7E1F164D514C381',
    'result_dir': 'output/results',
    'table_name': 'poi_qc_custom'  # 写入自定义表
})

# 4. 批量写入（同一表）
results = execute_batch([
    {'task_id': 'QC_001', 'result_dir': 'output/results', 'table_name': 'poi_qc_zk'},
    {'task_id': 'QC_002', 'result_dir': 'output/results', 'table_name': 'poi_qc_zk'}
])

# 5. 批量写入（不同表）
results = execute_batch([
    {'task_id': 'QC_001', 'result_dir': 'output/results', 'table_name': 'poi_qc_zk'},
    {'task_id': 'QC_002', 'result_dir': 'output/results', 'table_name': 'poi_qc_custom'},
    {'task_id': 'QC_003', 'result_dir': 'output/results', 'table_name': 'poi_qc_test'}
])
```

### 命令行调用

```bash
# 使用默认表名（poi_qc_zk）
python SKILL.py 219A8C6D8C334629A7E1F164D514C381 output/results

# 指定自定义表名（第3个参数）✨ NEW in v1.1.0
python SKILL.py 219A8C6D8C334629A7E1F164D514C381 output/results poi_qc_custom

# 查看帮助信息
python SKILL.py
```

---

## 数据库操作

### 执行的 SQL 语句

本技能对指定的表（默认或自定义）执行 UPDATE 操作。SQL 语句模式如下（表名根据参数动态替换）：

```sql
UPDATE public.<table_name>
SET
    qc_status = %s,
    qc_score = %s,
    qc_result = %s,
    has_risk = %s,
    is_qualified = %s,
    is_auto_approvable = %s,
    is_manual_required = %s,
    downgrade_issue_type = %s,
    downgrade_status = %s,
    is_downgrade_consistent = %s,
    quality_status = '已质检',
    updatetime = %s
WHERE task_id = %s
```

**例子**：

- 默认表：`UPDATE public.poi_qc_zk SET ...`
- 自定义表：`UPDATE public.poi_qc_custom SET ...`

### 表名验证规则（v1.1.0 新增）

为防止 SQL 注入，表名必须符合以下规则：

- ✅ 仅包含字母、数字、下划线
- ✅ 不能以数字开头
- ❌ 不允许特殊字符、空格、连字符等
- ❌ 不允许 SQL 关键字

**有效表名示例**：`poi_qc_zk`、`poi_qc_custom`、`QC_Result_v1`

**无效表名示例**：`poi-qc`（含连字符）、`123_table`（以数字开头）、`poi qc`（含空格）

---

## 验证命令

### PostgreSQL 查询验证

```bash
# 查询默认表（poi_qc_zk）中的最新已质检记录
psql -h <host> -U <user> -d big_poi -c \
    "SELECT task_id, qc_status, qc_score, quality_status FROM poi_qc_zk WHERE quality_status = '已质检' ORDER BY updatetime DESC LIMIT 5;"

# 查询默认表中特定 task_id 的记录
psql -h <host> -U <user> -d big_poi -c \
    "SELECT task_id, quality_status, qc_status FROM poi_qc_zk WHERE task_id = '219A8C6D8C334629A7E1F164D514C381';"

# 查询自定义表中的记录（v1.1.0）
psql -h <host> -U <user> -d big_poi -c \
    "SELECT task_id, qc_status, qc_score, quality_status FROM poi_qc_custom WHERE quality_status = '已质检' ORDER BY updatetime DESC LIMIT 5;"

# 查询所有已质检的表
psql -h <host> -U <user> -d big_poi -c \
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'poi_qc%';"
```

---

## 错误处理

| 错误码 | 说明 | 处理方式 |
|--------|------|---------|
| `FILE_NOT_FOUND` | 结果文件不存在 | 检查文件路径和任务ID是否匹配 |
| `JSON_DECODE_ERROR` | JSON文件格式错误 | 检查JSON文件格式是否有效 |
| `VALIDATION_ERROR` | 数据验证失败（缺少必需字段） | 检查 qc_result 是否符合 schema |
| `DB_ERROR` | 数据库操作失败 | 检查数据库连接和权限 |
| `INVALID_TABLE_NAME` | 表名验证失败（v1.1.0 新增）| 表名仅允许字母、数字、下划线，不能以数字开头 |
| `DUPLICATE_ERROR` | 重复记录（同一task_id已存在） | 无需重复处理，本技能保证幂等性 |

---

## 注意事项

1. **文件规范**：上游质检技能应按照指定格式生成 `.complete.json` 文件
2. **幂等性**：重复执行相同 `task_id` 的质检结果不会产生重复记录
3. **事务一致性**：写入失败时会自动回滚，确保表数据一致
4. **JSONB处理**：使用 `psycopg2.extras.Json` 包装JSON字段，确保正确编码
5. **数据映射**：统计字段自动从 `qc_result` 中提取，无需手动转换
6. **表名安全性** ✨（v1.1.0）：
   - 表名经过正则表达式验证，仅允许 `[a-zA-Z_][a-zA-Z0-9_]*` 格式
   - 防止 SQL 注入攻击
   - 无效表名会导致执行失败，返回 `ValueError`
7. **目标表要求**：
   - 无论指定哪个表，该表都必须存在于数据库
   - 该表必须包含与 `poi_qc_zk` 相同的字段结构
   - 推荐为 `task_id` 字段建立唯一索引或主键
8. **索引文件缺失处理** ✨（v1.1.0 新增）：
   - 本技能具有索引文件缺失的容错机制
   - 若 `results_index.json` 不存在或损坏，自动扫描目录查找最新的 `.complete.json` 文件
   - 这样即使上游质检技能在保存索引时失败，回库技能仍能成功运行
   - 目录扫描使用文件修改时间判断"最新"，确保获取最新的结果

---

## 作者

AI Skills Framework

---

## 更新日志

### v1.1.0 (2026-03-06)
- ✨ **新增表名参数支持**：execute() 和 write() 添加 `table_name` 参数，默认为 `poi_qc_zk`
- ✨ **灵活目标表配置**：支持指定不同的表名，适应多场景需求
- 🛡️ **增强容错机制**：新增索引文件缺失容错，当 `results_index.json` 不存在或损坏时自动扫描目录找到最新 `complete.json`
- 🔒 **增强安全性**：新增 `_validate_table_name()` 方法，防止 SQL 注入
- 📝 **更新文档**：补充表名验证规则、使用示例和索引缺失处理说明
- 🐛 **改进命令行**：支持第3个参数指定表名

### v1.0.0 (2026-03-04)
- 初始版本，支持本地化JSON文件读取
- 新增 FileLoader 类处理 .complete.json 文件加载
- 新增 DataConverter 类处理质检结果数据转换
- 使用 psycopg2.extras.Json 正确处理 JSONB 字段
- 支持文件自动查找模式（通过 result_dir 参数）
- 增强幂等性支持，避免重复插入

