#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def log_progress(message: str) -> None:
    sys.stderr.write(f"[build-web-plan] {message}\n")
    sys.stderr.flush()


GOVERNMENT_QUERY_INTENTS = (
    ("office_address", "办公地址"),
    ("contact_phone", "联系电话"),
)


def build_query_text(
    *,
    poi: dict,
    source: dict,
    config_category: str,
    intent_label: Optional[str] = None,
) -> str:
    if config_category == "government" and intent_label:
        return normalize_whitespace(f"{poi['city']} {poi['name']} {intent_label}") or ""
    return normalize_whitespace(f"{poi['city']} {poi['name']} {source.get('name', '')}") or ""


def build_search_queries_for_source(
    *,
    poi: dict,
    source: dict,
    config_category: str,
    host_info: Dict[str, Any],
    default_count: Optional[int],
) -> List[Dict[str, Any]]:
    query_items: List[Dict[str, Any]] = []
    source_type = str(source.get("type", ""))
    source_name = str(source.get("name", ""))
    source_url = str(source.get("url", ""))
    source_weight = float(source.get("weight", get_source_type_weight(source_type)))
    domain = host_info["host"] if host_info["can_filter_domain"] else None
    time_range = normalize_whitespace(source.get("time_range"))
    source_count = source.get("count")
    count = int(source_count) if source_count is not None else default_count

    if config_category == "government":
        intents: List[tuple[str, str]] = list(GOVERNMENT_QUERY_INTENTS)
    else:
        intents = [("general", "")]

    for query_intent, intent_label in intents:
        query = build_query_text(
            poi=poi,
            source=source,
            config_category=config_category,
            intent_label=intent_label or None,
        )
        item: Dict[str, Any] = {
            "source_name": source_name,
            "source_type": source_type,
            "source_url": source_url,
            "target_poi_name": str(poi["name"]),
            "target_city": str(poi["city"]),
            "target_poi_type": str(poi["poi_type"]),
            "query": query,
            "query_intent": query_intent,
            "weight": source_weight,
            "domain": domain,
            "mode": "search_discovery",
        }
        if count is not None:
            item["count"] = int(count)
        if time_range:
            item["time_range"] = time_range
        query_items.append(item)
    return query_items


def source_allows_direct_read(source: Dict[str, Any], host_info: Dict[str, Any]) -> bool:
    if not host_info.get("can_fetch_direct"):
        return False
    return bool(source.get("allow_direct_read"))


def new_web_plan_item(poi: dict, source: dict, config_category: str) -> dict:
    host_info = get_url_host_info(str(source.get("url", "")))
    query = build_query_text(poi=poi, source=source, config_category=config_category)
    item = {
        "source_name": str(source.get("name", "")),
        "source_type": str(source.get("type", "")),
        "source_url": str(source.get("url", "")),
        "target_poi_name": str(poi["name"]),
        "target_city": str(poi["city"]),
        "target_poi_type": str(poi["poi_type"]),
        "weight": float(source.get("weight", get_source_type_weight(str(source.get("type", ""))))),
        "mode": "direct_read" if source_allows_direct_read(source, host_info) else "search_discovery",
        "domain": host_info["host"] if host_info["can_filter_domain"] else None,
        "query": query,
    }
    if source.get("count") is not None:
        item["count"] = int(source["count"])
    if normalize_whitespace(source.get("time_range")):
        item["time_range"] = normalize_whitespace(source.get("time_range"))
    return item


def default_source_count(config_category: str) -> Optional[int]:
    if config_category == "government":
        return 5
    return None


