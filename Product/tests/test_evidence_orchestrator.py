import json
import os
import sys
from pathlib import Path

import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection/scripts")))

import merge_evidence_collection_outputs
from orchestrate_collection import collect_missing_vendors, run_json_command, should_fail_websearch_branch


def test_collect_missing_vendors_from_internal_proxy_payload(tmp_path: Path):
    payload = {
        "vendors": {
            "amap": {"items": [{"name": "A"}]},
            "bmap": {"items": []},
            "qmap": {"items": []},
        }
    }
    path = tmp_path / "internal.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    missing = collect_missing_vendors(path)
    assert missing == ["bmap", "qmap"]


def test_run_json_command_retries_and_succeeds():
    cmd = [sys.executable, "-c", "import json; print(json.dumps({'status':'ok'}))"]
    result = run_json_command(cmd, label="smoke", retries=1)
    assert result["status"] == "ok"


def test_should_not_fail_when_websearch_is_empty():
    assert should_fail_websearch_branch(1, {"status": "empty"}) is False
    assert should_fail_websearch_branch(1, {"status": "partial"}) is False
    assert should_fail_websearch_branch(1, {"status": "ok"}) is False


def test_should_fail_when_websearch_is_error():
    assert should_fail_websearch_branch(1, {"status": "error"}) is True


def test_merge_rejects_raw_websearch_payload(tmp_path: Path):
    poi = {"id": "poi_1", "name": "西丽街道办事处", "poi_type": "130105", "city": "深圳市"}
    internal_reviewed = {
        "status": "empty",
        "reviewed_at": "2026-04-02T00:00:00Z",
        "vendors": {
            "amap": {"vendor": "amap", "items": [], "review_summary": {"kept_count": 0, "dropped_count": 0}},
            "bmap": {"vendor": "bmap", "items": [], "review_summary": {"kept_count": 0, "dropped_count": 0}},
            "qmap": {"vendor": "qmap", "items": [], "review_summary": {"kept_count": 0, "dropped_count": 0}},
        },
        "review_summary": {},
        "context": {
            "run_id": "run_mock",
            "poi_id": "poi_1",
            "task_id": "task_mock",
            "created_at": "2026-04-02T00:00:00Z",
        },
    }
    websearch_raw = {
        "status": "ok",
        "items": [
            {
                "source": {
                    "source_id": "WEBSEARCH_1",
                    "source_name": "某政府网",
                    "source_type": "official",
                    "source_url": "https://www.example.gov.cn",
                    "weight": 1.0,
                },
                "data": {"name": "西丽街道办事处"},
                "metadata": {"signal_origin": "websearch"},
            }
        ],
        "context": {
            "run_id": "run_mock",
            "poi_id": "poi_1",
            "task_id": "task_mock",
            "created_at": "2026-04-02T00:00:00Z",
        },
    }

    poi_path = tmp_path / "poi.json"
    internal_path = tmp_path / "map-reviewed.json"
    websearch_path = tmp_path / "websearch-raw.json"
    output_path = tmp_path / "collector-merged.json"
    poi_path.write_text(json.dumps(poi, ensure_ascii=False), encoding="utf-8")
    internal_path.write_text(json.dumps(internal_reviewed, ensure_ascii=False), encoding="utf-8")
    websearch_path.write_text(json.dumps(websearch_raw, ensure_ascii=False), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "merge_evidence_collection_outputs.py",
            "-PoiPath",
            str(poi_path),
            "-InternalProxyPath",
            str(internal_path),
            "-WebSearchPath",
            str(websearch_path),
            "-OutputPath",
            str(output_path),
            "-RunId",
            "run_mock",
            "-TaskId",
            "task_mock",
        ],
    ):
        with pytest.raises(ValueError, match="websearch-reviewed payload"):
            merge_evidence_collection_outputs.main()
