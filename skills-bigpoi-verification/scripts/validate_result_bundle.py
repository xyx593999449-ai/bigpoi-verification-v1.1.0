#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bundle_common import (
    ALLOWED_DECISION_STATUS,
    ALLOWED_RECORD_STATUS,
    CORRECTION_FIELDS,
    ensure_stdout_utf8,
    find_latest_index,
    is_iso_time,
    read_json_file,
    test_bundle_name,
)
from run_context import collect_item_run_ids
from runtime_paths import build_task_dir, detect_workspace_root


CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def add_warning(warnings: list[str], message: str) -> None:
    warnings.append(message)


def normalize_scalar_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_coordinate_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized = {}
    if value.get("longitude") is not None:
        normalized["longitude"] = float(value["longitude"])
    if value.get("latitude") is not None:
        normalized["latitude"] = float(value["latitude"])
    if value.get("coordinate_system"):
        normalized["coordinate_system"] = str(value["coordinate_system"])
    return normalized or None


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) or isinstance(right, dict):
        return json.dumps(left or {}, ensure_ascii=False, sort_keys=True) == json.dumps(right or {}, ensure_ascii=False, sort_keys=True)
    return normalize_scalar_value(left) == normalize_scalar_value(right)


def format_change_value(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if value is None:
        return ""
    return str(value)


def validate_corrections_structure(corrections: Any, errors: list[str]) -> dict[str, dict[str, Any]]:
    if corrections is None:
        return {}
    if not isinstance(corrections, dict):
        add_error(errors, "decision.corrections must be an object")
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for field, correction in corrections.items():
        if field not in CORRECTION_FIELDS:
            add_error(errors, f"decision.corrections.{field} is not supported")
            continue
        if not isinstance(correction, dict):
            add_error(errors, f"decision.corrections.{field} must be an object")
            continue
        if "suggested" not in correction:
            add_error(errors, f"decision.corrections.{field}.suggested is required")
            continue
        reason = str(correction.get("reason") or "").strip()
        if not reason:
            add_error(errors, f"decision.corrections.{field}.reason is required")
        original = correction.get("original")
        suggested = correction.get("suggested")
        if field == "coordinates":
            original = normalize_coordinate_value(original) if original is not None else None
            suggested = normalize_coordinate_value(suggested)
            if suggested is None:
                add_error(errors, "decision.corrections.coordinates.suggested must include longitude and latitude")
                continue
        else:
            original = normalize_scalar_value(original)
            suggested = normalize_scalar_value(suggested)
            if suggested is None:
                add_error(errors, f"decision.corrections.{field}.suggested cannot be empty")
                continue
        if field in {"category", "city_adcode"} and suggested is not None and not re.fullmatch(r"\d{6}", str(suggested)):
            add_error(errors, f"decision.corrections.{field}.suggested must be a 6-digit code")
        if values_equal(original, suggested):
            add_error(errors, f"decision.corrections.{field} must change the value")
            continue
        normalized_entry = {"original": original, "suggested": suggested, "reason": reason}
        confidence = correction.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
            if confidence < 0 or confidence > 1:
                add_error(errors, f"decision.corrections.{field}.confidence must be between 0 and 1")
            else:
                normalized_entry["confidence"] = confidence
        normalized[field] = normalized_entry
    return normalized


def validate_decision(decision: dict, poi_id: str, expected_run_id: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    for field in ("decision_id", "poi_id", "overall", "dimensions", "created_at"):
        if field not in decision:
            add_error(errors, f"decision.{field} is required")
    if "poi_id" in decision and str(decision["poi_id"]) != poi_id:
        add_error(errors, "decision.poi_id must match record.poi_id")
    if "created_at" in decision and not is_iso_time(str(decision["created_at"])):
        add_error(errors, "decision.created_at must be ISO datetime")
    run_id = str(decision.get("run_id") or "").strip()
    if not run_id:
        add_error(errors, "decision.run_id is required")
    elif expected_run_id and run_id != expected_run_id:
        add_error(errors, "decision.run_id must match bundle run_id")
    overall = decision.get("overall")
    if overall is not None:
        if not isinstance(overall, dict):
            add_error(errors, "decision.overall must be an object")
        else:
            for field in ("status", "confidence", "summary"):
                if field not in overall:
                    add_error(errors, f"decision.overall.{field} is required")
            if overall.get("status") not in ALLOWED_DECISION_STATUS:
                add_error(errors, "decision.overall.status is invalid")
            summary = str(overall.get("summary") or "").strip()
            if not summary:
                add_error(errors, "decision.overall.summary is required")
            elif not CJK_PATTERN.search(summary):
                add_error(errors, "decision.overall.summary must be Chinese text")
    dimensions = decision.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, dict):
            add_error(errors, "decision.dimensions must be an object")
        else:
            for field in ("existence", "name", "address", "coordinates", "category"):
                if field not in dimensions:
                    add_error(errors, f"decision.dimensions.{field} is required")
    return validate_corrections_structure(decision.get("corrections"), errors)


def validate_evidence(evidence, poi_id: str, expected_run_id: str, errors: list[str]) -> None:
    if not isinstance(evidence, list):
        add_error(errors, "evidence must be an array")
        return
    if not evidence:
        add_error(errors, "evidence array cannot be empty")
        return
    run_ids = collect_item_run_ids(evidence)
    if not run_ids:
        add_error(errors, "evidence.metadata.run_id is required for all items")
    elif expected_run_id and run_ids != {expected_run_id}:
        add_error(errors, "evidence item run_id must match bundle run_id")
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
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else None
        if metadata is None:
            add_error(errors, f"evidence[{index}].metadata is required")
        elif expected_run_id and str(metadata.get("run_id") or "").strip() != expected_run_id:
            add_error(errors, f"evidence[{index}].metadata.run_id must match bundle run_id")
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


def validate_record(record: dict, expected_run_id: str, errors: list[str]) -> None:
    for field in ("record_id", "poi_id", "input_data", "verification_result", "audit_trail", "created_at"):
        if field not in record:
            add_error(errors, f"record.{field} is required")
    for field in ("created_at", "updated_at", "expires_at"):
        if record.get(field) and not is_iso_time(str(record[field])):
            add_error(errors, f"record.{field} must be ISO datetime")
    run_id = str(record.get("run_id") or "").strip()
    if expected_run_id and run_id != expected_run_id:
        add_error(errors, "record.run_id must match bundle run_id")
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
            changes = verification_result.get("changes")
            if changes is not None and not isinstance(changes, list):
                add_error(errors, "record.verification_result.changes must be an array")
    audit_trail = record.get("audit_trail")
    if audit_trail is not None:
        if not isinstance(audit_trail, dict):
            add_error(errors, "record.audit_trail must be an object")
        else:
            for field in ("created_by", "created_at"):
                if field not in audit_trail:
                    add_error(errors, f"record.audit_trail.{field} is required")


def validate_record_alignment(record: dict, corrections: dict[str, dict[str, Any]], errors: list[str]) -> None:
    verification_result = record.get("verification_result") if isinstance(record.get("verification_result"), dict) else {}
    final_values = verification_result.get("final_values") if isinstance(verification_result.get("final_values"), dict) else {}
    changes = verification_result.get("changes") if isinstance(verification_result.get("changes"), list) else []
    change_by_field = {
        str(item.get("field") or ""): item
        for item in changes
        if isinstance(item, dict) and str(item.get("field") or "").strip()
    }

    final_map = {
        "name": final_values.get("name"),
        "address": final_values.get("address"),
        "coordinates": normalize_coordinate_value(final_values.get("coordinates")),
        "category": final_values.get("category"),
        "city": final_values.get("city"),
        "city_adcode": final_values.get("city_adcode"),
    }

    for field, correction in corrections.items():
        suggested = correction.get("suggested")
        current_value = final_map.get(field)
        if not values_equal(current_value, suggested):
            add_error(errors, f"record.verification_result.final_values.{field} must match decision.corrections.{field}.suggested")
            continue
        change = change_by_field.get(field)
        if not isinstance(change, dict):
            add_error(errors, f"record.verification_result.changes must include field {field}")
            continue
        if format_change_value(suggested) != str(change.get("new_value") or ""):
            add_error(errors, f"record.verification_result.changes[{field}].new_value must match decision correction")
        if str(change.get("reason") or "").strip() != str(correction.get("reason") or "").strip():
            add_error(errors, f"record.verification_result.changes[{field}].reason must match decision correction reason")


def validate_index(index: dict, task_dir: Path, workspace_root: Path, poi_id: str, task_id: str, expected_run_id: str, errors: list[str]) -> None:
    for field in ("poi_id", "task_id", "created_at", "task_dir", "files", "description"):
        if field not in index:
            add_error(errors, f"index.{field} is required")
    if "poi_id" in index and str(index["poi_id"]) != poi_id:
        add_error(errors, "index.poi_id must match record.poi_id")
    if "task_id" in index and str(index["task_id"]) != task_id:
        add_error(errors, "index.task_id must match task directory name")
    if expected_run_id:
        run_id = str(index.get("run_id") or "").strip()
        if run_id != expected_run_id:
            add_error(errors, "index.run_id must match bundle run_id")
    if "created_at" in index and not is_iso_time(str(index["created_at"])):
        add_error(errors, "index.created_at must be ISO datetime")
    expected_task_dir = build_task_dir(workspace_root, task_id).resolve()
    if task_dir.resolve() != expected_task_dir:
        add_error(errors, "task_dir must resolve under workspace_root/output/results/{task_id}")
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
    parser.add_argument("-WorkspaceRoot")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    task_dir = Path(args.TaskDir)

    if not task_dir.is_dir():
        errors.append(f"task_dir does not exist: {task_dir}")
        json.dump({"status": "failed", "failed_stage": "parent_integration", "reasons": errors, "warnings": warnings, "retry_action": "rerun only parent bundle writer, then rerun validator"}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    resolved_task_dir = task_dir.resolve()
    task_id = resolved_task_dir.name
    workspace_detection = detect_workspace_root(workspace_hint=args.WorkspaceRoot, related_paths=(resolved_task_dir,), cwd=Path.cwd())
    workspace_root = workspace_detection.workspace_root.resolve()
    index_info = find_latest_index(resolved_task_dir)
    if index_info is None:
        errors.append("task_dir does not contain index_*.json")
        json.dump({"status": "failed", "failed_stage": "parent_integration", "reasons": errors, "warnings": warnings, "retry_action": "rerun only parent bundle writer, then rerun validator"}, sys.stdout, ensure_ascii=False, indent=2)
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
        json.dump({"status": "failed", "failed_stage": "parent_integration", "reasons": errors, "warnings": warnings, "retry_action": "rerun only parent bundle writer, then rerun validator", "task_dir": str(resolved_task_dir)}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    files = index.get("files") if isinstance(index.get("files"), dict) else {}
    decision_path = Path(str(files.get("decision", ""))) if files.get("decision") else None
    evidence_path = Path(str(files.get("evidence", ""))) if files.get("evidence") else None
    record_path = Path(str(files.get("record", ""))) if files.get("record") else None

    record = read_json_file(record_path) if record_path and record_path.is_file() else None
    if not isinstance(record, dict):
        errors.append("record file is missing or invalid")
        json.dump({"status": "failed", "failed_stage": "parent_integration", "reasons": errors, "warnings": warnings, "retry_action": "rerun only parent bundle writer, then rerun validator", "task_dir": str(resolved_task_dir)}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    poi_id = str(record.get("poi_id") or "")
    bundle_run_id = str(index.get("run_id") or record.get("run_id") or "").strip()
    if not bundle_run_id:
        errors.append("bundle run_id is required in index or record")
    validate_record(record, bundle_run_id, errors)

    decision = None
    decision_corrections: dict[str, dict[str, Any]] = {}
    if decision_path and decision_path.is_file():
        decision = read_json_file(decision_path)
        if isinstance(decision, dict):
            decision_corrections = validate_decision(decision, poi_id, bundle_run_id, errors)
        else:
            errors.append("decision file must contain an object")
    else:
        errors.append("decision file is missing")

    if evidence_path and evidence_path.is_file():
        evidence = read_json_file(evidence_path)
        validate_evidence(evidence, poi_id, bundle_run_id, errors)
    else:
        errors.append("evidence file is missing")

    if isinstance(decision, dict):
        validate_record_alignment(record, decision_corrections, errors)
    validate_index(index, resolved_task_dir, workspace_root, poi_id, task_id, bundle_run_id, errors)

    failed_stage = "complete"
    if any(message.startswith("evidence") for message in errors):
        failed_stage = "evidence_collection"
    elif any(message.startswith("decision") or message.startswith("record.verification_result") for message in errors):
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
        "run_id": bundle_run_id,
        "workspace_root": str(workspace_root),
        "workspace_detection": {"strategy": workspace_detection.strategy, "matched_marker": workspace_detection.matched_marker, "start_path": str(workspace_detection.start_path)},
        "index_path": str(index_path),
        "files": {"decision": str(decision_path) if decision_path else "", "evidence": str(evidence_path) if evidence_path else "", "record": str(record_path) if record_path else ""},
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
