#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
# Version: 1.0.0
# Author: BigPOI Verification System
# Date: 2026-03-03

功能定义说明:
    本脚本负责大POI核实流程中的图商API调用，实现统一的地图数据查询接口。
    支持内部代理优先调用策略，失败后降级到直接调用图商API。

用途说明:
    该脚本在整个核实流程中处于证据收集阶段，主要作用包括：
    1. 关键词搜索：根据城市和关键词搜索POI
    2. 周边搜索：根据中心点和关键词搜索周边POI
    3. API调用策略：优先调用内部代理接口，失败后降级到直接API
    4. 凭据池管理：支持多个API Key的轮询和重试机制
    5. 错误处理和日志记录

    应用场景：POI证据收集、地图API统一调用、多源数据获取
"""

import sys
import io
import json
import logging
import time
import random
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlencode, quote

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

# 强制UTF-8编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class APIKeyPool:
    """API Key 凭据池管理器"""

    def __init__(self, credentials: List[Dict[str, str]]):
        """
        初始化凭据池

        Args:
            credentials: 凭据列表，每个凭据包含 ak/key 和 referer
        """
        self.credentials = credentials
        self.current_index = 0
        self.failed_keys = set()
        logger.info(f"凭据池初始化完成，共 {len(credentials)} 个凭据")

    def get_next_credential(self) -> Optional[Dict[str, str]]:
        """
        获取下一个可用凭据（轮询策略）

        Returns:
            可用的凭据字典，如果全部失败则返回None
        """
        if not self.credentials:
            return None

        # 如果所有凭据都失败过，重置失败列表
        if len(self.failed_keys) >= len(self.credentials):
            logger.warning("所有凭据均已失败，重置失败列表")
            self.failed_keys.clear()

        # 尝试获取下一个可用凭据
        attempts = 0
        while attempts < len(self.credentials):
            credential = self.credentials[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.credentials)
            attempts += 1

            cred_id = credential.get('ak') or credential.get('key', '')
            if cred_id not in self.failed_keys:
                return credential

        return None

    def mark_failed(self, credential: Dict[str, str]):
        """
        标记凭据为失败

        Args:
            credential: 失败的凭据
        """
        cred_id = credential.get('ak') or credential.get('key', '')
        self.failed_keys.add(cred_id)
        logger.warning(f"凭据已标记为失败: {cred_id[:10]}...，剩余可用凭据: {len(self.credentials) - len(self.failed_keys)}")

    def reset(self):
        """重置凭据池状态"""
        self.failed_keys.clear()
        self.current_index = 0
        logger.info("凭据池状态已重置")


class MapAPIClient:
    """
    统一的图商API客户端
    支持内部代理优先调用策略，失败后降级到直接API
    """

    # Source 映射：内部代理使用的source值
    SOURCE_MAPPING = {
        'amap': 'amap2',
        'bmap': 'bmap',
        'qmap': 'qmap'
    }

    # 图商API端点配置
    API_ENDPOINTS = {
        'amap': 'https://restapi.amap.com/v3/place/text',
        'bmap': 'https://api.map.baidu.com/place/v2/search',
        'qmap': 'https://apis.map.qq.com/ws/place/v1/search'
    }

    def __init__(self, config: Dict[str, Any]):
        """
        初始化图商API客户端

        Args:
            config: 配置字典，包含凭据和代理配置
        """
        self.config = config
        self.credentials = config.get('credentials', {})
        self.global_config = config.get('global', {})
        self.internal_proxy_config = config.get('internal_proxy', {})
        self.map_vendors = config.get('map_vendors', {})

        # 初始化凭据池
        self.key_pools = {}
        for source, creds in self.credentials.items():
            if creds:
                self.key_pools[source] = APIKeyPool(creds)

        # 初始化HTTP会话
        self.session = None
        if requests:
            self.session = self._create_session()

        logger.info("图商API客户端初始化完成")

    def _create_session(self) -> 'requests.Session':
        """
        创建带重试策略的HTTP会话

        Returns:
            配置好的Session对象
        """
        session = requests.Session()

        # 配置重试策略
        retry_count = self.global_config.get('retry_count', 3)
        retry_strategy = Retry(
            total=retry_count,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def search_by_keyword(
        self,
        source: str,
        city: str,
        keyword: str,
        poi_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        关键词搜索

        Args:
            source: 图商来源 (amap/bmap/qmap)
            city: 城市名称
            keyword: 搜索关键词
            poi_type: POI类型（可选，用于细化搜索）

        Returns:
            搜索结果列表
        """
        logger.info(f"关键词搜索: source={source}, city={city}, keyword={keyword}")

        # 参数验证
        if source not in ['amap', 'bmap', 'qmap']:
            logger.error(f"不支持的图商: {source}")
            return []

        # 尝试调用内部代理
        if self.internal_proxy_config.get('enabled', True):
            try:
                results = self._call_internal_proxy(
                    source=source,
                    method='text',
                    city=city,
                    keyword=keyword,
                    poi_type=poi_type
                )
                if results:
                    logger.info(f"内部代理调用成功，返回 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.warning(f"内部代理调用失败: {e}")

        # 降级到直接API
        if self.internal_proxy_config.get('fallback_to_direct', True):
            try:
                results = self._call_direct_api(
                    source=source,
                    method='text',
                    city=city,
                    keyword=keyword,
                    poi_type=poi_type
                )
                if results:
                    logger.info(f"直接API调用成功，返回 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.error(f"直接API调用失败: {e}")

        logger.warning("所有调用方式均失败")
        return []

    def search_around(
        self,
        source: str,
        city: str,
        keyword: str,
        location: Tuple[float, float],
        radius: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        周边搜索

        Args:
            source: 图商来源 (amap/bmap/qmap)
            city: 城市名称
            keyword: 搜索关键词
            location: (经度, 纬度)
            radius: 搜索半径（米）

        Returns:
            搜索结果列表
        """
        logger.info(f"周边搜索: source={source}, city={city}, keyword={keyword}, location={location}, radius={radius}")

        # 参数验证
        if source not in ['amap', 'bmap', 'qmap']:
            logger.error(f"不支持的图商: {source}")
            return []

        lon, lat = location
        location_str = f"{lon},{lat}"

        # 尝试调用内部代理
        if self.internal_proxy_config.get('enabled', True):
            try:
                results = self._call_internal_proxy(
                    source=source,
                    method='around',
                    city=city,
                    keyword=keyword,
                    location=location_str,
                    radius=radius
                )
                if results:
                    logger.info(f"内部代理调用成功，返回 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.warning(f"内部代理调用失败: {e}")

        # 降级到直接API
        if self.internal_proxy_config.get('fallback_to_direct', True):
            try:
                results = self._call_direct_api(
                    source=source,
                    method='around',
                    city=city,
                    keyword=keyword,
                    location=location_str,
                    radius=radius
                )
                if results:
                    logger.info(f"直接API调用成功，返回 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.error(f"直接API调用失败: {e}")

        logger.warning("所有调用方式均失败")
        return []

    def _call_internal_proxy(
        self,
        source: str,
        method: str,
        city: str,
        keyword: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        调用内部代理接口

        Args:
            source: 图商来源
            method: 调用方法 (text/around)
            city: 城市名称
            keyword: 搜索关键词
            **kwargs: 其他参数

        Returns:
            搜索结果列表

        Raises:
            Exception: 调用失败时抛出异常
        """
        base_url = self.internal_proxy_config.get('base_url', 'http://10.82.122.209:9081/botshop/proxy/mapapi')
        timeout = self.internal_proxy_config.get('timeout', 30)
        retry_count = self.internal_proxy_config.get('retry_count', 3)

        # 映射source值
        proxy_source = self.SOURCE_MAPPING.get(source, source)

        # 构建查询参数
        params = {
            'source': proxy_source,
            'method': method,
            'city': city,
            'keyword': keyword
        }

        # 添加可选参数
        if 'location' in kwargs:
            params['location'] = kwargs['location']
        if 'radius' in kwargs:
            params['radius'] = kwargs['radius']
        if 'poi_type' in kwargs and kwargs['poi_type']:
            params['poi_type'] = kwargs['poi_type']

        url = f"{base_url}?{urlencode(params, quote_via=quote)}"

        logger.debug(f"内部代理URL: {url}")

        if not self.session:
            raise RuntimeError("requests库未安装，无法进行HTTP调用")

        # 重试机制
        last_error = None
        for attempt in range(retry_count):
            try:
                response = self.session.get(url, timeout=timeout)
                response.raise_for_status()

                data = response.json()
                return self._parse_internal_proxy_response(source, data)

            except Exception as e:
                last_error = e
                logger.warning(f"内部代理调用失败 (尝试 {attempt + 1}/{retry_count}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(1 * (attempt + 1))  # 指数退避

        raise last_error or Exception("内部代理调用失败")

    def _call_direct_api(
        self,
        source: str,
        method: str,
        city: str,
        keyword: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        直接调用图商API（降级方案）

        Args:
            source: 图商来源
            method: 调用方法 (text/around)
            city: 城市名称
            keyword: 搜索关键词
            **kwargs: 其他参数

        Returns:
            搜索结果列表

        Raises:
            Exception: 调用失败时抛出异常
        """
        timeout = self.global_config.get('request_timeout', 30)
        key_pool = self.key_pools.get(source)

        if not key_pool:
            raise Exception(f"图商 {source} 没有配置凭据")

        # 尝试使用不同凭据
        max_attempts = len(self.credentials.get(source, []))
        last_error = None

        for attempt in range(max_attempts):
            credential = key_pool.get_next_credential()
            if not credential:
                break

            try:
                if source == 'amap':
                    results = self._call_amap_direct(credential, method, city, keyword, timeout, **kwargs)
                elif source == 'bmap':
                    results = self._call_bmap_direct(credential, method, city, keyword, timeout, **kwargs)
                elif source == 'qmap':
                    results = self._call_qmap_direct(credential, method, city, keyword, timeout, **kwargs)
                else:
                    raise Exception(f"不支持的图商: {source}")

                return results

            except Exception as e:
                last_error = e
                key_pool.mark_failed(credential)
                logger.warning(f"凭据调用失败 (尝试 {attempt + 1}/{max_attempts}): {e}")

        raise last_error or Exception("直接API调用失败：所有凭据均已失败")

    def _call_amap_direct(
        self,
        credential: Dict[str, str],
        method: str,
        city: str,
        keyword: str,
        timeout: int,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """直接调用高德地图API"""
        api_key = credential.get('ak', '')
        endpoint = self.API_ENDPOINTS['amap']

        params = {
            'key': api_key,
            'keywords': keyword,
            'city': city,
            'output': 'json',
            'offset': 20,
            'page': 1
        }

        if method == 'around' and 'location' in kwargs:
            params['types'] = ''
            params['location'] = kwargs['location']
            params['radius'] = kwargs.get('radius', 1000)

        response = self.session.get(endpoint, params=params, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        return self._parse_amap_response(data)

    def _call_bmap_direct(
        self,
        credential: Dict[str, str],
        method: str,
        city: str,
        keyword: str,
        timeout: int,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """直接调用百度地图API"""
        api_key = credential.get('ak', '')
        endpoint = self.API_ENDPOINTS['bmap']

        params = {
            'ak': api_key,
            'query': keyword,
            'region': city,
            'output': 'json',
            'page_size': 20,
            'page_num': 0
        }

        if method == 'around' and 'location' in kwargs:
            params['radius'] = kwargs.get('radius', 1000)
            params['location'] = kwargs['location']

        response = self.session.get(endpoint, params=params, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        return self._parse_bmap_response(data)

    def _call_qmap_direct(
        self,
        credential: Dict[str, str],
        method: str,
        city: str,
        keyword: str,
        timeout: int,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """直接调用腾讯地图API"""
        api_key = credential.get('key', '')
        endpoint = self.API_ENDPOINTS['qmap']

        params = {
            'key': api_key,
            'keyword': keyword,
            'boundary': f'region({city},0)',
            'page_size': 20,
            'page_index': 1
        }

        if method == 'around' and 'location' in kwargs:
            params['boundary'] = f'nearby({kwargs["location"]},{kwargs.get("radius", 1000)})'

        response = self.session.get(endpoint, params=params, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        return self._parse_qmap_response(data)

    def _parse_internal_proxy_response(self, source: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析内部代理响应"""
        if source == 'amap':
            return self._parse_amap_response(data)
        elif source == 'bmap':
            return self._parse_bmap_response(data)
        elif source == 'qmap':
            return self._parse_qmap_response(data)
        return []

    def _parse_amap_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析高德地图API响应"""
        results = []

        if data.get('status') == 1 and 'pois' in data:
            for poi in data['pois']:
                results.append({
                    'name': poi.get('name', ''),
                    'address': poi.get('address', ''),
                    'location': poi.get('location', ''),
                    'tel': poi.get('tel', ''),
                    'type': poi.get('type', ''),
                    'typecode': poi.get('typecode', ''),
                    'adname': poi.get('adname', ''),
                    'cityname': poi.get('cityname', ''),
                    'pname': poi.get('pname', ''),
                })

        return results

    def _parse_bmap_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析百度地图API响应"""
        results = []

        if data.get('status') == 0 and 'results' in data:
            for poi in data['results']:
                location = poi.get('location', {})
                results.append({
                    'name': poi.get('name', ''),
                    'address': poi.get('address', ''),
                    'location': f"{location.get('lng', '')},{location.get('lat', '')}",
                    'telephone': poi.get('telephone', ''),
                    'detail_info': poi.get('detail_info', {}),
                    'area': poi.get('area', ''),
                    'city': poi.get('city', ''),
                })

        return results

    def _parse_qmap_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析腾讯地图API响应"""
        results = []

        if data.get('status') == 0 and 'data' in data:
            for poi in data['data']:
                location = poi.get('location', {})
                results.append({
                    'name': poi.get('title', ''),
                    'address': poi.get('address', ''),
                    'location': f"{location.get('lng', '')},{location.get('lat', '')}",
                    'tel': poi.get('tel', ''),
                    'type': poi.get('type', ''),
                    'ad_info': poi.get('ad_info', {}),
                })

        return results

    def search_all_sources(
        self,
        city: str,
        keyword: str,
        poi_type: Optional[str] = None,
        sources: Optional[List[str]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        并行搜索所有图商

        Args:
            city: 城市名称
            keyword: 搜索关键词
            poi_type: POI类型（可选）
            sources: 要搜索的图商列表，默认为 ['amap', 'bmap', 'qmap']

        Returns:
            各图商的搜索结果字典
        """
        if sources is None:
            sources = ['amap', 'bmap', 'qmap']

        results = {}
        for source in sources:
            try:
                source_results = self.search_by_keyword(source, city, keyword, poi_type)
                results[source] = source_results
                logger.info(f"{source} 搜索完成，返回 {len(source_results)} 条结果")
            except Exception as e:
                logger.error(f"{source} 搜索失败: {e}")
                results[source] = []

        return results

    def close(self):
        """关闭HTTP会话"""
        if self.session:
            self.session.close()
            logger.info("HTTP会话已关闭")


def load_config(config_path: str) -> Dict[str, Any]:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        # 尝试作为YAML加载
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except ImportError:
            logger.error("配置文件解析失败：请安装 pyyaml 库")
            raise
        except Exception as e:
            logger.error(f"配置文件加载失败: {e}")
            raise


def main():
    """
    主函数 - 示例用法
    """
    # 示例配置
    config = {
        'global': {
            'request_timeout': 30,
            'retry_count': 3
        },
        'internal_proxy': {
            'enabled': True,
            'base_url': 'http://10.82.122.209:9081/botshop/proxy/mapapi',
            'timeout': 30,
            'retry_count': 3,
            'fallback_to_direct': True
        },
        'credentials': {
            'amap': [{'ak': 'your_amap_key'}],
            'bmap': [{'ak': 'your_bmap_key'}],
            'qmap': [{'key': 'your_qmap_key'}]
        },
        'map_vendors': {
            'amap': {'name': '高德地图', 'weight': 0.85},
            'bmap': {'name': '百度地图', 'weight': 0.85},
            'qmap': {'name': '腾讯地图', 'weight': 0.8}
        }
    }

    # 创建客户端
    client = MapAPIClient(config)

    # 示例1：关键词搜索
    print("===== 关键词搜索示例 =====")
    results = client.search_by_keyword('amap', '武汉', '肯德基')
    print(f"找到 {len(results)} 条结果")
    for i, result in enumerate(results[:3], 1):
        print(f"{i}. {result.get('name')} - {result.get('address')}")

    # 示例2：周边搜索
    print("\n===== 周边搜索示例 =====")
    results = client.search_around('amap', '孝感', '逸景华庭', (113.980117, 30.860777))
    print(f"找到 {len(results)} 条结果")
    for i, result in enumerate(results[:3], 1):
        print(f"{i}. {result.get('name')} - {result.get('address')}")

    # 示例3：多源搜索
    print("\n===== 多源搜索示例 =====")
    all_results = client.search_all_sources('北京', '北京大学')
    for source, results in all_results.items():
        print(f"{source}: {len(results)} 条结果")

    # 关闭客户端
    client.close()


if __name__ == "__main__":
    main()
