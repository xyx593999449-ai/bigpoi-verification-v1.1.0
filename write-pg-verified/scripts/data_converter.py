#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据格式转换器模块
将上游JSON格式转换为数据库写入格式
"""

from typing import Dict, List, Any, Optional

try:
    from logger_config import get_logger
except ImportError:
    from .logger_config import get_logger

logger = get_logger(__name__)


class DataConverter:
    """
    数据格式转换器

    负责将上游大POI核实技能的JSON格式数据
    转换为数据库poi_verified表所需的格式
    """

    # 核实结果映射
    STATUS_MAP = {
        'accepted': '核实通过',
        'downgraded': '需人工核实',
        'manual_review': '需人工核实',
        'rejected': '需人工核实'
    }

    # POI状态映射
    POI_STATUS_MAP = {
        'pass': 1,        # 正常
        'uncertain': 4,   # 不确定
        'fail': 5,        # 不存在
        'upgrade': 2,     # 升级
        'downgrade': 3,   # 降级
        'split': 6        # 拆分
    }

    def __init__(self):
        """初始化数据转换器"""
        pass

    def decision_to_db_format(
        self,
        decision: Dict,
        evidence: List[Dict],
        poi_data: Dict,
        task_id: Optional[str] = None
    ) -> Dict:
        """
        将决策结果转换为数据库格式

        转换规则：
        - overall.status -> verify_result
        - overall.confidence -> overall_confidence
        - dimensions.existence.result -> poi_status
        - dimensions -> verify_info
        - evidence -> evidence_record
        - corrections -> changes_made
        - overall.summary -> verification_notes

        Args:
            decision: 决策结果字典
            evidence: 证据列表
            poi_data: POI基础数据
            task_id: 任务ID（优先使用此值，而非 decision.poi_id）

        Returns:
            数据库格式的字典
        """
        logger.debug("开始转换决策结果为数据库格式")

        # 提取overall信息
        overall = decision.get('overall', {})

        # 转换verify_result
        overall_status = overall.get('status', 'manual_review')
        verify_result = self.STATUS_MAP.get(overall_status, '需人工核实')

        # 转换poi_status
        dimensions = decision.get('dimensions', {})
        existence_result = dimensions.get('existence', {}).get('result', 'uncertain')
        poi_status = self.POI_STATUS_MAP.get(existence_result, 4)

        # 构建数据库格式数据
        # task_id 优先使用传入的参数，否则从 decision.poi_id 获取
        db_data = {
            'task_id': task_id if task_id else decision.get('poi_id', poi_data.get('id', '')),
            'id': poi_data.get('id', ''),
            'name': poi_data.get('name', ''),
            'x_coord': poi_data.get('x_coord'),
            'y_coord': poi_data.get('y_coord'),
            'poi_type': poi_data.get('poi_type'),
            'address': poi_data.get('address'),
            'city': poi_data.get('city'),
            'city_adcode': poi_data.get('city_adcode'),
            'verify_result': verify_result,
            'overall_confidence': overall.get('confidence'),
            'poi_status': poi_status,
            'verify_info': self._convert_dimensions(dimensions),
            'evidence_record': self._convert_evidence(evidence),
            'changes_made': self._convert_corrections(decision.get('corrections', [])),
            'verification_notes': overall.get('summary', ''),
            'verify_status': '已核实' if verify_result == '核实通过' else '需人工核实'
        }

        logger.debug(f"转换完成：task_id={db_data['task_id']}, verify_result={verify_result}, poi_status={poi_status}")
        return db_data

    def _convert_dimensions(self, dimensions: Dict) -> Dict:
        """
        转换维度信息为数据库格式

        Args:
            dimensions: 维度信息字典

        Returns:
            转换后的维度信息
        """
        if not dimensions:
            return {}

        # 确保返回的是字典类型
        if isinstance(dimensions, dict):
            return dimensions
        return {}

    def _convert_evidence(self, evidence: List[Dict]) -> List[Dict]:
        """
        转换证据记录为数据库格式

        Args:
            evidence: 证据列表

        Returns:
            转换后的证据列表
        """
        if not evidence:
            return []

        # 确保返回的是列表类型
        if isinstance(evidence, list):
            return evidence
        return [evidence] if isinstance(evidence, dict) else []

    def _convert_corrections(self, corrections: Any) -> Optional[List[Dict]]:
        """
        转换修正建议为数据库格式

        Args:
            corrections: 修正建议（可能是列表或字典）

        Returns:
            转换后的修正建议列表
        """
        if not corrections:
            return None

        if isinstance(corrections, list):
            return corrections
        elif isinstance(corrections, dict):
            return [corrections]
        return None

    def direct_data_to_db_format(self, data: Dict) -> Dict:
        """
        将直接输入的数据转换为数据库格式

        用于处理直接传递数据（非文件模式）的输入

        Args:
            data: 直接输入的数据字典

        Returns:
            数据库格式的字典
        """
        logger.debug("转换直接输入数据为数据库格式")

        # 如果数据中已包含verify_result，直接使用
        verify_result = data.get('verify_result', '需人工核实')

        # 构建数据库格式数据
        db_data = {
            'task_id': data.get('task_id', ''),
            'id': data.get('id', ''),
            'name': data.get('name', ''),
            'x_coord': data.get('x_coord'),
            'y_coord': data.get('y_coord'),
            'poi_type': data.get('poi_type'),
            'address': data.get('address'),
            'city': data.get('city'),
            'city_adcode': data.get('city_adcode'),
            'verify_result': verify_result,
            'overall_confidence': data.get('overall_confidence'),
            'poi_status': data.get('poi_status', 1),
            'verify_info': data.get('verify_info', {}),
            'evidence_record': data.get('evidence_record', {}),
            'changes_made': data.get('changes_made'),
            'verification_notes': data.get('verification_notes', ''),
            'verify_status': '已核实' if verify_result == '核实通过' else '需人工核实'
        }

        return db_data

    def validate_db_format(self, data: Dict) -> bool:
        """
        验证数据库格式数据的完整性

        Args:
            data: 数据库格式数据

        Returns:
            验证通过返回True，否则抛出异常
        """
        required_fields = ['task_id', 'id', 'verify_result']

        for field in required_fields:
            if field not in data or not data[field]:
                raise ValueError(f"数据库格式数据缺少必需字段：{field}")

        # 验证verify_result值
        valid_results = ['核实通过', '需人工核实']
        if data['verify_result'] not in valid_results:
            raise ValueError(f"verify_result值无效：{data['verify_result']}")

        return True

    def merge_with_poi_init_data(self, db_data: Dict, poi_init_data: Optional[Dict] = None) -> Dict:
        """
        将转换后的数据与poi_init表数据合并

        用于补充缺失的基础信息字段

        Args:
            db_data: 转换后的数据库格式数据
            poi_init_data: poi_init表中的原始数据

        Returns:
            合并后的数据
        """
        if not poi_init_data:
            return db_data

        # 补充缺失的基础字段
        merge_fields = ['name', 'x_coord', 'y_coord', 'poi_type', 'address', 'city', 'city_adcode']

        for field in merge_fields:
            if db_data.get(field) is None and field in poi_init_data:
                db_data[field] = poi_init_data[field]

        return db_data

    def extract_statistics_from_decision(self, decision: Dict) -> Dict[str, Any]:
        """
        从决策结果中提取统计信息

        Args:
            decision: 决策结果字典

        Returns:
            统计信息字典
        """
        overall = decision.get('overall', {})
        dimensions = decision.get('dimensions', {})

        stats = {
            'overall_status': overall.get('status', ''),
            'overall_confidence': overall.get('confidence', 0.0),
            'existence_result': dimensions.get('existence', {}).get('result', ''),
            'name_result': dimensions.get('name', {}).get('result', ''),
            'location_result': dimensions.get('location', {}).get('result', ''),
            'category_result': dimensions.get('category', {}).get('result', ''),
            'has_corrections': bool(decision.get('corrections')),
            'correction_count': len(decision.get('corrections', []))
        }

        return stats
