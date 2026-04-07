#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from run_context import attach_context, get_context
from evidence_collection_common import ensure_stdout_utf8, limit_text, normalize_input_poi, normalize_whitespace, read_json_file, utc_iso_now, write_json_file


def log_progress(message: str) -> None:
    sys.stderr.write(f"[prepare-webreader-review] {message}\n")
    sys.stderr.flush()


def build_result_id(index: int) -> str:
    return f"WR_{index + 1:03d}"


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-WebReaderRawPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    args = parser.parse_args()

    poi = normalize_input_poi(read_json_file(args.PoiPath))
    raw_payload = read_json_file(args.WebReaderRawPath)
    if not isinstance(raw_payload, dict):
        raise ValueError("webreader raw payload must be an object")

    raw_context = get_context(raw_payload) or {}
    resolved_run_id = str(args.RunId or raw_context.get("run_id") or "").strip()
    resolved_poi_id = str(raw_context.get("poi_id") or poi.get("id") or "").strip()
    resolved_task_id = str(args.TaskId or raw_context.get("task_id") or "").strip()
    items = raw_payload.get("items") if isinstance(raw_payload.get("items"), list) else []

    review_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        raw_page = item.get("raw_page") if isinstance(item.get("raw_page"), dict) else {}
        content = normalize_whitespace(raw_page.get("content"))
        if not content:
            continue
        review_items.append(
            {
                "result_id": build_result_id(index),
                "source": {
                    "source_id": source.get("source_id"),
                    "source_name": source.get("source_name"),
                    "source_type": source.get("source_type"),
                    "source_url": source.get("source_url"),
                },
                "candidate": {
                    "provider": item.get("provider"),
                    "page_title": raw_page.get("title"),
                    "page_description": raw_page.get("description"),
                    "content_excerpt": limit_text(content, 1200),
                    "read_reason": metadata.get("read_reason"),
                    "read_intents": metadata.get("read_intents"),
                    "enhances_result_id": metadata.get("enhances_result_id"),
                },
            }
        )

    output = {
        "status": "ok" if review_items else "empty",
        "generated_at": utc_iso_now(),
        "poi": {
            "id": str(poi.get("id")),
            "name": str(poi.get("name")),
            "city": str(poi.get("city")),
            "poi_type": str(poi.get("poi_type")),
        },
        "review_items": review_items,
        "summary": {
            "candidate_count": len(review_items),
            "raw_item_count": len(items),
            "failed_item_count": len(raw_payload.get("failed_items") or []),
        },
    }
    if resolved_run_id and resolved_poi_id:
        output = attach_context(output, resolved_run_id, resolved_poi_id, task_id=resolved_task_id or None)
    write_json_file(output, args.OutputPath)

    result = {
        "status": output["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "candidate_count": len(review_items),
        "summary_text": f"webreader review 输入准备完成：共 {len(review_items)} 条候选。",
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
