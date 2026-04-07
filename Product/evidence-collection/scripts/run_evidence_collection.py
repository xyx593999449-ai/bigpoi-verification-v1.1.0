#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
MERGE_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection-merge" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(MERGE_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(MERGE_SCRIPT_DIR))

from evidence_collection_common import ensure_stdout_utf8


def log_progress(message: str) -> None:
    sys.stderr.write(f"[run-evidence-collection] {message}\n")
    sys.stderr.flush()


def run_json_command(command: List[str], *, label: str, retries: int = 0) -> Dict[str, Any]:
    last_error = ""
    for attempt in range(retries + 1):
        if attempt == 0:
            log_progress(f"执行 {label}")
        else:
            log_progress(f"重试 {label}，第 {attempt} 次")
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        stderr_text = (completed.stderr or "").strip()
        if stderr_text:
            sys.stderr.write(stderr_text + ("\n" if not stderr_text.endswith("\n") else ""))
            sys.stderr.flush()
        if completed.returncode == 0:
            stdout = completed.stdout.strip() or "{}"
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                raise ValueError(f"{label} returned non-JSON output: {stdout}")
        last_error = (completed.stderr or completed.stdout or "").strip()
    raise RuntimeError(f"{label} failed after retries. error={last_error}")


def read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid json object: {path}")
    return payload


