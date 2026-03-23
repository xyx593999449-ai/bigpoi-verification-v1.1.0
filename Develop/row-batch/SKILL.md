---
name: row-batch
version: 1.0.0
description: 按行读取数据，并将每一行的指定字段输入到相应的技能中，进行技能的批量调用。
---------------------------------------------------------------------------------------------

# 按行批量执行技能（Row Batch Skill）

## 1. 技能目标（Skill Purpose）
本技能用于对 **CSV文件**或**数据库** 按行读取指定字段，并将字段拼接成调用指定技能所需的输入，批量调用指定技能。

本技能的核心目标一定是：

* 严格按行读取数据，不自动跳过某一行，也不重复读取某一行；
* 只有当技能执行完毕后，才开始读取下一行；
* 确保批量执行技能的效果，与单行一条一条手动触发技能的效果一致。

---

## 2. 批量执行流程（不可跳过！不要自己创建python脚本！python版本为python3）
整体流程如下：
1. 判断输入类型
2. 按行读取输入的指定字段
3. 指定技能调用
4. 记录每一行的输出结果

本技能的执行过程需遵循以下**阶段顺序**，不得跳过或颠倒以下阶段，阶段二-阶段四循环执行，直到阶段二无法获取新的行或者获取行为空，跳出循环。

### 阶段一：判断输入类型（由 Claude 处理）

* 校验输入数据格式，是否符合 `schema/input.schema.json` 定义，若为自然语言描述，需先转换为结构化数据；无法转换时，必须直接输出拒绝结果
* 如果输入数据的数据源路径以DB_开头，判断为数据库；如果输入数据的数据源路径以.csv结尾，判断为csv文件
* 不满足上述条件的输入不得进入后续流程，必须直接输出拒绝结果

**【实现说明】** 阶段一由 Claude 在 skill.md 中处理，主要任务包括：
- 解析并校验输入（结构化数据或自然语言转结构化）
- 通过 schema/input.schema.json 进行 JSON Schema 验证
- 判断数据源类型并验证其有效性
- 检查技能是否存在于 config/skill_table_map.csv 中
- 调用 `scripts/batch_executor.py` 传入已验证的参数（只需要调用脚本，任何阻塞超时问题不需要想办法解决）

**【调用示例】**
```bash
# CSV 数据源
python scripts/batch_executor.py ./test.csv skills-bigpoi-verification

# 数据库数据源
python scripts/batch_executor.py DB_#1 skills-bigpoi-verification
```

### 阶段二：按行读取输入的指定字段

**【阶段二前置】执行前置技能**
* 在按行读取数据之前，首先检查 `config/skill_table_map.csv` 中的 `pre_skill_name` 字段
* 如果配置了前置技能（多个技能用逗号分隔），按顺序执行前置技能
* 前置技能传参格式：`{"data_src_path": 数据源路径, "skill_name": 主技能名称, "worker_id": worker_id}`
* 前置技能通过 `run_claude()` 函数调用，与主技能使用相同的调用方式
* 前置技能常用于数据预处理、批次生成等场景（如 generate-batch、sample-batch）

**【实现】** `RowBatchExecutor.execute_pre_skills()` 方法 (batch_executor.py:265-309)
- 从 `skill_table_map.csv` 读取 `pre_skill_name` 配置
- 支持多个前置技能，用逗号分隔，按顺序执行
- 调用 `run_claude()` 函数执行前置技能，传入 `data_src_path`、`skill_name` 和 `worker_id`
- 前置技能执行完成后再进入主流程循环

**【初始化 Worker ID 和 Batch ID】**
* 使用雪花算法生成唯一的 worker_id
* 在前置技能执行完成后，根据 worker_id 从批次表查询 batch_id（只查询一次）
* 如果配置了 `batch_table_name` 和 `batch_id_fld`，执行查询并保存结果

