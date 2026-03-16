#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_context import attach_context, get_context, require_context
from evidence_collection_common import ensure_stdout_utf8, read_json_file, utc_iso_now, write_json_file


ALLOWED_STATUS = {"ok", "partial", "empty", "error"}


def build_candidate_key(item: dict, index: int) -> str:
    for field in ("vendor_item_id", "id", "uid"):
        value = item.get(field)
        if value is not None and str(value).strip():
            return str(value)
    return f"INDEX_{index + 1}"


def extract_vendor_payloads(raw_payload: dict) -> dict[str, dict]:
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


def extract_review_map(review_seed: dict) -> dict[str, dict]:
    if isinstance(review_seed.get("vendors"), dict):
        return {str(key): value for key, value in review_seed["vendors"].items() if isinstance(value, dict)}
    if review_seed.get("vendor"):
        vendor = str(review_seed["vendor"])
        return {vendor: review_seed}
    raise ValueError("review seed must contain vendors or vendor")


def normalize_review_decisions(review_vendor: dict) -> tuple[set[str], dict[str, str]]:
    keep_candidates = {str(item) for item in review_vendor.get("keep_candidates", []) if str(item).strip()}
    reasons: dict[str, str] = {}
    candidate_decisions = review_vendor.get("candidate_decisions", [])
    if isinstance(candidate_decisions, list):
        for item in candidate_decisions:
            if not isinstance(item, dict):
                continue
            candidate_key = str(item.get("candidate_key") or "").strip()
            if not candidate_key:
                continue
            if bool(item.get("is_relevant")):
                keep_candidates.add(candidate_key)
            if item.get("reason") is not None:
                reasons[candidate_key] = str(item.get("reason"))
    return keep_candidates, reasons


def review_vendor_payload(vendor: str, vendor_payload: dict, review_vendor: dict) -> tuple[dict, dict]:
    items = vendor_payload.get("items") if isinstance(vendor_payload.get("items"), list) else []
    keep_candidates, reasons = normalize_review_decisions(review_vendor)
    reviewed_items = []
    dropped_items = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        candidate_key = build_candidate_key(item, index)
        if candidate_key in keep_candidates:
            reviewed_item = dict(item)
            reviewed_item.setdefault("review", {})
            if isinstance(reviewed_item["review"], dict):
                reviewed_item["review"]["candidate_key"] = candidate_key
                reviewed_item["review"]["is_relevant"] = True
                if candidate_key in reasons:
                    reviewed_item["review"]["reason"] = reasons[candidate_key]
            reviewed_items.append(reviewed_item)
        else:
            dropped_items.append(
                {
                    "candidate_key": candidate_key,
                    "name": item.get("name"),
                    "address": item.get("address"),
                    "reason": reasons.get(candidate_key, "filtered_as_irrelevant"),
                }
            )

    reviewed_payload = {
        "vendor": vendor,
        "source_name": vendor_payload.get("source_name"),
        "requested_via": vendor_payload.get("requested_via"),
        "status": "ok" if reviewed_items else "empty",
        "result_count": len(reviewed_items),
        "items": reviewed_items,
        "error": vendor_payload.get("error"),
        "reviewed_at": utc_iso_now(),
        "review_summary": {
            "kept_count": len(reviewed_items),
            "dropped_count": len(dropped_items),
        },
    }
    summary = {
        "vendor": vendor,
        "raw_count": len(items),
        "kept_count": len(reviewed_items),
        "dropped_count": len(dropped_items),
        "dropped_candidates": dropped_items,
    }
    return reviewed_payload, summary


def build_output(raw_payload: dict, reviewed_vendors: dict[str, dict], summaries: dict[str, dict]) -> dict:
    if isinstance(raw_payload.get("vendors"), dict):
        missing_vendors = [vendor for vendor, payload in reviewed_vendors.items() if payload.get("result_count", 0) == 0]
        return {
            "status": raw_payload.get("status") if raw_payload.get("status") in ALLOWED_STATUS else "ok",
            "query": raw_payload.get("query", {}),
            "collected_at": raw_payload.get("collected_at"),
            "reviewed_at": utc_iso_now(),
            "vendors": reviewed_vendors,
            "missing_vendors": missing_vendors,
            "review_summary": summaries,
        }

    vendor = str(raw_payload.get("vendor"))
    payload = reviewed_vendors[vendor]
    return {
        "status": payload.get("status", "ok"),
        "vendor": vendor,
        "query": raw_payload.get("query", {}),
        "collected_at": raw_payload.get("collected_at"),
        "reviewed_at": utc_iso_now(),
        "requested_via": raw_payload.get("requested_via", "direct_api"),
        "result_count": payload.get("result_count", 0),
        "items": payload.get("items", []),
        "error": raw_payload.get("error"),
        "review_summary": summaries.get(vendor, {}),
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-RawMapPath", required=True)
    parser.add_argument("-ReviewSeedPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    raw_payload = read_json_file(args.RawMapPath)
    review_seed = read_json_file(args.ReviewSeedPath)
    if not isinstance(raw_payload, dict):
        raise ValueError("raw map payload must be an object")
    if not isinstance(review_seed, dict):
        raise ValueError("review seed must be an object")

    raw_context = require_context(raw_payload, label="raw_map", expected_poi_id=args.PoiId, expected_run_id=args.RunId, allow_missing=not bool(args.PoiId or args.RunId))
    review_context = require_context(review_seed, label="review_seed", expected_poi_id=args.PoiId or (raw_context or {}).get("poi_id"), expected_run_id=args.RunId or (raw_context or {}).get("run_id"), allow_missing=True)
    resolved_run_id = str(args.RunId or (review_context or {}).get("run_id") or (raw_context or {}).get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or (review_context or {}).get("poi_id") or (raw_context or {}).get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or (review_context or {}).get("task_id") or (raw_context or {}).get("task_id") or "").strip()

    raw_vendors = extract_vendor_payloads(raw_payload)
    review_map = extract_review_map(review_seed)

    reviewed_vendors: dict[str, dict] = {}
    summaries: dict[str, dict] = {}
    for vendor, vendor_payload in raw_vendors.items():
        if vendor not in review_map:
            raise ValueError(f"review seed is missing vendor decisions: {vendor}")
        reviewed_payload, summary = review_vendor_payload(vendor, vendor_payload, review_map[vendor])
        reviewed_vendors[vendor] = reviewed_payload
        summaries[vendor] = summary

    output = build_output(raw_payload, reviewed_vendors, summaries)
    if resolved_run_id and resolved_poi_id:
        output = attach_context(output, resolved_run_id, resolved_poi_id, task_id=resolved_task_id or None)
    write_json_file(output, args.OutputPath)

    result = {
        "status": "ok",
        "result_path": str(Path(args.OutputPath).resolve()),
        "run_id": resolved_run_id,
        "vendors": {vendor: {"kept_count": data["kept_count"], "dropped_count": data["dropped_count"]} for vendor, data in summaries.items()},
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
