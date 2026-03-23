---
name: generate-batch
version: 1.0.0
description: 选取表A的指定条件、字段、数量数据插入到表B，并生成对应批次号。
---------------------------------------------------------------------------------------------

# 批次生成技能（Generate Batch Skill）

## 1. 技能目标（Skill Purpose）
本技能用于对 **PostgreSQL数据库** 表A选取指定条件的数据，作为一个批次插入到表B，并生成唯一批次号。

本技能的核心目标一定是：

* 严格按照配置文件读取数据选取的条件；
* 确保表A和表B都存在；
* 确保同一时间产生的批次号相同，不同时间产生的批次号不同；
* 支持事务处理，确保数据一致性；
* 提供详细的日志记录。

---

## 2. 配置文件说明（Configuration Files）

### 2.1 database_map.csv
数据库连接映射文件，位于 `config/database_map.csv`

| 字段 | 说明 | 示例 |
|------|------|------|
| id | 数据库唯一标识 | DB_#1 |
| ip | 数据库IP地址 | 10.82.232.122 |
| port | 数据库端口 | 5432 |
| db | 数据库名称 | big_poi |
| user | 数据库用户名 | appdeploy |
| password | 数据库密码 | ywIu5IFAQrHqsnb |

### 2.2 skill_table_map.csv
技能表映射配置文件，位于 `config/skill_table_map.csv`

| 字段 | 说明 | 示例 |
|------|------|------|
| skill_name | 技能名称 | BigPoi-verification-qc |
| input_table_name | 源表名（含schema） | public.poi_verify_zk |
| input_table_flds | 需要选取的字段（逗号分隔） | "task_id,id,name,x_coord" |
| select_condition | 筛选条件（支持{batch_id}占位符） | verify_status='已核实' |
| select_limit | 限制选取条数 | 1000000 |
| update_condition | 更新条件（支持{batch_id}占位符） | verify_status='生成批次{batch_id}' |
| output_table_name | 目标表名（含schema） | public.poi_qc_zk2 |
| batch_table_name | 批次表名（含schema），用于存储worker_id和批次号的映射关系 | public.poi_batch_task |

**注意事项：**
* `input_table_flds` 支持带引号的字段列表，用于处理包含特殊字符的字段名
* `select_condition` 和 `update_condition` 中的 `{batch_id}` 会被替换为实际批次号
* `update_condition` 可为空，表示不更新源表状态

---

## 3. 批次生成流程（不可跳过！不要自己创建python脚本）

整体流程如下：
1. 判断输入类型
2. 批次生成

本技能的执行过程需遵循以下**阶段顺序**，不得跳过或颠倒以下阶段。

### 阶段一：判断输入类型（由 Claude 处理）

* 校验输入数据格式，是否符合 `schema/input.schema.json` 定义，若为自然语言描述，需先转换为结构化数据；无法转换时，必须直接输出拒绝结果
* 不满足上述条件的输入不得进入后续流程，必须直接输出拒绝结果

### 阶段二：批次生成（由 python 处理）

**脚本调用方式：**

```bash
python scripts/generate_batch.py <db_id> <db_ip> <db_port> <db_name> <db_user> <db_password> <skill_name> <config_dir> <worker_id>
```

**参数说明：**
| 参数 | 说明 | 示例 |
|------|------|------|
| db_id | 数据库ID | DB_#1 |
| db_ip | 数据库IP地址 | 10.82.232.122 |
| db_port | 数据库端口 | 5432 |
| db_name | 数据库名称 | big_poi |
| db_user | 数据库用户名 | appdeploy |
| db_password | 数据库密码 | ywIu5IFAQrHqsnb |
| skill_name | 技能名称 | BigPoi-verification-qc |
| config_dir | 配置文件目录 | .claude/Skills/generate-batch/config |
| worker_id | 工作进程ID（雪花算法生成的唯一标识，必填，字符串类型） | 1234567890123456789 |

**执行步骤：**

1. **加载配置**（步骤1-2）
   * 从 `config/database_map.csv` 加载数据库连接信息
   * 从 `config/skill_table_map.csv` 加载技能表映射配置

2. **连接数据库**（步骤3）
   * 使用提供的数据库参数建立PostgreSQL连接
   * 记录连接状态日志

