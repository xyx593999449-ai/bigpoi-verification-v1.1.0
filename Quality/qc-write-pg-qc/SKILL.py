#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QC Write PG QC v1.2.3 - 质检结果写入到 PostgreSQL poi_qc 表
入口文件：本技能从本地化 JSON 文件读取质检结果，写入数据库
支持灵活表名配置、索引缺失容错和完善的错误恢复机制
"""

import json
import importlib.util
import sys
from pathlib import Path

# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent
SCRIPTS_DIR = SCRIPT_DIR / "scripts"

# 添加 scripts 目录到 Python 路径
sys.path.insert(0, str(SCRIPTS_DIR))

from db_writer import QCWriter
from file_loader import FileLoader
from data_converter import DataConverter
import os

import io
# 强制UTF-8编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


_RESULT_VALIDATOR = None


def _find_qc_skill_dir() -> Path:
    """定位主质检技能目录，用于加载结果校验器。"""
    root_dir = FileLoader()._find_root_dir()
    candidates = [
        root_dir / 'BigPoi-verification-qc',
        SCRIPT_DIR.parent / 'BigPoi-verification-qc',
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError('未找到 BigPoi-verification-qc 目录，无法加载结果校验器')


def get_result_validator():
    """按需加载主质检技能的结果校验器。"""
    global _RESULT_VALIDATOR
    if _RESULT_VALIDATOR is not None:
        return _RESULT_VALIDATOR

    qc_skill_dir = _find_qc_skill_dir()
    validator_path = qc_skill_dir / 'scripts' / 'result_validator.py'
    schema_path = qc_skill_dir / 'schema' / 'qc_result.schema.json'
    scoring_policy_path = qc_skill_dir / 'config' / 'scoring_policy.json'

    if not validator_path.exists():
        raise FileNotFoundError(f'结果校验器不存在：{validator_path}')

    spec = importlib.util.spec_from_file_location('bigpoi_qc_result_validator', validator_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'无法加载结果校验器模块：{validator_path}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator_cls = getattr(module, 'ResultValidator', None)
    if validator_cls is None:
        raise ImportError(f'结果校验器模块缺少 ResultValidator：{validator_path}')

    _RESULT_VALIDATOR = validator_cls(
        schema_path=str(schema_path),
        scoring_policy_path=str(scoring_policy_path),
    )
    return _RESULT_VALIDATOR


def get_default_output_dir() -> str:
    """
    获取默认结果目录。

    优先使用 QC_OUTPUT_DIR；否则基于当前技能的根目录定位 output/results。
    """
    env_dir = os.environ.get('QC_OUTPUT_DIR')
    if env_dir:
        return str(Path(env_dir).expanduser().resolve())

    root_dir = FileLoader()._find_root_dir()
    return str(root_dir / 'output' / 'results')

def execute(params: dict) -> dict:
    """
    单条质检结果写入

    Args:
        params: 包含以下字段的字典
            - task_id: 质检任务ID（必需）
            - result_file: 结果文件完整路径（可选）
            - result_dir: 结果目录，用于自动查找文件（可选）
            - table_name: 目标表名（可选，默认为 poi_qc_zk）

    Returns:
        执行结果字典
    """
    try:
        task_id = params.get('task_id')
        if not task_id:
            return {
                'success': False,
                'error': '缺少必需参数：task_id',
                'error_type': 'ValueError'
            }

        # 1. 加载文件
        file_loader = FileLoader()
        result_file = params.get('result_file')
        result_dir = params.get('result_dir')

        qc_result = file_loader.load_result(
            task_id=task_id,
            result_file=result_file,
            result_dir=result_dir
        )

        # 2. 回库前先校验 qc_result，避免无效结果进入数据库
        validation = get_result_validator().validate(qc_result)
        if not validation.get('is_valid'):
            return {
                'success': False,
                'task_id': task_id,
                'error': '质检结果未通过回库前校验',
                'error_type': 'ValidationError',
                'validation_status': validation.get('status'),
                'validation_errors': validation.get('errors', []),
                'validation_warnings': validation.get('warnings', []),
            }

        # 3. 数据转换
        converter = DataConverter()
        converted_data = converter.convert(qc_result)

        # 4. 写入数据库
        table_name = params.get('table_name', 'poi_qc_zk')
        writer = QCWriter()
        writer.connect()
        try:
            result = writer.write(converted_data, table_name=table_name)
            return result
        finally:
            writer.close()

    except Exception as e:
        return {
            'success': False,
            'task_id': params.get('task_id'),
            'error': str(e),
            'error_type': type(e).__name__
        }


def execute_batch(params_list: list) -> dict:
    """
    批量质检结果写入

    Args:
        params_list: 参数字典列表

    Returns:
        批量执行结果
    """
    success_count = 0
    failure_count = 0
    errors = []

    for idx, params in enumerate(params_list):
        try:
            result = execute(params)
            if result.get('success'):
                success_count += 1
            else:
                failure_count += 1
                errors.append({
                    'index': idx,
                    'task_id': params.get('task_id'),
                    'error': result.get('error')
                })
        except Exception as e:
            failure_count += 1
            errors.append({
                'index': idx,
                'task_id': params.get('task_id'),
                'error': str(e)
            })

    return {
        'success': failure_count == 0,
        'total': len(params_list),
        'success_count': success_count,
        'failure_count': failure_count,
        'errors': errors if errors else None
    }


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("BigPOI QC Result Writer v1.2.3")
        print("本技能用于将质检结果写入 PostgreSQL poi_qc 表")
        print("\n使用方式：")
        print("  Python调用:")
        print("    from SKILL import execute")
        print("    result = execute({'task_id': '219A8C6D8C334629A7E1F164D514C381', 'result_dir': 'output/results'})")
        print("    # 指定表名（可选，默认为 poi_qc_zk）")
        print("    result = execute({'task_id': '219A8C...', 'result_dir': 'output/results', 'table_name': 'poi_qc_custom'})")
        print("\n  命令行调用:")
        print("    python SKILL.py <task_id> [result_dir] [table_name]")
        print("    例如: python SKILL.py 219A8C6D8C334629A7E1F164D514C381")
        print("    例如: python SKILL.py 219A8C6D8C334629A7E1F164D514C381 output/results")
        print("    例如: python SKILL.py 219A8C6D8C334629A7E1F164D514C381 output/results poi_qc_zk")
        return

    # 从命令行参数获取 task_id、result_dir 和 table_name
    task_id = sys.argv[1]
    # 默认使用相对于项目根目录的 output/results
    result_dir = sys.argv[2] if len(sys.argv) > 2 else get_default_output_dir()
    table_name = sys.argv[3] if len(sys.argv) > 3 else None

    params = {'task_id': task_id}
    if result_dir:
        params['result_dir'] = result_dir
    if table_name:
        params['table_name'] = table_name

    result = execute(params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

