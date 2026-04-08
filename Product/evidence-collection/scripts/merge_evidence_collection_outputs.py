#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_context import attach_context, collect_item_run_ids, get_context, require_context, set_item_run_context
from evidence_collection_common import (
    ensure_stdout_utf8,
    extract_source_domain,
    finalize_evidence_seed,
    get_generic_items,
    get_source_type_rank,
    iter_unique,
    new_generic_evidence_seed,
    new_map_vendor_evidence_seed,
    normalize_url_for_matching,
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


def log_progress(message: str) -> None:
    sys.stderr.write(f"[merge-evidence] {message}\n")
    sys.stderr.flush()


def is_reviewed_map_payload(payload: object) -> bool:
    return isinstance(payload, dict) and normalize_whitespace(payload.get("reviewed_at")) is not None


def map_payload_has_any_items(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("vendors"), dict):
        return any(
            isinstance(vendor_payload, dict) and isinstance(vendor_payload.get("items"), list) and bool(vendor_payload.get("items"))
            for vendor_payload in payload["vendors"].values()
        )
    return isinstance(payload.get("items"), list) and bool(payload.get("items"))


def is_reviewed_generic_payload(payload: object) -> bool:
    return isinstance(payload, dict) and normalize_whitespace(payload.get("reviewed_at")) is not None and isinstance(payload.get("review_summary"), dict)


def patch_merge_context(
    payload: object,
    *,
    expected_poi_id: str,
    fallback_run_id: str,
    fallback_task_id: str,
) -> object:
    if not isinstance(payload, dict):
        return payload
    context = get_context(payload)
    reviewed_or_generated_at = str(payload.get("reviewed_at") or payload.get("generated_at") or utc_iso_now())
    status = str(payload.get("status") or "").strip().lower()
    if context is None:
        if status in {"empty", "skipped"} and fallback_run_id:
            return attach_context(
                payload,
                fallback_run_id,
                expected_poi_id,
                task_id=fallback_task_id or None,
                created_at=reviewed_or_generated_at,
            )
        return payload
    poi_id = str(context.get("poi_id") or "").strip() or expected_poi_id
    run_id = str(context.get("run_id") or "").strip() or fallback_run_id
    task_id = str(context.get("task_id") or "").strip() or fallback_task_id
    created_at = str(context.get("created_at") or "").strip()
    if created_at:
        return payload
    if run_id and poi_id:
        return attach_context(
            payload,
            run_id,
            poi_id,
            task_id=task_id or None,
            created_at=reviewed_or_generated_at,
        )
    return payload


def seed_priority(seed: dict) -> tuple[float, float, float, int]:
    source = seed.get("source") if isinstance(seed.get("source"), dict) else {}
    verification = seed.get("verification") if isinstance(seed.get("verification"), dict) else {}
    metadata = seed.get("metadata") if isinstance(seed.get("metadata"), dict) else {}
    data = seed.get("data") if isinstance(seed.get("data"), dict) else {}
    populated_fields = sum(1 for field in ("name", "address", "phone", "category", "coordinates") if data.get(field))
    source_rank_score = float(10 - get_source_type_rank(str(source.get("source_type") or "")))
    weight = float(source.get("weight") or 0.0)
    confidence = float(verification.get("confidence") or 0.0)
    branch_bonus = 1 if str(metadata.get("signal_origin") or "").strip().lower() == "webreader" else 0
    return (source_rank_score + branch_bonus, weight, confidence, populated_fields)


def build_seed_identity_keys(seed: dict) -> list[str]:
    source = seed.get("source") if isinstance(seed.get("source"), dict) else {}
    metadata = seed.get("metadata") if isinstance(seed.get("metadata"), dict) else {}
    data = seed.get("data") if isinstance(seed.get("data"), dict) else {}
    signal_origin = str(metadata.get("signal_origin") or "").strip().lower()
    if signal_origin not in {"websearch", "webreader", "webfetch"}:
        return []

    source_type = str(source.get("source_type") or "").strip().lower()
    domain = normalize_whitespace(metadata.get("source_domain")) or extract_source_domain(source.get("source_url"))
    page_title = normalize_whitespace(metadata.get("page_title"))
    name = normalize_whitespace(data.get("name"))
    address = normalize_whitespace(data.get("address"))
    phone = normalize_whitespace(data.get("phone"))
    category = normalize_whitespace(data.get("category"))
    url = normalize_url_for_matching(metadata.get("canonical_url") or source.get("source_url"))

    keys: list[str] = []
    if url:
        keys.append(f"url|{signal_origin}|{source_type}|{url}")
    if domain and page_title and name:
        keys.append(
            "|".join(
                [
                    "page",
                    signal_origin,
                    source_type,
                    str(domain).lower(),
                    str(page_title).lower(),
                    name,
                    address or "",
                    phone or "",
                    category or "",
                ]
            )
        )
    return keys


def dedupe_evidence_seeds(evidence_seeds: list[dict]) -> tuple[list[dict], dict]:
    deduped: list[dict] = []
    key_to_index: dict[str, int] = {}
    duplicate_count = 0

    for seed in evidence_seeds:
        keys = build_seed_identity_keys(seed)
        matched_index = next((key_to_index[key] for key in keys if key in key_to_index), None)
        if matched_index is None:
            deduped.append(seed)
            new_index = len(deduped) - 1
            for key in keys:
                key_to_index[key] = new_index
            continue

        duplicate_count += 1
        if seed_priority(seed) > seed_priority(deduped[matched_index]):
            deduped[matched_index] = seed
        for key in keys:
            key_to_index[key] = matched_index

    summary = {
        "input_count": len(evidence_seeds),
        "kept_count": len(deduped),
        "duplicate_count": duplicate_count,
    }
    return deduped, summary


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-InternalProxyPath", required=True)
    parser.add_argument("-WebSearchPath")
    parser.add_argument("-WebReaderPath")
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
        "webreader": 0,
        "webfetch": 0,
    }
    internal_missing_vendors: list[str] = []
    fallback_recovered: set[str] = set()

    internal_payload = patch_merge_context(
        read_json_file(args.InternalProxyPath),
        expected_poi_id=str(poi["id"]),
        fallback_run_id=resolved_run_id,
        fallback_task_id=resolved_task_id,
    )
    internal_context = require_context(internal_payload, label="internal_proxy", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
    if not resolved_run_id and internal_context is not None:
        resolved_run_id = str(internal_context.get("run_id") or "").strip()
    if not resolved_task_id and internal_context is not None:
        resolved_task_id = str(internal_context.get("task_id") or "").strip()
    if not isinstance(internal_payload, dict) or not isinstance(internal_payload.get("vendors"), dict):
        raise ValueError("internal proxy output must contain vendors")
    if map_payload_has_any_items(internal_payload) and not is_reviewed_map_payload(internal_payload):
        raise ValueError("internal proxy path must point to map-reviewed payload; raw map payload cannot be merged directly")
    log_progress("开始归并各分支证据")

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
        payload = patch_merge_context(
            read_json_file(fallback_path),
            expected_poi_id=str(poi["id"]),
            fallback_run_id=resolved_run_id,
            fallback_task_id=resolved_task_id,
        )
        fallback_context = require_context(payload, label=f"vendor_fallback[{fallback_path}]", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
        if not resolved_run_id and fallback_context is not None:
            resolved_run_id = str(fallback_context.get("run_id") or "").strip()
        if not resolved_task_id and fallback_context is not None:
            resolved_task_id = str(fallback_context.get("task_id") or "").strip()
        if not isinstance(payload, dict) or not normalize_whitespace(payload.get("vendor")):
            errors.append(f"vendor fallback output must contain vendor: {fallback_path}")
            continue
        if map_payload_has_any_items(payload) and not is_reviewed_map_payload(payload):
            errors.append(f"vendor fallback path must point to map-reviewed payload: {fallback_path}")
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
        payload = patch_merge_context(
            read_json_file(args.WebSearchPath),
            expected_poi_id=str(poi["id"]),
            fallback_run_id=resolved_run_id,
            fallback_task_id=resolved_task_id,
        )
        websearch_context = require_context(payload, label="websearch", expected_poi_id=str(poi["id"]), expected_run_id=resolved_run_id or None, allow_missing=not bool(resolved_run_id))
        if not resolved_run_id and websearch_context is not None:
            resolved_run_id = str(websearch_context.get("run_id") or "").strip()
        if not resolved_task_id and websearch_context is not None:
            resolved_task_id = str(websearch_context.get("task_id") or "").strip()
        if not is_reviewed_generic_payload(payload):
            raise ValueError("websearch path must point to websearch-reviewed payload; raw websearch payload cannot be merged directly")
        items = get_generic_items(payload)
        branch_summary["websearch"] = len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            seed = sanitize_evidence_seed(new_generic_evidence_seed(poi, item, "websearch"))
            test_evidence_seed(seed, str(poi["id"]), "websearch", errors)
            evidence_seeds.append(seed)

    webreader_input_path = args.WebReaderPath or args.WebFetchPath
    if webreader_input_path:
        payload = patch_merge_context(
            read_json_file(webreader_input_path),
            expected_poi_id=str(poi["id"]),
            fallback_run_id=resolved_run_id,
            fallback_task_id=resolved_task_id,
        )
        webreader_context = require_context(
            payload,
            label="webreader",
            expected_poi_id=str(poi["id"]),
            expected_run_id=resolved_run_id or None,
            allow_missing=not bool(resolved_run_id),
        )
        if not resolved_run_id and webreader_context is not None:
            resolved_run_id = str(webreader_context.get("run_id") or "").strip()
        if not resolved_task_id and webreader_context is not None:
            resolved_task_id = str(webreader_context.get("task_id") or "").strip()
        if not is_reviewed_generic_payload(payload):
            raise ValueError("webreader path must point to reviewed payload; raw webreader payload cannot be merged directly")
        items = get_generic_items(payload)
        branch_summary["webreader"] = len(items)
        if args.WebFetchPath and not args.WebReaderPath:
            branch_summary["webfetch"] = len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            seed = sanitize_evidence_seed(new_generic_evidence_seed(poi, item, "webreader"))
            test_evidence_seed(seed, str(poi["id"]), "webreader", errors)
            evidence_seeds.append(seed)

    if not evidence_seeds:
        errors.append("no evidence was collected")
    if errors:
        raise ValueError("\n".join(errors))

    deduped_seeds, dedupe_summary = dedupe_evidence_seeds(evidence_seeds)
    sorted_seeds = sorted(
        deduped_seeds,
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
            "dedupe_summary": dedupe_summary,
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
        "summary_text": (
            "证据归并完成："
            f"map_vendor={source_type_distribution['map_vendor']}，"
            f"official={source_type_distribution['official']}，"
            f"internet={source_type_distribution['internet']}，"
            f"去重剔除={dedupe_summary['duplicate_count']}，"
            f"总计={len(final_evidence)}。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
