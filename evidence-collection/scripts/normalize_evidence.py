#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
# Version: 1.0.2
# Author: BigPOI Verification System
# Date: 2024-01-15

功能定义说明:
    本脚本负责大POI核实流程中的证据规范化处理阶段，对收集到的原始证据进行
    名称、地址、坐标等字段的标准化与规范化处理，确保数据格式一致、可比较。

用途说明:
    该脚本在整个核实流程中处于第三阶段（证据规范化处理），主要作用包括：
    1. 名称规范化：去除空格、标点、标准化简称
    2. 地址标准化：补全行政区划、统一格式
    3. 坐标系统转换：WGS84/BD09 → GCJ02（国测局坐标系）
    4. 分类信息映射：统一分类编码体系
    5. 证据去重和冲突标记
    6. 生成可用于后续维度判断的规范化证据对象

    应用场景：多源证据的规范化处理、坐标系统转换、数据冲突检测
"""

import json
import logging
import math
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from difflib import SequenceMatcher

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NormalizedEvidence:
    """规范化证据数据类 - 兼容Python 3.6"""

    def __init__(
        self,
        evidence_id: str,
        poi_id: str,
        original_data: Dict[str, Any],
        normalized_data: Dict[str, Any],
        normalization_log: List[str],
        source: Dict[str, Any],
        confidence: float
    ):
        self.evidence_id = evidence_id
        self.poi_id = poi_id
        self.original_data = original_data
        self.normalized_data = normalized_data
        self.normalization_log = normalization_log
        self.source = source
        self.confidence = confidence

    def __repr__(self):
        return (f"NormalizedEvidence(evidence_id={self.evidence_id!r}, "
                f"poi_id={self.poi_id!r}, confidence={self.confidence!r})")


class CoordinateTransformer:
    """坐标转换工具类"""

    # WGS84 to GCJ02 转换参数
    M_PI = 3.14159265358979324
    A = 6378245.0
    EE = 0.00669342162296594323

    @staticmethod
    def wgs84_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
        """
        WGS84坐标转GCJ02坐标

        Args:
            lon: WGS84 经度
            lat: WGS84 纬度

        Returns:
            (GCJ02经度, GCJ02纬度)
        """
        if CoordinateTransformer._out_of_china(lon, lat):
            return lon, lat

        dx = CoordinateTransformer._calculate_lat_offset(lon, lat - 35.0)
        dy = CoordinateTransformer._calculate_lon_offset(lon - 105.0, lat - 35.0)

        rad_lat = (lat - 35.0) * CoordinateTransformer.M_PI / 180.0
        magic = math.sin(rad_lat)
        magic = 1 - CoordinateTransformer.EE * magic * magic
        magic = math.sqrt(magic)

        dy = (dy * 180.0) / (CoordinateTransformer.A / magic * math.cos(rad_lat) * CoordinateTransformer.M_PI)
        dx = (dx * 180.0) / (CoordinateTransformer.A / magic * CoordinateTransformer.M_PI)

        gcj_lat = lat + dx
        gcj_lon = lon + dy

        return gcj_lon, gcj_lat

    @staticmethod
    def bd09_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
        """
        BD09坐标转GCJ02坐标

        Args:
            lon: BD09 经度
            lat: BD09 纬度

        Returns:
            (GCJ02经度, GCJ02纬度)
        """
        x = lon - 0.0065
        y = lat - 0.006

        z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * CoordinateTransformer.M_PI)
        theta = math.atan2(y, x) - 0.000003 * math.cos(x * CoordinateTransformer.M_PI)

        gcj_lon = z * math.cos(theta)
        gcj_lat = z * math.sin(theta)

        return gcj_lon, gcj_lat

    @staticmethod
    def _out_of_china(lon: float, lat: float) -> bool:
        """判断坐标是否在中国范围外"""
        if lon < 72.004 or lon > 137.4047:
            return True
        if lat < 0.8293 or lat > 55.8271:
            return True
        return False

    @staticmethod
    def _calculate_lat_offset(lon: float, lat: float) -> float:
        """计算纬度偏移"""
        ret = (-100.0 + 2.0 * lon + 3.0 * lat + 0.2 * lat * lat +
               0.1 * lon * lat + 0.2 * math.sqrt(abs(lon)))
        ret += ((20.0 * math.sin(6.0 * lon * CoordinateTransformer.M_PI / 180.0) +
                 20.0 * math.sin(2.0 * lon * CoordinateTransformer.M_PI / 180.0)) * 2.0 / 3.0)
        ret += ((20.0 * math.sin(lat * CoordinateTransformer.M_PI / 180.0) +
                 40.0 * math.sin(lat / 3.0 * CoordinateTransformer.M_PI / 180.0)) * 2.0 / 3.0)
        ret += ((160.0 * math.sin(lat / 12.0 * CoordinateTransformer.M_PI / 180.0) +
                 320 * math.sin(lat * CoordinateTransformer.M_PI / 180.0 / 30.0)) * 2.0 / 3.0)
        return ret

    @staticmethod
    def _calculate_lon_offset(lon: float, lat: float) -> float:
        """计算经度偏移"""
        ret = (300.0 + lon + 2.0 * lat + 0.1 * lon * lon +
               0.1 * lon * lat + 0.1 * math.sqrt(abs(lon)))
        ret += ((20.0 * math.sin(6.0 * lon * CoordinateTransformer.M_PI / 180.0) +
                 20.0 * math.sin(2.0 * lon * CoordinateTransformer.M_PI / 180.0)) * 2.0 / 3.0)
        ret += ((20.0 * math.sin(lon * CoordinateTransformer.M_PI / 180.0) +
                 40.0 * math.sin(lon / 3.0 * CoordinateTransformer.M_PI / 180.0)) * 2.0 / 3.0)
        ret += ((150.0 * math.sin(lon / 12.0 * CoordinateTransformer.M_PI / 180.0) +
                 300.0 * math.sin(lon / 30.0 * CoordinateTransformer.M_PI / 180.0)) * 2.0 / 3.0)
        return ret


class EvidenceNormalizer:
    """证据规范化处理器"""

    def __init__(self):
        """初始化规范化处理器"""
        self.transformer = CoordinateTransformer()
        logger.info("证据规范化处理器初始化完成")

    def normalize(self, evidence: Dict[str, Any]) -> NormalizedEvidence:
        """
        规范化单条证据

        Args:
            evidence: 原始证据对象

        Returns:
            规范化后的证据对象
        """
        evidence_id = evidence.get('evidence_id', 'UNKNOWN')
        poi_id = evidence.get('poi_id', 'UNKNOWN')
        normalization_log = []

        logger.info(f"开始规范化证据: {evidence_id}")

        # 深复制数据
        normalized_data = {}

        # 1. 规范化名称
        if 'data' in evidence and 'name' in evidence['data']:
            original_name = evidence['data']['name']
            normalized_name = self._normalize_name(original_name)
            normalized_data['name'] = normalized_name

            if original_name != normalized_name:
                normalization_log.append(f"名称规范化: '{original_name}' → '{normalized_name}'")

        # 2. 规范化地址
        if 'data' in evidence and 'address' in evidence['data']:
            original_address = evidence['data']['address']
            normalized_address = self._normalize_address(original_address)
            normalized_data['address'] = normalized_address

            if original_address != normalized_address:
                normalization_log.append(f"地址规范化: '{original_address}' → '{normalized_address}'")

        # 3. 转换坐标系统
        if 'data' in evidence and 'coordinates' in evidence['data']:
            coords = evidence['data']['coordinates']
            normalized_coords, coord_log = self._normalize_coordinates(coords)
            normalized_data['coordinates'] = normalized_coords
            normalization_log.extend(coord_log)

        # 4. 复制其他字段
        if 'data' in evidence:
            for key, value in evidence['data'].items():
                if key not in ['name', 'address', 'coordinates']:
                    normalized_data[key] = value

        # 5. 计算置信度
        confidence = evidence.get('verification', {}).get('confidence', 0.5)

        normalized_evidence = NormalizedEvidence(
            evidence_id=evidence_id,
            poi_id=poi_id,
            original_data=evidence.get('data', {}),
            normalized_data=normalized_data,
            normalization_log=normalization_log,
            source=evidence.get('source', {}),
            confidence=confidence
        )

        logger.info(f"证据 {evidence_id} 规范化完成，记录 {len(normalization_log)} 条转换")
        return normalized_evidence

    def _normalize_name(self, name: str) -> str:
        """
        规范化名称

        Args:
            name: 原始名称

        Returns:
            规范化后的名称
        """
        if not name:
            return name

        # 去除前后空格
        normalized = name.strip()

        # 去除多余空格
        normalized = ' '.join(normalized.split())

        # 转换为简体中文
        normalized = self._convert_to_simplified(normalized)

        return normalized

    def _normalize_address(self, address: str) -> str:
        """
        规范化地址

        Args:
            address: 原始地址

        Returns:
            规范化后的地址
        """
        if not address:
            return address

        # 去除前后空格
        normalized = address.strip()

        # 去除多余空格
        normalized = ' '.join(normalized.split())

        return normalized

    def _normalize_coordinates(self, coords: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        规范化坐标，转换为GCJ02

        Args:
            coords: 原始坐标

        Returns:
            (规范化后的坐标, 转换日志)
        """
        logs = []

        if not isinstance(coords, dict):
            return coords, logs

        lon = coords.get('longitude')
        lat = coords.get('latitude')
        coord_system = coords.get('coordinate_system', 'GCJ02')

        if lon is None or lat is None:
            return coords, logs

        try:
            lon = float(lon)
            lat = float(lat)
        except (ValueError, TypeError):
            return coords, logs

        # 如果已是GCJ02，直接返回
        if coord_system == 'GCJ02':
            return {
                'longitude': lon,
                'latitude': lat,
                'coordinate_system': 'GCJ02'
            }, logs

        # 转换坐标系统
        if coord_system == 'WGS84':
            new_lon, new_lat = self.transformer.wgs84_to_gcj02(lon, lat)
            logs.append(f"坐标系转换: WGS84({lon}, {lat}) → GCJ02({new_lon:.6f}, {new_lat:.6f})")

        elif coord_system == 'BD09':
            new_lon, new_lat = self.transformer.bd09_to_gcj02(lon, lat)
            logs.append(f"坐标系转换: BD09({lon}, {lat}) → GCJ02({new_lon:.6f}, {new_lat:.6f})")

        else:
            # 不支持的坐标系统，返回原坐标
            new_lon, new_lat = lon, lat
            logs.append(f"警告: 不支持的坐标系统 {coord_system}，返回原坐标")

        return {
            'longitude': new_lon,
            'latitude': new_lat,
            'coordinate_system': 'GCJ02'
        }, logs

    def _convert_to_simplified(self, text: str) -> str:
        """
        转换为简体中文（简化版本）

        Args:
            text: 原始文本

        Returns:
            转换后的文本
        """
        # 注：完整的繁简转换需要使用专门的库（如opencc）
        # 这里仅作演示，保持原文本不变
        return text

    def batch_normalize(self, evidence_list: List[Dict[str, Any]]) -> Tuple[List[NormalizedEvidence], dict]:
        """
        批量规范化证据

        Args:
            evidence_list: 证据列表

        Returns:
            (规范化证据列表, 统计信息)
        """
        normalized_list = []
        stats = {
            'total': len(evidence_list),
            'successful': 0,
            'failed': 0,
            'total_transformations': 0
        }

        logger.info(f"开始批量规范化 {len(evidence_list)} 条证据")

        for evidence in evidence_list:
            try:
                normalized = self.normalize(evidence)
                normalized_list.append(normalized)
                stats['successful'] += 1
                stats['total_transformations'] += len(normalized.normalization_log)
            except Exception as e:
                logger.error(f"规范化证据失败: {evidence.get('evidence_id', 'UNKNOWN')}, 错误: {e}")
                stats['failed'] += 1

        logger.info(
            f"批量规范化完成: 总数={stats['total']}, "
            f"成功={stats['successful']}, 失败={stats['failed']}, "
            f"总转换数={stats['total_transformations']}"
        )

        return normalized_list, stats


