import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection/scripts")))

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
