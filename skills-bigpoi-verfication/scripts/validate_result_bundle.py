#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bundle_common import (
    ALLOWED_DECISION_STATUS,
    ALLOWED_RECORD_STATUS,
    ensure_stdout_utf8,
    find_latest_index,
    is_iso_time,
    read_json_file,
    test_bundle_name,
)


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def add_warning(warnings: list[str], message: str) -> None:
    warnings.append(message)


def validate_decision(decision: dict, poi_id: str, errors: list[str]) -> None:
    for field in ("decision_id", "poi_id", "overall", "dimensions", "created_at"):
        if field not in decision:
            add_error(errors, f"decision.{field} is required")
    if "poi_id" in decision and str(decision["poi_id"]) != poi_id:
        add_error(errors, "decision.poi_id must match record.poi_id")
    if "created_at" in decision and not is_iso_time(str(decision["created_at"])):
        add_error(errors, "decision.created_at must be ISO datetime")
    overall = decision.get("overall")
    if overall is not None:
        if not isinstance(overall, dict):
            add_error(errors, "decision.overall must be an object")
        else:
            for field in ("status", "confidence"):
                if field not in overall:
                    add_error(errors, f"decision.overall.{field} is required")
            if overall.get("status") not in ALLOWED_DECISION_STATUS:
                add_error(errors, "decision.overall.status is invalid")
    dimensions = decision.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, dict):
            add_error(errors, "decision.dimensions must be an object")
        else:
            for field in ("existence", "name", "location", "category"):
                if field not in dimensions:
                    add_error(errors, f"decision.dimensions.{field} is required")


def validate_evidence(evidence, poi_id: str, errors: list[str]) -> None:
    if not isinstance(evidence, list):
        add_error(errors, "evidence must be an array")
        return
    if not evidence:
        add_error(errors, "evidence array cannot be empty")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            add_error(errors, f"evidence[{index}] must be an object")
            continue
        for field in ("evidence_id", "poi_id", "source", "collected_at", "data"):
            if field not in item:
                add_error(errors, f"evidence[{index}].{field} is required")
        if "poi_id" in item and str(item["poi_id"]) != poi_id:
            add_error(errors, f"evidence[{index}].poi_id must match record.poi_id")
        if "collected_at" in item and not is_iso_time(str(item["collected_at"])):
            add_error(errors, f"evidence[{index}].collected_at must be ISO datetime")
        source = item.get("source")
        if source is not None:
            if not isinstance(source, dict):
                add_error(errors, f"evidence[{index}].source must be an object")
            else:
                for field in ("source_id", "source_name", "source_type"):
                    if field not in source:
                        add_error(errors, f"evidence[{index}].source.{field} is required")
        data = item.get("data")
        if data is not None:
            if not isinstance(data, dict):
                add_error(errors, f"evidence[{index}].data must be an object")
            elif "name" not in data:
                add_error(errors, f"evidence[{index}].data.name is required")


def validate_record(record: dict, errors: list[str]) -> None:
    for field in ("record_id", "poi_id", "input_data", "verification_result", "audit_trail", "created_at"):
        if field not in record:
            add_error(errors, f"record.{field} is required")
    for field in ("created_at", "updated_at", "expires_at"):
        if record.get(field) and not is_iso_time(str(record[field])):
            add_error(errors, f"record.{field} must be ISO datetime")
    verification_result = record.get("verification_result")
    if verification_result is not None:
        if not isinstance(verification_result, dict):
            add_error(errors, "record.verification_result must be an object")
        else:
            for field in ("status", "confidence", "final_values"):
                if field not in verification_result:
                    add_error(errors, f"record.verification_result.{field} is required")
            if verification_result.get("status") not in ALLOWED_RECORD_STATUS:
                add_error(errors, "record.verification_result.status is invalid")
            final_values = verification_result.get("final_values")
            if final_values is not None:
                if not isinstance(final_values, dict):
                    add_error(errors, "record.verification_result.final_values must be an object")
                else:
                    for field in ("name", "address", "coordinates", "category", "city"):
                        if field not in final_values:
                            add_error(errors, f"record.verification_result.final_values.{field} is required")
    audit_trail = record.get("audit_trail")
    if audit_trail is not None:
        if not isinstance(audit_trail, dict):
            add_error(errors, "record.audit_trail must be an object")
        else:
            for field in ("created_by", "created_at"):
                if field not in audit_trail:
                    add_error(errors, f"record.audit_trail.{field} is required")


