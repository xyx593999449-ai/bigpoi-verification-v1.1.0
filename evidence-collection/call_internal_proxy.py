#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内部代理调用脚本 - Evidence Collection Sub-Skill
版本: 1.5.0
作者: BigPOI Verification System
日期: 2026-03-05

功能说明:
    本脚本专门用于调用内部图商代理接口，获取POI相关证据数据。
    内部代理统一处理认证、限流、重试等问题，是推荐的首选调用方式。

用途说明:
    该脚本是证据收集技能的内部代理专用入口，主要作用包括：
    1. 关键词搜索：根据城市和关键词搜索POI
    2. 周边搜索：根据中心点和关键词搜索周边POI
    3. 自动规范化：将搜索结果转换为标准Evidence格式
    4. 错误处理和日志记录

    应用场景：POI证据收集、地图API统一调用、多源数据获取
"""

import sys
import io
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

# 设置UTF-8编码输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加scripts目录到路径
script_dir = Path(__file__).parent / 'scripts'
sys.path.insert(0, str(script_dir))

from map_api_client import MapAPIClient


def execute(data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """
    执行内部代理调用

    输入参数：
    ```python
    data = {
        'poi_id': 'POI_123',           # 必需：POI唯一标识
        'name': '北京大学第一医院',      # 必需：POI名称
        'poi_type': '090101',          # 必需：POI类型代码
        'city': '北京市',               # 必需：城市名称
        'address': '西城区西什库大街8号', # 可选：地址
        'coordinates': {                # 可选：坐标
            'longitude': 116.3723,
            'latitude': 39.9342
        },
        'search_method': 'keyword',     # 可选：搜索方法，keyword/around，默认keyword
        'sources': ['amap', 'bmap'],    # 可选：图商列表，默认调用所有
        'config_dir': 'config'          # 可选：配置文件目录，默认config
    }
    ```

    输出格式：
    ```python
    {
        'success': True,
        'evidence_list': [
            {
                'evidence_id': 'EVD_001',
                'poi_id': 'POI_123',
                'source': {...},
                'data': {...},
                'collected_at': '2026-03-05T12:00:00Z'
            }
        ],
        'total_count': 2,
        'summary': {...}
    }
    ```

    Args:
        data: 输入数据字典
        **kwargs: 额外的参数

    Returns:
        执行结果字典
    """
    if data is None:
        return {
            'success': False,
            'error': '缺少必要的输入数据'
        }

    # 验证必需字段
    required_fields = ['poi_id', 'name', 'poi_type', 'city']
    for field in required_fields:
        if field not in data:
            return {
                'success': False,
                'error': f'缺少必需字段：{field}'
            }

    poi_id = data['poi_id']
    name = data['name']
    poi_type = data['poi_type']
    city = data['city']
    address = data.get('address', '')
    coordinates = data.get('coordinates', {})
    search_method = data.get('search_method', 'keyword')
    sources = data.get('sources', ['amap', 'bmap', 'qmap'])
    config_dir = data.get('config_dir', 'config')

    try:
        # 加载配置
        config = _load_config(poi_type, config_dir)

        # 初始化客户端
        client = MapAPIClient(config)

        # 确保只调用内部代理
        client.internal_proxy_config['fallback_to_direct'] = False

        # 收集证据
        evidence_list = []
        source_mapping = config.get('source_mapping', {})

        for source in sources:
            if source not in ['amap', 'bmap', 'qmap']:
                continue

            try:
                if search_method == 'keyword':
                    results = client.search_by_keyword(
                        source=source,
                        city=city,
                        keyword=name,
                        poi_type=poi_type
                    )
                elif search_method == 'around':
                    if 'longitude' not in coordinates or 'latitude' not in coordinates:
                        return {
                            'success': False,
                            'error': '周边搜索需要提供坐标信息（longitude和latitude）'
                        }
                    results = client.search_around(
                        source=source,
                        city=city,
                        keyword=name,
                        location=(coordinates['longitude'], coordinates['latitude'])
                    )
                else:
                    continue

                # 转换为Evidence格式
                for idx, result in enumerate(results):
                    evidence = _convert_to_evidence(
                        result=result,
                        poi_id=poi_id,
                        source=source,
                        source_mapping=source_mapping,
                        index=idx
                    )
                    evidence_list.append(evidence)

            except Exception as e:
                # 记录错误但继续处理其他源
                print(f"调用 {source} 失败: {e}", file=sys.stderr)
                continue

        return {
            'success': True,
            'evidence_list': evidence_list,
            'total_count': len(evidence_list),
            'summary': {
                'poi_id': poi_id,
                'search_method': search_method,
                'sources_requested': sources,
                'sources_success': len(set(e.get('source', {}).get('source_id', '')[:4] for e in evidence_list)),
                'total_evidence': len(evidence_list)
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def _load_config(poi_type: str, config_dir: str) -> Dict[str, Any]:
    """加载配置文件"""
    import yaml

    config_path = Path(__file__).parent / config_dir
    common_config = config_path / 'common.yaml'
    type_config = config_path / f'{poi_type}.yaml'

    config = {}

    # 加载公共配置
    if common_config.exists():
        with open(common_config, 'r', encoding='utf-8') as f:
            config.update(yaml.safe_load(f))

    # 加载类型特定配置
    if type_config.exists():
        with open(type_config, 'r', encoding='utf-8') as f:
            type_data = yaml.safe_load(f)
            # 合并数据源配置
            if 'data_sources' in type_data:
                config.setdefault('data_sources', []).extend(type_data['data_sources'])

    return config


def _convert_to_evidence(
    result: Dict[str, Any],
    poi_id: str,
    source: str,
    source_mapping: Dict[str, str],
    index: int
) -> Dict[str, Any]:
    """将API结果转换为Evidence格式"""
    from datetime import datetime
    import uuid

    evidence_id = f"EVD_{datetime.now().strftime('%Y%m%d%H%M%S')}_{source.upper()}_{index:03d}"

    # 获取source配置
    source_name_map = {
        'amap': '高德地图',
        'bmap': '百度地图',
        'qmap': '腾讯地图'
    }

    return {
        'evidence_id': evidence_id,
        'poi_id': poi_id,
        'source': {
            'source_id': f"{source.upper()}_{result.get('id', 'unknown')}",
            'source_name': source_name_map.get(source, source.upper()),
            'source_type': 'map_vendor',
            'source_url': result.get('url', ''),
            'weight': 0.85
        },
        'collected_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'data': {
            'name': result.get('name', ''),
            'address': result.get('address', ''),
            'coordinates': {
                'longitude': result.get('longitude'),
                'latitude': result.get('latitude')
            } if result.get('longitude') and result.get('latitude') else None,
            'phone': result.get('tel', ''),
            'category': result.get('type', ''),
            'administrative': {
                'province': result.get('pname', ''),
                'city': result.get('cityname', ''),
                'district': result.get('adname', '')
            }
        },
        'verification': {
            'is_valid': True,
            'confidence': 0.85
        }
    }


# 命令行测试入口
if __name__ == '__main__':
    if len(sys.argv) < 5:
        print("用法: python call_internal_proxy.py <poi_id> <name> <poi_type> <city> [address] [longitude] [latitude]")
        print("示例:")
        print("  关键词搜索: python call_internal_proxy.py POI_123 '北京大学第一医院' 090101 '北京市'")
        print("  周边搜索: python call_internal_proxy.py POI_123 '北京大学第一医院' 090101 '北京市' '' 116.3723 39.9342")
        sys.exit(1)

    test_data = {
        'poi_id': sys.argv[1],
        'name': sys.argv[2],
        'poi_type': sys.argv[3],
        'city': sys.argv[4],
        'address': sys.argv[5] if len(sys.argv) > 5 else '',
        'search_method': 'around' if len(sys.argv) > 7 else 'keyword'
    }

    if len(sys.argv) > 7:
        test_data['coordinates'] = {
            'longitude': float(sys.argv[6]),
            'latitude': float(sys.argv[7])
        }

    result = execute(test_data)
    print("\n=== 执行结果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
