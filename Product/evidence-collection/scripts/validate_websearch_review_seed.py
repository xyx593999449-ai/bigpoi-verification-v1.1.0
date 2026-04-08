#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evidence_collection_common import ensure_stdout_utf8, get_generic_items, normalize_whitespace, read_json_file


ALLOWED_ENTITY_RELATIONS = {"poi_body", "subordinate_org", "same_region", "mention_only", "unrelated"}


def log_progress(message: str) -> None:
    sys.stderr.write(f"[validate-websearch-review] {message}\n")
    sys.stderr.flush()


def build_result_id(index: int) -> str:
    return f"WEB_{index + 1:03d}"


def build_catalog_from_review_input(prepared_input: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    items = prepared_input.get("review_items") if isinstance(prepared_input.get("review_items"), list) else []
    catalog: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        result_id = str(item.get("result_id") or "").strip()
        if not result_id:
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        catalog[result_id] = {
            "source_type": normalize_whitespace(source.get("source_type")) or "other",
            "source_url": normalize_whitespace(source.get("source_url")),
            "page_title": normalize_whitespace(candidate.get("page_title")),
        }
    return catalog


def build_catalog_from_raw_payload(raw_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(get_generic_items(raw_payload)):
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        catalog[build_result_id(index)] = {
            "source_type": normalize_whitespace(source.get("source_type")) or "other",
            "source_url": normalize_whitespace(source.get("source_url")),
            "page_title": normalize_whitespace(metadata.get("page_title")),
        }
    return catalog


def validate_websearch_review_seed_against_catalog(
    catalog: Dict[str, Dict[str, Any]],
    review_seed: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    if str(review_seed.get("status") or "").strip() == "auto_generated":
        errors.append("websearch review seed cannot use auto_generated fallback output")

    items = review_seed.get("items")
    if not isinstance(items, list):
        raise ValueError("websearch review seed must contain items")

    item_by_id: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{index}] must be an object")
            continue
        result_id = str(item.get("result_id") or "").strip()
        if not result_id:
            errors.append(f"items[{index}].result_id is required")
            continue
        if result_id in item_by_id:
            errors.append(f"duplicate result_id in review seed: {result_id}")
            continue
        if not isinstance(item.get("is_relevant"), bool):
            errors.append(f"items[{index}].is_relevant must be boolean")
        if not normalize_whitespace(item.get("reason")):
            errors.append(f"items[{index}].reason is required")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)):
            errors.append(f"items[{index}].confidence must be numeric")
        elif float(confidence) < 0 or float(confidence) > 1:
            errors.append(f"items[{index}].confidence must be between 0 and 1")

        source_type = normalize_whitespace(item.get("source_type"))
        expected_source_type = catalog.get(result_id, {}).get("source_type")
        if not source_type:
            errors.append(f"items[{index}].source_type is required")
        elif expected_source_type and source_type != expected_source_type:
            errors.append(f"items[{index}].source_type must match review input: {result_id}")

        entity_relation = normalize_whitespace(item.get("entity_relation"))
        if not entity_relation:
            errors.append(f"items[{index}].entity_relation is required")
        elif entity_relation not in ALLOWED_ENTITY_RELATIONS:
            errors.append(
                f"items[{index}].entity_relation must be one of: {', '.join(sorted(ALLOWED_ENTITY_RELATIONS))}"
            )

        evidence_ready = item.get("evidence_ready")
        should_read = item.get("should_read")
        if should_read is None:
            should_read = item.get("should_fetch")
        if not isinstance(evidence_ready, bool):
            errors.append(f"items[{index}].evidence_ready must be boolean")
        if not isinstance(should_read, bool):
            errors.append(f"items[{index}].should_read must be boolean")
        read_url = normalize_whitespace(item.get("read_url") or item.get("fetch_url"))
        if should_read is True and not read_url:
            errors.append(f"items[{index}].read_url is required when should_read=true")

        extracted = item.get("extracted")
        if not isinstance(extracted, dict):
            errors.append(f"items[{index}].extracted must be an object")
            extracted = {}
        if item.get("is_relevant") is True:
            if not normalize_whitespace(extracted.get("name")):
                errors.append(f"items[{index}].extracted.name is required when is_relevant=true")
            if entity_relation == "poi_body":
                if evidence_ready is not True:
                    errors.append(f"items[{index}].evidence_ready must be true when entity_relation=poi_body")
            elif evidence_ready is True:
                errors.append(f"items[{index}].evidence_ready can only be true when entity_relation=poi_body")
        elif evidence_ready is True:
            errors.append(f"items[{index}].evidence_ready cannot be true when is_relevant=false")

        item_by_id[result_id] = item

    expected_ids = set(catalog.keys())
    actual_ids = set(item_by_id.keys())
    missing_ids = sorted(expected_ids - actual_ids)
    extra_ids = sorted(actual_ids - expected_ids)
    if missing_ids:
        errors.append(f"websearch review seed is missing result ids: {', '.join(missing_ids)}")
    if extra_ids:
        errors.append(f"websearch review seed contains unknown result ids: {', '.join(extra_ids)}")

    if errors:
        raise ValueError("\n".join(errors))

    return {
        "status": "ok",
        "result_count": len(expected_ids),
        "relevant_count": sum(1 for item in item_by_id.values() if item.get("is_relevant") is True),
        "read_count": sum(
            1
            for item in item_by_id.values()
            if (item.get("should_read") if item.get("should_read") is not None else item.get("should_fetch")) is True
        ),
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-WebSearchReviewInputPath", required=True)
    parser.add_argument("-ReviewSeedPath", required=True)
    args = parser.parse_args()

    review_input = read_json_file(args.WebSearchReviewInputPath)
    review_seed = read_json_file(args.ReviewSeedPath)
    if not isinstance(review_input, dict):
        raise ValueError("websearch review input must be an object")
    if not isinstance(review_seed, dict):
        raise ValueError("websearch review seed must be an object")

    result = validate_websearch_review_seed_against_catalog(
        build_catalog_from_review_input(review_input),
        review_seed,
    )
    result["summary_text"] = f"websearch review seed 校验通过：共 {result['result_count']} 条候选。"
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
