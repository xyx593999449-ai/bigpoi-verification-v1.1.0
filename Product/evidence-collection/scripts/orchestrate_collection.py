#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evidence_collection_common import ensure_stdout_utf8, normalize_input_poi, read_json_file


def load_json(path: str | Path) -> Any:
    return read_json_file(path)


def run_json_command(command: list[str], *, label: str, retries: int = 0) -> dict[str, Any]:
    last_error = ""
    for attempt in range(retries + 1):
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode == 0:
            stdout = completed.stdout.strip() or "{}"
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                raise ValueError(f"{label} returned non-JSON output: {stdout}")
        last_error = (completed.stderr or completed.stdout or "").strip()
    raise RuntimeError(f"{label} failed after retries. error={last_error}")


def collect_missing_vendors(internal_proxy_path: str | Path) -> list[str]:
    payload = load_json(internal_proxy_path)
    if not isinstance(payload, dict):
        return []
    vendors = payload.get("vendors") if isinstance(payload.get("vendors"), dict) else {}
    if vendors:
        result: list[str] = []
        for vendor in ("amap", "bmap", "qmap"):
            vendor_payload = vendors.get(vendor)
            items = vendor_payload.get("items") if isinstance(vendor_payload, dict) and isinstance(vendor_payload.get("items"), list) else []
            if not items:
                result.append(vendor)
        return result
    missing = payload.get("missing_vendors")
    if isinstance(missing, list):
        return [str(v) for v in missing if str(v).strip()]
    return []


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-OutputRoot", required=True)
    parser.add_argument("-RunId", required=True)
    parser.add_argument("-TaskId")
    parser.add_argument("-WebFetchPath")
    parser.add_argument("-CommonConfigPath")
    parser.add_argument("-RetryCount", type=int, default=1)
    args = parser.parse_args()

    poi = normalize_input_poi(load_json(args.PoiPath))
    for field in ("id", "name", "city"):
        if not str(poi.get(field) or "").strip():
            raise ValueError(f"input.{field} is required")

    output_root = Path(args.OutputRoot).resolve()
    process_dir = output_root / "runs" / str(args.RunId) / "process"
    staging_dir = output_root / "runs" / str(args.RunId) / "staging"
    process_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    web_plan_path = process_dir / "web-plan.json"
    internal_proxy_path = process_dir / "map-raw-internal-proxy.json"
    websearch_path = process_dir / "websearch-raw.json"
    collector_merged_path = process_dir / "collector-merged.json"

    py = sys.executable
    retry_count = max(int(args.RetryCount), 0)

    plan_cmd = [py, str(SCRIPT_DIR / "build_web_source_plan.py"), "-PoiPath", str(args.PoiPath), "-OutputPath", str(web_plan_path)]
    run_json_command(plan_cmd, label="build_web_source_plan", retries=retry_count)

    internal_cmd = [
        py,
        str(SCRIPT_DIR / "call_internal_proxy.py"),
        "-PoiName",
        str(poi["name"]),
        "-City",
        str(poi["city"]),
        "-PoiId",
        str(poi["id"]),
        "-RunId",
        str(args.RunId),
        "-OutputPath",
        str(internal_proxy_path),
    ]
    websearch_cmd = [
        py,
        str(SCRIPT_DIR / "websearch_adapter.py"),
        "-WebPlanPath",
        str(web_plan_path),
        "-OutputPath",
        str(websearch_path),
        "-PoiId",
        str(poi["id"]),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        internal_cmd.extend(["-TaskId", str(args.TaskId)])
        websearch_cmd.extend(["-TaskId", str(args.TaskId)])
    if args.CommonConfigPath:
        internal_cmd.extend(["-CommonConfigPath", str(args.CommonConfigPath)])
        websearch_cmd.extend(["-CommonConfigPath", str(args.CommonConfigPath)])

    internal_proc = subprocess.Popen(internal_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    websearch_proc = subprocess.Popen(websearch_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

    internal_stdout, internal_stderr = internal_proc.communicate()
    websearch_stdout, websearch_stderr = websearch_proc.communicate()
    if internal_proc.returncode != 0:
        raise RuntimeError(f"call_internal_proxy failed: {(internal_stderr or internal_stdout).strip()}")
    if websearch_proc.returncode != 0:
        raise RuntimeError(f"websearch_adapter failed: {(websearch_stderr or websearch_stdout).strip()}")
    json.loads(internal_stdout.strip() or "{}")
    json.loads(websearch_stdout.strip() or "{}")

    vendor_fallback_paths: list[str] = []
    missing_vendors = collect_missing_vendors(internal_proxy_path)
    for vendor in missing_vendors:
        fallback_path = process_dir / f"map-raw-fallback-{vendor}.json"
        fallback_cmd = [
            py,
            str(SCRIPT_DIR / "call_map_vendor.py"),
            "-PoiName",
            str(poi["name"]),
            "-City",
            str(poi["city"]),
            "-Source",
            vendor,
            "-PoiId",
            str(poi["id"]),
            "-RunId",
            str(args.RunId),
            "-OutputPath",
            str(fallback_path),
        ]
        if args.TaskId:
            fallback_cmd.extend(["-TaskId", str(args.TaskId)])
        if args.CommonConfigPath:
            fallback_cmd.extend(["-CommonConfigPath", str(args.CommonConfigPath)])
        run_json_command(fallback_cmd, label=f"call_map_vendor[{vendor}]", retries=retry_count)
        vendor_fallback_paths.append(str(fallback_path))

    merge_cmd = [
        py,
        str(SCRIPT_DIR / "merge_evidence_collection_outputs.py"),
        "-PoiPath",
        str(args.PoiPath),
        "-InternalProxyPath",
        str(internal_proxy_path),
        "-WebSearchPath",
        str(websearch_path),
        "-OutputPath",
        str(collector_merged_path),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        merge_cmd.extend(["-TaskId", str(args.TaskId)])
    if args.WebFetchPath:
        merge_cmd.extend(["-WebFetchPath", str(args.WebFetchPath)])
    if vendor_fallback_paths:
        merge_cmd.extend(["-VendorFallbackPaths", *vendor_fallback_paths])
    run_json_command(merge_cmd, label="merge_evidence_collection_outputs", retries=retry_count)

    write_cmd = [
        py,
        str(SCRIPT_DIR / "write_evidence_output.py"),
        "-PoiPath",
        str(args.PoiPath),
        "-CollectorOutputPath",
        str(collector_merged_path),
        "-OutputDirectory",
        str(staging_dir),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        write_cmd.extend(["-TaskId", str(args.TaskId)])
    write_result = run_json_command(write_cmd, label="write_evidence_output", retries=retry_count)

    result = {
        "status": "ok",
        "run_id": str(args.RunId),
        "poi_id": str(poi["id"]),
        "web_plan_path": str(web_plan_path),
        "internal_proxy_path": str(internal_proxy_path),
        "websearch_path": str(websearch_path),
        "vendor_fallback_paths": vendor_fallback_paths,
        "collector_merged_path": str(collector_merged_path),
        "evidence_path": write_result.get("evidence_path"),
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
