#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


ALLOWED_DECISION_STATUS = {"accepted", "downgraded", "manual_review", "rejected"}
ALLOWED_RECORD_STATUS = {"verified", "modified", "rejected", "manual_review_pending"}
CORRECTION_FIELDS = ("name", "address", "coordinates", "category", "city", "city_adcode")
ADDRESS_DETAIL_PATTERN = re.compile(r"(\d+|号|栋|楼|室|层|座|单元|路|街|巷|道|园|大厦|广场)")


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def read_json_file(path: Union[str, Path]) -> Any:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError(f"JSON file is empty: {file_path}")
    return json.loads(raw)


def write_json_file(data: Any, path: Union[str, Path]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8", newline="\n") as file_obj:
        file_obj.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


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


def get_best_evidence(evidence: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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


def normalize_scalar_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_coordinate_value(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, Any] = {}
    if value.get("longitude") is not None:
        normalized["longitude"] = float(value["longitude"])
    if value.get("latitude") is not None:
        normalized["latitude"] = float(value["latitude"])
    if value.get("coordinate_system"):
        normalized["coordinate_system"] = str(value["coordinate_system"])
    return normalized or None


def address_detail_score(value: Any) -> int:
    text = normalize_scalar_value(value)
    if text is None:
        return 0
    score = 1
    if re.search(r"\d", text):
        score += 2
    score += len(ADDRESS_DETAIL_PATTERN.findall(str(text)))
    return score


def get_preferred_evidence_address(evidence: List[Dict[str, Any]]) -> Optional[str]:
    best_address: Optional[str] = None
    best_priority: tuple[float, float, int, int] = (-1.0, -1.0, -1, -1)
    for item in evidence:
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        address = normalize_scalar_value(data.get("address"))
        if address is None:
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
        source_type = str(source.get("source_type") or "")
        source_priority = {
            "official": 3.0,
            "map_vendor": 2.0,
            "internet": 1.0,
        }.get(source_type, 0.0)
        weight = float(source.get("weight") or verification.get("confidence") or 0.0)
        detail = address_detail_score(address)
        confidence = int(round(float(verification.get("confidence") or 0.0) * 1000))
        priority = (source_priority, weight, detail, confidence)
        if priority > best_priority:
            best_priority = priority
            best_address = str(address)
    return best_address


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) or isinstance(right, dict):
        return json.dumps(left or {}, ensure_ascii=False, sort_keys=True) == json.dumps(right or {}, ensure_ascii=False, sort_keys=True)
    return normalize_scalar_value(left) == normalize_scalar_value(right)


def correction_value(corrections: dict[str, Any], field: str):
    correction = corrections.get(field)
    if isinstance(correction, dict):
        return correction.get("suggested")
    return None


def format_change_value(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if value is None:
        return ""
    return str(value)


def build_record(input_data: dict[str, Any], evidence: list[dict[str, Any]], decision: dict[str, Any], timestamp: str) -> dict[str, Any]:
    poi_id = str(input_data["id"])
    best = get_best_evidence(evidence) or {}
    best_data = best.get("data") if isinstance(best.get("data"), dict) else {}
    corrections = decision.get("corrections") if isinstance(decision.get("corrections"), dict) else {}
    dimensions = decision["dimensions"]
    created_at = utc_iso_now()
    run_id = str(decision.get("run_id") or "").strip()

    input_coordinates = normalize_coordinate_value(input_data.get("coordinates"))
    best_coordinates = normalize_coordinate_value(best_data.get("coordinates"))
    corrected_coordinates = normalize_coordinate_value(correction_value(corrections, "coordinates"))
    final_coordinates = get_first_non_empty([corrected_coordinates, input_coordinates, best_coordinates]) or {}
    preferred_evidence_address = get_preferred_evidence_address(evidence)
    address_result = str(dimensions.get("address", {}).get("result") or "")
    use_evidence_address = bool(preferred_evidence_address) and (
        normalize_scalar_value(input_data.get("address")) is None or address_result == "pass"
    )

    final_name = str(get_first_non_empty([
        normalize_scalar_value(correction_value(corrections, "name")),
        normalize_scalar_value(input_data.get("name")),
        normalize_scalar_value(best_data.get("name")),
    ]) or "")
    final_address = str(get_first_non_empty([
        normalize_scalar_value(correction_value(corrections, "address")),
        normalize_scalar_value(preferred_evidence_address) if use_evidence_address else None,
        normalize_scalar_value(input_data.get("address")),
        normalize_scalar_value(best_data.get("address")) if not use_evidence_address else None,
    ]) or "")
    final_category = str(get_first_non_empty([
        normalize_scalar_value(correction_value(corrections, "category")),
        normalize_scalar_value(input_data.get("poi_type")),
    ]) or "")
    final_city = str(get_first_non_empty([
        normalize_scalar_value(correction_value(corrections, "city")),
        normalize_scalar_value(input_data.get("city")),
        normalize_scalar_value(best_data.get("city")),
    ]) or "")
    final_city_adcode = str(get_first_non_empty([
        normalize_scalar_value(correction_value(corrections, "city_adcode")),
        normalize_scalar_value(input_data.get("city_adcode")),
    ]) or "")

    name_confidence = float(dimensions.get("name", {}).get("confidence", 0.0))
    location_confidence = float(dimensions.get("location", {}).get("confidence", 0.0))
    address_confidence = float(dimensions.get("address", {}).get("confidence", location_confidence))
    coordinates_confidence = float(dimensions.get("coordinates", {}).get("confidence", location_confidence))
    category_confidence = float(dimensions.get("category", {}).get("confidence", 0.0))
    city_confidence = float(dimensions.get("administrative", {}).get("confidence", 1.0))
    final_coordinates["confidence"] = float(corrections.get("coordinates", {}).get("confidence", coordinates_confidence) or coordinates_confidence)

    changes = []
    for field in CORRECTION_FIELDS:
        correction = corrections.get(field)
        if not isinstance(correction, dict):
            continue
        old_value = correction.get("original")
        new_value = correction.get("suggested")
        reason = str(correction.get("reason") or "").strip()
        if new_value is None or not reason or values_equal(old_value, new_value):
            continue
        changes.append(
            {
                "field": field,
                "old_value": format_change_value(old_value),
                "new_value": format_change_value(new_value),
                "reason": reason,
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
                "name_confidence": float(corrections.get("name", {}).get("confidence", name_confidence) or name_confidence),
                "address": final_address,
                "address_confidence": float(corrections.get("address", {}).get("confidence", address_confidence) or address_confidence),
                "coordinates": final_coordinates,
                "category": final_category,
                "category_confidence": float(corrections.get("category", {}).get("confidence", category_confidence) or category_confidence),
                "city": final_city,
                "city_confidence": float(corrections.get("city", {}).get("confidence", city_confidence) or city_confidence),
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
                    "version": "1.6.8",
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
                "contract:1.6.8",
                f"status:{decision['overall']['status']}",
                f"poi_type:{input_data['poi_type']}",
            ],
        },
        "metadata": {
            "skill_version": "1.6.8",
            "processing_time_ms": int(decision.get("processing_duration_ms", 0)),
            "data_sources": data_sources,
            "rules_applied": [f"{name}_dimension" for name in dimensions.keys()],
            "custom_fields": {
                "task_id": str(input_data.get("task_id") or ""),
                "contract_version": "1.6.8",
                "run_id": run_id,
            },
        },
        "created_at": created_at,
        "updated_at": created_at,
    }

    if final_city_adcode:
        record["verification_result"]["final_values"]["city_adcode"] = final_city_adcode
    if input_data.get("address") is not None:
        record["input_data"]["address"] = input_data["address"]
    if input_coordinates is not None:
        record["input_data"]["coordinates"] = input_coordinates
    if input_data.get("source") is not None:
        record["input_data"]["source"] = input_data["source"]
    if input_data.get("city_adcode") is not None:
        record["input_data"]["city_adcode"] = str(input_data["city_adcode"])

    for dimension_name, dimension in dimensions.items():
        if isinstance(dimension, dict):
            record["quality_metrics"]["dimension_scores"][dimension_name] = float(dimension.get("score", dimension.get("confidence", 0.0)))

    if record["flags"]["requires_periodic_review"]:
        expires_at = datetime.now(timezone.utc) + timedelta(days=int(record["flags"]["review_period_days"]))
        record["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    return record


def test_bundle_name(name: str, prefix: str) -> bool:
    return bool(re.fullmatch(rf"{re.escape(prefix)}_\d{{8}}T\d{{6}}Z\.json", name))


def find_latest_index(task_dir: Union[str, Path]) -> Optional[Dict[str, Any]]:
    files = sorted(Path(task_dir).glob("index_*.json"), key=lambda item: item.name, reverse=True)
    if not files:
        return None
    return {"latest": str(files[0]), "all": [str(path) for path in files]}


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