**【阶段二主流程】按行读取数据**
* 如果数据源为数据库，首先从 `config/database_map.csv` 找到对应id的数据库连接信息，然后从 `config/skill_table_map.csv` 找到对应skill_name的input_table_name、input_table_flds（按逗号分割）、select_condition（筛选条件）和update_condition（更新条件）
  * 如果已获取到 batch_id，将该批次ID过滤条件添加到 `select_condition` 中
  * 最后将**数据库连接信息**、**input_table_name**、**input_table_flds**、**合并后的筛选条件**和**update_condition**作为参数调用`scripts/read_db_row.py`获取数据库中的一行的相应字段数据，组合成json格式输出（id字段转换为poi_id），注意已经获取过的行需要跳过
* 如果数据源为csv文件，首先从 `config/skill_table_map.csv` 找到对应skill_name的input_table_flds（按逗号分割），将**data_src_path**和**input_table_flds**作为参数调用`scripts/read_csv_row.py`获取CSV文件中的一行的相应字段数据，组合成json格式输出（id字段转换为poi_id），注意已经获取过的行需要跳过

**【实现】** `RowBatchExecutor.read_next_row()` 方法 (batch_executor.py:312-468)
- CSV 源：通过 `subprocess.run()` 调用 `read_csv_row.py` 脚本
- 数据库源：通过 `subprocess.run()` 调用 `read_db_row.py` 脚本
- 自动加载对应技能的字段映射 (config/skill_table_map.csv)
- 自动转换 id → poi_id 字段
- JSON 格式输出
- 使用已保存的 worker_id 和 batch_id（不再重复查询）

**【批次过滤逻辑】**
- 配置字段：
  - `batch_table_name`：批次表名（如 `public.batch_info`）
  - `batch_id_fld`：批次ID字段名（如 `batch_id`）
- 查询逻辑：
  1. 从批次表中查询：`SELECT {batch_id_fld} FROM {batch_table_name} WHERE worker_id = '{worker_id}'`
  2. 将查询结果添加到筛选条件：`{select_condition} AND {batch_id_fld} = '{查询到的batch_id}'`
- 示例：
  - `select_condition`: `quality_status='待质检'`
  - `batch_table_name`: `public.batch_info`
  - `batch_id_fld`: `batch_no`
  - `worker_id`: `1234567890`
  - 查询结果：`batch_no = 'BATCH_001'`
  - 最终条件：`(quality_status='待质检') AND batch_no = 'BATCH_001'`

**【read_db_row.py 脚本说明】**
- 位置：`scripts/read_db_row.py`
- 功能：每次从数据库读取1条满足筛选条件的数据，并立即更新数据库状态
- 工作原理：
  1. 使用 `WHERE select_condition` 查询待处理数据
  2. 使用 `LIMIT 1` 每次只取1条
  3. 读取后立即执行 `UPDATE ... SET update_condition`
  4. 下次查询时由于状态已变更，不会再读到同一条记录
- 参数：
  - db_ip, db_port, db_name, db_user, db_password：数据库连接信息
  - table_name：表名
  - fields：需要读取的字段（逗号分隔）
  - select_condition：筛选条件（WHERE子句，不含WHERE关键字）
  - update_condition：更新条件（SET子句，不含SET关键字）
- 并发控制：使用 `FOR UPDATE SKIP LOCKED` 避免并发冲突
- 无需状态文件：完全依赖数据库状态字段控制流程

### 阶段三：指定技能调用（支持重试机制）

* 将阶段一输入的调用技能名称**skill_name**和阶段二输出结果**json_data**作为参数，调用`scripts/run_claude.py`，一定要用python调用，不要直接使用技能！
* 将 **worker_id** 添加到输入数据中传递给主技能
* **重试机制**：阶段三支持最多 5 次重试，每次重试包含完整流程（主技能执行 → 回库脚本执行 → 结果检查）

