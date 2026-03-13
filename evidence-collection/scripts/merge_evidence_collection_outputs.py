#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from run_context import attach_context, collect_item_run_ids, require_context, set_item_run_context
from evidence_collection_common import (
    ensure_stdout_utf8,
    finalize_evidence_seed,
    get_generic_items,
    get_source_type_rank,
    iter_unique,
    new_generic_evidence_seed,
    new_map_vendor_evidence_seed,
    normalize_input_poi,
    normalize_whitespace,
    read_json_file,
    sanitize_evidence_seed,
    test_evidence_seed,
    utc_iso_now,
    utc_timestamp,
    write_json_file,
)


VENDORS = ("amap", "bmap", "qmap")


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-InternalProxyPath", required=True)
    parser.add_argument("-WebSearchPath")
    parser.add_argument("-WebFetchPath")
    parser.add_argument("-VendorFallbackPaths", nargs="*")
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    args = parser.parse_args()

    poi = normalize_input_poi(read_json_file(args.PoiPath))
    for field in ("id", "name", "poi_type", "city"):
        if not normalize_whitespace(poi.get(field)):
            raise ValueError(f"input.{field} is required")

    errors: list[str] = []
    resolved_run_id = str(args.RunId or "").strip()
    resolved_task_id = str(args.TaskId or poi.get("task_id") or "").strip()
    evidence_seeds: list[dict] = []
    branch_summary = {
        "internal_proxy": {"amap": 0, "bmap": 0, "qmap": 0},
        "vendor_fallback": {},
        "websearch": 0,
        "webfetch": 0,
    }
    internal_missing_vendors: list[str] = []
    fallback_recovered: set[str] = set()

    internal_payload = read_json_file(args.InternalProxyPath)
    internal_context = require_context(internal_payload, label="internal_proxy", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
    if not resolved_run_id and internal_context is not None:
        resolved_run_id = str(internal_context.get("run_id") or "").strip()
    if not resolved_task_id and internal_context is not None:
        resolved_task_id = str(internal_context.get("task_id") or "").strip()
    if not isinstance(internal_payload, dict) or not isinstance(internal_payload.get("vendors"), dict):
        raise ValueError("internal proxy output must contain vendors")

    for vendor in VENDORS:
        vendor_payload = internal_payload["vendors"].get(vendor)
        if not isinstance(vendor_payload, dict):
            internal_missing_vendors.append(vendor)
            continue
        items = vendor_payload.get("items") if isinstance(vendor_payload.get("items"), list) else []
        branch_summary["internal_proxy"][vendor] = len(items)
        if not items:
            internal_missing_vendors.append(vendor)
        for item in items:
            if not isinstance(item, dict):
                continue
            seed = sanitize_evidence_seed(new_map_vendor_evidence_seed(poi, vendor, item, "internal_proxy"))
            test_evidence_seed(seed, str(poi["id"]), f"internal_proxy.{vendor}", errors)
            evidence_seeds.append(seed)

    for fallback_path in args.VendorFallbackPaths or []:
        if not normalize_whitespace(fallback_path):
            continue
        payload = read_json_file(fallback_path)
        fallback_context = require_context(payload, label=f"vendor_fallback[{fallback_path}]", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
        if not resolved_run_id and fallback_context is not None:
            resolved_run_id = str(fallback_context.get("run_id") or "").strip()
        if not resolved_task_id and fallback_context is not None:
            resolved_task_id = str(fallback_context.get("task_id") or "").strip()
        if not isinstance(payload, dict) or not normalize_whitespace(payload.get("vendor")):
            errors.append(f"vendor fallback output must contain vendor: {fallback_path}")
            continue
        vendor = str(payload["vendor"])
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        branch_summary["vendor_fallback"][vendor] = len(items)
        if items:
            fallback_recovered.add(vendor)
        for item in items:
            if not isinstance(item, dict):
                continue
            seed = sanitize_evidence_seed(new_map_vendor_evidence_seed(poi, vendor, item, "vendor_fallback"))
            test_evidence_seed(seed, str(poi["id"]), f"vendor_fallback.{vendor}", errors)
            evidence_seeds.append(seed)

    if args.WebSearchPath:
        payload = read_json_file(args.WebSearchPath)
        websearch_context = require_context(payload, label="websearch", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
        if not resolved_run_id and websearch_context is not None:
            resolved_run_id = str(websearch_context.get("run_id") or "").strip()
        if not resolved_task_id and websearch_context is not None:
            resolved_task_id = str(websearch_context.get("task_id") or "").strip()
        items = get_generic_items(payload)
        branch_summary["websearch"] = len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            seed = sanitize_evidence_seed(new_generic_evidence_seed(poi, item, "websearch"))
            test_evidence_seed(seed, str(poi["id"]), "websearch", errors)
            evidence_seeds.append(seed)

    if args.WebFetchPath:
        payload = read_json_file(args.WebFetchPath)
        webfetch_context = require_context(payload, label="webfetch", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
        if not resolved_run_id and webfetch_context is not None:
            resolved_run_id = str(webfetch_context.get("run_id") or "").strip()
        if not resolved_task_id and webfetch_context is not None:
            resolved_task_id = str(webfetch_context.get("task_id") or "").strip()
        items = get_generic_items(payload)
        branch_summary["webfetch"] = len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            seed = sanitize_evidence_seed(new_generic_evidence_seed(poi, item, "webfetch"))
            test_evidence_seed(seed, str(poi["id"]), "webfetch", errors)
            evidence_seeds.append(seed)

    if not evidence_seeds:
        errors.append("no evidence was collected")
    if errors:
        raise ValueError("\n".join(errors))

    sorted_seeds = sorted(
        evidence_seeds,
        key=lambda seed: (
            get_source_type_rank(str(seed["source"].get("source_type"))),
            str(seed["source"].get("source_name") or ""),
            str(seed["data"].get("name") or ""),
        ),
    )

    timestamp = utc_timestamp()
    final_evidence = [finalize_evidence_seed(set_item_run_context(seed, resolved_run_id or None, resolved_task_id or None), timestamp, index) for index, seed in enumerate(sorted_seeds)]

    final_missing_vendors = [vendor for vendor in iter_unique(internal_missing_vendors) if vendor not in fallback_recovered]
    source_type_distribution = {"official": 0, "map_vendor": 0, "internet": 0, "user_contributed": 0, "other": 0}
    for item in final_evidence:
        source_type = str(item["source"].get("source_type"))
        if source_type in source_type_distribution:
            source_type_distribution[source_type] += 1

    payload = {
        "status": "ok",
        "poi_id": str(poi["id"]),
        "generated_at": utc_iso_now(),
        "evidence_list": final_evidence,
        "summary": {
            "internal_missing_vendors": iter_unique(internal_missing_vendors),
            "final_missing_vendors": final_missing_vendors,
            "branch_counts": branch_summary,
            "source_type_distribution": source_type_distribution,
            "run_id": resolved_run_id,
        "evidence_count": len(final_evidence),
        },
    }
    if resolved_run_id:
        payload = attach_context(payload, resolved_run_id, str(poi["id"]), task_id=resolved_task_id or None)
    write_json_file(payload, args.OutputPath)

    result = {
        "status": "ok",
        "result_path": str(Path(args.OutputPath).resolve()),
        "run_id": resolved_run_id,
        "evidence_count": len(final_evidence),
        "final_missing_vendors": final_missing_vendors,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
