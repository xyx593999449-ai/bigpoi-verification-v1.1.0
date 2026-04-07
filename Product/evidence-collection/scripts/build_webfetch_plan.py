#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_context import attach_context, get_context
from evidence_collection_common import ensure_stdout_utf8, get_generic_items, normalize_whitespace, read_json_file, utc_iso_now, write_json_file


def log_progress(message: str) -> None:
    sys.stderr.write(f"[build-webfetch-plan] {message}\n")
    sys.stderr.flush()


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-WebSearchReviewedPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    reviewed_payload = read_json_file(args.WebSearchReviewedPath)
    if not isinstance(reviewed_payload, dict):
        raise ValueError("websearch reviewed payload must be an object")

    payload_context = get_context(reviewed_payload) or {}
    resolved_run_id = str(args.RunId or payload_context.get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or payload_context.get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or payload_context.get("task_id") or "").strip()

    fetch_targets = []
    for index, item in enumerate(get_generic_items(reviewed_payload)):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        fetch_url = normalize_whitespace(metadata.get("read_url") or metadata.get("fetch_url") or item.get("source", {}).get("source_url"))
        should_fetch = bool(metadata.get("should_read") if metadata.get("should_read") is not None else metadata.get("should_fetch")) and bool(fetch_url)
        if not should_fetch:
            continue
        fetch_targets.append(
            {
                "fetch_id": f"FETCH_{index + 1:03d}",
                "source_url": fetch_url,
                "source_type": item.get("source", {}).get("source_type"),
                "source_name": item.get("source", {}).get("source_name"),
                "enhances_result_id": metadata.get("result_id"),
            }
        )

    output = {
        "status": "ok" if fetch_targets else "empty",
        "generated_at": utc_iso_now(),
        "fetch_targets": fetch_targets,
        "fallback_policy": "websearch_reviewed_can_continue_when_webfetch_missing_or_failed",
    }
    if resolved_run_id and resolved_poi_id:
        output = attach_context(output, resolved_run_id, resolved_poi_id, task_id=resolved_task_id or None)
    write_json_file(output, args.OutputPath)

    result = {
        "status": output["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "fetch_target_count": len(fetch_targets),
        "summary_text": f"webfetch 计划生成完成：待抓取 {len(fetch_targets)} 条；webfetch 失败时继续使用 websearch-reviewed。"
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
