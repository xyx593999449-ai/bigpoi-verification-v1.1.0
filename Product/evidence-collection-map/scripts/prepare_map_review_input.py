#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from evidence_collection_common import (
    collect_authority_signals,
    ensure_stdout_utf8,
    normalize_input_poi,
    normalize_text,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)
from run_context import attach_context, get_context


def log_progress(message: str) -> None:
    sys.stderr.write(f"[prepare-map-review] {message}\n")
    sys.stderr.flush()


def build_candidate_key(item: Dict[str, Any], index: int) -> str:
    for field in ("vendor_item_id", "id", "uid"):
        value = item.get(field)
        if value is not None and str(value).strip():
            return str(value)
    return f"INDEX_{index + 1}"


def extract_vendor_payloads(raw_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if isinstance(raw_payload.get("vendors"), dict):
        return {str(key): value for key, value in raw_payload["vendors"].items() if isinstance(value, dict)}
    if raw_payload.get("vendor") and isinstance(raw_payload.get("items"), list):
        vendor = str(raw_payload["vendor"])
        return {
            vendor: {
                "vendor": vendor,
                "source_name": raw_payload.get("source_name"),
                "requested_via": raw_payload.get("requested_via", "direct_api"),
                "status": raw_payload.get("status", "ok"),
                "result_count": len(raw_payload.get("items", [])),
                "items": raw_payload.get("items", []),
                "error": raw_payload.get("error"),
            }
        }
    raise ValueError("raw map payload must be internal proxy output or single-vendor fallback output")


def compact_candidate(item: Dict[str, Any], index: int) -> Dict[str, Any]:
    compact = {
        "candidate_key": build_candidate_key(item, index),
        "name": normalize_text(item.get("name")),
        "address": normalize_text(item.get("address")),
        "category": normalize_text(item.get("category")),
        "phone": normalize_text(item.get("phone")),
        "authority_signals": collect_authority_signals(
            [
                item.get("name"),
                item.get("address"),
                item.get("category"),
            ]
        ),
    }
    if isinstance(item.get("coordinates"), dict):
        compact["coordinates"] = item["coordinates"]
    if isinstance(item.get("administrative"), dict):
        administrative = {
            key: normalize_text(item["administrative"].get(key))
            for key in ("province", "city", "district")
            if normalize_text(item["administrative"].get(key))
        }
        if administrative:
            compact["administrative"] = administrative
    if normalize_whitespace(item.get("computed_distance_meters")):
        compact["computed_distance_meters"] = item.get("computed_distance_meters")
    return compact


def build_output(poi: Dict[str, Any], raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    vendors_out: Dict[str, Dict[str, Any]] = {}
    vendor_candidate_counts: Dict[str, int] = {}
    total_candidates = 0

    for vendor, payload in extract_vendor_payloads(raw_payload).items():
        raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
        candidates = [compact_candidate(item, index) for index, item in enumerate(raw_items) if isinstance(item, dict)]
        total_candidates += len(candidates)
        vendor_candidate_counts[vendor] = len(candidates)
        vendors_out[vendor] = {
            "vendor": vendor,
            "source_name": normalize_text(payload.get("source_name")),
            "requested_via": normalize_text(payload.get("requested_via")),
            "status": normalize_text(payload.get("status")) or "ok",
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    poi_out = {
        "id": str(poi.get("id") or ""),
        "name": str(poi.get("name") or ""),
        "poi_type": str(poi.get("poi_type") or ""),
        "city": str(poi.get("city") or ""),
    }
    if isinstance(poi.get("coordinates"), dict):
        poi_out["coordinates"] = poi["coordinates"]

    return {
        "status": "ok",
        "prepared_at": utc_iso_now(),
        "poi": poi_out,
        "vendors": vendors_out,
        "summary": {
            "candidate_count": total_candidates,
            "vendor_candidate_counts": vendor_candidate_counts,
        },
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-RawMapPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    args = parser.parse_args()

    poi = normalize_input_poi(read_json_file(args.PoiPath))
    raw_payload = read_json_file(args.RawMapPath)
    if not isinstance(raw_payload, dict):
        raise ValueError("raw map payload must be an object")

    raw_context = get_context(raw_payload) or {}
    resolved_run_id = str(args.RunId or raw_context.get("run_id") or "").strip()
    resolved_task_id = str(args.TaskId or raw_context.get("task_id") or "").strip()

    output = build_output(poi, raw_payload)
    if resolved_run_id and normalize_whitespace(poi.get("id")):
        output = attach_context(output, resolved_run_id, str(poi["id"]), task_id=resolved_task_id or None)
    write_json_file(output, args.OutputPath)

    candidate_count = int(output.get("summary", {}).get("candidate_count") or 0)
    result = {
        "status": "ok",
        "result_path": str(Path(args.OutputPath).resolve()),
        "candidate_count": candidate_count,
        "summary_text": f"图商 review 输入准备完成：共 {candidate_count} 条候选。",
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
