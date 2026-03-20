#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据转换器 - 将质检结果转换为数据库格式
"""

from typing import Dict, Any


class DataConverter:
    """质检结果数据格式转换器"""

    def convert(self, qc_result: Dict) -> Dict:
        """
        将质检结果转换为数据库写入格式

        Args:
            qc_result: 质检结果对象（符合schema/qc_result.schema.json规范）

        Returns:
            转换后的数据库字段映射
        """
        # 验证必需字段
        # 数据结构为{"qc_result": {...}}
        if 'qc_result' in qc_result and isinstance(qc_result.get('qc_result'), dict):
            inner = qc_result.get('qc_result')
            if 'task_id' in qc_result and 'task_id' not in inner:
                inner['task_id'] = qc_result.get('task_id')
            qc_result = inner

        # 验证必需字段
        required_fields = ['task_id', 'qc_status', 'qc_score', 'has_risk',
                          'risk_dims', 'triggered_rules', 'dimension_results',
                          'explanation', 'statistics_flags']

        missing = [field for field in required_fields if field not in qc_result]
        if missing:
            keys = list(qc_result.keys())
            raise ValueError(f"缺少必需字段：{','.join(missing)}，现有字段：{keys}")

        # 提取统计标记
        statistics_flags = qc_result.get('statistics_flags', {})
        dimension_results = qc_result.get('dimension_results', {})
        downgrade_consistency = dimension_results.get('downgrade_consistency', {})
        legacy_downgrade = dimension_results.get('downgrade', {})

        # 优先使用当前结构 downgrade_consistency，保留对旧结构的兼容读取
        downgrade_status = downgrade_consistency.get('status')
        if downgrade_status is None:
            downgrade_status = legacy_downgrade.get('status')

        # 转换数据
        converted = {
            'task_id': qc_result['task_id'],
            'qc_status': qc_result['qc_status'],
            'qc_score': int(qc_result['qc_score']),
            'has_risk': 1 if qc_result.get('has_risk', False) else 0,
            'is_qualified': 1 if statistics_flags.get('is_qualified', False) else 0,
            'is_auto_approvable': 1 if statistics_flags.get('is_auto_approvable', False) else 0,
            'is_manual_required': 1 if statistics_flags.get('is_manual_required', False) else 0,
            'downgrade_issue_type': statistics_flags.get('downgrade_issue_type'),
            'downgrade_status': downgrade_status,
            'is_downgrade_consistent': 1 if downgrade_consistency.get('is_consistent', False) else 0,
            'qc_result': qc_result,  # 完整的qc_result对象，将由db_writer转换为JSONB
            'risk_dims': qc_result.get('risk_dims', []),
            'triggered_rules': qc_result.get('triggered_rules', []),
            'dimension_results': qc_result.get('dimension_results', {}),
            'explanation': qc_result.get('explanation', '')
        }

        return converted


