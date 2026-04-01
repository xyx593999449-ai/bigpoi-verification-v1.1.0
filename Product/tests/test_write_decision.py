import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../verification/scripts")))
import write_decision_output


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
