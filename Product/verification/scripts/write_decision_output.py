#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Union

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_context import collect_item_run_ids, require_context
from authority_category_inference import infer_authority_category


ALLOWED_CORRECTION_FIELDS = ("name", "address", "coordinates", "category", "city", "city_adcode")
REQUIRED_DIMENSIONS = ("existence", "name", "address", "coordinates", "category")
DIMENSION_LABELS = {
    "existence": "\u5b58\u5728\u6027",
    "name": "\u540d\u79f0",
    "address": "\u5730\u5740",
    "coordinates": "\u5750\u6807",
    "location": "\u4f4d\u7f6e",
    "category": "\u5206\u7c7b",
    "administrative": "\u884c\u653f\u533a",
    "timeliness": "\u65f6\u6548\u6027",
}
CHANGE_SIGNAL_PATTERN = re.compile(
    r"(\u5efa\u8bae(?:\u4fee\u6539|\u66f4\u6b63|\u8c03\u6574|\u66f4\u65b0|\u8865\u5145)|\u5e94\u6539\u4e3a|\u4fee\u6b63\u4e3a|\u4fee\u6539\u4e3a|\u9700\u6539\u4e3a|\u5efa\u8bae\u4f7f\u7528)"
)
ADDRESS_DETAIL_PATTERN = re.compile(r"(\d+|号|栋|楼|室|层|座|单元|路|街|巷|道|园|大厦|广场)")


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def prune_empty(value):
    if isinstance(value, dict):
        result = {}
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


def read_json_file(path: Union[str, Path]):
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError(f"JSON file is empty: {file_path}")
    return json.loads(raw)


