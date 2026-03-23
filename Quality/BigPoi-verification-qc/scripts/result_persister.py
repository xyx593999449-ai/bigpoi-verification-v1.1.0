#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果持久化脚本 - 将质检结果保存到本地文件系统

职责：
1. 创建规范的目录结构 output/results/{task_id}/
2. 生成完整结果文件 (complete.json)
3. 生成摘要文件 (summary.json)
4. 更新索引文件 (results_index.json)

所有文件名必须遵循格式：{YYYYMMDD_HHmmss}_{task_id}.{type}.json
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import random

def should_sample_for_qc(overall_confidence: float) -> bool:
    """
    [Sub-Agent 4 改造核心: 动态抽检逻辑]
    通过置信度梯度抛弃掉极大比例的质检消耗：
    - >= 0.95: 5% 概率抽检
    - >= 0.85: 20% 概率抽检
    - < 0.85: 100% 全量质检
    """
    if overall_confidence >= 0.95:
        return random.random() < 0.05
    if overall_confidence >= 0.85:
        return random.random() < 0.20
    return True


def _is_workspace_root(path: Path) -> bool:
    """判断是否为当前技能包工作区根目录。"""
    return (
        (path / 'BigPoi-verification-qc').is_dir()
        and (path / 'qc-write-pg-qc').is_dir()
    )


def _project_root_from_skill_install_path(path: Path) -> Optional[Path]:
    """如果路径位于 .claude/skills 或 .openclaw/skills 下，返回其工作区根目录。"""
    parts = list(path.parts)
    normalized = [part.lower() for part in parts]
    for index, part in enumerate(normalized[:-1]):
        if part in ('.claude', '.openclaw') and normalized[index + 1] == 'skills':
            if index == 0:
                return None
            root = Path(parts[0])
            for segment in parts[1:index]:
                root /= segment
            return root
    return None


def get_default_output_dir() -> str:
    """获取默认输出目录：优先当前技能工作区根目录。"""
    # 1) 明确指定: QC_OUTPUT_DIR 优先
    env_dir = os.environ.get('QC_OUTPUT_DIR')
    if env_dir:
        return str(Path(env_dir).expanduser().resolve())

    cwd = Path.cwd().resolve()

    # 2) 当前工作目录本身是项目根（含 .claude/.openclaw）
    if (cwd / '.claude').exists() or (cwd / '.openclaw').exists():
        return str(cwd / 'output' / 'results')

    # 3) 从当前工作目录向上查找：优先技能工作区根，再回退到 .claude/.openclaw 根
    for parent in [cwd, *cwd.parents]:
        if (parent / '.claude').exists() or (parent / '.openclaw').exists():
            return str(parent / 'output' / 'results')
        if _is_workspace_root(parent):
            return str(parent / 'output' / 'results')

    # 4) 从脚本位置向上查找：优先技能工作区根，再回退到 .claude/.openclaw 根
    script_dir = Path(__file__).resolve().parent
    for parent in [script_dir, *script_dir.parents]:
        if parent.name in ('.claude', '.openclaw'):
            return str(parent.parent / 'output' / 'results')
        if _is_workspace_root(parent):
            return str(parent / 'output' / 'results')

    # 5) 基于脚本位置定位单技能根目录（兼容独立发布）
    for parent in [script_dir, *script_dir.parents]:
        if (parent / 'schema').is_dir() and (parent / 'rules').is_dir():
            return str(parent / 'output' / 'results')

    # 6) 回退到当前工作目录
    return str(cwd / 'output' / 'results')

