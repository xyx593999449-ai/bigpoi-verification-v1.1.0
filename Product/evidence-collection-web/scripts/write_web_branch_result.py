#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from run_context import attach_context, get_context
from evidence_collection_common import ensure_stdout_utf8, utc_iso_now, write_json_file


def read_json_optional(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload
    return None


def read_created_at(*contexts: Optional[Dict[str, Any]]) -> Optional[str]:
    for context in contexts:
        if not isinstance(context, dict):
            continue
        value = str(context.get("created_at") or "").strip()
        if value:
            return value
    return None


def resolve_path(candidate: Optional[str], fallback: Path) -> Optional[str]:
    if candidate:
        path = Path(candidate)
        if path.exists():
            return str(path.resolve())
    if fallback.exists():
        return str(fallback.resolve())
    return None


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-ProcessDir", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    parser.add_argument("-PoiId")
    parser.add_argument("-WebSearchReviewedPath")
    parser.add_argument("-WebReaderReviewedPath")
    parser.add_argument("-WebSearchReviewSeedPath")
    parser.add_argument("-WebReaderReviewSeedPath")
    args = parser.parse_args()

    process_dir = Path(args.ProcessDir).resolve()
    output_path = Path(args.OutputPath).resolve()
    process_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    default_websearch_reviewed = process_dir / "websearch-reviewed.json"
    default_webreader_reviewed = process_dir / "webreader-reviewed.json"
    default_websearch_seed = process_dir / "websearch-review-seed.json"
    default_webreader_seed = process_dir / "webreader-review-seed.json"

    websearch_reviewed_path = resolve_path(args.WebSearchReviewedPath, default_websearch_reviewed)
    webreader_reviewed_path = resolve_path(args.WebReaderReviewedPath, default_webreader_reviewed)
    websearch_seed_path = resolve_path(args.WebSearchReviewSeedPath, default_websearch_seed)
    webreader_seed_path = resolve_path(args.WebReaderReviewSeedPath, default_webreader_seed)

    websearch_payload = read_json_optional(Path(websearch_reviewed_path)) if websearch_reviewed_path else None
    webreader_payload = read_json_optional(Path(webreader_reviewed_path)) if webreader_reviewed_path else None

    websearch_status = str((websearch_payload or {}).get("status") or "").strip().lower()
    webreader_status = str((webreader_payload or {}).get("status") or "").strip().lower()

    websearch_merge_input_path = websearch_reviewed_path if websearch_payload and "reviewed_at" in websearch_payload else None
    webreader_merge_input_path = webreader_reviewed_path if webreader_payload and "reviewed_at" in webreader_payload else None

    if websearch_merge_input_path or webreader_merge_input_path:
        status = "ok"
    elif websearch_status in {"empty", "skipped"} and webreader_status in {"", "empty", "skipped"}:
        status = "empty"
    elif webreader_status in {"empty", "skipped"} and websearch_status in {"", "empty", "skipped"}:
        status = "empty"
    else:
        status = "error"

    websearch_context = get_context(websearch_payload) if websearch_payload else None
    webreader_context = get_context(webreader_payload) if webreader_payload else None
    resolved_run_id = str(args.RunId or (websearch_context or {}).get("run_id") or (webreader_context or {}).get("run_id") or "").strip()
    resolved_poi_id = str(args.PoiId or (websearch_context or {}).get("poi_id") or (webreader_context or {}).get("poi_id") or "").strip()
    resolved_task_id = str(args.TaskId or (websearch_context or {}).get("task_id") or (webreader_context or {}).get("task_id") or "").strip()
    created_at = read_created_at(websearch_context, webreader_context) or utc_iso_now()

    output: Dict[str, Any] = {
        "status": status,
        "branch": "web",
        "run_id": resolved_run_id,
        "task_id": resolved_task_id,
        "poi_id": resolved_poi_id,
        "created_at": created_at,
        "websearch_reviewed_path": websearch_reviewed_path,
        "webreader_reviewed_path": webreader_reviewed_path,
        "websearch_review_seed_path": websearch_seed_path,
        "webreader_review_seed_path": webreader_seed_path,
        "websearch_merge_input_path": websearch_merge_input_path,
        "webreader_merge_input_path": webreader_merge_input_path,
        "summary_text": (
            f"web 分支汇总完成: status={status}, "
            f"websearch={websearch_status or 'missing'}, "
            f"webreader={webreader_status or 'missing'}"
        ),
    }
    if resolved_run_id and resolved_poi_id:
        output = attach_context(
            output,
            resolved_run_id,
            resolved_poi_id,
            task_id=resolved_task_id or None,
            created_at=created_at,
        )
    write_json_file(output, output_path)

    result = {
        "status": output["status"],
        "result_path": str(output_path),
        "run_id": resolved_run_id,
        "task_id": resolved_task_id,
        "websearch_merge_input_path": websearch_merge_input_path,
        "webreader_merge_input_path": webreader_merge_input_path,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if status in {"ok", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