3. **生成批次号**（步骤4）
   * 生成格式为 `BATCH_YYYYMMDD_HH_MM_SS_{worker_id}` 的唯一批次号
   * worker_id 会被追加到批次号末尾，确保不同 worker 生成的批次号不同
   * 确保同一时间同一 worker 产生的批次号唯一

4. **检查表存在性**（步骤5）
   * 验证源表（input_table_name）是否存在
   * 验证目标表（output_table_name）是否存在
   * 任一表不存在则终止操作

5. **解析字段**（步骤6）
   * 解析 `input_table_flds` 字段列表
   * 支持带引号的复杂字段名

6. **构建查询**（步骤7-8）
   * 替换 `select_condition` 中的 `{batch_id}` 占位符
   * 构建SELECT查询语句，应用筛选条件和限制条数

7. **执行查询**（步骤9）
   * 从源表选取符合条件的数据
   * 记录选取的记录数量

8. **插入数据**（步骤10-12）
   * 构建INSERT语句，将数据插入目标表
   * 执行批量插入操作
   * 提交事务

9. **更新源表状态**（步骤13）
   * 如果配置了 `update_condition`，更新源表中被选取记录的状态
   * 再次提交事务

10. **插入批次记录**（步骤14）
    * 如果配置了 `batch_table_name`，将 worker_id 和生成的批次号插入到批次表
    * 批次表需要包含以下字段：worker_id（字符串类型）、batch_id（字符串类型）、create_time（时间戳）
    * 记录 worker_id 与 batch_id 的映射关系，便于后续根据 worker_id 查询批次号

11. **返回结果**
    * 返回执行状态、批次号、处理记录数
    * 输出JSON格式结果便于解析

---

## 4. 输入与输出语义（Input & Output Semantics）

### 4.1 输入语义（Input）
* 技能接收结构化数据或自然语言描述，
    * 结构化数据字段约束与格式定义见：`schema/input.schema.json`
    * 自然语言语义上至少应包含：
        * 数据库ID（data_src_path）
        * 技能名称（skill_name）

**输入示例（JSON）：**
```json
{
  "data_src_path": "DB_#1",
  "skill_name": "BigPoi-verification-qc",
  "worker_id": "1234567890123456789"
}
```

### 4.2 输出语义（Output）

**成功输出示例：**
```json
{
  "success": true,
  "worker_id": "1234567890123456789",
  "batch_id": "BATCH_20260303_14_35_20_1234567890123456789",
  "count": 1000
}
```

**失败输出示例：**
```json
{
  "success": false,
  "worker_id": "1234567890123456789",
  "batch_id": "",
  "count": 0
}
```

**输出字段说明：**
| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 批次生成是否成功 |
| worker_id | string | 工作进程ID |
| batch_id | string | 生成的批次号，失败时为空 |
| count | integer | 处理的记录数量 |

---

## 5. 错误处理（Error Handling）

### 5.1 常见错误类型

| 错误类型 | 处理方式 |
|----------|----------|
| 配置文件不存在 | 记录错误日志，终止执行 |
| 数据库连接失败 | 记录错误日志，终止执行 |
| 源表不存在 | 记录错误日志，终止执行 |
| 目标表不存在 | 记录错误日志，终止执行 |
| SQL执行失败 | 回滚事务，记录详细错误信息 |
| 无数据符合条件 | 记录警告信息，正常返回 |

### 5.2 日志记录

* 日志目录：脚本外层目录的 `tmp/` 文件夹（自动创建）
* 日志文件：`tmp/generate_batch_worker_{worker_id}.log`
* 日志级别：INFO（正常信息）、ERROR（错误）、WARNING（警告）
* 日志格式：`时间 - 模块名 - 级别 - 消息`
* 所有操作步骤都有详细的日志记录，包含 Worker ID 信息

---

## 6. 事务处理（Transaction Management）

* 批次生成操作使用PostgreSQL事务确保数据一致性
* INSERT和UPDATE操作在同一事务中执行
* 发生错误时自动回滚，确保数据不会部分更新
* 所有操作成功后统一提交

---

## 7. 依赖项（Dependencies）

* Python 3.x
* psycopg2（PostgreSQL数据库驱动）
* 标准库：csv, os, sys, logging, datetime
