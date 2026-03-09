#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大POI核实结果回库技能 - 入口文件
版本: 1.5.0

功能：
从上游大POI核实技能本地化存储的JSON文件中读取核实结果，
批量回写到PostgreSQL数据库的 poi_verified 成果表，
同时更新 poi_init 原始表状态为'已核实'。

输入模式：
通过 task_id 和 search_directory 参数，自动查找索引文件并执行回库

"""

import json
import sys
import io
import os
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional

# 设置UTF-8编码输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from db_writer import VerifiedResultWriter
from logger_config import get_logger

logger = get_logger(__name__)


def find_index_file_by_task_id(task_id: str, search_directory: str) -> Optional[str]:
    """
    在指定搜索目录下查找包含指定task_id的索引文件

    Args:
        task_id: 任务ID
        search_directory: 搜索目录路径

    Returns:
        找到的索引文件完整路径，如果未找到则返回None
    """
    search_dir = Path(search_directory)
    if not search_dir.exists():
        logger.error(f"搜索目录不存在: {search_directory}")
        return None

    # 搜索所有可能的索引文件（index*.json 或 *index*.json）
    # 支持的命名模式：
    # - index_*.json
    # - *_index.json
    # - index.json
    index_patterns = [
        search_dir / "**" / f"index_{task_id}.json",
        search_dir / "**" / f"index*{task_id}*.json",
        search_dir / "**" / "index*.json",
    ]

    for pattern in index_patterns:
        for index_file in glob.glob(str(pattern), recursive=True):
            # 验证文件中的task_id是否匹配
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                    if index_data.get('task_id') == task_id:
                        logger.info(f"找到匹配的索引文件: {index_file}")
                        return str(index_file)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"无法读取索引文件 {index_file}: {e}")
                continue

    logger.warning(f"未找到task_id={task_id}的索引文件")
    return None


def execute(data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """
    执行单条POI核实结果写入

    输入模式：task_id + search_directory 模式（推荐）
    ```python
    data = {
        'task_id': 'TASK_20260227_001',
        'search_directory': 'output/results'
    }
    ```

    或者直接传入索引文件路径（兼容模式）：
    ```python
    data = {
        'task_id': 'TASK_20260227_001',
        'index_file': 'output/results/TASK_20260227_001/index.json'
    }
    ```

    索引文件格式要求：
    ```json
    {
      "task_id": "TASK_20260227_001",
      "poi_id": "POI_12345",
      "files": {
        "decision": "decision_DEC_20260227_001.json",
        "evidence": "evidence_EVD_20260227_001.json",
        "record": "record_REC_20260227_001.json"
      }
    }
    ```

    Args:
        data: 输入数据字典，必须包含 task_id 和 search_directory 或 index_file 字段
        **kwargs: 额外的参数（用于兼容性）

    Returns:
        执行结果字典：
        ```python
        {
            'success': True,
            'task_id': 'TASK_20260227_001',
            'poi_id': 'POI_123',
            'message': 'POI 核实结果已成功写入成果表',
            'tables_updated': ['poi_verified', 'poi_init'],
            'verify_time': '2026-03-04T12:00:00'
        }
        ```

    Raises:
        ValueError: 输入数据格式错误
        Exception: 数据库操作失败
    """
    if data is None:
        return {
            'success': False,
            'error': '缺少必要的输入数据'
        }

    # 验证必需字段
    if 'task_id' not in data:
        return {
            'success': False,
            'error': '缺少必需字段：task_id'
        }

    task_id = data['task_id']
    index_file = None

    # 优先使用 search_directory 查找索引文件
    if 'search_directory' in data:
        search_dir = data['search_directory']
        logger.info(f"在目录 {search_dir} 中查找 task_id={task_id} 的索引文件")
        index_file = find_index_file_by_task_id(task_id, search_dir)
        if index_file is None:
            return {
                'success': False,
                'error': f'在搜索目录 {search_dir} 中未找到 task_id={task_id} 的索引文件'
            }
    # 兼容模式：直接使用 index_file
    elif 'index_file' in data:
        index_file = data['index_file']
        logger.info(f"使用指定的索引文件: {index_file}")
    else:
        return {
            'success': False,
            'error': '缺少必需字段：search_directory 或 index_file（至少提供一个）'
        }

    # 构造写入数据
    write_data = {
        'task_id': task_id,
        'index_file': index_file
    }

    writer = None
    try:
        logger.info(f"开始执行单条写入：task_id={task_id}")

        # 初始化写入器
        writer = VerifiedResultWriter()
        writer.connect()

        # 执行写入
        result = writer.write(write_data)

        logger.info(f"写入完成：success={result.get('success')}")
        return result

    except ValueError as e:
        logger.error(f"输入数据验证失败：{e}")
        return {
            'success': False,
            'error': f'输入数据验证失败：{str(e)}'
        }
    except Exception as e:
        logger.error(f"执行失败：{e}")
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        if writer:
            writer.close()


def execute_batch(data_list: Optional[List[Dict]] = None, search_directory: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    批量执行POI核实结果写入

    输入模式1：task_id列表 + search_directory（推荐）
    ```python
    data_list = ['TASK_001', 'TASK_002', 'TASK_003', ...]
    search_directory = 'output/results'
    ```

    输入模式2：完整数据列表
    ```python
    data_list = [
        {'task_id': 'TASK_001', 'search_directory': 'output/results'},
        {'task_id': 'TASK_002', 'index_file': 'path/to/index2.json'},
        ...
    ]
    ```

    Args:
        data_list: 任务ID列表或完整数据列表
        search_directory: 搜索目录（当data_list为任务ID列表时使用）
        **kwargs: 额外的参数（用于兼容性）

    Returns:
        批量执行结果字典：
        ```python
        {
            'success': True,
            'total': 10,
            'success_count': 8,
            'failure_count': 1,
            'skipped_count': 1,
            'errors': [
                {
                    'index': 5,
                    'task_id': 'TASK_006',
                    'error': '错误信息'
                }
            ]
        }
        ```
    """
    if data_list is None or not isinstance(data_list, list):
        return {
            'success': False,
            'error': '输入必须是POI数据列表'
        }

    if len(data_list) == 0:
        return {
            'success': True,
            'total': 0,
            'success_count': 0,
            'failure_count': 0,
            'skipped_count': 0,
            'message': '输入列表为空，无需处理'
        }

    # 如果data_list是字符串列表（任务ID列表），转换为完整数据格式
    if all(isinstance(item, str) for item in data_list):
        if search_directory is None:
            return {
                'success': False,
                'error': '使用任务ID列表时，必须提供 search_directory 参数'
            }
        data_list = [
            {'task_id': task_id, 'search_directory': search_directory}
            for task_id in data_list
        ]

    # 验证每个元素
    for idx, item in enumerate(data_list):
        if not isinstance(item, dict):
            return {
                'success': False,
                'error': f'第{idx}个元素必须是字典类型'
            }
        if 'task_id' not in item:
            return {
                'success': False,
                'error': f'第{idx}个元素缺少必需字段：task_id'
            }
        if 'search_directory' not in item and 'index_file' not in item:
            return {
                'success': False,
                'error': f'第{idx}个元素缺少必需字段：search_directory 或 index_file（至少提供一个）'
            }

    writer = None
    try:
        logger.info(f"开始执行批量写入：total={len(data_list)}")

        # 初始化写入器
        writer = VerifiedResultWriter()
        writer.connect()

        # 转换数据格式为索引文件模式
        write_data_list = []
        for item in data_list:
            task_id = item['task_id']
            index_file = None

            if 'search_directory' in item:
                search_dir = item['search_directory']
                index_file = find_index_file_by_task_id(task_id, search_dir)
                if index_file is None:
                    logger.warning(f"未找到 task_id={task_id} 的索引文件，跳过")
                    continue
            else:
                index_file = item['index_file']

            write_data_list.append({
                'task_id': task_id,
                'index_file': index_file
            })

        # 执行批量写入
        result = writer.write_batch(write_data_list)

        logger.info(f"批量写入完成：total={result.get('total')}, "
                   f"success={result.get('success_count')}, "
                   f"failure={result.get('failure_count')}, "
                   f"skipped={result.get('skipped_count')}")

        return result

    except Exception as e:
        logger.error(f"批量执行失败：{e}")
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        if writer:
            writer.close()


# 兼容性别名
def main(data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """
    main函数 - execute的别名，用于兼容性

    Args:
        data: 输入数据字典
        **kwargs: 额外的参数

    Returns:
        执行结果字典
    """
    return execute(data, **kwargs)


# 测试入口
if __name__ == '__main__':
    import sys

    # 模式1：传入 task_id + search_directory（推荐）
    if len(sys.argv) == 3:
        task_id, search_dir = sys.argv[1], sys.argv[2]
        test_data = {
            'task_id': task_id,
            'search_directory': search_dir
        }
        result = execute(test_data)
        print("\n=== 执行结果 ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # 模式2：直接传入索引文件路径（兼容）
    elif len(sys.argv) == 2:
        index_file = sys.argv[1]
        test_data = {
            'task_id': Path(index_file).stem.replace('index_', ''),
            'index_file': index_file
        }
        result = execute(test_data)
        print("\n=== 执行结果 ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print("用法:")
        print("  模式1（推荐）: python SKILL.py <task_id> <search_directory>")
        print("  模式2（兼容）: python SKILL.py <index_file_path>")
        print("\n示例:")
        print("  python SKILL.py TASK_20260227_001 output/results")
        print("  python SKILL.py output/results/TASK_20260227_001/index.json")
