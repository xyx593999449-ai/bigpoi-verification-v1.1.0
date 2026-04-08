import json
import os
import sys
from pathlib import Path

import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection/scripts")))

import run_evidence_collection
import merge_evidence_collection_outputs


def test_run_json_command_retries_and_succeeds():
    cmd = [sys.executable, "-c", "import json; print(json.dumps({'status':'ok'}))"]
    result = run_evidence_collection.run_json_command(cmd, label="smoke", retries=1)
    assert result["status"] == "ok"


def test_resolve_merge_paths_from_branches_supports_vendor_map():
    web_branch = {
        "websearch_merge_input_path": "/tmp/websearch-reviewed.json",
        "webreader_merge_input_path": "/tmp/webreader-reviewed.json",
    }
    map_branch = {
        "internal_proxy_merge_input_path": "/tmp/map-reviewed-internal.json",
        "vendor_merge_input_paths": {
            "amap": "/tmp/map-reviewed-fallback-amap.json",
            "qmap": "/tmp/map-reviewed-fallback-qmap.json",
        },
    }
    result = run_evidence_collection.resolve_merge_paths_from_branches(web_branch, map_branch)
    assert result["internal_proxy_path"] == "/tmp/map-reviewed-internal.json"
    assert result["vendor_paths"] == [
        "/tmp/map-reviewed-fallback-amap.json",
        "/tmp/map-reviewed-fallback-qmap.json",
    ]
    assert result["websearch_path"] == "/tmp/websearch-reviewed.json"
    assert result["webreader_path"] == "/tmp/webreader-reviewed.json"


def test_resolve_merge_paths_requires_internal_proxy():
    with pytest.raises(ValueError, match="internal_proxy_merge_input_path is required"):
        run_evidence_collection.resolve_merge_paths_from_branches({}, {})


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


def test_merge_deduplicates_same_websearch_page(tmp_path: Path):
    poi = {"id": "poi_2", "name": "福保街道办事处", "poi_type": "130105", "city": "深圳市"}
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
            "run_id": "run_dedupe",
            "poi_id": "poi_2",
            "task_id": "task_dedupe",
            "created_at": "2026-04-02T00:00:00Z",
        },
    }
    websearch_reviewed = {
        "status": "ok",
        "reviewed_at": "2026-04-02T00:01:00Z",
        "items": [
            {
                "source": {
                    "source_id": "WEB_001",
                    "source_name": "福田政府在线",
                    "source_type": "official",
                    "source_url": "https://www.szft.gov.cn/a/detail.html",
                    "weight": 1.0,
                },
                "data": {
                    "name": "福保街道办事处",
                    "phone": "0755-83839006",
                },
                "verification": {"is_valid": True, "confidence": 0.88},
                "metadata": {
                    "signal_origin": "websearch",
                    "source_domain": "www.szft.gov.cn",
                    "page_title": "福保街道办联系方式",
                    "canonical_url": "https://www.szft.gov.cn/a/detail.html",
                },
            },
            {
                "source": {
                    "source_id": "WEB_002",
                    "source_name": "福田政府在线",
                    "source_type": "official",
                    "source_url": "https://www.szft.gov.cn/b/detail.html",
                    "weight": 1.0,
                },
                "data": {
                    "name": "福保街道办事处",
                    "phone": "0755-83839006",
                },
                "verification": {"is_valid": True, "confidence": 0.9},
                "metadata": {
                    "signal_origin": "websearch",
                    "source_domain": "www.szft.gov.cn",
                    "page_title": "福保街道办联系方式",
                },
            },
        ],
        "review_summary": {"kept_count": 2, "dropped_count": 0},
        "context": {
            "run_id": "run_dedupe",
            "poi_id": "poi_2",
            "task_id": "task_dedupe",
            "created_at": "2026-04-02T00:00:00Z",
        },
    }

    poi_path = tmp_path / "poi.json"
    internal_path = tmp_path / "map-reviewed.json"
    websearch_path = tmp_path / "websearch-reviewed.json"
    output_path = tmp_path / "collector-merged.json"
    poi_path.write_text(json.dumps(poi, ensure_ascii=False), encoding="utf-8")
    internal_path.write_text(json.dumps(internal_reviewed, ensure_ascii=False), encoding="utf-8")
    websearch_path.write_text(json.dumps(websearch_reviewed, ensure_ascii=False), encoding="utf-8")

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
            "run_dedupe",
            "-TaskId",
            "task_dedupe",
        ],
    ):
        assert merge_evidence_collection_outputs.main() == 0

    merged = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(merged["evidence_list"]) == 1
    assert merged["summary"]["dedupe_summary"]["duplicate_count"] == 1
