#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_context import collect_item_run_ids, require_context, set_item_run_context
from evidence_collection_common import ensure_stdout_utf8, normalize_input_poi, read_json_file, utc_iso_now, utc_timestamp, write_json_file
import math

# [Sub-Agent 3 改造核心: 前置物理距离预算，彻底剥离模型数学损耗]
def compute_haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> int:
    R = 6371000  # radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(R * c)

ALLOWED_SOURCE_TYPES = {"official", "map_vendor", "internet", "user_contributed", "other"}


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


def is_iso_time(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def get_evidence_items(collector_output):
    if isinstance(collector_output, list):
        return collector_output
    if isinstance(collector_output, dict) and isinstance(collector_output.get("evidence_list"), list):
        return collector_output["evidence_list"]
    raise ValueError("collector output must be an array or an object containing evidence_list")


def normalize_evidence_item(item: dict, poi: dict, timestamp: str, index: int, errors: list[str]) -> dict:
    poi_id = str(poi["id"])
    prefix = f"evidence[{index}]"
    normalized: dict = {}

    evidence_id = item.get("evidence_id") if str(item.get("evidence_id") or "").strip() else f"EVD_{timestamp}_{index + 1:03d}"
    normalized["evidence_id"] = str(evidence_id)

    item_poi_id = str(item.get("poi_id") or poi_id)
    if item_poi_id != poi_id:
        errors.append(f"{prefix}.poi_id must match input id")
    normalized["poi_id"] = poi_id

    source = item.get("source") if isinstance(item.get("source"), dict) else None
    if source is None:
        errors.append(f"{prefix}.source is required and must be an object")
    else:
        normalized_source = {}
        for field in ("source_id", "source_name", "source_type"):
            if not str(source.get(field) or "").strip():
                errors.append(f"{prefix}.source.{field} is required")
            else:
                normalized_source[field] = str(source[field])
        if normalized_source.get("source_type") not in ALLOWED_SOURCE_TYPES:
            errors.append(f"{prefix}.source.source_type is invalid")
        if source.get("source_url") is not None:
            normalized_source["source_url"] = str(source["source_url"])
        if source.get("weight") is not None:
            weight = float(source["weight"])
            if weight < 0 or weight > 1:
                errors.append(f"{prefix}.source.weight must be between 0 and 1")
            normalized_source["weight"] = weight
        normalized["source"] = prune_empty(normalized_source)

    collected_at = str(item.get("collected_at") or utc_iso_now())
    if not is_iso_time(collected_at):
        errors.append(f"{prefix}.collected_at must be an ISO date-time string")
    normalized["collected_at"] = collected_at

    data = item.get("data") if isinstance(item.get("data"), dict) else item.get("normalized_data") if isinstance(item.get("normalized_data"), dict) else None
    if data is None:
        errors.append(f"{prefix}.data is required and must be an object")
    else:
        normalized_data = {}
        if not str(data.get("name") or "").strip():
            errors.append(f"{prefix}.data.name is required")
        else:
            normalized_data["name"] = str(data["name"])
        for field in ("address", "phone", "category", "status", "level"):
            if field in data and data[field] is not None:
                normalized_data[field] = data[field]
        if isinstance(data.get("coordinates"), dict):
            coords = data["coordinates"]
            if "longitude" not in coords or "latitude" not in coords:
                errors.append(f"{prefix}.data.coordinates must contain longitude and latitude")
            else:
                lon = float(coords["longitude"])
                lat = float(coords["latitude"])
                normalized_data["coordinates"] = {"longitude": lon, "latitude": lat}
                
                # 预计算到源 POI 的真实物理距离
                input_coords = poi.get("coordinates", {})
                if isinstance(input_coords, dict) and "longitude" in input_coords and "latitude" in input_coords:
                    dist = compute_haversine_distance(
                        float(input_coords["longitude"]), 
                        float(input_coords["latitude"]), 
                        lon, 
                        lat
                    )
                    normalized_data["computed_distance_meters"] = dist
                    
        if isinstance(data.get("administrative"), dict):
            normalized_data["administrative"] = data["administrative"]
        
        # [EvidencePruner 脱水改造]
        # 抛弃携带大量无效标签与全量网络结构的 raw_data
        # if isinstance(data.get("raw_data"), dict):
        #     normalized_data["raw_data"] = data["raw_data"]
        
        normalized["data"] = prune_empty(normalized_data)

    for field in ("verification", "matching", "metadata"):
        if isinstance(item.get(field), dict):
            pruned = prune_empty(item[field])
            if pruned is not None:
                normalized[field] = pruned

    return normalized


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-CollectorOutputPath", required=True)
    parser.add_argument("-OutputDirectory", required=True)
    parser.add_argument("-RunId")
    parser.add_argument("-TaskId")
    args = parser.parse_args()

    poi = normalize_input_poi(read_json_file(args.PoiPath))
    if not isinstance(poi, dict):
        raise ValueError("input must be a JSON object")
    for field in ("id", "name", "poi_type", "city"):
        if not str(poi.get(field) or "").strip():
            raise ValueError(f"input.{field} is required")
    if not re.fullmatch(r"\d{6}", str(poi["poi_type"])):
        raise ValueError("input.poi_type must be a 6-digit code")

    collector_output = read_json_file(args.CollectorOutputPath)
    collector_context = require_context(collector_output, label="collector_output", expected_poi_id=str(poi["id"]), expected_run_id=args.RunId, allow_missing=not bool(args.RunId))
    resolved_run_id = str(args.RunId or (collector_context or {}).get("run_id") or "").strip()
    resolved_task_id = str(args.TaskId or poi.get("task_id") or (collector_context or {}).get("task_id") or "").strip()
    items = get_evidence_items(collector_output)
    errors: list[str] = []
    timestamp = utc_timestamp()
    normalized_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        normalized_items.append(normalize_evidence_item(item, poi, timestamp, index, errors))

    normalized_items = [set_item_run_context(item, resolved_run_id or None, resolved_task_id or None) for item in normalized_items]
    item_run_ids = collect_item_run_ids(normalized_items)
    if resolved_run_id and item_run_ids and item_run_ids != {resolved_run_id}:
        errors.append("evidence item run_id must match the current run")
    normalized_items = [item for item in (prune_empty(item) for item in normalized_items) if item is not None]
    if not normalized_items:
        errors.append("no evidence items were produced")
    if errors:
        raise ValueError("\n".join(errors))

    output_directory = Path(args.OutputDirectory)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"evidence_{timestamp}.json"
    write_json_file(normalized_items, output_path)

    result = {
        "status": "ok",
        "poi_id": str(poi["id"]),
        "run_id": resolved_run_id,
        "evidence_count": len(normalized_items),
        "evidence_path": str(output_path.resolve()),
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
