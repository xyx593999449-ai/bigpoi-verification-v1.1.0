#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批次抽样技能脚本（Sample Batch Skill Script）

本脚本用于对 PostgreSQL 数据库表中最新批次的数据分字段进行一定比例的抽样。

核心功能：
1. 连接到指定的 PostgreSQL 数据库
2. 查询指定表中最新批次的数据
3. 根据配置的抽样字段和权重进行分层抽样
4. 更新原表，标记被抽中和未抽中的记录

作者：Claude Code
版本：1.0.0
创建日期：2026-03-04
"""

import argparse
import logging
import sys
from typing import List, Dict, Tuple, Optional, Any
import random

# 第三方库导入
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


# ============================================================================
# 日志配置模块
# ============================================================================

def setup_logging(level: str = "INFO", worker_id: str = None) -> logging.Logger:
    """
    配置日志系统，输出详细的结构化日志。

    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        worker_id: 工作进程ID（可选）

    Returns:
        配置好的日志记录器
    """
    import os

    # 重新配置标准输出流为 UTF-8 编码（Windows GBK 环境兼容）
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    # 确保 tmp 目录存在（在脚本的外层目录下）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    log_dir = os.path.join(parent_dir, 'tmp')
    os.makedirs(log_dir, exist_ok=True)

    # 构建 log 文件名（包含 worker_id）
    if worker_id:
        log_file = os.path.join(log_dir, f'sample_batch_worker_{worker_id}.log')
    else:
        log_file = os.path.join(log_dir, 'sample_batch.log')

    # 创建自定义的 logger
    _logger = logging.getLogger(__name__)
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _logger.propagate = False  # 不传播到父 logger

    # 清除已有的 handlers
    _logger.handlers.clear()

    # 添加控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(console_formatter)
    _logger.addHandler(console_handler)

    # 添加文件 handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(file_formatter)
    _logger.addHandler(file_handler)

    return _logger


# 全局 logger 初始化为 None，将在 main() 函数中正确初始化
logger = None


def get_logger():
    """获取当前模块的 logger，如果未初始化则返回根 logger"""
    if logger is not None:
        return logger
    return logging.getLogger(__name__)


# ============================================================================
# 数据库连接模块
# ============================================================================

class DatabaseConnection:
    """
    数据库连接管理类，负责建立和管理与 PostgreSQL 数据库的连接。
    """

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        """
        初始化数据库连接参数。

        Args:
            host: 数据库主机地址
            port: 数据库端口
            database: 数据库名称
            user: 数据库用户名
            password: 数据库密码
        """
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.connection: Optional[Any] = None
        self.logger = logging.getLogger(__name__)

        self.logger.info("=" * 80)
        self.logger.info("初始化数据库连接")
        self.logger.info("=" * 80)

        self.logger.debug(f"数据库配置: host={host}, port={port}, database={database}, user={user}")

    def connect(self) -> None:
        """
        建立数据库连接。

        Raises:
            Exception: 连接失败时抛出异常
        """
        self.logger.info("正在尝试连接到数据库...")
        self.logger.debug(f"连接字符串: host={self.host}, port={self.port}, db={self.database}")

        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            self.connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.logger.info("✓ 数据库连接成功!")
            self.logger.info(f"  - 数据库: {self.database}")
            self.logger.info(f"  - 主机: {self.host}:{self.port}")
            self.logger.info(f"  - 用户: {self.user}")

        except Exception as e:
            self.logger.error("✗ 数据库连接失败!")
            self.logger.error(f"  错误详情: {str(e)}")
            raise

    def close(self) -> None:
        """
        关闭数据库连接。
        """
        if self.connection:
            self.logger.info("正在关闭数据库连接...")
            self.connection.close()
            self.logger.info("✓ 数据库连接已关闭")

    def execute_query(self, query: Any, params: Optional[Tuple] = None) -> List[Tuple]:
        """
        执行 SQL 查询并返回结果。

        Args:
            query: SQL 查询语句（使用 psycopg2.sql.SQL 构建）
            params: 查询参数

        Returns:
            查询结果列表

        Raises:
            Exception: 查询失败时抛出异常
        """
        self.logger.debug(f"执行查询: {query.as_string(self.connection) if params else query}")

        cursor = self.connection.cursor()

        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            result = cursor.fetchall()
            self.logger.debug(f"查询返回 {len(result)} 行结果")
            cursor.close()

            return result

        except Exception as e:
            self.logger.error(f"查询执行失败: {str(e)}")
            cursor.close()
            raise

    def execute_update(self, query: Any, params: Optional[Tuple] = None) -> int:
        """
        执行 SQL 更新语句并返回影响的行数。

        Args:
            query: SQL 更新语句（使用 psycopg2.sql.SQL 构建）
            params: 更新参数

        Returns:
            影响的行数

        Raises:
            Exception: 更新失败时抛出异常
        """
        self.logger.debug(f"执行更新: {query.as_string(self.connection) if params else query}")

        cursor = self.connection.cursor()

        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            affected_rows = cursor.rowcount
            self.logger.debug(f"更新影响了 {affected_rows} 行")
            cursor.close()

            return affected_rows

        except Exception as e:
            self.logger.error(f"更新执行失败: {str(e)}")
            cursor.close()
            raise


# ============================================================================
# 批次抽样模块
# ============================================================================

class BatchSampler:
    """
    批次抽样器，负责从数据库中按指定规则进行批次抽样。
    """

    def __init__(
        self,
        db_connection: DatabaseConnection,
        table_name: str,
        sample_fields: List[str],
        sample_weights: List[float],
        sample_ratio: float,
        positive_condition: str,
        negative_condition: str,
        primary_key: Optional[str] = None,
        batch_table_name: Optional[str] = None,
        batch_id_fld: Optional[str] = None,
        worker_id: Optional[str] = None
    ):
        """
        初始化批次抽样器。

        Args:
            db_connection: 数据库连接对象
            table_name: 输入表名
            sample_fields: 抽样字段列表
            sample_weights: 抽样字段权重列表
            sample_ratio: 总体抽样比例
            positive_condition: 被抽中记录的更新条件
            negative_condition: 未被抽中记录的更新条件
            primary_key: 主键字段名（可选，未指定时自动获取）
            batch_table_name: 批次表名（用于根据 worker_id 查询批次号）
            batch_id_fld: 批次表中批次ID字段名（同时也是数据表中的批次字段名）
            worker_id: 工作进程ID（雪花算法生成的唯一标识，必填）
        """
        # 初始化 logger
        self.logger = logging.getLogger(__name__)

        self.logger.info("=" * 80)
        self.logger.info("初始化批次抽样器")
        self.logger.info("=" * 80)
        self.logger.info(f"Worker ID: {worker_id}")

        self.db = db_connection
        self.table_name = table_name
        self.batch_id_fld = batch_id_fld
        self.sample_fields = sample_fields
        self.sample_weights = sample_weights
        self.sample_ratio = sample_ratio
        self.positive_condition = positive_condition
        self.negative_condition = negative_condition
        self.primary_key = primary_key
        self.batch_table_name = batch_table_name
        self.worker_id = worker_id

        # 参数校验
        self._validate_parameters()

        # 自动获取主键（如果未指定）
        if not self.primary_key:
            self.primary_key = self._get_primary_key()
            self.logger.info(f"✓ 自动检测到主键字段: {self.primary_key}")

        # 解析状态字段（用于判断是否已抽样）
        self.status_field = self._parse_status_field()
        self.sampled_status_values = self._parse_sampled_status_values()

        self.logger.info(f"输入表: {table_name}")
        self.logger.info(f"批次ID字段: {batch_id_fld}")
        self.logger.info(f"主键字段: {self.primary_key}")
        self.logger.info(f"抽样字段: {', '.join(sample_fields)}")
        self.logger.info(f"字段权重: {', '.join(map(str, sample_weights))}")
        self.logger.info(f"抽样比例: {sample_ratio * 100}%")
        self.logger.info(f"状态字段: {self.status_field}")
        self.logger.info(f"已抽样状态值: {self.sampled_status_values}")
        self.logger.info(f"抽中更新条件: {positive_condition}")
        self.logger.info(f"未抽中更新条件: {negative_condition}")

    def _validate_parameters(self) -> None:
        """
        验证参数的有效性。

        Raises:
            ValueError: 参数无效时抛出异常
        """
        self.logger.debug("开始参数校验...")

        if not self.table_name:
            self.logger.error("表名不能为空")
            raise ValueError("表名不能为空")

        if not self.batch_id_fld:
            self.logger.error("批次ID字段不能为空")
            raise ValueError("批次ID字段不能为空")

        if len(self.sample_fields) != len(self.sample_weights):
            self.logger.error(f"抽样字段数量({len(self.sample_fields)})与权重数量({len(self.sample_weights)})不匹配")
            raise ValueError("抽样字段与权重数量不匹配")

        if self.sample_ratio <= 0 or self.sample_ratio > 1:
            self.logger.error(f"抽样比例必须在(0, 1]范围内，当前值: {self.sample_ratio}")
            raise ValueError("抽样比例必须在(0, 1]范围内")

        self.logger.debug("✓ 参数校验通过")

    def _get_primary_key(self) -> str:
        """
        自动获取表的主键字段名。

        Returns:
            主键字段名

        Raises:
            Exception: 无法获取主键时抛出异常
        """
        self.logger.debug("正在自动检测表的主键...")

        schema_table = self.table_name.split('.')
        if len(schema_table) == 2:
            schema_name, table_name_only = schema_table
        else:
            schema_name = 'public'
            table_name_only = schema_table[0]

        query = sql.SQL("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
            AND i.indisprimary
        """)

        try:
            # 优先使用带 schema 的完整表名
            full_table = f"{schema_name}.{table_name_only}" if schema_name else table_name_only
            result = self.db.execute_query(query, (full_table,))

            if result and len(result) > 0:
                primary_key = str(result[0][0])
                self.logger.debug(f"✓ 检测到主键: {primary_key}")
                return primary_key

            # 如果失败，尝试只用表名
            result = self.db.execute_query(query, (table_name_only,))
            if result and len(result) > 0:
                primary_key = str(result[0][0])
                self.logger.debug(f"✓ 检测到主键: {primary_key}")
                return primary_key

            self.logger.warning("无法自动检测主键，将使用批次ID字段作为标识")
            return self.batch_id_fld

        except Exception as e:
            self.logger.warning(f"获取主键失败: {str(e)}，将使用批次ID字段作为标识")
            return self.batch_id_fld

    def _parse_status_field(self) -> Optional[str]:
        """
        从更新条件中解析状态字段名。

        通过解析 positive_condition，找出被更新的状态字段。

        Returns:
            状态字段名，无法解析时返回 None
        """
        self.logger.debug("正在解析状态字段...")

        # 从 positive_condition 中解析字段名
        # 格式如: "quality_status='待质检', updatetime=now()"
        import re

        # 匹配 field=value 或 field='value' 模式
        pattern = r"(\w+)\s*="
        matches = re.findall(pattern, self.positive_condition)

        if matches:
            # 优先选择包含 status 或 state 的字段名
            for field in matches:
                if 'status' in field.lower() or 'state' in field.lower():
                    self.logger.debug(f"✓ 解析到状态字段: {field}")
                    return field

            # 如果没有，使用第一个匹配的字段
            self.logger.debug(f"✓ 解析到状态字段: {matches[0]}")
            return matches[0]

        self.logger.debug("无法从更新条件中解析状态字段")
        return None

    def _parse_sampled_status_values(self) -> List[str]:
        """
        从 negative_condition 中解析已抽样的状态值。

        只从 negative_condition（未被抽中记录的更新条件）中解析状态值，
        因为只有标记为'未抽中'的记录才表示该批次已被抽样处理过。

        Returns:
            状态值列表
        """
        self.logger.debug("正在解析已抽样状态值...")

        import re

        status_values = []

        # 只从 negative_condition 中解析值（未被抽中记录的状态）
        # 格式如: "quality_status='未抽中', updatetime=now()"
        pattern = r"(\w+)\s*=\s*['\"]([^'\"]+)['\"]"
        matches = re.findall(pattern, self.negative_condition)

        for field, value in matches:
            if field == self.status_field:
                status_values.append(value)

        if status_values:
            self.logger.debug(f"✓ 解析到已抽样状态值: {status_values}")
        else:
            self.logger.debug("无法从 negative_condition 中解析已抽样状态值")

        return status_values

    def _is_batch_sampled(self, batch_id: str) -> bool:
        """
        检查指定批次是否已经被抽样过。

        通过检查批次中是否存在已标记状态的记录来判断。

        Args:
            batch_id: 批次号

        Returns:
            True 表示已抽样，False 表示未抽样
        """
        self.logger.debug(f"检查批次 {batch_id} 是否已抽样...")

        if not self.status_field or not self.sampled_status_values:
            self.logger.debug("无法判断批次抽样状态（缺少状态字段或状态值）")
            return False

        # 检查批次中是否存在任何已标记状态的记录
        query = sql.SQL("""
            SELECT COUNT(*)
            FROM {table}
            WHERE {batch_id_fld} = %s
            AND {status_field} = ANY(%s)
        """).format(
            table=sql.Identifier(*self.table_name.split('.')),
            batch_id_fld=sql.Identifier(self.batch_id_fld),
            status_field=sql.Identifier(self.status_field)
        )

        try:
            result = self.db.execute_query(query, (batch_id, self.sampled_status_values))
            count = result[0][0] if result else 0

            is_sampled = count > 0

            if is_sampled:
                self.logger.info(f"批次 {batch_id} 已抽样（发现 {count} 条已标记记录）")
            else:
                self.logger.debug(f"批次 {batch_id} 未抽样")

            return is_sampled

        except Exception as e:
            self.logger.warning(f"检查批次抽样状态失败: {str(e)}")
            return False

    def get_latest_batch(self) -> Optional[str]:
        """
        根据 worker_id 从批次表中获取对应的批次号。

        Args:
            无

        Returns:
            批次号，如果没有可用批次则返回 None

        Raises:
            Exception: 查询失败时抛出异常
        """
        self.logger.info("正在从批次表查询批次号...")
        self.logger.info(f"批次表: {self.batch_table_name}")
        self.logger.info(f"查询条件: worker_id = {self.worker_id}")

        query = sql.SQL("""
            SELECT {batch_id_fld}
            FROM {batch_table}
            WHERE worker_id = %s
            LIMIT 1
        """).format(
            batch_id_fld=sql.Identifier(self.batch_id_fld),
            batch_table=sql.Identifier(*self.batch_table_name.split('.'))
        )

        try:
            result = self.db.execute_query(query, (self.worker_id,))

            if result and len(result) > 0:
                batch_id = str(result[0][0])
                self.logger.info(f"✓ 从批次表查询到批次号: {batch_id}")
                return batch_id
            else:
                self.logger.warning(f"批次表中未找到 worker_id={self.worker_id} 对应的批次号")
                return None

        except Exception as e:
            self.logger.error(f"从批次表查询批次号失败: {str(e)}")
            raise

    def get_batch_records(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        获取指定批次的所有记录，包括主键信息。

        Args:
            batch_id: 批次号

        Returns:
            记录列表，每条记录包含主键和所有抽样字段的值

        Raises:
            Exception: 查询失败时抛出异常
        """
        self.logger.info(f"正在获取批次 {batch_id} 的记录...")

        # 构建查询字段（主键 + 批次ID字段 + 抽样字段）
        query_fields = [sql.Identifier(self.primary_key), sql.Identifier(self.batch_id_fld)]
        query_fields.extend([sql.Identifier(field) for field in self.sample_fields])

        query = sql.SQL("""
            SELECT {fields}
            FROM {table}
            WHERE {batch_id_fld} = %s
        """).format(
            fields=sql.SQL(', ').join(query_fields),
            table=sql.Identifier(*self.table_name.split('.')),
            batch_id_fld=sql.Identifier(self.batch_id_fld)
        )

        try:
            result = self.db.execute_query(query, (batch_id,))

            records = []
            for row in result:
                record = {
                    'primary_key': str(row[0]),  # 主键值
                    'batch_id': str(row[1]),      # 批次ID
                    'field_values': [str(row[i + 2]) if row[i + 2] is not None else None for i in range(len(self.sample_fields))]
                }
                records.append(record)

            self.logger.info(f"✓ 获取到 {len(records)} 条记录")
            self.logger.debug(f"  主键字段: {self.primary_key}")
            self.logger.debug(f"  记录字段: {', '.join(self.sample_fields)}")

            return records

        except Exception as e:
            self.logger.error(f"获取批次记录失败: {str(e)}")
            raise

    def perform_sampling(self, records: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        """
        根据配置的规则进行批次抽样，返回主键列表。

        Args:
            records: 待抽样的记录列表

        Returns:
            (被抽中的记录主键列表, 未被抽中的记录主键列表)
        """
        self.logger.info("=" * 80)
        self.logger.info("开始执行批次抽样")
        self.logger.info("=" * 80)
        self.logger.info(f"总记录数: {len(records)}")
        self.logger.info(f"目标抽样数: {int(len(records) * self.sample_ratio)} (约 {self.sample_ratio * 100}%)")

        # 根据抽样字段和权重进行分层抽样
        sampled_indices = set()
        remaining_indices = set(range(len(records)))

        # 计算每个字段层的样本数量
        total_samples = int(len(records) * self.sample_ratio)

        # 为每个抽样字段创建分组
        field_groups = {}
        for field_idx in range(len(self.sample_fields)):
            groups = {}
            for idx, record in enumerate(records):
                field_value = record['field_values'][field_idx]
                if field_value not in groups:
                    groups[field_value] = []
                groups[field_value].append(idx)

            field_groups[field_idx] = groups
            self.logger.debug(f"字段 {self.sample_fields[field_idx]} 分组情况:")
            for value, indices in groups.items():
                self.logger.debug(f"  - {value}: {len(indices)} 条记录")

        # 按字段权重依次抽样
        remaining_samples = total_samples

        for field_idx, weight in enumerate(self.sample_weights):
            if remaining_samples <= 0:
                break

            # 按权重分配当前字段的样本数
            field_sample_count = int(remaining_samples * weight)

            if field_sample_count <= 0:
                continue

            self.logger.info(f"字段 {self.sample_fields[field_idx]} (权重 {weight}): 抽取 {field_sample_count} 条")

            # 获取该字段的分组
            groups = field_groups[field_idx]

            # 计算每组应抽取的样本数
            group_samples = {}
            total_group_size = sum(len(indices) for indices in groups.values() if set(indices) & remaining_indices)

            for value, indices in groups.items():
                available_indices = set(indices) & remaining_indices
                if available_indices and total_group_size > 0:
                    group_sample_size = max(1, int(len(available_indices) / total_group_size * field_sample_count))
                    group_samples[value] = (available_indices, group_sample_size)

            # 从每组中抽取样本
            for value, (available_indices, sample_size) in group_samples.items():
                if len(available_indices) > 0:
                    # 从可用索引中随机抽取指定数量的样本
                    actual_sample_size = min(sample_size, len(available_indices))
                    chosen = random.sample(list(available_indices), actual_sample_size)

                    for idx in chosen:
                        sampled_indices.add(idx)
                        remaining_indices.discard(idx)

                    remaining_samples -= actual_sample_size
                    self.logger.debug(f"  - {value}: 抽取 {actual_sample_size}/{len(available_indices)} 条")

        # 如果还有剩余样本配额，从未抽中的记录中随机补充
        if remaining_samples > 0 and remaining_indices:
            additional_samples = min(remaining_samples, len(remaining_indices))
            additional_chosen = random.sample(list(remaining_indices), additional_samples)

            for idx in additional_chosen:
                sampled_indices.add(idx)
                remaining_indices.discard(idx)

            self.logger.info(f"补充抽样: 额外抽取 {additional_samples} 条记录")

        # 获取被抽中和未被抽中的记录主键（使用主键而非批次ID）
        sampled_pks = [records[i]['primary_key'] for i in sorted(sampled_indices)]
        unsampled_pks = [records[i]['primary_key'] for i in sorted(remaining_indices)]

        self.logger.info("=" * 80)
        self.logger.info("抽样完成统计")
        self.logger.info("=" * 80)
        self.logger.info(f"被抽中记录数: {len(sampled_pks)} ({len(sampled_pks)/len(records)*100:.1f}%)")
        self.logger.info(f"未被抽中记录数: {len(unsampled_pks)} ({len(unsampled_pks)/len(records)*100:.1f}%)")

        return sampled_pks, unsampled_pks

    def _build_set_clause(self, condition: str) -> sql.Composed:
        """
        从更新条件字符串构建安全的 SQL SET 子句。

        解析形如 "field1='value1', field2=now()" 的条件字符串，
        并构建安全的 SQL SET 子句。

        Args:
            condition: 更新条件字符串

        Returns:
            psycopg2.sql.Composed 对象
        """
        import re

        set_parts = []
        # 解析 field=value 格式，支持引号和函数
        # 匹配: field='value' 或 field=value 或 field=function()
        pattern = r"(\w+)\s*=\s*(.+?)(?:\s*,\s*|\s*$)"

        for match in re.finditer(pattern, condition.strip()):
            field = match.group(1)
            value = match.group(2).strip()

            # 判断值的类型
            if value.startswith("'") and value.endswith("'"):
                # 字符串字面量
                set_parts.append(sql.SQL("{0} = {1}").format(
                    sql.Identifier(field),
                    sql.SQL(value)
                ))
            elif value.startswith('"') and value.endswith('"'):
                # 字符串字面量（双引号）
                set_parts.append(sql.SQL("{0} = {1}").format(
                    sql.Identifier(field),
                    sql.SQL(value)
                ))
            elif re.match(r'^[a-z_]+\(\)$', value, re.IGNORECASE):
                # SQL 函数（如 now()）
                set_parts.append(sql.SQL("{0} = {1}()").format(
                    sql.Identifier(field),
                    sql.SQL(value[:-2])
                ))
            elif value.isdigit() or re.match(r'^\d+\.\d+$', value):
                # 数字
                set_parts.append(sql.SQL("{0} = {1}").format(
                    sql.Identifier(field),
                    sql.SQL(value)
                ))
            else:
                # 其他情况，作为 SQL 片段处理
                set_parts.append(sql.SQL("{0} = {1}").format(
                    sql.Identifier(field),
                    sql.SQL(value)
                ))

        return sql.SQL(', ').join(set_parts)

    def update_records(self, sampled_pks: List[str], unsampled_pks: List[str]) -> None:
        """
        更新数据库中的抽样状态，使用主键进行更新。

        Args:
            sampled_pks: 被抽中的记录主键列表
            unsampled_pks: 未被抽中的记录主键列表

        Raises:
            Exception: 更新失败时抛出异常
        """
        self.logger.info("=" * 80)
        self.logger.info("开始更新数据库记录（按主键更新）")
        self.logger.info("=" * 80)
        self.logger.info(f"主键字段: {self.primary_key}")

        # 更新被抽中的记录（使用主键）
        if sampled_pks:
            self.logger.info(f"更新被抽中的 {len(sampled_pks)} 条记录...")
            self.logger.debug(f"更新条件: {self.positive_condition}")

            set_clause = self._build_set_clause(self.positive_condition)

            query = sql.SQL("""
                UPDATE {table}
                SET {set_clause}
                WHERE {primary_key} = ANY(%s)
            """).format(
                table=sql.Identifier(*self.table_name.split('.')),
                set_clause=set_clause,
                primary_key=sql.Identifier(self.primary_key)
            )

            try:
                affected = self.db.execute_update(query, (sampled_pks,))
                self.logger.info(f"✓ 成功更新 {affected} 条被抽中的记录")
                if affected != len(sampled_pks):
                    self.logger.warning(f"更新行数({affected})与传入主键数({len(sampled_pks)})不一致")
            except Exception as e:
                self.logger.error(f"更新被抽中记录失败: {str(e)}")
                raise

        # 更新未被抽中的记录（使用主键）
        if unsampled_pks:
            self.logger.info(f"更新未被抽中的 {len(unsampled_pks)} 条记录...")
            self.logger.debug(f"更新条件: {self.negative_condition}")

            set_clause = self._build_set_clause(self.negative_condition)

            query = sql.SQL("""
                UPDATE {table}
                SET {set_clause}
                WHERE {primary_key} = ANY(%s)
            """).format(
                table=sql.Identifier(*self.table_name.split('.')),
                set_clause=set_clause,
                primary_key=sql.Identifier(self.primary_key)
            )

            try:
                affected = self.db.execute_update(query, (unsampled_pks,))
                self.logger.info(f"✓ 成功更新 {affected} 条未被抽中的记录")
                if affected != len(unsampled_pks):
                    self.logger.warning(f"更新行数({affected})与传入主键数({len(unsampled_pks)})不一致")
            except Exception as e:
                self.logger.error(f"更新未被抽中记录失败: {str(e)}")
                raise

        self.logger.info("=" * 80)
        self.logger.info("✓ 所有记录更新完成")
        self.logger.info("=" * 80)

    def run(self) -> Dict[str, Any]:
        """
        执行完整的批次抽样流程。

        Returns:
            包含执行结果的字典

        Raises:
            Exception: 执行失败时抛出异常
        """
        self.logger.info("")
        self.logger.info("╔" + "=" * 78 + "╗")
        self.logger.info("║" + " " * 20 + "开始执行批次抽样流程" + " " * 35 + "║")
        self.logger.info("╚" + "=" * 78 + "╝")
        self.logger.info("")

        result = {
            'success': False,
            'latest_batch': None,
            'total_records': 0,
            'sampled_count': 0,
            'unsampled_count': 0,
            'error': None
        }

        try:
            self.logger.info(f"Worker ID: {self.worker_id}")
            # 步骤1: 获取最新批次
            latest_batch = self.get_latest_batch()

            if not latest_batch:
                self.logger.warning("没有找到可用的批次，流程终止")
                result['error'] = "没有找到可用的批次"
                return result

            result['latest_batch'] = latest_batch

            # 步骤2: 获取批次记录
            records = self.get_batch_records(latest_batch)

            if not records:
                self.logger.warning(f"批次 {latest_batch} 中没有找到记录")
                result['error'] = f"批次 {latest_batch} 中没有找到记录"
                return result

            result['total_records'] = len(records)

            # 步骤3: 执行抽样
            sampled_ids, unsampled_ids = self.perform_sampling(records)

            result['sampled_count'] = len(sampled_ids)
            result['unsampled_count'] = len(unsampled_ids)

            # 步骤4: 更新数据库
            self.update_records(sampled_ids, unsampled_ids)

            result['success'] = True

            self.logger.info("")
            self.logger.info("╔" + "=" * 78 + "╗")
            self.logger.info("║" + " " * 25 + "批次抽样执行成功!" + " " * 30 + "║")
            self.logger.info("╚" + "=" * 78 + "╝")
            self.logger.info("")

        except Exception as e:
            self.logger.error(f"批次抽样流程执行失败: {str(e)}")
            result['error'] = str(e)

        return result


# ============================================================================
# 命令行接口模块
# ============================================================================

# ============================================================================
# 配置文件读取模块
# ============================================================================

def load_skill_config(skill_name: str) -> Dict[str, Any]:
    """
    从 skill_table_map.csv 中加载指定技能的配置。

    Args:
        skill_name: 技能名称

    Returns:
        包含配置的字典

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置无效或找不到指定技能
    """
    import os
    import csv

    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')
    config_file = os.path.join(config_dir, 'skill_table_map.csv')

    logger.debug(f"正在加载配置文件: {config_file}")

    if not os.path.exists(config_file):
        raise FileNotFoundError(f"配置文件不存在: {config_file}")

    with open(config_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            if row['skill_name'] == skill_name:
                config = {
                    'input_table_name': row['input_table_name'],
                    'batch_id_fld': row.get('batch_id_fld', '').strip(),
                    'batch_table_name': row.get('batch_table_name', '').strip(),
                    'sample_flds': [f.strip() for f in row['sample_flds'].split(',')],
                    'sample_fld_weight': [float(w.strip()) for w in row['sample_fld_weight'].split(',')],
                    'sample_ratio': float(row['sample_ratio']),
                    'positive_update_condition': row['positive_update_condition'],
                    'negative_update_condition': row['negative_update_condition']
                }

                logger.debug(f"✓ 从配置文件加载到技能配置: {skill_name}")
                logger.debug(f"  输入表: {config['input_table_name']}")
                logger.debug(f"  批次ID字段: {config['batch_id_fld']}")
                logger.debug(f"  批次表: {config['batch_table_name']}")
                logger.debug(f"  抽样字段: {config['sample_flds']}")
                logger.debug(f"  抽样权重: {config['sample_fld_weight']}")
                logger.debug(f"  抽样比例: {config['sample_ratio']}")

                return config

    raise ValueError(f"在配置文件中找不到技能: {skill_name}")


def parse_arguments() -> argparse.Namespace:
    """
    解析命令行参数。

    Returns:
        解析后的参数对象
    """
    parser = argparse.ArgumentParser(
        description='批次抽样工具 - 对数据库表中最新批次的数据按字段进行随机抽样',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  python sample_batch.py --skill-name BigPoi-verification-qc \\
    --host localhost --port 5432 --db mydb --user user --password pass \\
    --worker-id "1234567890123456789" \\
    --table public.mytable --sample-fields field1,field2 \\
    --sample-weights 0.5,0.5 \\
    --positive-condition "status='sampled',update_time=now()" \\
    --negative-condition "status='unsampled',update_time=now()"

注意：
  - 抽样比例 (sample_ratio) 从 skill_table_map.csv 配置文件中读取
  - 批次ID字段 (batch_id_fld) 从 skill_table_map.csv 配置文件中读取
        '''
    )

    # 技能配置
    skill_group = parser.add_argument_group('技能配置')
    skill_group.add_argument('--skill-name', required=True, help='技能名称，用于从配置文件读取抽样比例等参数')
    skill_group.add_argument('--worker-id', required=True, help='工作进程ID（雪花算法生成的唯一标识，必填）')

    # 数据库连接参数
    db_group = parser.add_argument_group('数据库连接参数')
    db_group.add_argument('--host', required=True, help='数据库主机地址')
    db_group.add_argument('--port', type=int, required=True, help='数据库端口')
    db_group.add_argument('--db', required=True, help='数据库名称')
    db_group.add_argument('--user', required=True, help='数据库用户名')
    db_group.add_argument('--password', required=True, help='数据库密码')

    # 表和字段配置
    table_group = parser.add_argument_group('表和字段配置')
    table_group.add_argument('--table', required=True, help='输入表名 (包含 schema，如 public.mytable)')
    table_group.add_argument('--primary-key', help='主键字段名 (可选，未指定时自动检测)')
    table_group.add_argument('--sample-fields', required=True, help='抽样字段列表，逗号分隔')
    table_group.add_argument('--sample-weights', required=True, help='抽样字段权重列表，逗号分隔 (0-1之间)')

    # 更新条件
    update_group = parser.add_argument_group('更新条件')
    update_group.add_argument('--positive-condition', required=True, help='被抽中记录的更新条件 (SQL SET 子句)')
    update_group.add_argument('--negative-condition', required=True, help='未被抽中记录的更新条件 (SQL SET 子句)')

    # 其他选项
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='日志级别 (默认: INFO)')
    parser.add_argument('--seed', type=int, help='随机种子，用于可重复抽样')

    return parser.parse_args()


def main() -> int:
    """
    主函数，解析参数并执行批次抽样。

    Returns:
        程序退出码 (0 表示成功，非 0 表示失败)
    """
    args = parse_arguments()

    # 设置日志级别
    global logger
    logger = setup_logging(args.log_level, args.worker_id)

    # 设置随机种子
    if args.seed is not None:
        random.seed(args.seed)
        logger.info(f"使用随机种子: {args.seed}")

    try:
        # 从配置文件读取技能配置（包含抽样比例）
        skill_config = load_skill_config(args.skill_name)

        # 创建数据库连接
        db_connection = DatabaseConnection(
            host=args.host,
            port=args.port,
            database=args.db,
            user=args.user,
            password=args.password
        )
        db_connection.connect()

        # 解析抽样字段和权重
        sample_fields = [f.strip() for f in args.sample_fields.split(',')]
        sample_weights = [float(w.strip()) for w in args.sample_weights.split(',')]

        # 归一化权重
        total_weight = sum(sample_weights)
        if total_weight > 0:
            sample_weights = [w / total_weight for w in sample_weights]

        # 从配置文件读取抽样比例
        sample_ratio = skill_config['sample_ratio']
        logger.info(f"从配置文件读取抽样比例: {sample_ratio} ({sample_ratio * 100}%)")

        # 创建批次抽样器
        sampler = BatchSampler(
            db_connection=db_connection,
            table_name=args.table,
            sample_fields=sample_fields,
            sample_weights=sample_weights,
            sample_ratio=sample_ratio,
            positive_condition=args.positive_condition,
            negative_condition=args.negative_condition,
            primary_key=args.primary_key,
            batch_table_name=skill_config.get('batch_table_name', ''),
            batch_id_fld=skill_config.get('batch_id_fld', ''),
            worker_id=args.worker_id
        )

        # 执行抽样
        result = sampler.run()

        # 关闭数据库连接
        db_connection.close()

        # 返回结果
        if result['success']:
            logger.info("")
            logger.info("=" * 80)
            logger.info("最终执行结果:")
            logger.info(f"  Worker ID: {args.worker_id}")
            logger.info(f"  批次ID: {result['latest_batch']}")
            logger.info(f"  总记录数: {result['total_records']}")
            logger.info(f"  被抽中: {result['sampled_count']}")
            logger.info(f"  未被抽中: {result['unsampled_count']}")
            logger.info("=" * 80)
            logger.info("")
            return 0
        else:
            logger.error(f"执行失败: {result.get('error', '未知错误')}")
            return 1

    except Exception as e:
        logger.error(f"程序异常: {str(e)}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
