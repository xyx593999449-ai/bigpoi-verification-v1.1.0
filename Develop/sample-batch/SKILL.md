---
name: sample-batch
version: 1.0.0
description: 对数据库表中最新批次的数据分字段进行一定比例的抽样，支持分层抽样和多字段权重配置。
---------------------------------------------------------------------------------------------

# 批次抽样技能（Sample Batch Skill）

## 1. 技能目标（Skill Purpose）
本技能用于对 **PostgreSQL数据库** 表中最新批次的数据按照指定字段和权重进行分层抽样。

本技能的核心目标一定是：

* 严格按照配置文件读取数据选取的条件；
* 确保源表存在且可访问；
* 确保只在同一批次内进行抽样操作；
* 自动跳过已抽样的批次；
* 使用主键进行精确的状态更新；
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
| password | 数据库密码 | *** |

### 2.2 skill_table_map.csv
技能表映射配置文件，位于 `config/skill_table_map.csv`

| 字段 | 说明 | 示例 |
|------|------|------|
| skill_name | 技能名称 | BigPoi-verification-qc |
| input_table_name | 输入表名（含schema） | public.poi_qc_zk2 |
| batch_id_fld | 批次ID字段名 | batch_id |
| batch_table_name | 批次表名（含schema） | public.poi_batch_task |
| sample_flds | 抽样字段列表（逗号分隔） | batch_id |
| sample_fld_weight | 抽样字段权重列表（逗号分隔） | 1 |
| sample_ratio | 总体抽样比例（0-1） | 0.5 |
| positive_update_condition | 被抽中记录的更新条件 | quality_status='待质检' |
| negative_update_condition | 未被抽中记录的更新条件 | quality_status='未抽中' |

**注意事项：**
* `sample_flds` 和 `sample_fld_weight` 的数量必须一致
* `sample_ratio` 为 0-1 之间的小数，表示总体抽样比例
* 更新条件中的字段会被解析为状态字段，用于判断批次是否已抽样
* `batch_id_fld` 是数据表中的批次字段名，同时也是批次表中存储批次ID的字段名
* `batch_table_name` 用于根据 worker_id 查询对应的批次号

---

## 3. 批次抽样流程（不可跳过！不要自己创建python脚本）

整体流程如下：
1. 判断输入类型
2. 批次抽样

本技能的执行过程需遵循以下**阶段顺序**，不得跳过或颠倒以下阶段。

### 阶段一：判断输入类型（由 Claude 处理）

* 校验输入数据格式，是否符合 `schema/input.schema.json` 定义，若为自然语言描述，需先转换为结构化数据；无法转换时，必须直接输出拒绝结果
* 不满足上述条件的输入不得进入后续流程，必须直接输出拒绝结果

### 阶段二：批次抽样（由 python 处理）

**脚本调用方式：**

```bash
python scripts/sample_batch.py \
  --skill-name <skill_name> \
  --worker-id <worker_id> \
  --host <host> --port <port> --db <database> \
  --user <user> --password <password> \
  --table <table> \
  --sample-fields <fields> --sample-weights <weights> \
  --positive-condition <positive> \
  --negative-condition <negative>
```

**参数说明：**
| 参数 | 说明 | 示例 |
|------|------|------|
| skill-name | 技能名称，用于从配置文件读取抽样比例等参数 | BigPoi-verification-qc |
| worker-id | 工作进程ID（雪花算法生成的唯一标识，必填） | 1234567890123456789 |
| host | 数据库主机地址 | 10.82.232.122 |
| port | 数据库端口 | 5432 |
| db | 数据库名称 | big_poi |
| user | 数据库用户名 | appdeploy |
| password | 数据库密码 | *** |
| table | 输入表名（含schema） | public.poi_qc_zk2 |
| sample-fields | 抽样字段列表（逗号分隔） | batch_id |
| sample-weights | 抽样字段权重列表（逗号分隔） | 1 |
| positive-condition | 被抽中记录的更新条件 | quality_status='待质检' |
| negative-condition | 未被抽中记录的更新条件 | quality_status='未抽中' |
| primary-key | 主键字段名（可选） | id |
| log-level | 日志级别（可选，默认INFO） | INFO |
| seed | 随机种子（可选） | 12345 |

