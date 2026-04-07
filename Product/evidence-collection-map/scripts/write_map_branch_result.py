#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from run_context import attach_context, get_context
from evidence_collection_common import ensure_stdout_utf8, utc_iso_now, write_json_file

VENDORS = ("amap", "bmap", "qmap")


def read_json_optional(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload
    return None


def read_created_at(*contexts: Optional[Dict[str, Any]]) -> Optional[str]:
    for context in contexts:
        if not isinstance(context, dict):
            continue
        value = str(context.get("created_at") or "").strip()
        if value:
            return value
    return None


def resolve_path(candidate: Optional[str], fallback: Path) -> Optional[str]:
    if candidate:
        path = Path(candidate)
        if path.exists():
            return str(path.resolve())
    if fallback.exists():
        return str(fallback.resolve())
    return None


def extract_vendor_counts(payload: Optional[Dict[str, Any]]) -> Dict[str, int]:
    counts = {vendor: 0 for vendor in VENDORS}
    if not isinstance(payload, dict):
        return counts
    if isinstance(payload.get("vendors"), dict):
        for vendor in VENDORS:
            vendor_payload = payload["vendors"].get(vendor)
            items = vendor_payload.get("items") if isinstance(vendor_payload, dict) and isinstance(vendor_payload.get("items"), list) else []
            counts[vendor] = len(items)
        return counts
    vendor = str(payload.get("vendor") or "").strip()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if vendor in counts:
        counts[vendor] = len(items)
    return counts


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-ProcessDir", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    parser.add_argument("-PoiId")
    parser.add_argument("-InternalReviewedPath")
    parser.add_argument("-InternalRawPath")
    parser.add_argument("-FallbackReviewedPaths", nargs="*")
    args = parser.parse_args()

    process_dir = Path(args.ProcessDir).resolve()
    output_path = Path(args.OutputPath).resolve()
    process_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    default_internal_reviewed = process_dir / "map-reviewed-internal-proxy.json"
    default_internal_raw = process_dir / "map-raw-internal-proxy.json"

    internal_reviewed_path = resolve_path(args.InternalReviewedPath, default_internal_reviewed)
    internal_raw_path = resolve_path(args.InternalRawPath, default_internal_raw)
    internal_merge_input_path = internal_reviewed_path or internal_raw_path

    fallback_paths = []
    if args.FallbackReviewedPaths:
        for value in args.FallbackReviewedPaths:
            text = str(value or "").strip()
            if not text:
                continue
            path = Path(text)
            if path.exists():
                fallback_paths.append(str(path.resolve()))
    else:
        for vendor in VENDORS:
            fallback_candidate = process_dir / f"map-reviewed-fallback-{vendor}.json"
            if fallback_candidate.exists():
                fallback_paths.append(str(fallback_candidate.resolve()))

    internal_payload = read_json_optional(Path(internal_merge_input_path)) if internal_merge_input_path else None
    internal_status = str((internal_payload or {}).get("status") or "").strip().lower()

    internal_counts = extract_vendor_counts(internal_payload)
    missing_vendors = [vendor for vendor, count in internal_counts.items() if count <= 0]

    fallback_vendor_paths: Dict[str, str] = {}
    fallback_recovered_vendors: list[str] = []
    fallback_summaries: Dict[str, Dict[str, Any]] = {}
    for path_text in fallback_paths:
        payload = read_json_optional(Path(path_text))
        if not isinstance(payload, dict):
            continue
        vendor = str(payload.get("vendor") or "").strip()
        if not vendor:
            continue
        item_count = len(payload.get("items")) if isinstance(payload.get("items"), list) else 0
        status = str(payload.get("status") or "").strip().lower()
        fallback_vendor_paths[vendor] = path_text
        fallback_summaries[vendor] = {
            "status": status,
            "item_count": item_count,
            "path": path_text,
        }
        if item_count > 0:
            fallback_recovered_vendors.append(vendor)

    final_missing_vendors = [vendor for vendor in missing_vendors if vendor not in set(fallback_recovered_vendors)]
    has_any_map_items = sum(internal_counts.values()) > 0 or bool(fallback_recovered_vendors)
    if has_any_map_items:
        status = "ok"
    elif internal_status in {"empty", "partial", "ok"}:
        status = "empty"
    else:
        status = "error"

    internal_context = get_context(internal_payload) if internal_payload else None
    resolved_run_id = str(args.RunId or (internal_context or {}).get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or (internal_context or {}).get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or (internal_context or {}).get("task_id") or "").strip()
    created_at = read_created_at(internal_context) or utc_iso_now()

    output: Dict[str, Any] = {
        "status": status,
        "branch": "map",
        "run_id": resolved_run_id,
        "task_id": resolved_task_id,
        "poi_id": resolved_poi_id,
        "created_at": created_at,
        "internal_proxy_merge_input_path": internal_merge_input_path,
        "internal_reviewed_path": internal_reviewed_path,
        "internal_raw_path": internal_raw_path,
        "internal_vendor_counts": internal_counts,
        "missing_vendors": missing_vendors,
        "vendor_merge_input_paths": fallback_vendor_paths,
        "fallback_summaries": fallback_summaries,
        "fallback_recovered_vendors": fallback_recovered_vendors,
        "final_missing_vendors": final_missing_vendors,
        "summary_text": (
            f"map 分支汇总完成: status={status}, "
            f"internal={internal_status or 'missing'}, "
            f"fallback_recovered={','.join(fallback_recovered_vendors) or 'none'}"
        ),
    }
    if resolved_run_id and resolved_poi_id:
        output = attach_context(
            output,
            resolved_run_id,
            resolved_poi_id,
            task_id=resolved_task_id or None,
            created_at=created_at,
        )
    write_json_file(output, output_path)

    result = {
        "status": output["status"],
        "result_path": str(output_path),
        "run_id": resolved_run_id,
        "task_id": resolved_task_id,
        "internal_proxy_merge_input_path": internal_merge_input_path,
        "vendor_merge_input_paths": fallback_vendor_paths,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if status in {"ok", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