def resolve_merge_paths_from_branches(web_branch: Dict[str, Any], map_branch: Dict[str, Any]) -> Dict[str, Any]:
    internal_proxy_path = str(map_branch.get("internal_proxy_merge_input_path") or "").strip()
    if not internal_proxy_path:
        raise ValueError("map-branch-result.internal_proxy_merge_input_path is required")

    vendor_paths_payload = map_branch.get("vendor_merge_input_paths")
    vendor_paths: List[str] = []
    if isinstance(vendor_paths_payload, dict):
        for value in vendor_paths_payload.values():
            path_text = str(value or "").strip()
            if path_text:
                vendor_paths.append(path_text)
    elif isinstance(vendor_paths_payload, list):
        for value in vendor_paths_payload:
            path_text = str(value or "").strip()
            if path_text:
                vendor_paths.append(path_text)

    websearch_path = str(web_branch.get("websearch_merge_input_path") or "").strip() or None
    webreader_path = str(web_branch.get("webreader_merge_input_path") or "").strip() or None

    return {
        "internal_proxy_path": internal_proxy_path,
        "vendor_paths": vendor_paths,
        "websearch_path": websearch_path,
        "webreader_path": webreader_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-InputPath", required=True)
    parser.add_argument("-RunId", required=True)
    parser.add_argument("-TaskId", required=True)
    parser.add_argument("-WorkspaceRoot", required=True)
    parser.add_argument("-OutputPath")
    parser.add_argument("-LogDirectory")
    parser.add_argument("-RetryCount", type=int, default=1)
    parser.add_argument("-TimeoutSeconds", type=int, default=1200)
    return parser.parse_args()


def main() -> int:
    ensure_stdout_utf8()
    args = parse_args()

    py = sys.executable
    workspace_root = Path(args.WorkspaceRoot).resolve()
    input_path = Path(args.InputPath).resolve()
    run_id = str(args.RunId)
    task_id = str(args.TaskId)
    retry_count = max(int(args.RetryCount), 0)

    process_dir = workspace_root / "output" / "runs" / run_id / "process"
    staging_dir = workspace_root / "output" / "runs" / run_id / "staging"
    process_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    output_path = Path(args.OutputPath).resolve() if args.OutputPath else process_dir / "evidence-merge-result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parallel_runner_output = process_dir / "parallel-agent-runner.json"
    log_directory = Path(args.LogDirectory).resolve() if args.LogDirectory else workspace_root / "output" / "results" / task_id / "claude-agent-logs"

    log_progress(f"启动并行 worker: run_id={run_id} task_id={task_id}")
    runner_cmd = [
        py,
        str(SCRIPT_DIR / "run_parallel_claude_agents.py"),
        "-InputPath",
        str(input_path),
        "-RunId",
        run_id,
        "-TaskId",
        task_id,
        "-WorkspaceRoot",
        str(workspace_root),
        "-OutputPath",
        str(parallel_runner_output),
        "-LogDirectory",
        str(log_directory),
        "-TimeoutSeconds",
        str(max(int(args.TimeoutSeconds), 1)),
    ]
    runner_result = run_json_command(runner_cmd, label="run_parallel_claude_agents", retries=retry_count)
    if str(runner_result.get("status") or "").strip() != "ok":
        raise RuntimeError(
            "parallel workers failed. check logs under output/results/{task_id}/claude-agent-logs/"
        )

    web_branch_path = process_dir / "web-branch-result.json"
    map_branch_path = process_dir / "map-branch-result.json"
    if not web_branch_path.exists():
        raise RuntimeError("web branch result is missing: output/runs/{run_id}/process/web-branch-result.json")
    if not map_branch_path.exists():
        raise RuntimeError("map branch result is missing: output/runs/{run_id}/process/map-branch-result.json")

    web_branch_result = read_json(web_branch_path)
    map_branch_result = read_json(map_branch_path)
    if str(web_branch_result.get("status") or "").strip() not in {"ok", "empty"}:
        raise RuntimeError("web branch status is not mergeable. expected ok/empty in web-branch-result.json")
    if str(map_branch_result.get("status") or "").strip() not in {"ok", "empty"}:
        raise RuntimeError("map branch status is not mergeable. expected ok/empty in map-branch-result.json")

    merge_inputs = resolve_merge_paths_from_branches(web_branch_result, map_branch_result)
    collector_merged_path = process_dir / "collector-merged.json"
    merge_cmd = [
        py,
        str(MERGE_SCRIPT_DIR / "merge_evidence_collection_outputs.py"),
        "-PoiPath",
        str(input_path),
        "-InternalProxyPath",
        str(merge_inputs["internal_proxy_path"]),
        "-OutputPath",
        str(collector_merged_path),
        "-RunId",
        run_id,
        "-TaskId",
        task_id,
    ]
    if merge_inputs["websearch_path"]:
        merge_cmd.extend(["-WebSearchPath", str(merge_inputs["websearch_path"])])
    if merge_inputs["webreader_path"]:
        merge_cmd.extend(["-WebReaderPath", str(merge_inputs["webreader_path"])])
    if merge_inputs["vendor_paths"]:
        merge_cmd.extend(["-VendorFallbackPaths", *merge_inputs["vendor_paths"]])
    merge_result = run_json_command(merge_cmd, label="merge_evidence_collection_outputs", retries=retry_count)

    write_cmd = [
        py,
        str(MERGE_SCRIPT_DIR / "write_evidence_output.py"),
        "-PoiPath",
        str(input_path),
        "-CollectorOutputPath",
        str(collector_merged_path),
        "-OutputDirectory",
        str(staging_dir),
        "-RunId",
        run_id,
        "-TaskId",
        task_id,
    ]
    write_result = run_json_command(write_cmd, label="write_evidence_output", retries=retry_count)

    result = {
        "status": "ok",
        "run_id": run_id,
        "task_id": task_id,
        "poi_id": str(write_result.get("poi_id") or ""),
        "parallel_runner_result_path": str(parallel_runner_output),
        "web_branch_result_path": str(web_branch_path),
        "map_branch_result_path": str(map_branch_path),
        "collector_merged_path": str(collector_merged_path),
        "evidence_path": str(write_result.get("evidence_path") or ""),
        "evidence_count": int(write_result.get("evidence_count") or 0),
        "summary_text": (
            f"evidence-collection 完成：run_id={run_id}，"
            f"merge={merge_result.get('evidence_count', 0)} 条，"
            f"formal={write_result.get('evidence_count', 0)} 条。"
        ),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