**注意：**
* 抽样比例（`sample_ratio`）从 `config/skill_table_map.csv` 配置文件中读取
* 批次ID字段（`batch_id_fld`）从 `config/skill_table_map.csv` 配置文件中读取
* 批次表（`batch_table_name`）从 `config/skill_table_map.csv` 配置文件中读取

**执行步骤：**

1. **加载配置**（步骤1-2）
   * 从 `config/database_map.csv` 加载数据库连接信息
   * 从 `config/skill_table_map.csv` 加载技能表映射配置

2. **连接数据库**（步骤3）
   * 使用提供的数据库参数建立PostgreSQL连接
   * 记录连接状态日志

3. **自动检测主键**（步骤4）
   * 从系统表中查询表的主键字段
   * 如未指定主键参数，使用检测到的主键

4. **解析状态字段**（步骤5）
   * 从 `positive_update_condition` 解析状态字段名
   * 解析已抽样的状态值列表

5. **根据 worker_id 查询批次号**（步骤6）
   * 从批次表（`batch_table_name`）中根据 `worker_id` 查询对应的批次号
   * 查询语句：`SELECT {batch_id_fld} FROM {batch_table_name} WHERE worker_id = '{worker_id}'`

6. **获取批次记录**（步骤7）
   * 从数据表中查询指定批次的所有记录
   * 包含主键和所有抽样字段

7. **执行分层抽样**（步骤8-10）
   * 按抽样字段分组
   * 根据权重分配各组抽样配额
   * 在每组内随机抽取指定数量的记录
   * 补充抽样至目标数量

8. **更新记录状态**（步骤11-12）
   * 使用主键更新被抽中记录的状态
   * 使用主键更新未被抽中记录的状态
   * 提交事务

9. **返回结果**
   * 返回执行状态、批次号、抽样统计
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
  "latest_batch": "BATCH_20260304_001",
  "total_records": 1000,
  "sampled_count": 500,
  "unsampled_count": 500
}
```

**失败输出示例：**
```json
{
  "success": false,
  "error": "没有找到可用的批次"
}
```

**输出字段说明：**
| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 执行是否成功 |
| latest_batch | string | 抽样的批次ID |
| total_records | integer | 批次总记录数 |
| sampled_count | integer | 被抽中的记录数 |
| unsampled_count | integer | 未被抽中的记录数 |
| error | string | 错误消息（失败时） |

---

## 5. 错误处理（Error Handling）

### 5.1 常见错误类型

| 错误类型 | 处理方式 |
|----------|----------|
| 配置文件不存在 | 记录错误日志，终止执行 |
| 数据库连接失败 | 记录错误日志，终止执行 |
| 表不存在 | 记录错误日志，终止执行 |
| 无法检测主键 | 使用批次字段作为标识，继续执行 |
| 所有批次已抽样 | 记录警告信息，正常返回空结果 |
| SQL执行失败 | 回滚事务，记录详细错误信息 |

### 5.2 日志记录

* 日志目录：脚本外层目录的 `tmp/` 文件夹
* 日志文件：`tmp/sample_batch_worker_{worker_id}.log`
* 日志级别：DEBUG（详细）、INFO（正常）、WARNING（警告）、ERROR（错误）
* 日志格式：`时间 - 模块名 - 级别 - 消息`
* 所有操作步骤都有详细的日志记录，包含 Worker ID 信息

---

## 6. 事务处理（Transaction Management）

* 批次抽样操作使用PostgreSQL事务确保数据一致性
* UPDATE操作在同一事务中执行
* 发生错误时自动回滚，确保数据不会部分更新
* 所有操作成功后统一提交

---

## 7. 依赖项（Dependencies）

* Python 3.x
* psycopg2（PostgreSQL数据库驱动）
* 标准库：argparse, logging, random, re, typing
