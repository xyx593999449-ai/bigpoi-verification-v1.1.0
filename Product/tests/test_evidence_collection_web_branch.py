import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

WEB_SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection-web/scripts"))
if WEB_SCRIPT_DIR not in sys.path:
    sys.path.insert(0, WEB_SCRIPT_DIR)

import write_web_branch_result


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_write_web_branch_result_marks_completed_empty_reader_as_empty(tmp_path: Path):
    process_dir = tmp_path / "process"
    output_path = process_dir / "web-branch-result.json"

    _write_json(
        process_dir / "websearch-reviewed.json",
        {
            "status": "empty",
            "reviewed_at": "2026-04-08T00:00:00Z",
            "items": [],
            "review_summary": {"kept_count": 0, "dropped_count": 0},
            "context": {
                "run_id": "run_web_empty",
                "poi_id": "poi_web_empty",
                "task_id": "TASK_web_empty",
                "created_at": "2026-04-08T00:00:00Z",
            },
        },
    )
    _write_json(
        process_dir / "webreader-plan.json",
        {
            "status": "ok",
            "read_target_count": 1,
            "read_targets": [
                {
                    "read_id": "READ_001",
                    "source_url": "https://www.example.gov.cn/detail",
                }
            ],
            "context": {
                "run_id": "run_web_empty",
                "poi_id": "poi_web_empty",
                "task_id": "TASK_web_empty",
                "created_at": "2026-04-08T00:00:00Z",
            },
        },
    )
    _write_json(
        process_dir / "webreader-raw.json",
        {
            "status": "ok",
            "items": [
                {
                    "read_id": "READ_001",
                    "status": "ok",
                    "source": {"source_url": "https://www.example.gov.cn/detail"},
                    "raw_page": {"content": "详情页内容"},
                }
            ],
            "failed_items": [],
            "context": {
                "run_id": "run_web_empty",
                "poi_id": "poi_web_empty",
                "task_id": "TASK_web_empty",
                "created_at": "2026-04-08T00:00:00Z",
            },
        },
    )
    _write_json(
        process_dir / "webreader-reviewed.json",
        {
            "status": "empty",
            "reviewed_at": "2026-04-08T00:01:00Z",
            "items": [],
            "review_summary": {"kept_count": 0, "dropped_count": 1},
            "context": {
                "run_id": "run_web_empty",
                "poi_id": "poi_web_empty",
                "task_id": "TASK_web_empty",
                "created_at": "2026-04-08T00:00:00Z",
            },
        },
    )

    with patch(
        "sys.argv",
        [
            "write_web_branch_result.py",
            "-ProcessDir",
            str(process_dir),
            "-OutputPath",
            str(output_path),
        ],
    ):
        assert write_web_branch_result.main() == 0

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["status"] == "empty"
    assert result["webreader_execution_state"] == "completed_empty"
    assert result["attention_required"] is False


def test_write_web_branch_result_keeps_ok_but_flags_missing_reader_execution(tmp_path: Path):
    process_dir = tmp_path / "process"
    output_path = process_dir / "web-branch-result.json"

    _write_json(
        process_dir / "websearch-reviewed.json",
        {
            "status": "ok",
            "reviewed_at": "2026-04-08T00:00:00Z",
            "items": [
                {
                    "source": {"source_url": "https://www.example.gov.cn/detail"},
                    "data": {"name": "福保街道办事处"},
                }
            ],
            "review_summary": {"kept_count": 1, "dropped_count": 0},
            "context": {
                "run_id": "run_web_attention",
                "poi_id": "poi_web_attention",
                "task_id": "TASK_web_attention",
                "created_at": "2026-04-08T00:00:00Z",
            },
        },
    )
    _write_json(
        process_dir / "webreader-plan.json",
        {
            "status": "ok",
            "read_target_count": 1,
            "read_targets": [
                {
                    "read_id": "READ_001",
                    "source_url": "https://www.example.gov.cn/detail",
                }
            ],
            "context": {
                "run_id": "run_web_attention",
                "poi_id": "poi_web_attention",
                "task_id": "TASK_web_attention",
                "created_at": "2026-04-08T00:00:00Z",
            },
        },
    )

    with patch(
        "sys.argv",
        [
            "write_web_branch_result.py",
            "-ProcessDir",
            str(process_dir),
            "-OutputPath",
            str(output_path),
        ],
    ):
        assert write_web_branch_result.main() == 0

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["webreader_execution_state"] == "missing_execution"
    assert result["attention_required"] is True
