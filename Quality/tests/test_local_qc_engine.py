import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../BigPoi-verification-qc/scripts')))
from result_persister import should_sample_for_qc
from dsl_validator import LocalQCEngine

def test_dynamic_sampling_rate():
    """验证动态抽检拦截逻辑"""
    import random
    random.seed(42)  # 固定种子使得期望概率稳定
    
    # >= 0.95 应该只有 5% 概率为 True
    results_95 = [should_sample_for_qc(0.96) for _ in range(1000)]
    assert 20 < sum(results_95) < 80  # 大致约等于 50 次
    
    # >= 0.85 应该有 20% 概率为 True
    results_85 = [should_sample_for_qc(0.88) for _ in range(1000)]
    assert 150 < sum(results_85) < 250
    
    # < 0.85 应该是 100% 全量质检
    results_low = [should_sample_for_qc(0.75) for _ in range(100)]
    assert all(results_low)


def test_local_qc_engine_execution():
    """验证本地纯代码质检执行代理（剥离LLM）的算力接管与判断准确性"""
    engine = LocalQCEngine()
    
    # 测试数据：坐标差异极大，名字完全不同
    qc_input_fail = {
        "record": {
            "task_id": "test_fail",
            "name": "北京烤鸭西直门店",
            "location": {"longitude": 116.3, "latitude": 39.9}
        },
        "evidence_data": [
            {
                "data": {
                    "name": "南京大排档",  # difflib < 0.8
                    "location": {"longitude": 120.0, "latitude": 30.0} # haversine > 50m
                }
            }
        ]
    }
    
    res_fail = engine.execute_qc(qc_input_fail)
    assert res_fail["qc_status"] == "risky"
    assert res_fail["has_risk"] is True
    assert res_fail["dimension_results"]["location"]["status"] == "risk"
    assert res_fail["dimension_results"]["name"]["status"] == "risk"
    
    # 测试数据：坐标一致，名字高度相似
    qc_input_pass = {
        "record": {
            "task_id": "test_pass",
            "name": "北京烤鸭西直门店",
            "location": {"longitude": 116.353, "latitude": 39.940}
        },
        "evidence_data": [
            {
                "data": {
                    "name": "北京烤鸭(西直门分店)", # difflib > 0.8
                    "location": {"longitude": 116.353, "latitude": 39.940} # distance = 0m
                }
            }
        ]
    }
    
    res_pass = engine.execute_qc(qc_input_pass)
    assert res_pass["qc_status"] == "qualified"
    assert res_pass["has_risk"] is False
    assert res_pass["dimension_results"]["location"]["status"] == "pass"
    assert res_pass["dimension_results"]["name"]["status"] == "pass"

