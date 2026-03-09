#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库写入器模块
提供将核实结果写入PostgreSQL数据库的功能
版本: 1.4.0
"""

import json
import sys
import psycopg2
import psycopg2.extras
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

# 确保可以导入同目录下的模块
try:
    from logger_config import get_logger
except ImportError:
    # 如果导入失败，尝试相对导入
    from .logger_config import get_logger

logger = get_logger(__name__)


class VerifiedResultWriter:
    """
    PostgreSQL 核实结果写入器

    功能：
    1. 仅支持索引文件模式加载JSON数据
    2. 使用 psycopg2.extras.Json 处理 JSONB 字段
    3. 原子性事务保证数据一致性
    4. 完整的幂等性支持
    5. 确保原始表状态同步更新
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化数据库写入器

        Args:
            config_path: 数据库配置文件路径，默认为 config/db_config.yaml
        """
        if config_path is None:
            script_dir = Path(__file__).parent
            config_path = script_dir.parent / "config" / "db_config.yaml"

        self.config_path = Path(config_path)
        self.db_config = self._load_config()
        self.conn = None
        self.converter = None  # 延迟导入避免循环依赖

    def _load_config(self) -> Dict:
        """从 YAML 文件加载数据库配置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            logger.info(f"数据库配置加载成功：{self.config_path}")
            return config
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件未找到：{self.config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"配置文件格式错误：{e}")

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
            self.conn.set_client_encoding('UTF8')
            logger.info(f"数据库连接成功：{self.db_config['host']}:{self.db_config['port']}")
        except psycopg2.Error as e:
            logger.error(f"数据库连接失败：{e}")
            raise Exception(f"数据库连接失败：{e}")

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")

    def _convert_to_json(self, data: Any) -> Optional[psycopg2.extras.Json]:
        """
        将数据转换为 psycopg2.extras.Json 对象

        使用 psycopg2.extras.Json() 包装，确保正确处理 JSONB 字段

        Args:
            data: 可以是字典、列表或已经是 JSON 字符串

        Returns:
            psycopg2.extras.Json 对象或 None
        """
        if data is None:
            return None
        if isinstance(data, str):
            try:
                parsed_dict = json.loads(data)
                return psycopg2.extras.Json(parsed_dict)
            except json.JSONDecodeError:
                raise ValueError(f"JSON 字符串格式错误：{data}")
        elif isinstance(data, (dict, list)):
            return psycopg2.extras.Json(data)
        else:
            raise ValueError(f"无法转换为 JSON：{type(data)}")

    def _check_task_exists(self, task_id: str) -> bool:
        """
        检查成果表中是否已存在该 task_id

        Args:
            task_id: 任务ID

        Returns:
            存在返回 True，否则返回 False
        """
        try:
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("""
                SELECT 1 FROM public.poi_verified
                WHERE task_id = %s
                LIMIT 1
            """, (task_id,))
            result = cursor.fetchone() is not None
            cursor.close()
            return result
        except psycopg2.Error as e:
            raise Exception(f"检查 task_id 是否存在失败：{e}")

    def _validate_input(self, data: Dict) -> bool:
        """
        验证输入数据的必要字段

        Args:
            data: 输入的 POI 核实数据（必须包含 index_file 字段）

        Returns:
            验证通过返回 True，否则抛出异常
        """
        if 'index_file' not in data:
            raise ValueError("缺少必需字段：index_file")

        if not data['index_file']:
            raise ValueError("index_file 字段不能为空")

        return True

    def write(self, data: Dict) -> Dict:
        """
        写入单条核实结果

        输入模式：仅支持索引文件模式
        data = {'index_file': 'path/to/index.json'}

        Args:
            data: 输入数据（必须包含 index_file 字段）

        Returns:
            包含写入状态的字典
        """
        try:
            # 验证输入
            self._validate_input(data)

            # 从索引文件写入
            return self._write_from_index_file(data['index_file'])

        except Exception as e:
            logger.error(f"写入失败：{e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _write_from_index_file(self, index_file_path: str) -> Dict:
        """
        从索引文件写入核实结果

        Args:
            index_file_path: 索引文件路径

        Returns:
            包含写入状态的字典
        """
        # 延迟导入避免循环依赖
        from file_loader import FileLoader
        from data_converter import DataConverter

        loader = FileLoader()
        converter = DataConverter()

        # 加载所有数据
        all_data = loader.load_all_from_index(index_file_path, load_evidence=True, load_record=True)

        index_data = all_data['index']
        decision = all_data['decision']
        evidence = all_data.get('evidence', [])
        record = all_data.get('record', {})

        # 提取 POI 基础信息
        # 优先级：record.verification_result.final_values > record.input_data > index.poi_data
        if record and 'verification_result' in record and 'final_values' in record['verification_result']:
            logger.info("从 record.verification_result.final_values 中提取核实后的POI信息")
            final_values = record['verification_result']['final_values']
            coordinates = final_values.get('coordinates', {})
            poi_data = {
                'id': record.get('poi_id', index_data.get('poi_id', '')),
                'name': final_values.get('name', ''),
                'x_coord': coordinates.get('longitude'),  # 经度 -> x_coord
                'y_coord': coordinates.get('latitude'),   # 纬度 -> y_coord
                'poi_type': final_values.get('category'),  # category -> poi_type
                'address': final_values.get('address'),
                'city': final_values.get('city'),
                'city_adcode': ''  # final_values 中可能没有此字段，回退到 input_data 获取
            }
            # 如果 final_values 没有 city_adcode，尝试从 input_data 获取
            if not poi_data['city_adcode'] and 'input_data' in record:
                poi_data['city_adcode'] = record['input_data'].get('city_adcode', '')
        elif record and 'input_data' in record:
            logger.info("从 record.input_data 中提取 POI 基础信息（未找到 final_values，使用原始数据）")
            input_data = record['input_data']
            coordinates = input_data.get('coordinates', {})
            poi_data = {
                'id': record.get('poi_id', index_data.get('poi_id', '')),
                'name': input_data.get('name', ''),
                'x_coord': coordinates.get('longitude'),  # 经度 -> x_coord
                'y_coord': coordinates.get('latitude'),   # 纬度 -> y_coord
                'poi_type': input_data.get('poi_type'),
                'address': input_data.get('address'),
                'city': input_data.get('city'),
                'city_adcode': input_data.get('city_adcode', '')
            }
        elif 'poi_data' in index_data:
            logger.info("从索引文件的 poi_data 中提取 POI 基础信息")
            poi_data = index_data['poi_data']
        else:
            logger.warning("未找到 POI 基础信息，使用空字典")
            poi_data = {
                'id': index_data.get('poi_id', ''),
                'name': '',
                'x_coord': None,
                'y_coord': None,
                'poi_type': None,
                'address': '',
                'city': '',
                'city_adcode': ''
            }

        # 转换为数据库格式
        # 传递索引文件的 task_id，确保使用正确的 task_id 而非 decision.poi_id
        task_id = index_data.get('task_id', '')
        db_data = converter.decision_to_db_format(decision, evidence, poi_data, task_id=task_id)

        # 执行数据库写入
        return self._execute_db_write(db_data)

    def _execute_db_write(self, db_data: Dict) -> Dict:
        """
        执行数据库写入操作

        重要说明：
        1. 即使成果表已存在该 task_id，也会执行原始表状态更新
        2. 这样确保原始表状态始终能同步更新为'已核实'

        Args:
            db_data: 数据库格式数据

        Returns:
            包含写入状态的字典
        """
        task_id = db_data['task_id']
        poi_id = db_data['id']

        logger.info(f"开始写入核实结果：task_id = {task_id}, POI ID = {poi_id}")

        # 检查幂等性
        task_exists = self._check_task_exists(task_id)

        if task_exists:
            logger.warning(f"task_id {task_id} 已存在于成果表中，仅更新原始表状态")

        # 准备数据
        current_time = datetime.now()

        # 执行事务
        cursor = self.conn.cursor()
        try:
            # 步骤1：如果不存在，插入成果表
            if not task_exists:
                # 转换 JSON 数据为 psycopg2.extras.Json 对象
                verify_info_json = self._convert_to_json(db_data.get('verify_info'))
                evidence_record_json = self._convert_to_json(db_data.get('evidence_record'))
                changes_made_json = self._convert_to_json(db_data.get('changes_made'))

                insert_sql = """
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
                """

                cursor.execute(insert_sql, (
                    task_id,
                    db_data['id'],
                    db_data.get('name', ''),
                    db_data.get('x_coord'),
                    db_data.get('y_coord'),
                    db_data.get('poi_type'),
                    db_data.get('address'),
                    db_data.get('city'),
                    db_data.get('city_adcode'),
                    db_data.get('verify_status', '已核实'),
                    db_data['verify_result'],
                    db_data.get('overall_confidence'),
                    db_data.get('poi_status', 1),
                    task_id,
                    db_data['id'],
                    verify_info_json,
                    evidence_record_json,
                    changes_made_json,
                    db_data.get('verification_notes'),
                    current_time,
                    current_time,
                    'system',
                    '1.4.0'
                ))

            # 步骤2：更新原始表状态为'已核实'（无论成果表是否已存在）
            update_sql = """
                UPDATE public.poi_init
                SET verify_status = %s, updatetime = %s
                WHERE task_id = %s
            """

            cursor.execute(update_sql, ('已核实', current_time, task_id))

            # 检查是否更新了原始表
            if cursor.rowcount == 0:
                logger.warning(f"原始表未找到 task_id = {task_id} 的记录，可能已被删除")

            # 提交事务
            self.conn.commit()
            logger.info(f"核实结果写入成功：task_id = {task_id}, 原始表状态已更新")

            return {
                'success': True,
                'task_id': task_id,
                'poi_id': poi_id,
                'message': 'POI 核实结果已成功写入' if not task_exists else 'POI 核实结果已存在，原始表状态已更新',
                'tables_updated': ['poi_init'] if task_exists else ['poi_verified', 'poi_init'],
                'verify_time': current_time.isoformat(),
                'skipped': task_exists
            }

        except Exception as e:
            self.conn.rollback()
            cursor.close()
            logger.error(f"数据库操作失败：{e}")
            raise e
        finally:
            cursor.close()

    def write_batch(self, data_list: List[Dict]) -> Dict:
        """
        批量写入核实结果

        Args:
            data_list: 数据列表（每个元素可以是索引文件路径或直接数据）

        Returns:
            包含批量写入状态的字典
        """
        success_count = 0
        failure_count = 0
        skipped_count = 0
        errors = []

        for idx, data in enumerate(data_list):
            try:
                result = self.write(data)
                if result.get('success'):
                    if result.get('skipped'):
                        skipped_count += 1
                    else:
                        success_count += 1
                else:
                    failure_count += 1
                    errors.append({
                        'index': idx,
                        'task_id': data.get('task_id') or data.get('index_file', 'unknown'),
                        'error': result.get('error', '未知错误')
                    })
            except Exception as e:
                failure_count += 1
                errors.append({
                    'index': idx,
                    'task_id': data.get('task_id') or data.get('index_file', 'unknown'),
                    'error': str(e)
                })

        return {
            'success': failure_count == 0,
            'total': len(data_list),
            'success_count': success_count,
            'failure_count': failure_count,
            'skipped_count': skipped_count,
            'errors': errors if errors else None
        }


def main():
    """主函数 - 用于测试"""
    if len(sys.argv) < 2:
        print("用法: python -m scripts.db_writer <index_file_path>")
        print("示例: python -m scripts.db_writer output/results/TASK_20260227_001/index.json")
        sys.exit(1)

    writer = None
    try:
        writer = VerifiedResultWriter()
        writer.connect()

        # 测试索引文件模式
        index_file = sys.argv[1]
        test_data = {'index_file': index_file}

        result = writer.write(test_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        return result

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if writer:
            writer.close()


if __name__ == '__main__':
    main()
