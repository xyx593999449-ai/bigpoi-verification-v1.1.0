#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bundle_common import (
    build_record,
    ensure_stdout_utf8,
    normalize_input,
    prune_empty,
    read_json_file,
    validate_basic_decision,
    validate_basic_evidence,
    validate_basic_input,
    write_json_file,
)
from run_context import collect_item_run_ids
from runtime_paths import build_task_dir, detect_workspace_root


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-InputPath", required=True)
    parser.add_argument("-EvidencePath", required=True)
    parser.add_argument("-DecisionPath", required=True)
    parser.add_argument("-WorkspaceRoot")
    args = parser.parse_args()

    workspace_detection = detect_workspace_root(
        workspace_hint=args.WorkspaceRoot,
        related_paths=(args.InputPath, args.EvidencePath, args.DecisionPath),
        cwd=Path.cwd(),
    )
    workspace_root = workspace_detection.workspace_root
    input_data = normalize_input(read_json_file(args.InputPath))
    evidence = read_json_file(args.EvidencePath)
    decision = read_json_file(args.DecisionPath)

    if not isinstance(input_data, dict):
        raise ValueError("input must be a JSON object")
    if not isinstance(decision, dict):
        raise ValueError("decision must be a JSON object")

    validate_basic_input(input_data)
    validate_basic_evidence(evidence, str(input_data["id"]))
    validate_basic_decision(decision, str(input_data["id"]))

    decision_run_id = str(decision.get("run_id") or "").strip()
    evidence_run_ids = collect_item_run_ids(evidence)
    if not decision_run_id:
        raise ValueError("decision.run_id is required")
    if not evidence_run_ids:
        raise ValueError("evidence.metadata.run_id is required for all items")
    if evidence_run_ids != {decision_run_id}:
        raise ValueError("evidence and decision must belong to the same run")

    task_id = str(input_data.get("task_id") or f"TASK_{input_data['id']}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_dir = build_task_dir(workspace_root, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)

    decision_out = task_dir / f"decision_{timestamp}.json"
    evidence_out = task_dir / f"evidence_{timestamp}.json"
    record_out = task_dir / f"record_{timestamp}.json"
    index_out = task_dir / f"index_{timestamp}.json"

    compact_decision = prune_empty(decision)
    compact_evidence = prune_empty(evidence)
    write_json_file(compact_decision, decision_out)
    write_json_file(compact_evidence, evidence_out)

    record = prune_empty(build_record(input_data, compact_evidence, compact_decision, timestamp))
    write_json_file(record, record_out)

    index = prune_empty(
        {
            "poi_id": str(input_data["id"]),
            "task_id": task_id,
            "run_id": decision_run_id,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_dir": f"output/results/{task_id}",
            "files": {
                "decision": str(decision_out.resolve()),
                "evidence": str(evidence_out.resolve()),
                "record": str(record_out.resolve()),
            },
            "description": "Big POI verification result bundle",
        }
    )
    write_json_file(index, index_out)

    validator = SCRIPT_DIR / "validate_result_bundle.py"
    if not validator.is_file():
        raise FileNotFoundError("validate_result_bundle.py is missing")

    completed = subprocess.run(
        [
            sys.executable,
            str(validator),
            "-TaskDir",
            str(task_dir),
            "-WorkspaceRoot",
            str(workspace_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"bundle validator execution failed: {completed.stderr.strip() or completed.stdout.strip()}")
    validation = json.loads(completed.stdout)
    if validation.get("status") != "passed":
        reason_text = "; ".join(validation.get("reasons", []))
        raise ValueError(f"bundle validation failed at stage {validation.get('failed_stage')}: {reason_text}")

    result = {
        "status": "ok",
        "task_id": task_id,
        "run_id": decision_run_id,
        "workspace_root": str(workspace_root),
        "workspace_detection": {
            "strategy": workspace_detection.strategy,
            "matched_marker": workspace_detection.matched_marker,
            "start_path": str(workspace_detection.start_path),
        },
        "task_dir": str(task_dir.resolve()),
        "files": {
            "decision": str(decision_out.resolve()),
            "evidence": str(evidence_out.resolve()),
            "record": str(record_out.resolve()),
            "index": str(index_out.resolve()),
        },
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
