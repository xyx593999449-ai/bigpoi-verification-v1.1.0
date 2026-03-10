#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大POI核实结果回库技能 - 入口文件

功能：
从上游技能生成的本地 JSON 文件读取核实结果，
批量回写到 PostgreSQL 的核实成果表，
同时更新原始表状态为“已核实”。

输入模式：
通过 task_id 和 search_directory 参数自动查找索引文件并执行回库。
如果同一个 task_id 因重试产生多个 index 文件，则优先使用最新修改时间的文件。

可选参数：
- init: 原始表名，默认 poi_init
- verified: 核实成果表名，默认 poi_verified
"""

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 设置 UTF-8 编码输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from db_writer import VerifiedResultWriter
from logger_config import get_logger

logger = get_logger(__name__)


def find_index_file_by_task_id(task_id: str, search_directory: str) -> Optional[str]:
    """在指定搜索目录下查找包含指定 task_id 的索引文件。"""
    search_dir = Path(search_directory)
    if not search_dir.exists():
        logger.error(f"搜索目录不存在: {search_directory}")
        return None

    candidate_files = [
        *search_dir.rglob(f"index_{task_id}.json"),
        *search_dir.rglob(f"index*{task_id}*.json"),
        *search_dir.rglob("index*.json"),
    ]

    matched_index_files: List[Tuple[float, str]] = []
    visited_files = set()

    for index_file in candidate_files:
        normalized_path = str(index_file.resolve())
        if normalized_path in visited_files:
            continue
        visited_files.add(normalized_path)

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            if index_data.get("task_id") != task_id:
                continue

            modified_time = index_file.stat().st_mtime
            matched_index_files.append((modified_time, normalized_path))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"无法读取索引文件 {index_file}: {e}")
        except OSError as e:
            logger.warning(f"无法获取索引文件时间戳 {index_file}: {e}")

    if not matched_index_files:
        logger.warning(f"未找到 task_id={task_id} 的索引文件")
        return None

    matched_index_files.sort(key=lambda item: item[0], reverse=True)
    latest_mtime, latest_index_file = matched_index_files[0]

    logger.info(
        "找到 %s 个匹配的索引文件，按最后修改时间选择最新文件: %s (mtime=%s)",
        len(matched_index_files),
        latest_index_file,
        latest_mtime,
    )
    return latest_index_file


def execute(
    data: Optional[Dict[str, Any]] = None,
    init: Optional[str] = None,
    verified: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """执行单条 POI 核实结果写入。"""
    if data is None:
        return {
            "success": False,
            "error": "缺少必要的输入数据",
        }

    if init is not None:
        data["init"] = init
    if verified is not None:
        data["verified"] = verified

    if "task_id" not in data:
        return {
            "success": False,
            "error": "缺少必需字段: task_id",
        }

    task_id = data["task_id"]
    index_file = None

    if "search_directory" in data:
        search_dir = data["search_directory"]
        logger.info("在目录 %s 中查找 task_id=%s 的索引文件", search_dir, task_id)
        index_file = find_index_file_by_task_id(task_id, search_dir)
        if index_file is None:
            return {
                "success": False,
                "error": f"在搜索目录 {search_dir} 中未找到 task_id={task_id} 的索引文件",
            }
    elif "index_file" in data:
        index_file = data["index_file"]
        logger.info("使用指定的索引文件: %s", index_file)
    else:
        return {
            "success": False,
            "error": "缺少必需字段: search_directory 或 index_file（至少提供一个）",
        }

    write_data = {
        "task_id": task_id,
        "index_file": index_file,
    }
    if "init" in data:
        write_data["init"] = data["init"]
    if "verified" in data:
        write_data["verified"] = data["verified"]

    writer = None
    try:
        logger.info("开始执行单条写入: task_id=%s", task_id)

        writer = VerifiedResultWriter()
        writer.connect()

        result = writer.write(write_data)
        logger.info("写入完成: success=%s", result.get("success"))
        return result
    except ValueError as e:
        logger.error("输入数据验证失败: %s", e)
        return {
            "success": False,
            "error": f"输入数据验证失败: {str(e)}",
        }
    except Exception as e:
        logger.error("执行失败: %s", e)
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        if writer:
            writer.close()


def execute_batch(
    data_list: Optional[List[Dict]] = None,
    search_directory: Optional[str] = None,
    init: Optional[str] = None,
    verified: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """批量执行 POI 核实结果写入。"""
    if data_list is None or not isinstance(data_list, list):
        return {
            "success": False,
            "error": "输入必须是 POI 数据列表",
        }

    if len(data_list) == 0:
        return {
            "success": True,
            "total": 0,
            "success_count": 0,
            "failure_count": 0,
            "skipped_count": 0,
            "message": "输入列表为空，无需处理",
        }

    if all(isinstance(item, str) for item in data_list):
        if search_directory is None:
            return {
                "success": False,
                "error": "使用任务 ID 列表时，必须提供 search_directory 参数",
            }
        data_list = [
            {"task_id": task_id, "search_directory": search_directory}
            for task_id in data_list
        ]

    for idx, item in enumerate(data_list):
        if not isinstance(item, dict):
            return {
                "success": False,
                "error": f"第 {idx} 个元素必须是字典类型",
            }
        if "task_id" not in item:
            return {
                "success": False,
                "error": f"第 {idx} 个元素缺少必需字段: task_id",
            }
        if "search_directory" not in item and "index_file" not in item:
            return {
                "success": False,
                "error": f"第 {idx} 个元素缺少必需字段: search_directory 或 index_file（至少提供一个）",
            }

    writer = None
    try:
        logger.info("开始执行批量写入: total=%s", len(data_list))

        writer = VerifiedResultWriter()
        writer.connect()

        write_data_list = []
        for item in data_list:
            task_id = item["task_id"]

            if "search_directory" in item:
                index_file = find_index_file_by_task_id(task_id, item["search_directory"])
                if index_file is None:
                    logger.warning("未找到 task_id=%s 的索引文件，跳过", task_id)
                    continue
            else:
                index_file = item["index_file"]

            write_item = {
                "task_id": task_id,
                "index_file": index_file,
            }
            if item.get("init") or init:
                write_item["init"] = item.get("init") or init
            if item.get("verified") or verified:
                write_item["verified"] = item.get("verified") or verified

            write_data_list.append(write_item)

        result = writer.write_batch(write_data_list)
        logger.info(
            "批量写入完成: total=%s, success=%s, failure=%s, skipped=%s",
            result.get("total"),
            result.get("success_count"),
            result.get("failure_count"),
            result.get("skipped_count"),
        )
        return result
    except Exception as e:
        logger.error("批量执行失败: %s", e)
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        if writer:
            writer.close()


def main(data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """兼容入口，等价于 execute。"""
    return execute(data, **kwargs)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        task_id, search_dir = sys.argv[1], sys.argv[2]
        test_data = {
            "task_id": task_id,
            "search_directory": search_dir,
        }
        result = execute(test_data)
        print("\n=== 执行结果 ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif len(sys.argv) == 2:
        index_file = sys.argv[1]
        test_data = {
            "task_id": Path(index_file).stem.replace("index_", ""),
            "index_file": index_file,
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
