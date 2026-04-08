import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../verification/scripts")))
import write_decision_output
import authority_category_inference


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_single_decision(output_dir: Path) -> dict:
    files = list(output_dir.glob("decision_*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_low_confidence_still_outputs_decision(tmp_path: Path):
    poi = {
        "id": "poi_001",
        "name": "示例点位",
        "poi_type": "090101",
        "city": "北京市",
    }
    evidence = [
        {
            "evidence_id": "EVD_1",
            "poi_id": "poi_001",
            "source": {"source_id": "official_1", "source_name": "官网", "source_type": "official"},
            "collected_at": "2026-04-01T00:00:00Z",
            "data": {"name": "示例点位"},
            "metadata": {"run_id": "run_1"},
        }
    ]
    seed = {
        "context": {"run_id": "run_1", "poi_id": "poi_001", "created_at": "2026-04-01T00:00:00Z"},
        "overall": {"confidence": 0.45},
        "dimensions": {
            "existence": {"result": "pass", "confidence": 0.45},
            "name": {"result": "pass", "confidence": 0.45},
            "address": {"result": "pass", "confidence": 0.45},
            "coordinates": {"result": "pass", "confidence": 0.45},
            "category": {"result": "pass", "confidence": 0.45},
        },
    }

    poi_path = tmp_path / "poi.json"
    evidence_path = tmp_path / "evidence.json"
    seed_path = tmp_path / "seed.json"
    out_dir = tmp_path / "out"
    _write_json(poi_path, poi)
    _write_json(evidence_path, evidence)
    _write_json(seed_path, seed)

    argv = [
        "write_decision_output.py",
        "-PoiPath",
        str(poi_path),
        "-EvidencePath",
        str(evidence_path),
        "-DecisionSeedPath",
        str(seed_path),
        "-OutputDirectory",
        str(out_dir),
        "-RunId",
        "run_1",
    ]
    with patch("sys.argv", argv):
        assert write_decision_output.main() == 0

    decision = _read_single_decision(out_dir)
    assert decision["overall"]["status"] == "manual_review"
    assert decision["overall"]["confidence"] == 0.45


def test_authority_inference_generates_category_correction(tmp_path: Path):
    poi = {
        "id": "poi_002",
        "name": "某某市公安局",
        "poi_type": "130103",
        "city": "某某市",
    }
    evidence = [
        {
            "evidence_id": "EVD_2",
            "poi_id": "poi_002",
            "source": {
                "source_id": "official_police",
                "source_name": "某某市公安局官网",
                "source_type": "official",
                "source_url": "https://gaj.example.gov.cn/",
            },
            "collected_at": "2026-04-01T00:00:00Z",
            "data": {"name": "某某市公安局"},
            "metadata": {
                "run_id": "run_2",
                "signal_origin": "websearch",
                "source_domain": "gaj.example.gov.cn",
                "page_title": "某某市公安局",
                "text_snippet": "某某市公安局负责辖区治安管理",
                "authority_signals": ["公安局"],
            },
        }
    ]
    seed = {
        "context": {"run_id": "run_2", "poi_id": "poi_002", "created_at": "2026-04-01T00:00:00Z"},
        "dimensions": {
            "existence": {"result": "pass", "confidence": 0.9},
            "name": {"result": "pass", "confidence": 0.9},
            "address": {"result": "pass", "confidence": 0.9},
            "coordinates": {"result": "pass", "confidence": 0.9},
            "category": {"result": "pass", "confidence": 0.9},
        },
    }

    poi_path = tmp_path / "poi.json"
    evidence_path = tmp_path / "evidence.json"
    seed_path = tmp_path / "seed.json"
    out_dir = tmp_path / "out"
    _write_json(poi_path, poi)
    _write_json(evidence_path, evidence)
    _write_json(seed_path, seed)

    argv = [
        "write_decision_output.py",
        "-PoiPath",
        str(poi_path),
        "-EvidencePath",
        str(evidence_path),
        "-DecisionSeedPath",
        str(seed_path),
        "-OutputDirectory",
        str(out_dir),
        "-RunId",
        "run_2",
    ]
    with patch("sys.argv", argv):
        assert write_decision_output.main() == 0

    decision = _read_single_decision(out_dir)
    assert decision["dimensions"]["category"]["result"] == "fail"
    assert decision["corrections"]["category"]["suggested"] == "130501"


def test_authority_metadata_missing_fields_are_explicitly_downgraded():
    rich_item = {
        "source": {"source_type": "official", "source_url": "https://gaj.example.gov.cn/"},
        "metadata": {
            "signal_origin": "websearch",
            "source_domain": "gaj.example.gov.cn",
            "page_title": "某某市公安局",
            "text_snippet": "某某市公安局负责辖区治安管理",
        },
    }
    weak_item = {
        "source": {"source_type": "official", "source_url": "https://gaj.example.gov.cn/"},
        "metadata": {
            "signal_origin": "",
            "source_domain": "",
            "page_title": "",
            "text_snippet": "",
        },
    }

    rich_weight = authority_category_inference._item_weight(rich_item)
    weak_weight = authority_category_inference._item_weight(weak_item)
    assert rich_weight > weak_weight


def test_authority_gray_zone_supports_model_adjudication():
    poi = {"poi_type": "130103", "name": "某某机关", "city": "某市"}
    # 同时命中检察院/法院关键词，规则层应进入灰区候选
    evidence = [
        {
            "evidence_id": "E1",
            "source": {"source_type": "internet", "source_url": "https://news.example.com/a"},
            "data": {"name": "某区人民检察院与人民法院联合发布公告"},
            "metadata": {
                "signal_origin": "websearch",
                "source_domain": "news.example.com",
                "page_title": "联合公告",
                "text_snippet": "人民检察院与人民法院",
            },
        }
    ]
    without_model = authority_category_inference.infer_authority_category(poi, evidence)
    assert without_model["result"] == "uncertain"
    candidates = without_model["details"]["candidate_codes"]
    assert "130502" in candidates or "130503" in candidates

    with_model = authority_category_inference.infer_authority_category(
        poi,
        evidence,
        model_judgment={
            "selected_code": "130502",
            "confidence": 0.82,
            "reason": "检察院信号更集中",
            "evidence_refs": ["E1"],
        },
    )
    assert with_model["result"] == "fail"
    assert with_model["selected_code"] == "130502"
    assert with_model["details"]["adjudication_source"] == "model_judgment"


def test_write_decision_downgrades_when_address_has_more_specific_conflicting_evidence(tmp_path: Path):
    poi = {
        "id": "poi_003",
        "name": "福保街道办事处",
        "poi_type": "130105",
        "city": "深圳市",
        "address": "广东省深圳市福田区福保街道",
    }
    evidence = [
        {
            "evidence_id": "EVD_OFFICIAL_1",
            "poi_id": "poi_003",
            "source": {
                "source_id": "official_1",
                "source_name": "福田政府在线",
                "source_type": "official",
                "source_url": "https://www.szft.gov.cn/detail",
                "weight": 1.0,
            },
            "collected_at": "2026-04-01T00:00:00Z",
            "data": {
                "name": "福保街道办事处",
                "address": "深圳市福田区福民路123号1409室",
            },
            "verification": {"is_valid": True, "confidence": 0.92},
            "metadata": {"run_id": "run_3", "signal_origin": "websearch"},
        }
    ]
    seed = {
        "context": {"run_id": "run_3", "poi_id": "poi_003", "created_at": "2026-04-01T00:00:00Z"},
        "dimensions": {
            "existence": {"result": "pass", "confidence": 0.92},
            "name": {"result": "pass", "confidence": 0.92},
            "address": {"result": "pass", "confidence": 0.92},
            "coordinates": {"result": "pass", "confidence": 0.92},
            "category": {"result": "pass", "confidence": 0.92},
        },
    }

    poi_path = tmp_path / "poi.json"
    evidence_path = tmp_path / "evidence.json"
    seed_path = tmp_path / "seed.json"
    out_dir = tmp_path / "out"
    _write_json(poi_path, poi)
    _write_json(evidence_path, evidence)
    _write_json(seed_path, seed)

    argv = [
        "write_decision_output.py",
        "-PoiPath",
        str(poi_path),
        "-EvidencePath",
        str(evidence_path),
        "-DecisionSeedPath",
        str(seed_path),
        "-OutputDirectory",
        str(out_dir),
        "-RunId",
        "run_3",
    ]
    with patch("sys.argv", argv):
        assert write_decision_output.main() == 0

    decision = _read_single_decision(out_dir)
    assert decision["overall"]["status"] == "downgraded"
    assert decision["dimensions"]["address"]["result"] == "uncertain"
    assert decision["processing_duration_ms"] > 0