def write_json_file(data, path: Union[str, Path]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_iso_time(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def parse_iso_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_input(poi: dict) -> dict:
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


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_input(poi: dict, errors: list[str]) -> None:
    for field in ("id", "name", "poi_type", "city"):
        if not str(poi.get(field) or "").strip():
            add_error(errors, f"input.{field} is required")
    if poi.get("poi_type") is not None and not re.fullmatch(r"\d{6}", str(poi["poi_type"])):
        add_error(errors, "input.poi_type must be a 6-digit code")
    if poi.get("coordinates") is not None:
        coordinates = poi["coordinates"]
        if not isinstance(coordinates, dict):
            add_error(errors, "input.coordinates must be an object")
        else:
            for field in ("longitude", "latitude"):
                if field not in coordinates:
                    add_error(errors, f"input.coordinates.{field} is required")


def validate_evidence(evidence, poi_id: str, expected_run_id: str, errors: list[str]) -> None:
    if not isinstance(evidence, list):
        add_error(errors, "evidence must be an array")
        return
    if not evidence:
        add_error(errors, "evidence array cannot be empty")
        return
    item_run_ids = collect_item_run_ids(evidence)
    if not item_run_ids:
        add_error(errors, "evidence.metadata.run_id is required for all items")
    elif item_run_ids != {expected_run_id}:
        add_error(errors, "evidence item run_id must match the current run")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            add_error(errors, f"evidence[{index}] must be an object")
            continue
        for field in ("evidence_id", "poi_id", "source", "collected_at", "data"):
            if field not in item:
                add_error(errors, f"evidence[{index}].{field} is required")
        if "poi_id" in item and str(item["poi_id"]) != poi_id:
            add_error(errors, f"evidence[{index}].poi_id must match input id")
        if "collected_at" in item and not is_iso_time(str(item["collected_at"])):
            add_error(errors, f"evidence[{index}].collected_at must be ISO datetime")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else None
        if metadata is None:
            add_error(errors, f"evidence[{index}].metadata is required")
        elif str(metadata.get("run_id") or "").strip() != expected_run_id:
            add_error(errors, f"evidence[{index}].metadata.run_id must match the current run")
        source = item.get("source")
        if source is not None:
            if not isinstance(source, dict):
                add_error(errors, f"evidence[{index}].source must be an object")
            else:
                for field in ("source_id", "source_name", "source_type"):
                    if not str(source.get(field) or "").strip():
                        add_error(errors, f"evidence[{index}].source.{field} is required")
                if source.get("source_type") not in {"official", "map_vendor", "internet", "user_contributed", "other"}:
                    add_error(errors, f"evidence[{index}].source.source_type is invalid")
        data = item.get("data")
        if data is not None:
            if not isinstance(data, dict):
                add_error(errors, f"evidence[{index}].data must be an object")
            elif not str(data.get("name") or "").strip():
                add_error(errors, f"evidence[{index}].data.name is required")


def validate_dimension(dimension: dict, name: str, errors: list[str]) -> None:
    for field in ("result", "confidence"):
        if field not in dimension:
            add_error(errors, f"seed.dimensions.{name}.{field} is required")
    if dimension.get("result") not in {"pass", "fail", "uncertain"}:
        add_error(errors, f"seed.dimensions.{name}.result is invalid")
    if "confidence" in dimension:
        confidence = float(dimension["confidence"])
        if confidence < 0 or confidence > 1:
            add_error(errors, f"seed.dimensions.{name}.confidence must be between 0 and 1")
    if "score" in dimension:
        score = float(dimension["score"])
        if score < 0 or score > 1:
            add_error(errors, f"seed.dimensions.{name}.score must be between 0 and 1")


def clone_dimension(dimension: dict) -> dict:
    return json.loads(json.dumps(dimension, ensure_ascii=False))


def aggregate_location_dimension(address_dimension: dict, coordinates_dimension: dict) -> dict:
    result_values = [address_dimension.get("result"), coordinates_dimension.get("result")]
    if "fail" in result_values:
        result = "fail"
    elif "uncertain" in result_values:
        result = "uncertain"
    else:
        result = "pass"

    confidences = [
        float(dimension.get("confidence", 0.0))
        for dimension in (address_dimension, coordinates_dimension)
        if dimension.get("confidence") is not None
    ]
    scores = [
        float(dimension.get("score", dimension.get("confidence", 0.0)))
        for dimension in (address_dimension, coordinates_dimension)
        if dimension.get("score") is not None or dimension.get("confidence") is not None
    ]

    location_dimension = {
        "result": result,
        "confidence": round(min(confidences), 4) if confidences else 0.0,
        "details": {"source_dimensions": ["address", "coordinates"]},
    }
    if scores:
        location_dimension["score"] = round(min(scores), 4)
    return location_dimension


def reconcile_dimensions(raw_dimensions: dict, errors: list[str]) -> dict:
    normalized = {}
    for name, dimension in raw_dimensions.items():
        normalized[name] = clone_dimension(dimension) if isinstance(dimension, dict) else dimension

    address_dimension = normalized.get("address")
    coordinates_dimension = normalized.get("coordinates")
    if not isinstance(address_dimension, dict):
        add_error(errors, "seed.dimensions.address is required")
    if not isinstance(coordinates_dimension, dict):
        add_error(errors, "seed.dimensions.coordinates is required")

    if isinstance(address_dimension, dict) and isinstance(coordinates_dimension, dict):
        normalized["location"] = aggregate_location_dimension(address_dimension, coordinates_dimension)

    return normalized


def measure_overall_confidence(dimensions: dict) -> float:
    weights = {
        "existence": 0.25,
        "name": 0.25,
        "address": 0.10,
        "coordinates": 0.10,
        "category": 0.15,
        "administrative": 0.10,
        "timeliness": 0.05,
        "location": 0.0,
    }
    weighted_sum = 0.0
    total_weight = 0.0
    for name, dimension in dimensions.items():
        weight = weights.get(name, 0.0)
        if weight <= 0:
            continue
        weighted_sum += float(dimension["confidence"]) * weight
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 4)


def infer_status(dimensions: dict, overall_confidence: float) -> str:
    relevant_dimensions = [dimension for name, dimension in dimensions.items() if name != "location"]
    if dimensions["existence"]["result"] == "fail":
        return "rejected"
    if overall_confidence < 0.6:
        return "manual_review"
    if any(dimension["result"] == "fail" for dimension in relevant_dimensions):
        return "manual_review"
    if any(dimension["result"] == "uncertain" for dimension in relevant_dimensions):
        return "downgraded"
    return "accepted"


def get_action(status: str) -> str:
    mapping = {
        "accepted": "adopt",
        "downgraded": "modify",
        "manual_review": "manual_review",
        "rejected": "reject",
        "trigger_fallback": "reroute_model",
    }
    return mapping.get(status, "manual_review")


def normalize_scalar_value(value):
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_coordinate_value(value, field: str, errors: list[str]):
    if not isinstance(value, dict):
        add_error(errors, f"seed.corrections.{field} must be an object")
        return None
    normalized = {}
    for key in ("longitude", "latitude"):
        if value.get(key) is None:
            add_error(errors, f"seed.corrections.{field}.{key} is required")
            continue
        normalized[key] = float(value[key])
    coordinate_system = str(value.get("coordinate_system") or "").strip()
    if coordinate_system:
        normalized["coordinate_system"] = coordinate_system
    return normalized if "longitude" in normalized and "latitude" in normalized else None


def get_default_original_value(field: str, poi: dict):
    if field == "coordinates":
        coordinates = poi.get("coordinates")
        if not isinstance(coordinates, dict):
            return None
        normalized = {}
        if coordinates.get("longitude") is not None:
            normalized["longitude"] = float(coordinates["longitude"])
        if coordinates.get("latitude") is not None:
            normalized["latitude"] = float(coordinates["latitude"])
        if coordinates.get("coordinate_system"):
            normalized["coordinate_system"] = str(coordinates["coordinate_system"])
        return normalized or None
    mapping = {
        "name": poi.get("name"),
        "address": poi.get("address"),
        "category": poi.get("poi_type"),
        "city": poi.get("city"),
        "city_adcode": poi.get("city_adcode"),
    }
    return normalize_scalar_value(mapping.get(field))


def values_equal(left, right) -> bool:
    if isinstance(left, dict) or isinstance(right, dict):
        return json.dumps(left or {}, ensure_ascii=False, sort_keys=True) == json.dumps(right or {}, ensure_ascii=False, sort_keys=True)
    return normalize_scalar_value(left) == normalize_scalar_value(right)


def normalize_address_text(value: object) -> Optional[str]:
    text = normalize_scalar_value(value)
    if text is None:
        return None
    return re.sub(r"[\s,，。；;:：()（）-]", "", str(text))


def address_detail_score(value: object) -> int:
    text = normalize_scalar_value(value)
    if text is None:
        return 0
    score = 1
    if re.search(r"\d", text):
        score += 2
    score += len(ADDRESS_DETAIL_PATTERN.findall(text))
    return score


def select_best_evidence_address(evidence: list[dict]) -> Optional[dict]:
    best_candidate: Optional[dict] = None
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
            best_candidate = {
                "address": str(address),
                "source_type": source_type,
                "evidence_id": str(item.get("evidence_id") or ""),
                "detail_score": detail,
                "weight": weight,
            }
    return best_candidate


def apply_address_consistency_guard(
    poi: dict,
    evidence: list[dict],
    dimensions: dict,
    corrections: dict,
) -> tuple[dict, dict]:
    address_dimension = dimensions.get("address")
    if not isinstance(address_dimension, dict):
        return dimensions, corrections
    if str(address_dimension.get("result") or "") != "pass":
        return dimensions, corrections
    if isinstance(corrections.get("address"), dict):
        return dimensions, corrections

    input_address = normalize_scalar_value(poi.get("address"))
    if input_address is None:
        return dimensions, corrections

    best_candidate = select_best_evidence_address(evidence)
    if not best_candidate:
        return dimensions, corrections

    normalized_input = normalize_address_text(input_address)
    normalized_candidate = normalize_address_text(best_candidate["address"])
    if not normalized_input or not normalized_candidate or normalized_input == normalized_candidate:
        return dimensions, corrections

    input_score = address_detail_score(input_address)
    candidate_score = int(best_candidate.get("detail_score") or 0)
    if candidate_score <= input_score:
        return dimensions, corrections

    output_dimensions = dict(dimensions)
    guarded_dimension = clone_dimension(address_dimension)
    guarded_dimension["result"] = "uncertain"
    guarded_dimension["confidence"] = round(min(float(address_dimension.get("confidence", 0.0)), 0.59), 4)
    details = dict(guarded_dimension.get("details") if isinstance(guarded_dimension.get("details"), dict) else {})
    details["reason"] = "存在比输入地址更具体的高权重证据地址，但尚未通过 corrections 完成收敛"
    details["input_address"] = str(input_address)
    details["best_evidence_address"] = str(best_candidate["address"])
    details["best_evidence_source_type"] = str(best_candidate.get("source_type") or "")
    if best_candidate.get("evidence_id"):
        guarded_dimension["evidence_refs"] = [str(best_candidate["evidence_id"])]
    guarded_dimension["details"] = prune_empty(details)
    output_dimensions["address"] = guarded_dimension
    output_dimensions["location"] = aggregate_location_dimension(
        guarded_dimension,
        output_dimensions.get("coordinates", {}),
    )
    return output_dimensions, corrections


def collect_change_signal_texts(seed: dict) -> list[str]:
    texts: list[str] = []
    overall = seed.get("overall")
    if isinstance(overall, dict):
        summary = overall.get("summary")
        if isinstance(summary, str) and summary.strip():
            texts.append(summary)
    downgrade_info = seed.get("downgrade_info")
    if isinstance(downgrade_info, dict):
        for key in ("reason_description", "recommendation"):
            value = downgrade_info.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
    dimensions = seed.get("dimensions")
    if isinstance(dimensions, dict):
        for dimension in dimensions.values():
            if not isinstance(dimension, dict):
                continue
            details = dimension.get("details")
            if not isinstance(details, dict):
                continue
            for key in ("notes", "matched_value", "expected_value", "observed_value", "reason", "suggestion"):
                value = details.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value)
    return texts