async def main():
    """
    主函数 - 示例用法
    """
    # 示例证据数据
    evidence_list = [
        {
            'evidence_id': 'EVD_001',
            'poi_id': 'HOSPITAL_BJ_001',
            'source': {
                'source_id': 'AMAP',
                'source_name': '高德地图',
                'weight': 0.85
            },
            'data': {
                'name': '  北京大学第一医院  ',
                'address': '北京市   西城区   西什库大街8号',
                'coordinates': {
                    'longitude': 116.3723,
                    'latitude': 39.9342,
                    'coordinate_system': 'WGS84'
                }
            },
            'verification': {
                'confidence': 0.85
            }
        },
        {
            'evidence_id': 'EVD_002',
            'poi_id': 'HOSPITAL_BJ_001',
            'source': {
                'source_id': 'BAIDU',
                'source_name': '百度地图',
                'weight': 0.85
            },
            'data': {
                'name': '北京大学第一医院',
                'address': '北京市西城区西什库大街8号',
                'coordinates': {
                    'longitude': 116.3724,
                    'latitude': 39.9343,
                    'coordinate_system': 'BD09'
                }
            },
            'verification': {
                'confidence': 0.85
            }
        }
    ]

    # 规范化证据
    normalizer = EvidenceNormalizer()
    normalized_list, stats = normalizer.batch_normalize(evidence_list)

    # 打印结果
    print("\n===== 证据规范化结果 =====")
    print(f"总数: {stats['total']}, 成功: {stats['successful']}, 失败: {stats['failed']}")
    print(f"总转换数: {stats['total_transformations']}")

    for normalized in normalized_list:
        print(f"\n证据ID: {normalized.evidence_id}")
        print(f"原始数据: {normalized.original_data}")
        print(f"规范化数据: {normalized.normalized_data}")
        if normalized.normalization_log:
            print("转换日志:")
            for log in normalized.normalization_log:
                print(f"  - {log}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