class ResultPersister:
    """质检结果本地持久化器"""

    def __init__(self, output_dir: str = None, logger: Optional[logging.Logger] = None):
        """
        初始化持久化器

        Args:
            output_dir: 输出目录；可传 `output/results` 基目录，也可直接传 `{task_id}` 目录
            logger: 日志记录器，可选
        """
        self.logger = logger or logging.getLogger(__name__)
        if output_dir is None:
            raw_output_dir = Path(get_default_output_dir())
        else:
            raw_output_dir = Path(output_dir)
        self.output_dir = self._normalize_output_dir(raw_output_dir)

    def _normalize_output_dir(self, output_dir: Path) -> Path:
        """
        归一化输出目录，避免结果落到 .claude/skills/<skill>/output/results 下。

        对相对路径，先按当前工作目录解析；如果解析结果位于技能安装目录下，
        自动改写到工作区根目录的 output/results。
        """
        candidate = output_dir.expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd().resolve() / candidate).resolve()
        else:
            candidate = candidate.resolve()

        workspace_root = _project_root_from_skill_install_path(candidate)
        if workspace_root:
            rewritten = workspace_root / 'output' / 'results'
            self.logger.warning(
                "检测到输出目录位于技能安装目录下，自动改写为工作区输出目录：%s -> %s",
                candidate,
                rewritten,
            )
            return rewritten

        return candidate

    def _resolve_task_dir(self, task_id: str) -> Path:
        """归一化任务目录，避免 output_dir 已包含 task_id 时再拼一层。"""
        if self.output_dir.name == task_id:
            self.logger.info(f"output_dir 已指向 task_id 目录，直接复用：{self.output_dir}")
            return self.output_dir
        return self.output_dir / task_id

    def persist(self, qc_result: Dict, task_id: Optional[str] = None) -> Dict:
        """
        将质检结果持久化到本地文件系统

        Args:
            qc_result: 质检结果JSON对象
            task_id: 任务ID，如果不提供则从qc_result中读取

        Returns:
            {
                'success': bool,  # 仅当 3 个必需文件全部写入成功时为 true
                'status': 'success' | 'partial' | 'failed',
                'output_dir': str,  # 结果保存的目录
                'files': {
                    'complete': str,
                    'summary': str,
                    'index': str
                },
                'errors': []  # 错误信息列表
            }
        """
        errors = []
        files_created = {}

        try:
            # 1. 获取task_id
            if not task_id:
                task_id = qc_result.get('task_id')
            if not task_id:
                return {
                    'success': False,
                    'status': 'failed',
                    'output_dir': None,
                    'files': {},
                    'errors': ['qc_result 缺少 task_id 字段，且未提供 task_id 参数']
                }

            # 2. 创建任务目录
            task_dir = self._resolve_task_dir(task_id)
            try:
                task_dir.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"创建任务目录：{task_dir}")
            except Exception as e:
                error_msg = f"创建目录 {task_dir} 失败：{str(e)}"
                self.logger.error(error_msg)
                return {
                    'success': False,
                    'status': 'failed',
                    'output_dir': None,
                    'files': {},
                    'errors': [error_msg]
                }

            # 3. 生成时间戳
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # 4. 写入完整结果文件
            complete_filename = f"{timestamp}_{task_id}.complete.json"
            complete_path = task_dir / complete_filename
            try:
                with open(complete_path, 'w', encoding='utf-8') as f:
                    json.dump(qc_result, f, ensure_ascii=False, indent=2)
                files_created['complete'] = str(complete_path)
                self.logger.info(f"完整结果文件已写入：{complete_path}")
            except Exception as e:
                error_msg = f"写入完整结果文件 {complete_filename} 失败：{str(e)}"
                self.logger.error(error_msg)
                errors.append(error_msg)

            # 5. 生成摘要文件
            summary_filename = f"{timestamp}_{task_id}.summary.json"
            summary_path = task_dir / summary_filename
            try:
                summary_data = self._generate_summary(qc_result, timestamp)
                with open(summary_path, 'w', encoding='utf-8') as f:
                    json.dump(summary_data, f, ensure_ascii=False, indent=2)
                files_created['summary'] = str(summary_path)
                self.logger.info(f"摘要文件已写入：{summary_path}")
            except Exception as e:
                error_msg = f"生成摘要文件 {summary_filename} 失败：{str(e)}"
                self.logger.error(error_msg)
                errors.append(error_msg)

            # 6. 更新索引文件（写入稳定文件名 + 时间戳文件名）
            index_filename = f"{timestamp}_{task_id}.results_index.json"
            index_path = task_dir / index_filename
            stable_index_path = task_dir / "results_index.json"
            try:
                self._update_index(task_id, timestamp, qc_result, index_path)
                files_created['index'] = str(index_path)
                self.logger.info(f"索引文件已写入：{index_path}")

                if stable_index_path != index_path:
                    self._update_index(task_id, timestamp, qc_result, stable_index_path)
                    files_created['index_stable'] = str(stable_index_path)
                    self.logger.info(f"索引文件已写入：{stable_index_path}")
            except Exception as e:
                error_msg = f"生成索引文件 {index_filename} 失败：{str(e)}"
                self.logger.error(error_msg)
                errors.append(error_msg)

            # 7. 确定返回状态
            if not errors:
                status = 'success'
                success = True
            else:
                # 部分文件写入成功也视为失败，避免调用方继续回库
                status = 'partial' if files_created else 'failed'
                success = False

            return {
                'success': success,
                'status': status,
                'output_dir': str(task_dir),
                'files': files_created,
                'errors': errors
            }

        except Exception as e:
            error_msg = f"持久化过程发生未预期的异常：{str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {
                'success': False,
                'status': 'failed',
                'output_dir': None,
                'files': files_created,
                'errors': [error_msg]
            }

    def _generate_summary(self, qc_result: Dict, timestamp: str) -> Dict:
        """
        从完整结果生成摘要

        Args:
            qc_result: 完整的质检结果
            timestamp: 时间戳

        Returns:
            摘要数据对象
        """
        dimension_results = {}
        for dim_name, dim_result in qc_result.get('dimension_results', {}).items():
            dimension_results[dim_name] = dim_result.get('status', 'unknown')

        summary = {
            'task_id': qc_result.get('task_id'),
            'timestamp': timestamp,
            'qc_status': qc_result.get('qc_status'),
            'qc_score': qc_result.get('qc_score'),
            'has_risk': qc_result.get('has_risk'),
            'explanation': qc_result.get('explanation'),
            'dimension_results': dimension_results,
            'statistics_flags': qc_result.get('statistics_flags', {})
        }

        # 添加降级一致性信息
        downgrade_consistency = qc_result.get('dimension_results', {}).get('downgrade_consistency', {})
        if downgrade_consistency:
            summary['downgrade_consistency'] = {
                'is_consistent': downgrade_consistency.get('is_consistent'),
                'issue_type': downgrade_consistency.get('issue_type')
            }

        return summary

    def _update_index(self, task_id: str, timestamp: str, qc_result: Dict, index_path: Path) -> None:
        """
        更新或创建索引文件（v1.2+ 新格式）

        新索引文件结构：
        {
            "task_id": "当前任务的task_id",
            "total_results": 1,
            "last_updated": "2026-03-04T10:30:00Z",
            "results": [
                {
                    "timestamp": "20260304_103000",
                    "qc_status": "qualified",
                    "qc_score": 85,
                    "has_risk": false,
                    "result_files": {
                        "complete": "output/results/{task_id}/20260304_103000_{task_id}.complete.json",
                        "summary": "output/results/{task_id}/20260304_103000_{task_id}.summary.json"
                    }
                }
            ]
        }

        Args:
            task_id: 任务ID
            timestamp: 时间戳
            qc_result: 质检结果
            index_path: 索引文件路径
        """
        # 读取现有索引或创建新索引
        if index_path.exists():
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            # 检查 task_id 是否匹配
            if index_data.get('task_id') != task_id:
                # task_id 不匹配，创建新索引
                index_data = {
                    'task_id': task_id,
                    'total_results': 0,
                    'last_updated': None,
                    'results': []
                }
            results_list = index_data.get('results', [])
        else:
            index_data = {
                'task_id': task_id,
                'total_results': 0,
                'last_updated': None,
                'results': []
            }
            results_list = []

        # 创建新的索引记录
        new_record = {
            'task_id': task_id,
            'timestamp': timestamp,
            'qc_status': qc_result.get('qc_status'),
            'qc_score': qc_result.get('qc_score'),
            'has_risk': qc_result.get('has_risk'),
            'result_files': {
                'complete': f"{timestamp}_{task_id}.complete.json",
                'summary': f"{timestamp}_{task_id}.summary.json"
            }
        }

        # 检查是否已存在相同的记录（同一个 task_id + timestamp）
        existing_index = None
        for i, record in enumerate(results_list):
            if record.get('task_id') == task_id and record.get('timestamp') == timestamp:
                existing_index = i
                break

        if existing_index is not None:
            # 更新现有记录
            results_list[existing_index] = new_record
        else:
            # 添加新记录
            results_list.append(new_record)

        # 保持最多 1000 条记录（FIFO）
        if len(results_list) > 1000:
            results_list = results_list[-1000:]

        # 更新索引元数据
        index_data['total_results'] = len(results_list)
        index_data['last_updated'] = datetime.now().isoformat() + 'Z'
        index_data['results'] = results_list

        # 写入索引文件
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    """
    命令行使用入口

    用法：
      python result_persister.py <result_json_file> [options]

    参数：
      result_json_file    : 质检结果JSON文件路径（必需）
      --task-id ID        : 任务ID（可选，如果JSON中有task_id字段可不提供）
      --output-dir PATH   : 输出目录（可选，默认为 <workspace_root>/output/results）
      --output-format     : 输出格式，json 或 text（默认：json）

    示例：
      python result_persister.py result.json
      python result_persister.py result.json --task-id my_task_001
      python result_persister.py result.json --output-dir ./results
    """
    import sys
    import argparse
    from pathlib import Path

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description='将质检结果持久化到本地文件系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'result_json',
        type=str,
        help='质检结果JSON文件路径'
    )

    parser.add_argument(
        '--task-id',
        type=str,
        default=None,
        help='任务ID（如果JSON中没有task_id字段，需要指定此参数）'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help=f'输出目录（默认：{get_default_output_dir()}）'
    )

    parser.add_argument(
        '--output-format',
        type=str,
        choices=['json', 'text'],
        default='json',
        help='输出格式（默认：json）'
    )

    args = parser.parse_args()

    # 验证输入文件存在
    result_file = Path(args.result_json)
    if not result_file.exists():
        logger.error(f"质检结果文件不存在：{args.result_json}")
        sys.exit(1)

    # 读取质检结果
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            qc_result = json.load(f)
        logger.info(f"成功读取质检结果：{result_file}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON文件格式错误：{str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"读取文件失败：{str(e)}")
        sys.exit(1)

    # 确定输出目录
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = get_default_output_dir()

    logger.info(f"输出目录：{output_dir}")

    # 创建持久化器
    try:
        persister = ResultPersister(output_dir=output_dir, logger=logger)
        logger.info("持久化器初始化成功")
    except Exception as e:
        logger.error(f"持久化器初始化失败：{str(e)}")
        sys.exit(1)

    # 执行持久化
    try:
        result = persister.persist(qc_result, task_id=args.task_id)
        logger.info("持久化完成")
    except Exception as e:
        logger.error(f"持久化过程发生异常：{str(e)}")
        sys.exit(1)

    # 输出结果
    if args.output_format == 'json':
        output = json.dumps(result, ensure_ascii=False, indent=2)
        print(output)
    else:
        # 文本格式输出
        print("=" * 60)
        print("质检结果持久化报告")
        print("=" * 60)
        print(f"状态：{result['status']}")
        print(f"是否成功：{'是' if result['success'] else '否'}")
        print(f"输出目录：{result['output_dir']}")

        if result['files']:
            print(f"\n生成的文件（共 {len(result['files'])} 个）：")
            for file_type, file_path in result['files'].items():
                print(f"  - {file_type}: {file_path}")

        if result['errors']:
            print(f"\n错误（共 {len(result['errors'])} 个）：")
            for i, error in enumerate(result['errors'], 1):
                print(f"  {i}. {error}")

    # 根据持久化结果设置退出码
    sys.exit(0 if result['success'] else 1)
