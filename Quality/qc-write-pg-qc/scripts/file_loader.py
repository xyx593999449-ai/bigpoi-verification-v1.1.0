#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件加载器 - 从本地化 JSON 文件加载质检结果。

策略：
1. 先按标准目录定位 `result_dir/{task_id}`。
2. 标准目录失败后，再做受约束递归恢复。
3. 递归恢复仅接受 `{task_id}` 目录下的索引文件和 complete 文件。
4. 如果恢复阶段出现多个合法候选，拒绝自动猜测，直接报歧义。
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


TIMESTAMP_PATTERN = re.compile(r'^\d{8}_\d{6}$')


class FileLoader:
    """质检结果文件加载器（基于索引文件）"""

    def __init__(self):
        self.logger = None

    @staticmethod
    def _is_workspace_root(path: Path) -> bool:
        """判断是否为当前技能包的工作区根目录。"""
        return (
            (path / 'BigPoi-verification-qc').is_dir()
            and (path / 'qc-write-pg-qc').is_dir()
        )

    def _find_root_dir(self) -> Path:
        """
        查找根目录（优先 QC_OUTPUT_DIR，其次当前工作目录）

        Returns:
            根目录路径
        """
        env_dir = os.environ.get('QC_OUTPUT_DIR')
        if env_dir:
            env_path = Path(env_dir).expanduser().resolve()
            if env_path.name == 'results' and env_path.parent.name == 'output':
                return env_path.parent.parent

        cwd = Path.cwd().resolve()

        if (cwd / '.claude').exists() or (cwd / '.openclaw').exists():
            return cwd

        for parent in [cwd, *cwd.parents]:
            if (parent / '.claude').exists() or (parent / '.openclaw').exists():
                return parent
            if self._is_workspace_root(parent):
                return parent

        script_dir = Path(__file__).resolve().parent
        for parent in [script_dir, *script_dir.parents]:
            if parent.name in ('.claude', '.openclaw'):
                return parent.parent
            if self._is_workspace_root(parent):
                return parent

        for parent in [script_dir, *script_dir.parents]:
            if (parent / 'schema').is_dir() and (parent / 'rules').is_dir():
                return parent

        return cwd

    @staticmethod
    def _project_root_from_skill_install_path(path: Path) -> Optional[Path]:
        """如果路径位于 .claude/skills 或 .openclaw/skills 下，返回其工作区根目录。"""
        parts = list(path.resolve().parts)
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

    def _is_skill_install_artifact(self, path: Path) -> bool:
        """判断候选是否位于技能安装目录下。"""
        return self._project_root_from_skill_install_path(path) is not None

    def _prefer_workspace_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        在存在多个合法候选时，优先使用非技能安装目录下的正式工作区结果。
        只有当全部候选都位于技能安装目录下时，才保留这些候选参与后续判断。
        """
        preferred = [
            candidate
            for candidate in candidates
            if not self._is_skill_install_artifact(candidate['complete_path'])
            and not self._is_skill_install_artifact(candidate['source_path'])
        ]
        return preferred or candidates

    def load_result(
        self,
        task_id: str,
        result_file: Optional[str] = None,
        result_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        加载质检结果文件

        Args:
            task_id: 质检任务ID
            result_file: 结果文件完整路径（可选）
            result_dir: 结果目录（如 output/results）

        Returns:
            解析后的质检结果对象
        """
        if not result_file and not result_dir:
            raise ValueError('必须提供 result_file 或 result_dir')

        if result_file:
            file_path = self._resolve_result_file_path(result_file)
        else:
            file_path = self._load_from_index(task_id, result_dir)

        if not isinstance(file_path, Path):
            raise ValueError(f'文件定位失败，返回了无效路径对象：{file_path!r}')
        if not file_path.exists():
            raise FileNotFoundError(f'结果文件不存在：{file_path}')

        payload = self._read_json(file_path)
        return self._normalize_qc_result(payload, file_path, task_id)

    def _resolve_result_file_path(self, result_file: str) -> Path:
        """解析 result_file 路径：支持相对路径，优先当前目录，其次项目根目录。"""
        file_path = Path(result_file)
        if file_path.is_absolute():
            return file_path

        cwd_candidate = Path.cwd().resolve() / file_path
        if cwd_candidate.exists():
            return cwd_candidate

        root_dir = self._find_root_dir()
        root_candidate = root_dir / file_path
        if root_candidate.exists():
            return root_candidate

        return file_path

    def _read_json(self, file_path: Path) -> Dict[str, Any]:
        with open(file_path, 'r', encoding='utf-8') as handle:
            return json.load(handle)

    def _normalize_qc_result(self, data: Any, source_path: Path, task_id: str) -> Dict[str, Any]:
        """将读取到的 JSON 规范化为完整 qc_result。"""
        if self._is_index_like(data):
            data = self._load_complete_from_index(data, source_path, task_id)

        if self._is_wrapper_like(data):
            data = self._unwrap_qc_result(data, task_id, source_path)

        if self._is_summary_like(data):
            raise ValueError(
                f'检测到 summary 结果文件，缺少完整字段，请使用 *.complete.json（当前文件：{source_path}）'
            )

        if not isinstance(data, dict):
            raise ValueError(f'结果文件内容必须是 JSON 对象：{source_path}')

        if 'task_id' not in data and task_id:
            data['task_id'] = task_id

        if 'task_id' not in data:
            raise ValueError(f'结果文件缺少 task_id 字段：{source_path}')

        if task_id and data.get('task_id') != task_id:
            raise ValueError(f'task_id 不匹配：参数={task_id}，文件={data.get("task_id")}，路径={source_path}')

        return data

    def _is_index_like(self, data: Any) -> bool:
        """判断是否为 results_index.json 结构。"""
        if not isinstance(data, dict):
            return False
        if 'results' not in data:
            return False
        if 'qc_status' in data and 'dimension_results' in data:
            return False
        return True

    def _is_wrapper_like(self, data: Any) -> bool:
        """判断是否为包裹结构：{"qc_result": {...}, ...}。"""
        return isinstance(data, dict) and isinstance(data.get('qc_result'), dict)

    def _unwrap_qc_result(self, wrapper: Dict[str, Any], task_id: str, source_path: Path) -> Dict[str, Any]:
        """从包裹结构中提取 qc_result，并补齐 task_id。"""
        inner = wrapper.get('qc_result', {})
        if not isinstance(inner, dict):
            raise ValueError(f'qc_result 字段不是对象：{source_path}')

        if 'task_id' not in inner and wrapper.get('task_id'):
            inner['task_id'] = wrapper.get('task_id')
        if 'task_id' not in inner and task_id:
            inner['task_id'] = task_id
        return inner

    def _is_summary_like(self, data: Any) -> bool:
        """判断是否为 summary 结构（非完整结果）。"""
        if not isinstance(data, dict):
            return False
        if 'timestamp' in data and 'dimension_results' in data and 'qc_status' in data:
            if 'risk_dims' not in data or 'triggered_rules' not in data:
                return True
        return False

    def _resolve_complete_path(self, complete_file: str, base_dir: Path) -> Path:
        """解析 index 中的 complete 路径。"""
        complete_path = Path(complete_file)
        if complete_path.is_absolute():
            return complete_path

        candidate = base_dir / complete_file
        if candidate.exists():
            return candidate

        root_dir = self._find_root_dir()
        candidate = root_dir / complete_file
        if candidate.exists():
            return candidate

        return complete_path

    def _parse_timestamp(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and TIMESTAMP_PATTERN.match(value):
            return value
        return None

    def _timestamp_from_complete_name(self, file_path: Path, task_id: str) -> Optional[str]:
        pattern = re.compile(rf'^(?P<timestamp>\d{{8}}_\d{{6}})_{re.escape(task_id)}\.complete\.json$')
        match = pattern.match(file_path.name)
        if not match:
            return None
        return match.group('timestamp')

    def _timestamp_from_index_name(self, file_path: Path, task_id: str) -> Optional[str]:
        pattern = re.compile(rf'^(?P<timestamp>\d{{8}}_\d{{6}})_{re.escape(task_id)}\.results_index\.json$')
        match = pattern.match(file_path.name)
        if not match:
            return None
        return match.group('timestamp')

    def _select_latest_record(self, results: List[Any], task_id: str) -> Optional[Dict[str, Any]]:
        """从索引 results 中选择时间戳最新的一条合法记录。"""
        matching: List[Dict[str, Any]] = [
            record
            for record in results
            if isinstance(record, dict) and record.get('task_id') == task_id
        ]
        if not matching:
            return None

        def sort_key(item: Dict[str, Any]) -> tuple:
            timestamp = self._parse_timestamp(item.get('timestamp')) or ''
            return (timestamp, matching.index(item))

        return max(matching, key=sort_key)

    def _candidate_sort_key(self, candidate: Dict[str, Any]) -> tuple:
        timestamp = candidate.get('timestamp') or ''
        try:
            mtime = candidate['complete_path'].stat().st_mtime
        except OSError:
            mtime = 0
        return (timestamp, mtime)

    def _load_complete_from_index(
        self,
        index_data: Dict[str, Any],
        index_path: Path,
        task_id: str,
    ) -> Dict[str, Any]:
        """从索引数据中解析并加载 complete.json。"""
        if index_path.parent.name != task_id:
            raise ValueError(f'索引文件不在 task_id 目录下：{index_path}')

        if index_data.get('task_id') != task_id:
            raise ValueError(f'索引文件 task_id 不匹配：{index_path}')

        results = index_data.get('results', [])
        if not isinstance(results, list) or not results:
            raise ValueError(f'索引文件无有效结果记录：{index_path}')

        chosen = self._select_latest_record(results, task_id)
        if not chosen:
            raise ValueError(f'索引文件中没有匹配 task_id 的结果记录：{index_path}')

        result_files = chosen.get('result_files') or {}
        complete_file = result_files.get('complete')
        if not complete_file:
            raise ValueError(f'索引文件缺少 complete 文件路径：{index_path}')

        complete_path = self._resolve_complete_path(complete_file, index_path.parent)
        if complete_path.parent.name != task_id:
            raise ValueError(f'索引指向的 complete 文件不在 task_id 目录下：{complete_path}')
        if not complete_path.exists():
            raise FileNotFoundError(f'索引指向的 complete.json 不存在：{complete_path}')

        return self._read_json(complete_path)

    def _load_from_index(self, task_id: str, result_dir: str) -> Path:
        """
        从索引文件读取完整文件路径，或在索引文件不存在时做受约束递归恢复。
        """
        base_dir = Path(result_dir)
        if not base_dir.is_absolute():
            base_dir = self._find_root_dir() / base_dir

        task_dir = base_dir if base_dir.name == task_id else base_dir / task_id

        if not task_dir.is_dir():
            return self._recover_from_search_roots(task_id, base_dir)

        index_files = self._collect_index_files(task_dir, task_id)
        for index_file in index_files:
            try:
                index_data = self._read_json(index_file)
                chosen = self._select_latest_record(index_data.get('results', []), task_id)
                if not chosen:
                    continue
                complete_file = (chosen.get('result_files') or {}).get('complete')
                if not complete_file:
                    continue
                complete_path = self._resolve_complete_path(complete_file, index_file.parent)
                if complete_path.parent.name != task_id:
                    continue
                self._normalize_qc_result(self._read_json(complete_path), complete_path, task_id)
                return complete_path
            except Exception:
                continue

        try:
            return self._find_latest_complete_file(task_dir, task_id)
        except FileNotFoundError:
            return self._recover_from_search_roots(task_id, base_dir)

    def _recover_from_search_roots(self, task_id: str, base_dir: Path) -> Path:
        """按搜索范围逐级做受约束恢复。"""
        search_roots: List[Path] = []
        if base_dir.exists():
            search_roots.append(base_dir)

        root_dir = self._find_root_dir()
        if root_dir not in search_roots:
            search_roots.append(root_dir)

        errors: List[str] = []
        for search_root in search_roots:
            try:
                return self._search_task_in_tree(task_id, search_root)
            except FileNotFoundError as exc:
                errors.append(str(exc))

        raise FileNotFoundError('\n'.join(errors))

    def _collect_index_files(self, task_dir: Path, task_id: str) -> List[Path]:
        """收集 task_id 目录下的索引文件。"""
        index_files: List[Path] = []
        stable_index = task_dir / 'results_index.json'
        if stable_index.exists():
            index_files.append(stable_index)

        timestamped = sorted(
            task_dir.glob(f'*_{task_id}.results_index.json'),
            key=lambda path: self._timestamp_from_index_name(path, task_id) or '',
            reverse=True,
        )
        for path in timestamped:
            if path not in index_files:
                index_files.append(path)
        return index_files

    def _build_complete_candidate(self, complete_path: Path, task_id: str) -> Dict[str, Any]:
        if complete_path.parent.name != task_id:
            raise ValueError(f'complete 文件不在 task_id 目录下：{complete_path}')

        timestamp = self._timestamp_from_complete_name(complete_path, task_id)
        if not timestamp:
            raise ValueError(f'complete 文件名不符合规范：{complete_path.name}')

        payload = self._read_json(complete_path)
        self._normalize_qc_result(payload, complete_path, task_id)

        return {
            'source_type': 'complete',
            'source_path': complete_path,
            'complete_path': complete_path,
            'timestamp': timestamp,
        }

    def _build_index_candidate(self, index_path: Path, task_id: str) -> Dict[str, Any]:
        if index_path.parent.name != task_id:
            raise ValueError(f'索引文件不在 task_id 目录下：{index_path}')

        index_data = self._read_json(index_path)
        if not self._is_index_like(index_data):
            raise ValueError(f'文件不是合法索引结构：{index_path}')
        if index_data.get('task_id') != task_id:
            raise ValueError(f'索引文件 task_id 不匹配：{index_path}')

        chosen = self._select_latest_record(index_data.get('results', []), task_id)
        if not chosen:
            raise ValueError(f'索引文件中没有匹配 task_id 的记录：{index_path}')

        complete_file = (chosen.get('result_files') or {}).get('complete')
        if not complete_file:
            raise ValueError(f'索引文件缺少 complete 文件路径：{index_path}')

        complete_path = self._resolve_complete_path(complete_file, index_path.parent)
        payload = self._read_json(complete_path)
        self._normalize_qc_result(payload, complete_path, task_id)

        timestamp = (
            self._parse_timestamp(chosen.get('timestamp'))
            or self._timestamp_from_complete_name(complete_path, task_id)
            or self._timestamp_from_index_name(index_path, task_id)
        )
        if not timestamp:
            raise ValueError(f'无法为索引候选解析时间戳：{index_path}')

        return {
            'source_type': 'index',
            'source_path': index_path,
            'complete_path': complete_path,
            'timestamp': timestamp,
        }

    def _find_latest_complete_file(self, task_dir: Path, task_id: str) -> Path:
        """在标准 task_id 目录内选择时间戳最新的合法 complete.json。"""
        candidates: List[Dict[str, Any]] = []
        errors: List[str] = []

        for complete_path in task_dir.glob(f'*_{task_id}.complete.json'):
            try:
                candidates.append(self._build_complete_candidate(complete_path, task_id))
            except Exception as exc:
                errors.append(f'{complete_path}: {exc}')

        if not candidates:
            detail = f'；忽略的非法候选数={len(errors)}' if errors else ''
            raise FileNotFoundError(
                f'无法从标准目录中找到合法的 complete.json（task_id={task_id}）：{task_dir}{detail}'
            )

        latest = max(candidates, key=self._candidate_sort_key)
        return latest['complete_path']

    def _find_task_dirs(self, search_root: Path, task_id: str) -> List[Path]:
        """在恢复搜索根目录下查找所有名为 task_id 的目录。"""
        if not search_root.exists():
            return []

        found_dirs: List[Path] = []
        seen = set()

        candidates = [search_root] if search_root.name == task_id and search_root.is_dir() else []
        try:
            candidates.extend(path for path in search_root.rglob(task_id) if path.is_dir())
        except (PermissionError, OSError):
            pass

        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found_dirs.append(resolved)

        return found_dirs

    def _search_task_in_tree(self, task_id: str, search_root: Path) -> Path:
        """
        在目录树中做受约束递归恢复。

        仅接受以下候选：
        - **/{task_id}/results_index.json
        - **/{task_id}/*_{task_id}.results_index.json
        - **/{task_id}/*_{task_id}.complete.json
        """
        candidates: Dict[Path, Dict[str, Any]] = {}
        rejected: List[str] = []

        for task_dir in self._find_task_dirs(search_root, task_id):
            for index_path in self._collect_index_files(task_dir, task_id):
                try:
                    candidate = self._build_index_candidate(index_path, task_id)
                    candidates[candidate['complete_path'].resolve()] = candidate
                except Exception as exc:
                    rejected.append(f'{index_path}: {exc}')

            for complete_path in task_dir.glob(f'*_{task_id}.complete.json'):
                try:
                    candidate = self._build_complete_candidate(complete_path, task_id)
                    candidates[candidate['complete_path'].resolve()] = candidate
                except Exception as exc:
                    rejected.append(f'{complete_path}: {exc}')

        valid_candidates = self._prefer_workspace_candidates(list(candidates.values()))
        if not valid_candidates:
            detail = '\n'.join(rejected[:10])
            if detail:
                detail = f'\n候选校验失败：\n{detail}'
            raise FileNotFoundError(
                f'在恢复搜索中未找到合法结果文件（task_id={task_id}，搜索根目录={search_root}）{detail}'
            )

        if len(valid_candidates) > 1:
            lines = []
            for candidate in sorted(valid_candidates, key=self._candidate_sort_key, reverse=True):
                lines.append(
                    f"- timestamp={candidate['timestamp']} source={candidate['source_path']} complete={candidate['complete_path']}"
                )
            raise ValueError(
                f'检测到多个合法结果文件候选，拒绝自动猜测（task_id={task_id}，搜索根目录={search_root}）：\n'
                + '\n'.join(lines)
            )

        return valid_candidates[0]['complete_path']
