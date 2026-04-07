#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from run_context import attach_context, get_context
from evidence_collection_common import (
    ensure_stdout_utf8,
    get_generic_items,
    normalize_text,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)
from validate_websearch_review_seed import build_catalog_from_raw_payload, validate_websearch_review_seed_against_catalog


def log_progress(message: str) -> None:
    sys.stderr.write(f"[write-websearch-review] {message}\n")
    sys.stderr.flush()


def build_result_id(index: int) -> str:
    return f"WEB_{index + 1:03d}"


def read_created_at(*contexts: Dict[str, Any]) -> str:
    for context in contexts:
        value = str(context.get("created_at") or "").strip()
        if value:
            return value
    return utc_iso_now()


def normalize_review_map(review_seed: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    items = review_seed.get("items") if isinstance(review_seed.get("items"), list) else []
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        result_id = str(item.get("result_id") or "").strip()
        if not result_id:
            continue
        mapping[result_id] = item
    return mapping


def is_mergeable_review_item(review_item: Dict[str, Any]) -> bool:
    if not bool(review_item.get("is_relevant")):
        return False
    return normalize_whitespace(review_item.get("entity_relation")) == "poi_body"


def build_reviewed_item(raw_item: Dict[str, Any], review_item: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(raw_item.get("source") if isinstance(raw_item.get("source"), dict) else {})
    raw_data = dict(raw_item.get("data") if isinstance(raw_item.get("data"), dict) else {})
    metadata = dict(raw_item.get("metadata") if isinstance(raw_item.get("metadata"), dict) else {})
    extracted = review_item.get("extracted") if isinstance(review_item.get("extracted"), dict) else {}

    data = {
        "name": normalize_text(extracted.get("name") or raw_data.get("name")),
    }
    for field in ("address", "phone", "category", "status", "level"):
        value = normalize_text(extracted.get(field) or raw_data.get(field))
        if value:
            data[field] = value

    if isinstance(raw_data.get("coordinates"), dict):
        data["coordinates"] = raw_data["coordinates"]

    metadata["signal_origin"] = "websearch"
    metadata["review_status"] = "approved"
    metadata["review_reason"] = normalize_text(review_item.get("reason")) or "relevant_websearch_result"
    metadata["entity_relation"] = normalize_text(review_item.get("entity_relation")) or "poi_body"
    metadata["result_id"] = str(review_item.get("result_id"))
    should_read = bool(review_item.get("should_read")) if review_item.get("should_read") is not None else bool(review_item.get("should_fetch"))
    metadata["should_read"] = should_read
    metadata["should_fetch"] = should_read
    read_url = normalize_whitespace(review_item.get("read_url") or review_item.get("fetch_url"))
    if read_url:
        metadata["read_url"] = read_url
        metadata["fetch_url"] = read_url
    if normalize_whitespace(extracted.get("category_hint")):
        metadata["level_hint"] = str(extracted["category_hint"])
    if normalize_whitespace(extracted.get("email")):
        metadata["email"] = str(extracted["email"])

    verification = {
        "is_valid": True,
        "confidence": float(review_item.get("confidence") or source.get("weight") or 0.6),
    }

    return {
        "source": source,
        "data": data,
        "collected_at": raw_item.get("collected_at") or utc_iso_now(),
        "verification": verification,
        "metadata": metadata,
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-WebSearchRawPath", required=True)
    parser.add_argument("-ReviewSeedPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    raw_payload = read_json_file(args.WebSearchRawPath)
    review_seed = read_json_file(args.ReviewSeedPath)
    if not isinstance(raw_payload, dict):
        raise ValueError("websearch raw payload must be an object")
    if not isinstance(review_seed, dict):
        raise ValueError("review seed must be an object")

    raw_context = get_context(raw_payload) or {}
    seed_context = get_context(review_seed) or {}
    resolved_run_id = str(args.RunId or raw_context.get("run_id") or seed_context.get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or raw_context.get("poi_id") or seed_context.get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or raw_context.get("task_id") or seed_context.get("task_id") or "").strip()
    created_at = read_created_at(raw_context, seed_context)

    validate_websearch_review_seed_against_catalog(build_catalog_from_raw_payload(raw_payload), review_seed)
    review_map = normalize_review_map(review_seed)
    reviewed_items = []
    dropped_count = 0
    filtered_by_relation_count = 0
    for index, raw_item in enumerate(get_generic_items(raw_payload)):
        if not isinstance(raw_item, dict):
            continue
        result_id = build_result_id(index)
        review_item = review_map.get(result_id)
        if not review_item:
            dropped_count += 1
            continue
        if not bool(review_item.get("is_relevant")):
            dropped_count += 1
            continue
        if not is_mergeable_review_item(review_item):
            dropped_count += 1
            filtered_by_relation_count += 1
            continue
        reviewed_items.append(build_reviewed_item(raw_item, review_item))

    output = {
        "status": "ok" if reviewed_items else "empty",
        "reviewed_at": utc_iso_now(),
        "items": reviewed_items,
        "review_summary": {
            "kept_count": len(reviewed_items),
            "dropped_count": dropped_count,
            "filtered_by_relation_count": filtered_by_relation_count,
        },
    }
    if resolved_run_id and resolved_poi_id:
        output = attach_context(
            output,
            resolved_run_id,
            resolved_poi_id,
            task_id=resolved_task_id or None,
            created_at=created_at,
        )
    write_json_file(output, args.OutputPath)

    result = {
        "status": output["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "kept_count": len(reviewed_items),
        "dropped_count": dropped_count,
        "filtered_by_relation_count": filtered_by_relation_count,
        "summary_text": (
            f"websearch review 写出完成：保留 {len(reviewed_items)} 条，"
            f"剔除 {dropped_count} 条，其中弱相关过滤 {filtered_by_relation_count} 条。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
