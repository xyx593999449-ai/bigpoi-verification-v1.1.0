#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


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


def read_json_file(path: str | Path):
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    raw = file_path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError(f"JSON file is empty: {file_path}")
    return json.loads(raw)


def write_json_file(data, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_iso_time(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


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
            add_error(errors, f"evidence[{index}].poi_id must match input id")
        if "collected_at" in item and not is_iso_time(str(item["collected_at"])):
            add_error(errors, f"evidence[{index}].collected_at must be ISO datetime")
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


def measure_overall_confidence(dimensions: dict) -> float:
    weights = {
        "existence": 0.25,
        "name": 0.25,
        "location": 0.20,
        "category": 0.15,
        "administrative": 0.10,
        "timeliness": 0.05,
    }
    weighted_sum = 0.0
    total_weight = 0.0
    for name, dimension in dimensions.items():
        weight = weights.get(name, 0.1)
        weighted_sum += float(dimension["confidence"]) * weight
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 4)


def infer_status(dimensions: dict, overall_confidence: float) -> str:
    if dimensions["existence"]["result"] == "fail":
        return "rejected"
    if overall_confidence < 0.6:
        return "manual_review"
    if any(dimension["result"] == "fail" for dimension in dimensions.values()):
        return "manual_review"
    if any(dimension["result"] == "uncertain" for dimension in dimensions.values()):
        return "downgraded"
    return "accepted"


def get_action(status: str) -> str:
    mapping = {
        "accepted": "adopt",
        "downgraded": "modify",
        "manual_review": "manual_review",
        "rejected": "reject",
    }
    return mapping.get(status, "manual_review")


def get_summary(status: str, confidence: float, dimensions: dict) -> str:
    failed = [name for name, dimension in dimensions.items() if dimension["result"] == "fail"]
    uncertain = [name for name, dimension in dimensions.items() if dimension["result"] == "uncertain"]
    if status == "accepted":
        return f"all required dimensions passed; overall confidence {confidence}"
    if status == "downgraded":
        return f"some dimensions remain uncertain: {', '.join(uncertain)}; overall confidence {confidence}"
    if status == "manual_review":
        return f"manual review required because failed dimensions: {', '.join(failed)}; overall confidence {confidence}"
    if status == "rejected":
        return f"verification rejected because existence failed; overall confidence {confidence}"
    return f"manual review required; overall confidence {confidence}"


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-EvidencePath", required=True)
    parser.add_argument("-DecisionSeedPath", required=True)
    parser.add_argument("-OutputDirectory", required=True)
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
    validate_evidence(evidence, poi_id, errors)

    dimensions = seed.get("dimensions")
    if not isinstance(dimensions, dict):
        add_error(errors, "seed.dimensions is required and must be an object")
    else:
        for name in ("existence", "name", "location", "category"):
            if not isinstance(dimensions.get(name), dict):
                add_error(errors, f"seed.dimensions.{name} is required")
            else:
                validate_dimension(dimensions[name], name, errors)
        for name, dimension in dimensions.items():
            if isinstance(dimension, dict):
                validate_dimension(dimension, name, errors)

    if errors:
        raise ValueError("\n".join(errors))

    timestamp = datetime.now(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    created_at = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    overall_seed = seed.get("overall") if isinstance(seed.get("overall"), dict) else {}
    overall_confidence = float(overall_seed.get("confidence", measure_overall_confidence(dimensions)))
    status = str(overall_seed.get("status", infer_status(dimensions, overall_confidence)))
    action = str(overall_seed.get("action", get_action(status)))
    summary = str(overall_seed.get("summary", get_summary(status, overall_confidence, dimensions)))

    hash_source = f"{poi_id}|{stamp}|decision".encode("utf-8")
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

    decision = {
        "decision_id": f"DEC_{stamp}_{short_hash}",
        "poi_id": poi_id,
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
        "processed_at": str(seed.get("processed_at") or created_at),
        "processing_duration_ms": int(seed.get("processing_duration_ms", 0)),
        "version": str(seed.get("version") or "1.6.0"),
    }
    if "downgrade_info" in seed:
        decision["downgrade_info"] = seed["downgrade_info"]
    if "corrections" in seed:
        decision["corrections"] = seed["corrections"]

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
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