**【实现】** `RowBatchExecutor.call_skill()` 方法 (batch_executor.py:726-856)
- 直接导入并调用 `run_claude()` 函数
- 传入技能名称、行数据（包含 worker_id）
- **重试循环**（最多 5 次）：
  1. 执行主技能，失败则重试
  2. 如果配置了回库脚本，执行回库 Python 脚本，失败则重试
  3. 回库成功后，检查主键 + check_condition 是否为空，为空则重试
- **失败处理**：达到最大重试次数（5次）后返回 error，结束整体执行

**【阶段三回库】执行回库 Python 脚本**
* 从 `config/skill_table_map.csv` 读取 `output_skill_py`、`output_skill_py_params` 和 `check_condition` 字段
* 根据根目录（.claude 所在目录）拼接 `output_skill_py` 找到 Python 文件
* 解析 `output_skill_py_params`：
  - 不带单引号：从行数据中获取对应 key 的值
  - 带单引号且是路径：与根目录拼接
  - 带单引号且不是路径：作为常量
* 进入到脚本所在目录，传入解析后的参数执行

**【回库结果检查】**
* 如果配置了 `check_condition`，在回库脚本执行成功后进行检查
* 自动查询数据库表主键（通过 PostgreSQL 系统表）
* 检查逻辑：`SELECT COUNT(*) FROM {table} WHERE {primary_key} = {value} AND {check_condition}`
* 如果查询结果为 0（未找到符合条件的记录），触发重试
* 如果未配置 `check_condition` 或非数据库源，跳过检查

**【配置示例】**
```csv
output_skill_py,output_skill_py_params,check_condition
"./.claude/Skills/update-pg-bigpoi/SKILL.py","",""
"./.claude/Skills/qc-write-pg-qc/SKILL.py","task_id,'./output/results'","verify_status='已质检'"
```

### 阶段四：记录每一行的输出结果

* 阶段三输出结果生成的每一个json文件带上行号和 worker_id 后缀，并额外生成一个record_map.csv文件（添加初次创建时间后缀和 worker_id）记录行号与阶段二读取的行之间的映射关系（一次任务只生成一次，循环不断往里面追加）

**【实现】**
- `RowBatchExecutor._save_output()` 方法 (batch_executor.py:859-872)：生成 `result_worker_{worker_id}_row_{row_number}.json`
- `RowBatchExecutor._append_record_map()` 方法 (batch_executor.py:874-889)：追加行号与输入数据映射到 `record_map_worker_{worker_id}_{timestamp}.csv`
- `RowBatchExecutor.execute()` 主循环 (batch_executor.py:892-979)：实现阶段二-四的循环执行

**【错误处理】**
- 如果阶段三返回 error（达到最大重试次数），立即停止所有阶段的执行
- 调用 `sys.exit(1)` 结束程序，不再处理后续行
- 在结束前记录当前行的映射关系和错误信息

**【文件命名】**
- 结果文件：`result_worker_{worker_id}_row_{row_number}.json`
- 映射文件：`record_map_worker_{worker_id}_{timestamp}.csv`
- 日志文件：`log_worker_{worker_id}.txt`（位于脚本外层目录的 tmp/ 文件夹）

---

## 3. 调用方式（Usage）

**第一步：Claude 处理阶段一（输入验证）**
```
接收用户输入 → 校验格式 → 检查数据源和技能有效性
```

**第二步：Claude 调用 batch_executor.py 执行阶段二-四**
```bash
python scripts/batch_executor.py <data_src_path> <skill_name>
```

示例：
```bash
python scripts/batch_executor.py ./test.csv skills-bigpoi-verification
python scripts/batch_executor.py DB_#1 skills-bigpoi-verification
```

## 6. 输入与输出语义（Input & Output Semantics）

### 6.1 输入语义（Input）
* 技能接收结构化数据或自然语言描述，
    * 结构化数据字段约束与格式定义见：`schema/input.schema.json`
    * 自然语言语义上至少应包含： 
        * CSV文件路径或数据库ID
        * 指定技能名称
