#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evidence_collection_common import (
    ensure_stdout_utf8,
    get_source_type_weight,
    get_type_config_sources,
    get_url_host_info,
    normalize_input_poi,
    normalize_whitespace,
    read_json_file,
    resolve_poi_type_category,
    utc_iso_now,
    write_json_file,
)


def new_web_plan_item(poi: dict, source: dict) -> dict:
    host_info = get_url_host_info(str(source.get("url", "")))
    query = normalize_whitespace(f"{poi['city']} {poi['name']} {source.get('name', '')}")
    return {
        "source_name": str(source.get("name", "")),
        "source_type": str(source.get("type", "")),
        "source_url": str(source.get("url", "")),
        "weight": float(source.get("weight", get_source_type_weight(str(source.get("type", ""))))),
        "mode": "direct_fetch" if host_info["can_fetch_direct"] else "search_first",
        "domain": host_info["host"] if host_info["can_filter_domain"] else None,
        "query": query,
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    args = parser.parse_args()

    poi = normalize_input_poi(read_json_file(args.PoiPath))
    for field in ("id", "name", "poi_type", "city"):
        if not normalize_whitespace(poi.get(field)):
            raise ValueError(f"input.{field} is required")

    repo_root = SCRIPT_DIR.parent.parent
    mapping_path = repo_root / "skills-bigpoi-verification" / "config" / "poi_type_mapping.yaml"
    config_name = resolve_poi_type_category(str(poi["poi_type"]), mapping_path)
    if not config_name:
        raise ValueError(f"unsupported poi_type for evidence collection: {poi['poi_type']}")

    config_path = SCRIPT_DIR.parent / "config" / f"{config_name}.yaml"
    sources = get_type_config_sources(config_path)

    official_sources = []
    internet_sources = []
    for source in sources:
        if not isinstance(source, dict) or "type" not in source:
            continue
        item = new_web_plan_item(poi, source)
        if source["type"] == "official":
            official_sources.append(item)
        elif source["type"] == "internet":
            internet_sources.append(item)

    if normalize_whitespace(poi.get("website")):
        host_info = get_url_host_info(str(poi["website"]))
        official_sources = [
            {
                "source_name": "输入POI官网",
                "source_type": "official",
                "source_url": str(poi["website"]),
                "weight": 1.0,
                "mode": "direct_fetch" if host_info["can_fetch_direct"] else "search_first",
                "domain": host_info["host"] if host_info["can_filter_domain"] else None,
                "query": normalize_whitespace(f"{poi['city']} {poi['name']} 官网"),
            },
            *official_sources,
        ]

    plan = {
        "status": "ok",
        "poi": {
            "id": str(poi["id"]),
            "name": str(poi["name"]),
            "poi_type": str(poi["poi_type"]),
            "city": str(poi["city"]),
            "config_category": config_name,
        },
        "generated_at": utc_iso_now(),
        "official_sources": official_sources,
        "internet_sources": internet_sources,
    }

    write_json_file(plan, args.OutputPath)
    result = {
        "status": "ok",
        "result_path": str(Path(args.OutputPath).resolve()),
        "config_category": config_name,
        "official_count": len(official_sources),
        "internet_count": len(internet_sources),
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
