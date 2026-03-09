#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON文件加载器模块
提供从本地化JSON文件加载核实结果数据的功能
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from logger_config import get_logger
except ImportError:
    from .logger_config import get_logger

logger = get_logger(__name__)


class FileLoader:
    """
    本地化JSON文件加载器

    用于加载上游大POI核实技能生成的JSON文件：
    - index.json: 索引文件，包含所有相关文件的路径和POI基础信息
    - decision_*.json: 决策结果文件
    - evidence_*.json: 证据记录文件
    - record_*.json: 原始记录文件
    """

    def __init__(self, base_dir: Optional[str] = None):
        """
        初始化文件加载器

        Args:
            base_dir: 基础目录路径，用于解析相对路径
        """
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()

    def load_json_file(self, file_path: str) -> Dict:
        """
        加载JSON文件

        Args:
            file_path: JSON文件路径（绝对路径或相对于base_dir的相对路径）

        Returns:
            解析后的JSON字典

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON格式错误
        """
        path = self._resolve_path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{path}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.debug(f"成功加载JSON文件：{path}")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"JSON格式错误：{path}, {e}")
            raise

    def _resolve_path(self, file_path: str) -> Path:
        """
        解析文件路径（支持绝对路径和相对路径）

        Args:
            file_path: 文件路径

        Returns:
            解析后的Path对象
        """
        path = Path(file_path)
        if path.is_absolute():
            return path
        return self.base_dir / path

    def load_index_file(self, index_file_path: str) -> Dict:
        """
        加载索引文件

        索引文件格式：
        {
          "task_id": "TASK_20260227_001",
          "poi_id": "POI_12345",
          "files": {
            "decision": "decision_DEC_20260227_001.json",
            "evidence": "evidence_EVD_20260227_001.json",
            "record": "record_REC_20260227_001.json"
          }
        }

        注意：POI 基础数据从 record 文件的 input_data 字段中读取

        Args:
            index_file_path: 索引文件路径

        Returns:
            索引文件内容的字典
        """
        logger.info(f"加载索引文件：{index_file_path}")
        index_data = self.load_json_file(index_file_path)

        # 验证必需字段（移除 poi_data，因为数据从 record 文件读取）
        required_fields = ['task_id', 'poi_id', 'files']
        for field in required_fields:
            if field not in index_data:
                raise ValueError(f"索引文件缺少必需字段：{field}")

        # 验证files字段
        files = index_data['files']
        if 'decision' not in files:
            raise ValueError("索引文件的files字段缺少decision文件路径")

        return index_data

    def load_decision_file(self, file_path: str) -> Dict:
        """
        加载决策结果文件

        决策文件包含：
        - decision_id: 决策唯一标识
        - poi_id: 关联的POI ID
        - overall: 整体决策结果（status, confidence, action, summary）
        - dimensions: 多维度决策结果
        - evidence_summary: 证据摘要
        - corrections: 修正建议

        Args:
            file_path: 决策文件路径

        Returns:
            决策结果字典
        """
        logger.info(f"加载决策文件：{file_path}")
        decision = self.load_json_file(file_path)

        # 验证必需字段
        if 'overall' not in decision:
            raise ValueError("决策文件缺少overall字段")
        if 'dimensions' not in decision:
            raise ValueError("决策文件缺少dimensions字段")

        return decision

    def load_evidence_file(self, file_path: str) -> List[Dict]:
        """
        加载证据记录文件

        证据文件可以是单个证据对象或证据数组

        Args:
            file_path: 证据文件路径

        Returns:
            证据列表
        """
        logger.info(f"加载证据文件：{file_path}")
        evidence_data = self.load_json_file(file_path)

        # 如果是单个对象，包装成数组
        if isinstance(evidence_data, dict):
            return [evidence_data]
        elif isinstance(evidence_data, list):
            return evidence_data
        else:
            raise ValueError(f"证据文件格式不正确，应为对象或数组：{type(evidence_data)}")

    def load_record_file(self, file_path: str) -> Dict:
        """
        加载原始记录文件

        Args:
            file_path: 记录文件路径

        Returns:
            原始记录字典
        """
        logger.info(f"加载记录文件：{file_path}")
        return self.load_json_file(file_path)

    def load_all_from_index(self, index_file_path: str, load_evidence: bool = True, load_record: bool = False) -> Dict[str, Any]:
        """
        从索引文件加载所有相关数据

        Args:
            index_file_path: 索引文件路径
            load_evidence: 是否加载证据文件
            load_record: 是否加载记录文件

        Returns:
            包含所有加载数据的字典：
            {
                'index': {...},  # 索引文件内容
                'decision': {...},  # 决策文件内容
                'evidence': [...],  # 证据文件内容（如果load_evidence=True）
                'record': {...}  # 记录文件内容（如果load_record=True）
            }
        """
        # 加载索引文件
        index_data = self.load_index_file(index_file_path)

        # 获取索引文件所在目录，用于解析相对路径
        index_dir = Path(index_file_path).parent

        result = {
            'index': index_data
        }

        # 加载决策文件（必需）
        decision_path = index_dir / index_data['files']['decision']
        result['decision'] = self.load_decision_file(str(decision_path))

        # 加载证据文件（可选）
        if load_evidence and 'evidence' in index_data['files']:
            evidence_path = index_dir / index_data['files']['evidence']
            result['evidence'] = self.load_evidence_file(str(evidence_path))
        else:
            result['evidence'] = []

        # 加载记录文件（可选）
        if load_record and 'record' in index_data['files']:
            record_path = index_dir / index_data['files']['record']
            result['record'] = self.load_record_file(str(record_path))

        logger.info(f"成功从索引文件加载所有数据：task_id={index_data['task_id']}")
        return result

    def validate_index_structure(self, index_data: Dict) -> bool:
        """
        验证索引文件结构的完整性

        Args:
            index_data: 索引文件内容

        Returns:
            验证通过返回True，否则抛出异常
        """
        # 验证必需字段（移除 poi_data，因为数据从 record 文件读取）
        required_fields = ['task_id', 'poi_id', 'files']

        for field in required_fields:
            if field not in index_data:
                raise ValueError(f"索引文件缺少必需字段：{field}")

        # 验证files字段
        files = index_data['files']
        if not isinstance(files, dict):
            raise ValueError("索引文件的files字段必须是对象类型")

        if 'decision' not in files:
            raise ValueError("索引文件的files字段缺少decision文件路径")

        return True
