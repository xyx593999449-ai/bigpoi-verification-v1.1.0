#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ALLOWED_DECISION_STATUS = {"accepted", "downgraded", "manual_review", "rejected"}
ALLOWED_RECORD_STATUS = {"verified", "modified", "rejected", "manual_review_pending"}


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def read_json_file(path: str | Path) -> Any:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError(f"JSON file is empty: {file_path}")
    return json.loads(raw)


def write_json_file(data: Any, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_input(poi: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(poi)
    if "id" not in normalized and normalized.get("poi_id"):
        normalized["id"] = str(normalized["poi_id"])
    if "coordinates" not in normalized and normalized.get("x_coord") is not None and normalized.get("y_coord") is not None:
        normalized["coordinates"] = {
            "longitude": float(normalized["x_coord"]),
            "latitude": float(normalized["y_coord"]),
            "coordinate_system": "GCJ02",
        }
    return normalized


def is_iso_time(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_basic_input(poi: dict[str, Any]) -> None:
    for field in ("id", "name", "poi_type", "city"):
        if not str(poi.get(field) or "").strip():
            raise ValueError(f"input.{field} is required")
    if not re.fullmatch(r"\d{6}", str(poi["poi_type"])):
        raise ValueError("input.poi_type must be a 6-digit code")


def validate_basic_evidence(evidence: Any, poi_id: str) -> None:
    if not isinstance(evidence, list):
        raise ValueError("evidence must be an array")
    if not evidence:
        raise ValueError("evidence array cannot be empty")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise ValueError(f"evidence[{index}] must be an object")
        for field in ("evidence_id", "poi_id", "source", "collected_at", "data"):
            if field not in item:
                raise ValueError(f"evidence[{index}].{field} is required")
        if str(item["poi_id"]) != poi_id:
            raise ValueError(f"evidence[{index}].poi_id must match input id")


def validate_basic_decision(decision: dict[str, Any], poi_id: str) -> None:
    for field in ("decision_id", "poi_id", "overall", "dimensions", "created_at"):
        if field not in decision:
            raise ValueError(f"decision.{field} is required")
    if str(decision["poi_id"]) != poi_id:
        raise ValueError("decision.poi_id must match input id")


def new_short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def get_best_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    best_item = None
    best_weight = -1.0
    for item in evidence:
        candidate = 0.0
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        if source.get("weight") is not None:
            candidate = float(source["weight"])
        if candidate > best_weight:
            best_item = item
            best_weight = candidate
    return best_item


def get_first_non_empty(values: list[Any]) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        if isinstance(value, dict) and not value:
            continue
        return value
    return None


def get_decision_record_status(status: str) -> str:
    mapping = {
        "accepted": "verified",
        "downgraded": "modified",
        "manual_review": "manual_review_pending",
        "rejected": "rejected",
    }
    return mapping.get(status, "manual_review_pending")


def build_record(input_data: dict[str, Any], evidence: list[dict[str, Any]], decision: dict[str, Any], timestamp: str) -> dict[str, Any]:
    poi_id = str(input_data["id"])
    best = get_best_evidence(evidence) or {}
    best_data = best.get("data") if isinstance(best.get("data"), dict) else {}
    corrections = decision.get("corrections") if isinstance(decision.get("corrections"), dict) else {}
    dimensions = decision["dimensions"]
    created_at = utc_iso_now()
    run_id = str(decision.get("run_id") or "").strip()

    coordinate_candidates = []
    if isinstance(corrections.get("coordinates"), dict):
        coordinate_candidates.append(corrections["coordinates"].get("suggested"))
    if input_data.get("coordinates") is not None:
        coordinate_candidates.append(input_data["coordinates"])
    if best_data.get("coordinates") is not None:
        coordinate_candidates.append(best_data["coordinates"])
    coordinates_source = get_first_non_empty(coordinate_candidates)

    name_candidates = []
    if isinstance(corrections.get("name"), dict):
        name_candidates.append(corrections["name"].get("suggested"))
    name_candidates.append(input_data["name"])
    if best_data.get("name") is not None:
        name_candidates.append(best_data["name"])

    address_candidates = []
    if isinstance(corrections.get("address"), dict):
        address_candidates.append(corrections["address"].get("suggested"))
    if input_data.get("address") is not None:
        address_candidates.append(input_data["address"])
    if best_data.get("address") is not None:
        address_candidates.append(best_data["address"])

    category_candidates = []
    if isinstance(corrections.get("category"), dict):
        category_candidates.append(corrections["category"].get("suggested"))
    category_candidates.append(input_data["poi_type"])

    final_coordinates: dict[str, Any] = {}
    if isinstance(coordinates_source, dict):
        if coordinates_source.get("longitude") is not None:
            final_coordinates["longitude"] = float(coordinates_source["longitude"])
        if coordinates_source.get("latitude") is not None:
            final_coordinates["latitude"] = float(coordinates_source["latitude"])

    name_confidence = float(dimensions.get("name", {}).get("confidence", 0.0))
    location_confidence = float(dimensions.get("location", {}).get("confidence", 0.0))
    category_confidence = float(dimensions.get("category", {}).get("confidence", 0.0))
    city_confidence = float(dimensions.get("administrative", {}).get("confidence", 1.0))
    final_coordinates["confidence"] = location_confidence

    final_name = str(get_first_non_empty(name_candidates) or "")
    final_address = str(get_first_non_empty(address_candidates) or "")
    final_category = str(get_first_non_empty(category_candidates) or "")

    changes = []
    for field in ("name", "address", "coordinates", "category"):
        correction = corrections.get(field)
        if not isinstance(correction, dict):
            continue
        old_value = correction.get("original")
        new_value = correction.get("suggested")
        if old_value is None and new_value is None:
            continue
        dimension_field = "location" if field == "coordinates" else field
        changes.append(
            {
                "field": field,
                "old_value": json.dumps(old_value, ensure_ascii=False, separators=(",", ":")) if isinstance(old_value, dict) else str(old_value),
                "new_value": json.dumps(new_value, ensure_ascii=False, separators=(",", ":")) if isinstance(new_value, dict) else str(new_value),
                "reason": f"derived from decision.dimensions.{dimension_field}",
            }
        )

    evidence_refs = [str(item.get("evidence_id", "")) for item in evidence]
    data_sources = sorted(
        {
            str(item["source"]["source_id"])
            for item in evidence
            if isinstance(item.get("source"), dict) and str(item["source"].get("source_id") or "").strip()
        }
    )
    source_types = sorted(
        {
            str(item["source"]["source_type"])
            for item in evidence
            if isinstance(item.get("source"), dict) and str(item["source"].get("source_type") or "").strip()
        }
    )
    valid_confidences = [
        float(item["verification"]["confidence"])
        for item in evidence
        if isinstance(item.get("verification"), dict) and item["verification"].get("confidence") is not None
    ]
    evidence_quality = round(sum(valid_confidences) / len(valid_confidences), 4) if valid_confidences else 0.0

    record = {
        "record_id": f"REC_{timestamp}_{new_short_hash(f'{poi_id}|{timestamp}|record')}",
        "poi_id": poi_id,
        "run_id": run_id,
        "input_data": {
            "name": str(input_data["name"]),
            "poi_type": str(input_data["poi_type"]),
            "city": str(input_data["city"]),
        },
        "verification_result": {
            "status": get_decision_record_status(str(decision["overall"]["status"])),
            "confidence": float(decision["overall"]["confidence"]),
            "final_values": {
                "name": final_name,
                "name_confidence": name_confidence,
                "address": final_address,
                "address_confidence": name_confidence,
                "coordinates": final_coordinates,
                "category": final_category,
                "category_confidence": category_confidence,
                "city": str(input_data["city"]),
                "city_confidence": city_confidence,
            },
            "changes": changes,
        },
        "decision_ref": str(decision["decision_id"]),
        "evidence_refs": evidence_refs,
        "audit_trail": {
            "created_by": "bigpoi-verification",
            "created_at": created_at,
            "version_history": [
                {
                    "version": "1.6.0",
                    "timestamp": created_at,
                    "operator": "bigpoi-verification",
                    "action": "bundle_output",
                }
            ],
        },
        "quality_metrics": {
            "dimension_scores": {},
            "evidence_quality": evidence_quality,
            "source_diversity": round(len(source_types) / 5.0, 4),
        },
        "flags": {
            "is_sensitive": False,
            "is_disputed": any(dimension.get("result") == "uncertain" for dimension in dimensions.values() if isinstance(dimension, dict)),
            "requires_periodic_review": str(decision["overall"]["status"]) != "accepted",
            "review_period_days": 365 if str(decision["overall"]["status"]) == "accepted" else 30,
            "tags": [
                "contract:1.6.0",
                f"status:{decision['overall']['status']}",
                f"poi_type:{input_data['poi_type']}",
            ],
        },
        "metadata": {
            "skill_version": "1.6.0",
            "processing_time_ms": int(decision.get("processing_duration_ms", 0)),
            "data_sources": data_sources,
            "rules_applied": [f"{name}_dimension" for name in dimensions.keys()],
            "custom_fields": {
                "task_id": str(input_data.get("task_id") or ""),
                "contract_version": "1.6.0",
                "run_id": run_id,
            },
        },
        "created_at": created_at,
        "updated_at": created_at,
    }

    if input_data.get("address") is not None:
        record["input_data"]["address"] = input_data["address"]
    if input_data.get("coordinates") is not None:
        record["input_data"]["coordinates"] = input_data["coordinates"]
    if input_data.get("source") is not None:
        record["input_data"]["source"] = input_data["source"]
    if input_data.get("city_adcode") is not None:
        record["input_data"]["city_adcode"] = str(input_data["city_adcode"])
        record["verification_result"]["final_values"]["city_adcode"] = str(input_data["city_adcode"])

    for dimension_name, dimension in dimensions.items():
        if isinstance(dimension, dict):
            record["quality_metrics"]["dimension_scores"][dimension_name] = float(dimension.get("score", dimension.get("confidence", 0.0)))

    if record["flags"]["requires_periodic_review"]:
        expires_at = datetime.now(timezone.utc) + timedelta(days=int(record["flags"]["review_period_days"]))
        record["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    return record


def test_bundle_name(name: str, prefix: str) -> bool:
    return bool(re.fullmatch(rf"{re.escape(prefix)}_\d{{8}}T\d{{6}}Z\.json", name))


def find_latest_index(task_dir: str | Path) -> dict[str, Any] | None:
    files = sorted(Path(task_dir).glob("index_*.json"), key=lambda item: item.name, reverse=True)
    if not files:
        return None
    return {
        "latest": str(files[0]),
        "all": [str(path) for path in files],
    }

def prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            pruned = prune_empty(item)
            if pruned is None:
                continue
            result[key] = pruned
        return result or None
    if isinstance(value, list):
        result = []
        for item in value:
            pruned = prune_empty(item)
            if pruned is None:
                continue
            result.append(pruned)
        return result or None
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value