def normalize_corrections(seed: dict, poi: dict, errors: list[str]) -> dict:
    corrections = seed.get("corrections")
    if corrections is None:
        return {}
    if not isinstance(corrections, dict):
        add_error(errors, "seed.corrections must be an object")
        return {}

    normalized = {}
    for field, correction in corrections.items():
        if field not in ALLOWED_CORRECTION_FIELDS:
            add_error(errors, f"seed.corrections.{field} is not supported")
            continue
        if not isinstance(correction, dict):
            add_error(errors, f"seed.corrections.{field} must be an object")
            continue

        original = correction.get("original", get_default_original_value(field, poi))
        suggested = correction.get("suggested")
        reason = str(correction.get("reason") or "").strip()

        if field == "coordinates":
            original = normalize_coordinate_value(original, f"{field}.original", errors) if original is not None else get_default_original_value(field, poi)
            suggested = normalize_coordinate_value(suggested, f"{field}.suggested", errors)
        else:
            original = normalize_scalar_value(original)
            suggested = normalize_scalar_value(suggested)

        if suggested is None:
            add_error(errors, f"seed.corrections.{field}.suggested is required")
            continue
        if field in {"category", "city_adcode"} and not re.fullmatch(r"\d{6}", str(suggested)):
            add_error(errors, f"seed.corrections.{field}.suggested must be a 6-digit code")
        if not reason:
            add_error(errors, f"seed.corrections.{field}.reason is required")
        if values_equal(original, suggested):
            add_error(errors, f"seed.corrections.{field} must change the value")
            continue

        normalized_entry = {
            "original": original,
            "suggested": suggested,
            "reason": reason,
        }
        confidence = correction.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
            if confidence < 0 or confidence > 1:
                add_error(errors, f"seed.corrections.{field}.confidence must be between 0 and 1")
            else:
                normalized_entry["confidence"] = confidence
        normalized[field] = normalized_entry

    return normalized


