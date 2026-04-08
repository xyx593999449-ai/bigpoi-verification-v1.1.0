import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

VALIDATOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../skills-bigpoi-verification/scripts"))
if VALIDATOR_DIR not in sys.path:
    sys.path.insert(0, VALIDATOR_DIR)

import validate_result_bundle


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_validate_result_bundle_rejects_accepted_coarse_address(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    task_id = "TASK_bundle_guard"
    task_dir = workspace_root / "output" / "results" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    decision_path = task_dir / "decision_20260408T000100Z.json"
    evidence_path = task_dir / "evidence_20260408T000100Z.json"
    record_path = task_dir / "record_20260408T000100Z.json"
    index_path = task_dir / "index_20260408T000100Z.json"

    evidence = [
        {
            "evidence_id": "EVD_001",
            "poi_id": "poi_bundle_guard",
            "source": {
                "source_id": "official_1",
                "source_name": "福田政府在线",
                "source_type": "official",
                "source_url": "https://www.szft.gov.cn/detail",
                "weight": 1.0,
            },
            "collected_at": "2026-04-08T00:00:30Z",
            "data": {
                "name": "福保街道办事处",
                "address": "深圳市福田区福民路123号1409室",
            },
            "verification": {"is_valid": True, "confidence": 0.93},
            "metadata": {"run_id": "run_bundle_guard", "signal_origin": "websearch"},
        }
    ]
    decision = {
        "decision_id": "DEC_20260408T000100Z_TEST0001",
        "poi_id": "poi_bundle_guard",
        "run_id": "run_bundle_guard",
        "overall": {
            "status": "accepted",
            "confidence": 0.93,
            "summary": "核实通过，核心维度均满足要求，综合置信度0.93。",
        },
        "dimensions": {
            "existence": {"result": "pass", "confidence": 0.93},
            "name": {"result": "pass", "confidence": 0.93},
            "address": {"result": "pass", "confidence": 0.93},
            "coordinates": {"result": "pass", "confidence": 0.93},
            "category": {"result": "pass", "confidence": 0.93},
            "location": {"result": "pass", "confidence": 0.93},
        },
        "created_at": "2026-04-08T00:01:00Z",
        "processed_at": "2026-04-08T00:01:00Z",
        "processing_duration_ms": 1000,
        "version": "1.6.8",
        "metadata": {
            "task_id": task_id,
            "seed_created_at": "2026-04-08T00:00:00Z",
        },
    }
    record = {
        "record_id": "REC_20260408T000100Z_TEST0001",
        "poi_id": "poi_bundle_guard",
        "run_id": "run_bundle_guard",
        "input_data": {
            "name": "福保街道办事处",
            "poi_type": "130105",
            "city": "深圳市",
        },
        "verification_result": {
            "status": "verified",
            "confidence": 0.93,
            "final_values": {
                "name": "福保街道办事处",
                "address": "广东省深圳市福田区福保街道",
                "coordinates": {
                    "longitude": 114.05,
                    "latitude": 22.52,
                    "coordinate_system": "GCJ02",
                },
                "category": "130105",
                "city": "深圳市",
            },
            "changes": [],
        },
        "audit_trail": {
            "created_by": "bigpoi-verification",
            "created_at": "2026-04-08T00:01:05Z",
        },
        "created_at": "2026-04-08T00:01:05Z",
        "updated_at": "2026-04-08T00:01:05Z",
        "expires_at": "2027-04-08T00:01:05Z",
    }
    index = {
        "poi_id": "poi_bundle_guard",
        "task_id": task_id,
        "run_id": "run_bundle_guard",
        "created_at": "2026-04-08T00:01:10Z",
        "task_dir": f"output/results/{task_id}",
        "description": "bundle validator guard",
        "files": {
            "decision": str(decision_path.resolve()),
            "evidence": str(evidence_path.resolve()),
            "record": str(record_path.resolve()),
        },
    }

    _write_json(evidence_path, evidence)
    _write_json(decision_path, decision)
    _write_json(record_path, record)
    _write_json(index_path, index)

    stdout = io.StringIO()
    with patch(
        "sys.argv",
        [
            "validate_result_bundle.py",
            "-TaskDir",
            str(task_dir),
            "-WorkspaceRoot",
            str(workspace_root),
        ],
    ), patch("sys.stdout", stdout):
        assert validate_result_bundle.main() == 0

    result = json.loads(stdout.getvalue())
    assert result["status"] == "failed"
    assert any("final_values.address" in reason for reason in result["reasons"])