def validate_index(index: dict, task_dir: Path, poi_id: str, task_id: str, errors: list[str]) -> None:
    for field in ("poi_id", "task_id", "created_at", "task_dir", "files", "description"):
        if field not in index:
            add_error(errors, f"index.{field} is required")
    if "poi_id" in index and str(index["poi_id"]) != poi_id:
        add_error(errors, "index.poi_id must match record.poi_id")
    if "task_id" in index and str(index["task_id"]) != task_id:
        add_error(errors, "index.task_id must match task directory name")
    if "created_at" in index and not is_iso_time(str(index["created_at"])):
        add_error(errors, "index.created_at must be ISO datetime")
    if "task_dir" in index and str(index["task_dir"]) != f"output/results/{task_id}":
        add_error(errors, "index.task_dir must match output/results/{task_id}")
    files = index.get("files")
    if files is not None:
        if not isinstance(files, dict):
            add_error(errors, "index.files must be an object")
        else:
            for field in ("decision", "evidence", "record"):
                if field not in files:
                    add_error(errors, f"index.files.{field} is required")
                    continue
                file_path = Path(str(files[field]))
                if not file_path.is_absolute():
                    add_error(errors, f"index.files.{field} must be an absolute path")
                    continue
                if not file_path.is_file():
                    add_error(errors, f"index.files.{field} points to a missing file")
                    continue
                if not test_bundle_name(file_path.name, field):
                    add_error(errors, f"index.files.{field} points to an invalid filename")
                if file_path.resolve().parent != task_dir.resolve():
                    add_error(errors, f"index.files.{field} must stay inside the task directory")


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-TaskDir", required=True)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    task_dir = Path(args.TaskDir)

    if not task_dir.is_dir():
        errors.append(f"task_dir does not exist: {task_dir}")
        json.dump(
            {
                "status": "failed",
                "failed_stage": "parent_integration",
                "reasons": errors,
                "warnings": warnings,
                "retry_action": "rerun only parent bundle writer, then rerun validator",
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    resolved_task_dir = task_dir.resolve()
    task_id = resolved_task_dir.name
    index_info = find_latest_index(resolved_task_dir)
    if index_info is None:
        errors.append("task_dir does not contain index_*.json")
        json.dump(
            {
                "status": "failed",
                "failed_stage": "parent_integration",
                "reasons": errors,
                "warnings": warnings,
                "retry_action": "rerun only parent bundle writer, then rerun validator",
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    if len(index_info["all"]) > 1:
        add_warning(warnings, "task_dir contains multiple index files; validated only the latest bundle")

    index_path = Path(index_info["latest"])
    if not test_bundle_name(index_path.name, "index"):
        add_error(errors, "latest index filename is invalid")

    index = read_json_file(index_path)
    if not isinstance(index, dict):
        errors.append("index file must contain an object")
        json.dump(
            {
                "status": "failed",
                "failed_stage": "parent_integration",
                "reasons": errors,
                "warnings": warnings,
                "retry_action": "rerun only parent bundle writer, then rerun validator",
                "task_dir": str(resolved_task_dir),
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    files = index.get("files") if isinstance(index.get("files"), dict) else {}
    decision_path = Path(str(files.get("decision", ""))) if files.get("decision") else None
    evidence_path = Path(str(files.get("evidence", ""))) if files.get("evidence") else None
    record_path = Path(str(files.get("record", ""))) if files.get("record") else None

    record = read_json_file(record_path) if record_path and record_path.is_file() else None
    if not isinstance(record, dict):
        errors.append("record file is missing or invalid")
        json.dump(
            {
                "status": "failed",
                "failed_stage": "parent_integration",
                "reasons": errors,
                "warnings": warnings,
                "retry_action": "rerun only parent bundle writer, then rerun validator",
                "task_dir": str(resolved_task_dir),
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    poi_id = str(record.get("poi_id") or "")
    validate_record(record, errors)

    if decision_path and decision_path.is_file():
        decision = read_json_file(decision_path)
        if isinstance(decision, dict):
            validate_decision(decision, poi_id, errors)
        else:
            errors.append("decision file must contain an object")
    else:
        errors.append("decision file is missing")

    if evidence_path and evidence_path.is_file():
        evidence = read_json_file(evidence_path)
        validate_evidence(evidence, poi_id, errors)
    else:
        errors.append("evidence file is missing")

    validate_index(index, resolved_task_dir, poi_id, task_id, errors)

    failed_stage = "complete"
    if any(message.startswith("evidence") for message in errors):
        failed_stage = "evidence_collection"
    elif any(message.startswith("decision") for message in errors):
        failed_stage = "verification"
    elif errors:
        failed_stage = "parent_integration"

    retry_action = {
        "evidence_collection": "rerun evidence collection, then rerun parent bundle writer and validator",
        "verification": "rerun verification output generation, then rerun parent bundle writer and validator",
        "parent_integration": "rerun only parent bundle writer, then rerun validator",
        "complete": "no retry required",
    }[failed_stage]

    result = {
        "status": "passed" if not errors else "failed",
        "failed_stage": failed_stage,
        "reasons": errors,
        "warnings": warnings,
        "retry_action": retry_action,
        "task_dir": str(resolved_task_dir),
        "task_id": task_id,
        "index_path": str(index_path),
        "files": {
            "decision": str(decision_path) if decision_path else "",
            "evidence": str(evidence_path) if evidence_path else "",
            "record": str(record_path) if record_path else "",
        },
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
