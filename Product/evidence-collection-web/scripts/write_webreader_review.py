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
    normalize_text,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)
from validate_webreader_review_seed import build_catalog_from_review_input, validate_webreader_review_seed_against_catalog


def log_progress(message: str) -> None:
    sys.stderr.write(f"[write-webreader-review] {message}\n")
    sys.stderr.flush()


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


def build_result_id(index: int) -> str:
    return f"WR_{index + 1:03d}"


def build_reviewed_item(raw_item: Dict[str, Any], review_item: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(raw_item.get("source") if isinstance(raw_item.get("source"), dict) else {})
    metadata = dict(raw_item.get("metadata") if isinstance(raw_item.get("metadata"), dict) else {})
    raw_page = dict(raw_item.get("raw_page") if isinstance(raw_item.get("raw_page"), dict) else {})
    extracted = review_item.get("extracted") if isinstance(review_item.get("extracted"), dict) else {}

    data = {
        "name": normalize_text(extracted.get("name") or source.get("source_name")),
    }
    for field in ("address", "phone", "category", "status", "level"):
        value = normalize_text(extracted.get(field))
        if value:
            data[field] = value

    metadata["signal_origin"] = "webreader"
    metadata["review_status"] = "approved"
    metadata["review_reason"] = normalize_text(review_item.get("reason")) or "relevant_webreader_result"
    metadata["result_id"] = str(review_item.get("result_id"))
    metadata["existence_status"] = normalize_text(review_item.get("existence_status")) or "unknown"
    metadata["webreader_provider"] = raw_item.get("provider")
    metadata["page_title"] = normalize_text(raw_page.get("title")) or metadata.get("page_title")
    metadata["text_snippet"] = normalize_text(raw_page.get("description")) or metadata.get("text_snippet")
    if normalize_whitespace(extracted.get("email")):
        metadata["email"] = str(extracted["email"])

    verification = {
        "is_valid": True,
        "confidence": float(review_item.get("confidence") or source.get("weight") or 0.65),
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
    parser.add_argument("-WebReaderRawPath", required=True)
    parser.add_argument("-WebReaderReviewInputPath", required=True)
    parser.add_argument("-ReviewSeedPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    raw_payload = read_json_file(args.WebReaderRawPath)
    review_input = read_json_file(args.WebReaderReviewInputPath)
    review_seed = read_json_file(args.ReviewSeedPath)
    if not isinstance(raw_payload, dict):
        raise ValueError("webreader raw payload must be an object")
    if not isinstance(review_input, dict):
        raise ValueError("webreader review input must be an object")
    if not isinstance(review_seed, dict):
        raise ValueError("webreader review seed must be an object")

    raw_context = get_context(raw_payload) or {}
    review_input_context = get_context(review_input) or {}
    seed_context = get_context(review_seed) or {}
    resolved_run_id = str(args.RunId or raw_context.get("run_id") or review_input_context.get("run_id") or seed_context.get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or raw_context.get("poi_id") or review_input_context.get("poi_id") or seed_context.get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or raw_context.get("task_id") or review_input_context.get("task_id") or seed_context.get("task_id") or "").strip()
    created_at = read_created_at(raw_context, review_input_context, seed_context)

    validate_webreader_review_seed_against_catalog(build_catalog_from_review_input(review_input), review_seed)
    review_map = normalize_review_map(review_seed)
    raw_items = raw_payload.get("items") if isinstance(raw_payload.get("items"), list) else []

    reviewed_items = []
    dropped_count = 0
    for index, raw_item in enumerate(raw_items):
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
        reviewed_items.append(build_reviewed_item(raw_item, review_item))

    output = {
        "status": "ok" if reviewed_items else "empty",
        "reviewed_at": utc_iso_now(),
        "items": reviewed_items,
        "review_summary": {
            "kept_count": len(reviewed_items),
            "dropped_count": dropped_count,
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
        "summary_text": f"webreader review 写出完成：保留 {len(reviewed_items)} 条，剔除 {dropped_count} 条。",
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
