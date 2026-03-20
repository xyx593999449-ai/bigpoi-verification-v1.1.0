#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库写入器 - 将转换后的数据写入 PostgreSQL
"""

import json
import psycopg2
import psycopg2.extras
import yaml
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any


class QCWriter:
    """PostgreSQL 质检结果写入器"""

    def __init__(self, config_path: str = None, logger: logging.Logger = None):
        """
        初始化数据库连接器

        Args:
            config_path: 数据库配置文件路径
            logger: 日志记录器
        """
        if config_path is None:
            script_dir = Path(__file__).parent.parent
            config_path = script_dir / "config" / "db_config.yaml"

        self.config_path = Path(config_path)
        self.logger = logger
        self.conn = None
        self.db_config = self._load_config()

    def _load_config(self) -> Dict:
        """从 YAML 文件加载数据库配置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件未找到：{self.config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"配置文件格式错误：{e}")

    def _validate_table_name(self, table_name: str) -> bool:
        """
        验证表名（防止 SQL 注入）

        Args:
            table_name: 要验证的表名

        Returns:
            表名是否有效
        """
        import re
        # 仅允许字母、数字、下划线，且不能以数字开头
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
            return False
        return True

    def connect(self):
        """建立数据库连接"""
        try:
            self.conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                database=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                connect_timeout=10,
                client_encoding='utf8'
            )
        except psycopg2.Error as e:
            raise Exception(f"数据库连接失败：{e}")

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()

    def write(self, data: Dict, table_name: str = 'poi_qc_zk') -> Dict:
        """
        将质检结果更新到指定的表

        Args:
            data: 转换后的数据字典
            table_name: 目标表名（默认为 poi_qc_zk）

        Returns:
            更新状态
        """
        try:
            task_id = data.get('task_id')
            qc_result = data.get('qc_result')

            # 验证表名（防止 SQL 注入）
            if not self._validate_table_name(table_name):
                raise ValueError(f"无效的表名：{table_name}")

            # 转换 JSON 为 JSONB
            qc_result_json = psycopg2.extras.Json(qc_result)

            cursor = self.conn.cursor()

            # 动态生成 UPDATE SQL（使用 format 方法）
            update_sql = f"""
                UPDATE public.{table_name}
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
            """

            current_time = datetime.now()

            cursor.execute(update_sql, (
                data.get('qc_status'),
                data.get('qc_score'),
                qc_result_json,
                data.get('has_risk'),
                data.get('is_qualified'),
                data.get('is_auto_approvable'),
                data.get('is_manual_required'),
                data.get('downgrade_issue_type'),
                data.get('downgrade_status'),
                data.get('is_downgrade_consistent'),
                current_time,
                task_id
            ))

            # 检查是否有行被更新
            if cursor.rowcount == 0:
                cursor.close()
                self.conn.rollback()
                raise ValueError(f"未找到要更新的质检记录：Task ID = {task_id}")

            # 提交事务
            self.conn.commit()
            rowcount = cursor.rowcount
            cursor.close()

            return {
                'success': True,
                'task_id': task_id,
                'message': f'质检结果已成功更新到 {table_name} 表',
                'table_updated': table_name,
                'updated_records': rowcount,
                'qc_time': current_time.isoformat()
            }

        except psycopg2.Error as e:
            self.conn.rollback()
            raise Exception(f"数据库操作失败：{e}")

    def write_batch(self, data_list: list, table_name: str = 'poi_qc_zk') -> Dict:
        """
        批量更新质检结果到指定的表

        Args:
            data_list: 数据字典列表
            table_name: 目标表名（默认为 poi_qc_zk）

        Returns:
            批量更新状态
        """
        success_count = 0
        failure_count = 0
        errors = []

        for idx, data in enumerate(data_list):
            try:
                result = self.write(data, table_name=table_name)
                success_count += 1
            except Exception as e:
                failure_count += 1
                errors.append({
                    'index': idx,
                    'task_id': data.get('task_id'),
                    'error': str(e)
                })

                # 尝试恢复连接
                try:
                    self.conn.rollback()
                except:
                    pass

                try:
                    self.close()
                    self.connect()
                except Exception as reconnect_error:
                    break

        return {
            'success': failure_count == 0,
            'total': len(data_list),
            'success_count': success_count,
            'failure_count': failure_count,
            'errors': errors if errors else None
        }