def get_summary(status: str, confidence: float, dimensions: dict, corrections: dict) -> str:
    failed = [DIMENSION_LABELS.get(name, name) for name, dimension in dimensions.items() if name != "location" and dimension["result"] == "fail"]
    uncertain = [DIMENSION_LABELS.get(name, name) for name, dimension in dimensions.items() if name != "location" and dimension["result"] == "uncertain"]
    confidence_text = f"{confidence:.2f}"
    correction_count = len(corrections)
    if status == "accepted":
        if correction_count:
            return f"\u6838\u5b9e\u901a\u8fc7\uff0c\u5efa\u8bae\u6309\u7ed3\u6784\u5316\u4fee\u6b63\u66f4\u65b0{correction_count}\u9879\u5b57\u6bb5\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"
        return f"\u6838\u5b9e\u901a\u8fc7\uff0c\u6838\u5fc3\u7ef4\u5ea6\u5747\u6ee1\u8db3\u8981\u6c42\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"
    if status == "downgraded":
        uncertain_text = "\u3001".join(uncertain) if uncertain else "\u90e8\u5206\u7ef4\u5ea6"
        if correction_count:
            return f"\u6838\u5b9e\u964d\u7ea7\uff0c{uncertain_text}\u4ecd\u5b58\u5728\u4e0d\u786e\u5b9a\u6027\uff0c\u4e14\u5efa\u8bae\u4fee\u6b63{correction_count}\u9879\u5b57\u6bb5\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"
        return f"\u6838\u5b9e\u964d\u7ea7\uff0c{uncertain_text}\u4ecd\u5b58\u5728\u4e0d\u786e\u5b9a\u6027\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"
    if status == "manual_review":
        failed_text = "\u3001".join(failed) if failed else "\u5173\u952e\u7ef4\u5ea6"
        return f"\u9700\u8981\u4eba\u5de5\u590d\u6838\uff0c\u539f\u56e0\u662f{failed_text}\u672a\u901a\u8fc7\u6216\u5b58\u5728\u51b2\u7a81\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"
    if status == "rejected":
        return f"\u6838\u5b9e\u62d2\u7edd\uff0c\u5b58\u5728\u6027\u7ef4\u5ea6\u672a\u901a\u8fc7\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"
    return f"\u9700\u8981\u4eba\u5de5\u590d\u6838\uff0c\u7efc\u5408\u7f6e\u4fe1\u5ea6{confidence_text}\u3002"


