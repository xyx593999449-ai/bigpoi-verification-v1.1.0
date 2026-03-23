import sys
import os
import json
import pytest
from unittest.mock import patch, mock_open

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../verification/scripts')))
import write_decision_output

def test_model_route_fallback():
    """验证决策层的置信度熔断机制：当置信度低于 0.85 时必须抛出拦截异常要求重路由"""
    # 构造低置信度种子
    mock_seed = {
        "context": {"poi_id": "test_01", "run_id": "r1"},
        "overall": {"status": "accepted", "confidence": 0.50},
        "dimensions": {
            "existence": {"result": "pass", "confidence": 0.5},
            "name": {"result": "pass", "confidence": 0.5},
            "address": {"result": "pass", "confidence": 0.5},
            "coordinates": {"result": "pass", "confidence": 0.5},
            "category": {"result": "pass", "confidence": 0.5}
        }
    }
    mock_poi = {"id": "test_01", "name": "Fake Name", "poi_type": "123456", "city": "Beijing"}
    mock_evidence = [{"evidence_id": "e1", "metadata": {"run_id": "r1"}, "poi_id": "test_01", "source": {"source_id": "1", "source_name": "a", "source_type": "official"}, "data": {"name": "a"}, "collected_at": "2026-01-01T00:00:00Z"}]

    def mock_read_json(path):
        if "poi" in path.lower(): return mock_poi
        if "evidence" in path.lower(): return mock_evidence
        if "seed" in path.lower(): return mock_seed
        return {}

    test_args = ["script.py", "-PoiPath", "poi.json", "-EvidencePath", "evi.json", "-DecisionSeedPath", "seed.json", "-OutputDirectory", ".", "-RunId", "r1"]
    
    with patch("sys.argv", test_args):
        with patch("write_decision_output.read_json_file", side_effect=mock_read_json):
            # 必须捕获到 Fallback 抛出
            with pytest.raises(ValueError) as exc:
                write_decision_output.main()
            assert "[ModelRouteFallback]" in str(exc.value)
            assert "< 0.85" in str(exc.value)
