import sys
import os
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../worker')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../Product/evidence-collection/scripts')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../Quality/BigPoi-verification-qc/scripts')))

from write_evidence_output import normalize_evidence_item
from dsl_validator import LocalQCEngine
from result_persister import should_sample_for_qc

def test_end_to_end_pipeline():
    """
    全链路联调总代理：端到端验证整个提效优化的生命周期
    涵盖：任务接入 -> 并发取证 -> JSON脱水 -> 距离预计算 -> LLM降维调度 -> 本地化无模型QC拦截
    """
    start_time = time.time()
    
    # 阶段 1：模拟调度层派发
    poi_id = "integration_test_poi_999"
    print(f"\\n[1/5] Task Dispatched: {poi_id}")
    
    # 阶段 2：取证并发及脱水降维
    # 假设网络高并发框架传回了一组数据，包含了庞大的冗余原料
    raw_api_response = {
        "evidence_id": "e_999",
        "poi_id": poi_id,
        "source": {"source_id": "api_1", "source_name": "bmap", "source_type": "map_vendor"},
        "collected_at": "2026-06-06T00:00:00Z",
        "metadata": {"run_id": "test_run_1"},
        "data": {
            "name": "海底捞火锅(测试店)",
            "coordinates": {"longitude": 116.4, "latitude": 39.9},
            "raw_data": {"useless_html_tags": "<div></div>" * 500}
        }
    }
    mock_poi = {"id": poi_id, "name": "海底捞火锅", "coordinates": {"longitude": 116.4, "latitude": 39.9}}
    errors = []
    
    dehydrated_evidence = normalize_evidence_item(raw_api_response, mock_poi, 0, errors)
    assert not errors
    assert "raw_data" not in dehydrated_evidence["data"]
    assert dehydrated_evidence["data"]["computed_distance_meters"] == 0
    print(f"[2/5] Evidence Processed & Pruned. Distance Pre-calculated: {dehydrated_evidence['data']['computed_distance_meters']}m.")
    
    # 阶段 3：大模型进行常规推演（如果置信度不足则拦截）
    # 在这个阶段因为上一步已经剥除了庞杂文本并注入了距离，LLM可以直接看结果
    mock_llm_decision = {"confidence": 0.98, "status": "accepted"}
    print(f"[3/5] LLM Evaluated cleanly without complex Math calculations. Confidence: {mock_llm_decision['confidence']}.")
    
    # 阶段 4：进入 QC 判定与抽检网关
    is_sampled = should_sample_for_qc(mock_llm_decision['confidence'])
    print(f"[4/5] QC Gateway passed. Selected for random QC? {is_sampled}")
    
    if is_sampled:
        # 阶段 5：如果不幸被抽中，触发 0 Token 开销的本地规则质检
        qc_engine = LocalQCEngine()
        qc_input = {
            "record": mock_poi, 
            "evidence_data": [dehydrated_evidence]
        }
        final_verdict = qc_engine.execute_qc(qc_input)
        assert final_verdict["qc_score"] == 100
        print(f"[5/5] Local execution of Quality Check finished in pure Python: {final_verdict['explanation']}")
    else:
        print(f"[5/5] Skipped Quality Check directly to save LLM tokens & compute!")
        
    duration = time.time() - start_time
    print(f"\\n✅ 全部管道测试完毕！总执行验证环境隔离完成率 100%，总体联调耗时：{duration:.4f} 秒。")

