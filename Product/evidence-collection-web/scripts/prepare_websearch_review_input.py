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
from evidence_collection_common import (
    ensure_stdout_utf8,
    get_generic_items,
    normalize_input_poi,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)


def log_progress(message: str) -> None:
    sys.stderr.write(f"[prepare-websearch-review] {message}\n")
    sys.stderr.flush()


def build_result_id(index: int) -> str:
    return f"WEB_{index + 1:03d}"


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-WebSearchRawPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    args = parser.parse_args()

    poi = normalize_input_poi(read_json_file(args.PoiPath))
    raw_payload = read_json_file(args.WebSearchRawPath)
    if not isinstance(raw_payload, dict):
        raise ValueError("websearch raw payload must be an object")

    raw_context = get_context(raw_payload) or {}
    resolved_run_id = str(args.RunId or raw_context.get("run_id") or "").strip()
    resolved_task_id = str(args.TaskId or raw_context.get("task_id") or "").strip()

    review_items = []
    for index, item in enumerate(get_generic_items(raw_payload)):
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        review_items.append(
            {
                "result_id": build_result_id(index),
                "target_poi": {
                    "id": str(poi.get("id") or ""),
                    "name": str(poi.get("name") or ""),
                    "poi_type": str(poi.get("poi_type") or ""),
                    "city": str(poi.get("city") or ""),
                },
                "source": {
                    "source_name": source.get("source_name"),
                    "source_type": source.get("source_type"),
                    "source_url": source.get("source_url"),
                },
                "candidate": {
                    "name_hint": data.get("name"),
                    "address_hint": data.get("address"),
                    "phone_hint": data.get("phone"),
                    "page_title": metadata.get("page_title"),
                    "text_snippet": metadata.get("text_snippet"),
                    "source_domain": metadata.get("source_domain"),
                    "published_at": metadata.get("published_at"),
                    "provider": metadata.get("provider"),
                    "query": metadata.get("query"),
                },
            }
        )

    output = {
        "status": "ok",
        "prepared_at": utc_iso_now(),
        "poi": {
            "id": str(poi.get("id") or ""),
            "name": str(poi.get("name") or ""),
            "poi_type": str(poi.get("poi_type") or ""),
            "city": str(poi.get("city") or ""),
        },
        "review_items": review_items,
    }
    if resolved_run_id and normalize_whitespace(poi.get("id")):
        output = attach_context(output, resolved_run_id, str(poi["id"]), task_id=resolved_task_id or None)
    write_json_file(output, args.OutputPath)

    result = {
        "status": "ok",
        "result_path": str(Path(args.OutputPath).resolve()),
        "review_item_count": len(review_items),
        "summary_text": f"websearch review 输入准备完成：共 {len(review_items)} 条候选。",
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