def dedupe_search_queries(queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_signatures: set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            continue
        query = normalize_whitespace(item.get("query")) or ""
        if not query:
            continue
        domain = normalize_whitespace(item.get("domain")) or ""
        intent = normalize_whitespace(item.get("query_intent")) or ""
        signature = f"{query}|{domain}|{intent}"
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        deduped.append(item)
    return deduped


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
    log_progress(f"开始生成检索计划: poi_id={poi['id']} name={poi['name']} poi_type={poi['poi_type']}")

    repo_root = SCRIPT_DIR.parent.parent
    mapping_path = repo_root / "skills-bigpoi-verification" / "config" / "poi_type_mapping.yaml"
    config_name = resolve_poi_type_category(str(poi["poi_type"]), mapping_path)
    if not config_name:
        raise ValueError(f"unsupported poi_type for evidence collection: {poi['poi_type']}")

    config_path = SCRIPT_DIR.parent / "config" / f"{config_name}.yaml"
    sources = get_type_config_sources(config_path)

    official_sources: List[Dict[str, Any]] = []
    internet_sources: List[Dict[str, Any]] = []
    direct_read_sources: List[Dict[str, Any]] = []
    search_queries: List[Dict[str, Any]] = []

    category_default_count = default_source_count(config_name)

    for source in sources:
        if not isinstance(source, dict) or "type" not in source:
            continue
        item = new_web_plan_item(poi, source, config_name)
        if source["type"] == "official":
            official_sources.append(item)
        elif source["type"] == "internet":
            internet_sources.append(item)
        host_info = get_url_host_info(str(source.get("url", "")))
        if source_allows_direct_read(source, host_info):
            direct_item = {
                "source_name": str(source.get("name", "")),
                "source_type": str(source.get("type", "")),
                "source_url": str(source.get("url", "")),
                "target_poi_name": str(poi["name"]),
                "target_city": str(poi["city"]),
                "target_poi_type": str(poi["poi_type"]),
                "weight": float(source.get("weight", get_source_type_weight(str(source.get("type", ""))))),
                "mode": "direct_read",
                "read_intents": [intent for _, intent in GOVERNMENT_QUERY_INTENTS] if config_name == "government" else None,
            }
            direct_read_sources.append(direct_item)
        else:
            search_queries.extend(
                build_search_queries_for_source(
                    poi=poi,
                    source=source,
                    config_category=config_name,
                    host_info=host_info,
                    default_count=category_default_count,
                )
            )

    if category_default_count is not None:
        for item in official_sources + internet_sources:
            if item.get("count") is None:
                item["count"] = category_default_count

    if normalize_whitespace(poi.get("website")):
        host_info = get_url_host_info(str(poi["website"]))
        website_source = {
            "source_name": "输入POI官网",
            "source_type": "official",
            "source_url": str(poi["website"]),
            "target_poi_name": str(poi["name"]),
            "target_city": str(poi["city"]),
            "target_poi_type": str(poi["poi_type"]),
            "weight": 1.0,
            "mode": "direct_read" if host_info["can_fetch_direct"] else "search_discovery",
            "domain": host_info["host"] if host_info["can_filter_domain"] else None,
            "query": normalize_whitespace(f"{poi['city']} {poi['name']} 官网"),
        }
        if category_default_count is not None:
            website_source["count"] = category_default_count
        official_sources = [website_source, *official_sources]
        if host_info["can_fetch_direct"]:
            direct_read_sources = [
                {
                    "source_name": "输入POI官网",
                    "source_type": "official",
                    "source_url": str(poi["website"]),
                    "target_poi_name": str(poi["name"]),
                    "target_city": str(poi["city"]),
                    "target_poi_type": str(poi["poi_type"]),
                    "weight": 1.0,
                    "mode": "direct_read",
                    "read_intents": [intent for _, intent in GOVERNMENT_QUERY_INTENTS] if config_name == "government" else None,
                },
                *direct_read_sources,
            ]
        if not host_info["can_fetch_direct"]:
            website_search_queries = build_search_queries_for_source(
                poi=poi,
                source={
                    "name": "输入POI官网",
                    "type": "official",
                    "url": str(poi["website"]),
                    "weight": 1.0,
                    "count": category_default_count,
                },
                config_category=config_name,
                host_info=host_info,
                default_count=category_default_count,
            )
            search_queries = [*website_search_queries, *search_queries]

    search_queries = dedupe_search_queries(search_queries)
    for index, query_item in enumerate(search_queries):
        query_item["query_id"] = f"QRY_{index + 1:03d}"

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
        "direct_read_sources": direct_read_sources,
        "search_queries": search_queries,
    }

    write_json_file(plan, args.OutputPath)
    result = {
        "status": "ok",
        "result_path": str(Path(args.OutputPath).resolve()),
        "config_category": config_name,
        "official_count": len(official_sources),
        "internet_count": len(internet_sources),
        "direct_read_count": len(direct_read_sources),
        "search_query_count": len(search_queries),
        "summary_text": (
            f"检索计划生成完成：类目={config_name}，"
            f"官方源 {len(official_sources)} 个，"
            f"互联网源 {len(internet_sources)} 个，"
            f"直读源 {len(direct_read_sources)} 个，"
            f"查询 {len(search_queries)} 条。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