def apply_authority_category_enhancement(poi: dict, evidence: list[dict], dimensions: dict, corrections: dict, seed: Optional[dict] = None) -> Tuple[dict, dict]:
    model_judgment = None
    if isinstance(seed, dict) and isinstance(seed.get("authority_model_judgment"), dict):
        model_judgment = seed["authority_model_judgment"]
    inference = infer_authority_category(poi, evidence, model_judgment=model_judgment)
    if not inference:
        return dimensions, corrections

    output_dimensions = dict(dimensions)
    category_dimension = clone_dimension(output_dimensions.get("category", {}))
    category_dimension["result"] = inference["result"]
    category_dimension["confidence"] = float(inference["confidence"])
    details = dict(category_dimension.get("details") if isinstance(category_dimension.get("details"), dict) else {})
    details.update(inference.get("details") if isinstance(inference.get("details"), dict) else {})
    category_dimension["details"] = prune_empty(details)
    if isinstance(inference.get("details"), dict) and isinstance(inference["details"].get("evidence_refs"), list):
        category_dimension["evidence_refs"] = inference["details"]["evidence_refs"]
    output_dimensions["category"] = category_dimension

    output_corrections = dict(corrections)
    selected_code = str(inference.get("selected_code") or "").strip()
    if inference["result"] == "fail" and selected_code and selected_code != str(poi.get("poi_type")) and "category" not in output_corrections:
        output_corrections["category"] = {
            "original": str(poi.get("poi_type")),
            "suggested": selected_code,
            "reason": str((inference.get("details") or {}).get("reason") or "authority 分类修正"),
            "confidence": float(inference["confidence"]),
        }
    return output_dimensions, output_corrections


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-EvidencePath", required=True)
    parser.add_argument("-DecisionSeedPath", required=True)
    parser.add_argument("-OutputDirectory", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    args = parser.parse_args()

    errors: list[str] = []
    poi = normalize_input(read_json_file(args.PoiPath))
    evidence = read_json_file(args.EvidencePath)
    seed = read_json_file(args.DecisionSeedPath)

    if not isinstance(poi, dict):
        raise ValueError("input must be a JSON object")
    if not isinstance(seed, dict):
        raise ValueError("decision seed must be a JSON object")

    validate_input(poi, errors)
    poi_id = str(poi.get("id") or "")
    seed_context = require_context(seed, label="decision_seed", expected_poi_id=poi_id, expected_run_id=args.RunId, allow_missing=False)
    resolved_run_id = str(args.RunId or (seed_context or {}).get("run_id") or "").strip()
    if not resolved_run_id:
        add_error(errors, "decision_seed.context.run_id is required")
    resolved_task_id = str(args.TaskId or poi.get("task_id") or (seed_context or {}).get("task_id") or "").strip()
    validate_evidence(evidence, poi_id, resolved_run_id, errors)

    processed_at = str(seed.get("processed_at") or "")
    if processed_at and not is_iso_time(processed_at):
        add_error(errors, "seed.processed_at must be ISO datetime")

    normalized_corrections = normalize_corrections(seed, poi, errors)
    change_signal_texts = collect_change_signal_texts(seed)
    if any(CHANGE_SIGNAL_PATTERN.search(text) for text in change_signal_texts) and not normalized_corrections:
        add_error(errors, "seed.corrections is required when the seed contains modification suggestions")

    dimensions = seed.get("dimensions")
    if not isinstance(dimensions, dict):
        add_error(errors, "seed.dimensions is required and must be an object")
    else:
        dimensions = reconcile_dimensions(dimensions, errors)
        for name in REQUIRED_DIMENSIONS:
            if not isinstance(dimensions.get(name), dict):
                add_error(errors, f"seed.dimensions.{name} is required")
            else:
                validate_dimension(dimensions[name], name, errors)
        for name, dimension in dimensions.items():
            if isinstance(dimension, dict):
                validate_dimension(dimension, name, errors)

    if errors:
        raise ValueError("\n".join(errors))

    seed_created_at = str((seed_context or {}).get("created_at") or "").strip()
    seed_created_dt = parse_iso_time(seed_created_at) if seed_created_at else None
    timestamp = datetime.now(timezone.utc)
    if seed_created_dt and timestamp < seed_created_dt:
        timestamp = seed_created_dt
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    created_at = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    overall_seed = seed.get("overall") if isinstance(seed.get("overall"), dict) else {}
    dimensions, normalized_corrections = apply_authority_category_enhancement(poi, evidence, dimensions, normalized_corrections, seed=seed)
    dimensions, normalized_corrections = apply_address_consistency_guard(poi, evidence, dimensions, normalized_corrections)
    overall_confidence = float(overall_seed.get("confidence", measure_overall_confidence(dimensions)))

    status = str(overall_seed.get("status", infer_status(dimensions, overall_confidence)))
    action = str(overall_seed.get("action", get_action(status)))
    summary = get_summary(status, overall_confidence, dimensions, normalized_corrections)

    hash_source = f"{poi_id}|{resolved_run_id}|{stamp}|decision".encode("utf-8")
    short_hash = hashlib.sha256(hash_source).hexdigest()[:8].upper()

    distribution = {"official": 0, "map_vendor": 0, "internet": 0}
    valid_count = 0
    high_weight_count = 0
    for item in evidence:
        verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
        if verification.get("is_valid") is True:
            valid_count += 1
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        if source.get("weight") is not None and float(source["weight"]) >= 0.8:
            high_weight_count += 1
        source_type = source.get("source_type")
        if source_type in distribution:
            distribution[source_type] += 1

    processing_duration_ms = int(seed.get("processing_duration_ms", 0) or 0)
    if processing_duration_ms <= 0 and seed_created_dt is not None:
        processing_duration_ms = max(int((timestamp - seed_created_dt).total_seconds() * 1000), 1)

    decision = {
        "decision_id": f"DEC_{stamp}_{short_hash}",
        "poi_id": poi_id,
        "run_id": resolved_run_id,
        "overall": {
            "status": status,
            "confidence": round(overall_confidence, 4),
            "action": action,
            "summary": summary,
        },
        "dimensions": dimensions,
        "evidence_summary": {
            "total_count": len(evidence),
            "valid_count": valid_count,
            "high_weight_count": high_weight_count,
            "source_distribution": distribution,
        },
        "created_at": created_at,
        "processed_at": processed_at or created_at,
        "processing_duration_ms": processing_duration_ms,
        "version": str(seed.get("version") or "1.6.8"),
        "metadata": prune_empty({"task_id": resolved_task_id, "seed_created_at": seed_created_at}),
    }
    if "downgrade_info" in seed:
        decision["downgrade_info"] = seed["downgrade_info"]
    if normalized_corrections:
        decision["corrections"] = normalized_corrections

    decision = prune_empty(decision)
    output_directory = Path(args.OutputDirectory)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"decision_{stamp}.json"
    write_json_file(decision, output_path)

    result = {
        "status": "ok",
        "decision_path": str(output_path.resolve()),
        "decision_id": decision["decision_id"],
        "poi_id": poi_id,
        "run_id": resolved_run_id,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
