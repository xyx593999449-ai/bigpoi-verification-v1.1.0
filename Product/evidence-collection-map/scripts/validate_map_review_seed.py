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

from evidence_collection_common import ensure_stdout_utf8, normalize_whitespace, read_json_file
from prepare_map_review_input import build_candidate_key, extract_vendor_payloads


def log_progress(message: str) -> None:
    sys.stderr.write(f"[validate-map-review] {message}\n")
    sys.stderr.flush()


def build_candidate_catalog_from_prepared_input(prepared_input: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    vendors = prepared_input.get("vendors") if isinstance(prepared_input.get("vendors"), dict) else {}
    return {
        str(vendor): [candidate for candidate in payload.get("candidates", []) if isinstance(candidate, dict)]
        for vendor, payload in vendors.items()
        if isinstance(payload, dict)
    }


def build_candidate_catalog_from_raw_payload(raw_payload: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    catalog: Dict[str, List[Dict[str, Any]]] = {}
    for vendor, payload in extract_vendor_payloads(raw_payload).items():
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        catalog[vendor] = [
            {
                "candidate_key": build_candidate_key(item, index),
                "name": item.get("name"),
                "address": item.get("address"),
                "category": item.get("category"),
            }
            for index, item in enumerate(items)
            if isinstance(item, dict)
        ]
    return catalog


def extract_review_map(review_seed: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if isinstance(review_seed.get("vendors"), dict):
        return {str(key): value for key, value in review_seed["vendors"].items() if isinstance(value, dict)}
    if review_seed.get("vendor"):
        vendor = str(review_seed["vendor"])
        return {vendor: review_seed}
    raise ValueError("review seed must contain vendors or vendor")


def validate_map_review_seed_against_catalog(
    candidate_catalog: Dict[str, List[Dict[str, Any]]],
    review_seed: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    if str(review_seed.get("status") or "").strip() == "auto_generated":
        errors.append("map review seed cannot use auto_generated fallback output")

    try:
        review_map = extract_review_map(review_seed)
    except ValueError as exc:
        errors.append(str(exc))
        review_map = {}

    vendor_summary: Dict[str, Dict[str, int]] = {}
    for vendor, candidates in candidate_catalog.items():
        review_vendor = review_map.get(vendor)
        if review_vendor is None:
            if candidates:
                errors.append(f"review seed is missing vendor decisions: {vendor}")
            continue

        if any(str(item).strip() for item in review_vendor.get("keep_candidates", []) or []):
            errors.append(f"{vendor} review seed must use candidate_decisions for every candidate, not keep_candidates shortcuts")

        decisions = review_vendor.get("candidate_decisions")
        if candidates and not isinstance(decisions, list):
            errors.append(f"{vendor} review seed must contain candidate_decisions")
            continue
        decisions = decisions if isinstance(decisions, list) else []

        decision_by_key: Dict[str, Dict[str, Any]] = {}
        for index, decision in enumerate(decisions):
            if not isinstance(decision, dict):
                errors.append(f"{vendor}.candidate_decisions[{index}] must be an object")
                continue
            candidate_key = str(decision.get("candidate_key") or "").strip()
            if not candidate_key:
                errors.append(f"{vendor}.candidate_decisions[{index}].candidate_key is required")
                continue
            if candidate_key in decision_by_key:
                errors.append(f"{vendor}.candidate_decisions contains duplicate candidate_key: {candidate_key}")
                continue
            if not isinstance(decision.get("is_relevant"), bool):
                errors.append(f"{vendor}.candidate_decisions[{index}].is_relevant must be boolean")
            if not normalize_whitespace(decision.get("reason")):
                errors.append(f"{vendor}.candidate_decisions[{index}].reason is required")
            decision_by_key[candidate_key] = decision

        expected_keys = {str(candidate.get("candidate_key") or "").strip() for candidate in candidates if str(candidate.get("candidate_key") or "").strip()}
        actual_keys = set(decision_by_key.keys())
        missing_keys = sorted(expected_keys - actual_keys)
        extra_keys = sorted(actual_keys - expected_keys)
        if missing_keys:
            errors.append(f"{vendor} review seed is missing candidate decisions: {', '.join(missing_keys)}")
        if extra_keys:
            errors.append(f"{vendor} review seed contains unknown candidate keys: {', '.join(extra_keys)}")

        vendor_summary[vendor] = {
            "candidate_count": len(expected_keys),
            "decision_count": len(actual_keys),
        }

    if errors:
        raise ValueError("\n".join(errors))

    return {
        "status": "ok",
        "vendor_count": len(candidate_catalog),
        "candidate_count": sum(len(candidates) for candidates in candidate_catalog.values()),
        "vendor_summary": vendor_summary,
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-MapReviewInputPath", required=True)
    parser.add_argument("-ReviewSeedPath", required=True)
    args = parser.parse_args()

    prepared_input = read_json_file(args.MapReviewInputPath)
    review_seed = read_json_file(args.ReviewSeedPath)
    if not isinstance(prepared_input, dict):
        raise ValueError("map review input must be an object")
    if not isinstance(review_seed, dict):
        raise ValueError("review seed must be an object")

    result = validate_map_review_seed_against_catalog(
        build_candidate_catalog_from_prepared_input(prepared_input),
        review_seed,
    )
    result["summary_text"] = f"图商 review seed 校验通过：共 {result['candidate_count']} 条候选。"
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
