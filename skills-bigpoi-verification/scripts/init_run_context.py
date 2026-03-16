#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bundle_common import ensure_stdout_utf8, normalize_input, read_json_file
from runtime_paths import detect_workspace_root
from run_context import build_run_directories, build_run_id


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-InputPath", required=True)
    parser.add_argument("-WorkspaceRoot")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    input_data = normalize_input(read_json_file(args.InputPath))
    if not isinstance(input_data, dict):
        raise ValueError("input must be a JSON object")
    poi_id = str(input_data.get("id") or "")
    if not poi_id:
        raise ValueError("input.id is required")
    task_id = str(input_data.get("task_id") or f"TASK_{poi_id}")

    workspace_detection = detect_workspace_root(
        workspace_hint=args.WorkspaceRoot,
        related_paths=(args.InputPath,),
        cwd=Path.cwd(),
    )
    workspace_root = workspace_detection.workspace_root.resolve()
    run_id = str(args.RunId or build_run_id(task_id, poi_id))
    run_dirs = build_run_directories(workspace_root, run_id)
    for path in run_dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    result = {
        "status": "ok",
        "task_id": task_id,
        "poi_id": poi_id,
        "run_id": run_id,
        "workspace_root": str(workspace_root),
        "workspace_detection": {
            "strategy": workspace_detection.strategy,
            "matched_marker": workspace_detection.matched_marker,
            "start_path": str(workspace_detection.start_path),
        },
        "paths": {key: str(value) for key, value in run_dirs.items()},
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
