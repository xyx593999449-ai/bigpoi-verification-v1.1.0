#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_context import attach_context, get_context
from evidence_collection_common import (
    ensure_stdout_utf8,
    get_generic_items,
    normalize_url_for_matching,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)


def log_progress(message: str) -> None:
    sys.stderr.write(f"[build-webreader-plan] {message}\n")
    sys.stderr.flush()


def _normalize_direct_read_targets(web_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    sources = web_plan.get("direct_read_sources") if isinstance(web_plan.get("direct_read_sources"), list) else []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_url = normalize_whitespace(source.get("source_url"))
        if not source_url:
            continue
        read_intents = source.get("read_intents")
        result.append(
            {
                "source_url": source_url,
                "source_name": source.get("source_name"),
                "source_type": source.get("source_type"),
                "read_reason": "direct_read",
                "read_intents": read_intents if isinstance(read_intents, list) else None,
                "enhances_result_id": None,
            }
        )
    return result


def _normalize_search_read_targets(websearch_reviewed: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in get_generic_items(websearch_reviewed):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        should_read = bool(metadata.get("should_read") if metadata.get("should_read") is not None else metadata.get("should_fetch"))
        read_url = normalize_whitespace(metadata.get("read_url") or metadata.get("fetch_url") or source.get("source_url"))
        if not should_read or not read_url:
            continue
        read_intents = metadata.get("read_intents")
        result.append(
            {
                "source_url": read_url,
                "source_name": source.get("source_name"),
                "source_type": source.get("source_type"),
                "read_reason": "search_followup",
                "read_intents": read_intents if isinstance(read_intents, list) else None,
                "enhances_result_id": metadata.get("result_id"),
            }
        )
    return result


def _dedupe_targets(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for target in targets:
        url = normalize_whitespace(target.get("source_url"))
        canonical_url = normalize_url_for_matching(url)
        if not canonical_url or canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        deduped.append(target)
    return deduped


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-WebPlanPath")
    parser.add_argument("-WebSearchReviewedPath")
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    if not args.WebPlanPath and not args.WebSearchReviewedPath:
        raise ValueError("at least one of -WebPlanPath or -WebSearchReviewedPath is required")

    web_plan: Dict[str, Any] = {}
    plan_context: Dict[str, Any] = {}
    if args.WebPlanPath:
        payload = read_json_file(args.WebPlanPath)
        if not isinstance(payload, dict):
            raise ValueError("web plan payload must be an object")
        web_plan = payload
        plan_context = get_context(payload) or {}

    websearch_reviewed: Dict[str, Any] = {}
    reviewed_context: Dict[str, Any] = {}
    if args.WebSearchReviewedPath:
        payload = read_json_file(args.WebSearchReviewedPath)
        if not isinstance(payload, dict):
            raise ValueError("websearch reviewed payload must be an object")
        websearch_reviewed = payload
        reviewed_context = get_context(payload) or {}

    resolved_run_id = str(args.RunId or reviewed_context.get("run_id") or plan_context.get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or reviewed_context.get("poi_id") or plan_context.get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or reviewed_context.get("task_id") or plan_context.get("task_id") or "").strip()

    direct_targets = _normalize_direct_read_targets(web_plan)
    followup_targets = _normalize_search_read_targets(websearch_reviewed)
    merged_targets = _dedupe_targets([*direct_targets, *followup_targets])

    read_targets: List[Dict[str, Any]] = []
    for index, target in enumerate(merged_targets):
        read_targets.append(
            {
                "read_id": f"READ_{index + 1:03d}",
                "source_url": target["source_url"],
                "source_name": target.get("source_name"),
                "source_type": target.get("source_type"),
                "read_reason": target.get("read_reason"),
                "read_intents": target.get("read_intents"),
                "enhances_result_id": target.get("enhances_result_id"),
            }
        )

    output = {
        "status": "ok" if read_targets else "empty",
        "generated_at": utc_iso_now(),
        "read_targets": read_targets,
        "read_target_count": len(read_targets),
        "fallback_policy": "websearch_reviewed_can_continue_when_webreader_missing_or_failed",
    }
    if resolved_run_id and resolved_poi_id:
        output = attach_context(output, resolved_run_id, resolved_poi_id, task_id=resolved_task_id or None)
    write_json_file(output, args.OutputPath)

    result = {
        "status": output["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "read_target_count": len(read_targets),
        "direct_read_count": len([item for item in read_targets if item.get("read_reason") == "direct_read"]),
        "followup_read_count": len([item for item in read_targets if item.get("read_reason") == "search_followup"]),
        "summary_text": (
            f"webreader 计划生成完成：待读取 {len(read_targets)} 条，"
            f"其中 direct_read={len([item for item in read_targets if item.get('read_reason') == 'direct_read'])}，"
            f"search_followup={len([item for item in read_targets if item.get('read_reason') == 'search_followup'])}。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
