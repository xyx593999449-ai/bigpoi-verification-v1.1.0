import sys
import os
import time
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../evidence-collection/scripts')))
import call_map_vendor
from write_evidence_output import normalize_evidence_item

@pytest.mark.asyncio
async def test_async_io_concurrency():
    """测试多路图商 API 请求的异步并发能力"""
    start_time = time.time()
    
    # 模拟 3 个网络请求，假定服务器响应慢，每个强制睡眠拉长到 0.5 秒钟
    async def mock_fetch(*args, **kwargs):
        await asyncio.sleep(0.5)
        return {"status": "success", "source": args[1] if len(args)>1 else "mock"}
        
    with patch("call_map_vendor.fetch_vendor_response_async", side_effect=mock_fetch):
        # 抛出三个分支图商打点
        tasks = [
            call_map_vendor.fetch_vendor_response_async(None, "amap", "id1", "key1"),
            call_map_vendor.fetch_vendor_response_async(None, "bmap", "id1", "key2"),
            call_map_vendor.fetch_vendor_response_async(None, "qmap", "id1", "key3")
        ]
        results = await asyncio.gather(*tasks)
        
    duration = time.time() - start_time
    assert len(results) == 3
    # 如果是同步串行执行，这里起步将耗时 1.5 秒；如果在 asyncio 环境中，则总时间应该约为 0.5 秒
    assert duration < 0.6, f"异步并发控制失效，函数总耗时达 {duration} 秒无法满足高吞吐期待！"

def test_evidence_pruning_and_haversine():
    """测试 EvidencePruner 成功脱水 raw_data 且成功注入 computed_distance_meters 预计算里程"""
    mock_poi = {
        "coordinates": {"longitude": 116.40, "latitude": 39.90}
    }
    raw_evidence = {
        "evidence_id": "ev_001",
        "poi_id": "poi_1",
        "source": { "source_id": "s1", "source_name": "amap", "source_type": "map_vendor" },
        "collected_at": "2026-03-01T00:00:00Z",
        "data": {
            "name": "TEST",
            "coordinates": {"longitude": 116.40, "latitude": 39.90},
            "raw_data": {"huge_string": "A" * 10000}  # 此噪音节点应该被清出
        },
        "metadata": {"run_id": "run_1"}
    }
    errors = []
    
    normalized = normalize_evidence_item(raw_evidence, mock_poi, 0, errors)
    
    assert not errors
    assert "raw_data" not in normalized.get("data", {}), "数据脱水失败，JSON中仍然存在 raw_data 节点损耗 token 额度"
    assert "computed_distance_meters" in normalized.get("data", {}), "地理距离预计算注入节点已丢失"
    assert normalized["data"]["computed_distance_meters"] == 0, "同经纬度模拟距离计算校验未归零"
