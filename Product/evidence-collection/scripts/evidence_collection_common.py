#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union


ALLOWED_SOURCE_TYPES = {"official", "map_vendor", "internet", "user_contributed", "other"}
UTC_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UTC_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
TRACKING_QUERY_KEYS = {
    "spm",
    "from",
    "fromid",
    "source",
    "page",
    "page_index",
    "pageindex",
    "pn",
    "p",
}
HOMEPAGE_FILE_NAMES = {"index", "home", "homepage", "default", "main"}


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
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime(UTC_ISO_FORMAT)


def utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime(UTC_STAMP_FORMAT)


def normalize_input_poi(poi: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(poi)
    if "id" not in normalized and normalized.get("poi_id"):
        normalized["id"] = str(normalized["poi_id"])
    if "coordinates" not in normalized and normalized.get("x_coord") is not None and normalized.get("y_coord") is not None:
        normalized["coordinates"] = {
            "longitude": float(normalized["x_coord"]),
            "latitude": float(normalized["y_coord"]),
        }
    return normalized


def normalize_whitespace(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return None
    return re.sub(r"\s+", " ", text).strip()


def normalize_punctuation(value: Any) -> Optional[str]:
    return normalize_whitespace(value)


def normalize_text(value: Any) -> Optional[str]:
    return normalize_punctuation(value)


def normalize_source_token(value: Any) -> str:
    text = normalize_whitespace(value)
    if not text:
        return "UNKNOWN"
    token = re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")
    if not token:
        return "UNKNOWN"
    return token[:48]


def new_source_id(prefix: str, token: Any) -> str:
    value = f"{normalize_source_token(prefix)}_{normalize_source_token(token)}"
    return value[:64]


def get_source_type_weight(source_type: Optional[str]) -> float:
    mapping = {
        "official": 1.0,
        "map_vendor": 0.85,
        "internet": 0.6,
        "user_contributed": 0.5,
    }
    return mapping.get(source_type or "", 0.4)


def get_source_type_rank(source_type: Optional[str]) -> int:
    mapping = {
        "official": 1,
        "map_vendor": 2,
        "internet": 3,
        "user_contributed": 4,
    }
    return mapping.get(source_type or "", 5)


def get_map_vendor_definition(source: str) -> dict[str, Any]:
    definitions = {
        "amap": {
            "source": "amap",
            "proxy_source": "amap2",
            "source_id_prefix": "AMAP",
            "name": "高德地图",
            "weight": 0.85,
            "url": "https://www.amap.com/",
            "endpoint": "https://restapi.amap.com/v3/place/text",
            "default_coordinate_system": "GCJ02",
            "credential_field": "key",
        },
        "bmap": {
            "source": "bmap",
            "proxy_source": "bmap",
            "source_id_prefix": "BMAP",
            "name": "百度地图",
            "weight": 0.85,
            "url": "https://map.baidu.com/",
            "endpoint": "https://api.map.baidu.com/place/v2/search",
            "default_coordinate_system": "BD09",
            "credential_field": "ak",
        },
        "qmap": {
            "source": "qmap",
            "proxy_source": "qmap",
            "source_id_prefix": "QMAP",
            "name": "腾讯地图",
            "weight": 0.8,
            "url": "https://map.qq.com/",
            "endpoint": "https://apis.map.qq.com/ws/place/v1/search",
            "default_coordinate_system": "GCJ02",
            "credential_field": "key",
        },
    }
    if source not in definitions:
        raise ValueError(f"Unsupported map vendor: {source}")
    return dict(definitions[source])


def split_location_string(location: Optional[str]) -> Optional[Dict[str, float]]:
    if not location:
        return None
    parts = [part.strip() for part in location.split(",")]
    if len(parts) < 2:
        return None
    try:
        return {"longitude": float(parts[0]), "latitude": float(parts[1])}
    except ValueError:
        return None


def _is_out_of_china(longitude: float, latitude: float) -> bool:
    return longitude < 72.004 or longitude > 137.4047 or latitude < 0.8293 or latitude > 55.8271


def _lat_offset(longitude: float, latitude: float) -> float:
    value = -100.0 + 2.0 * longitude + 3.0 * latitude + 0.2 * latitude * latitude + 0.1 * longitude * latitude + 0.2 * math.sqrt(abs(longitude))
    value += (20.0 * math.sin(6.0 * longitude * math.pi / 180.0) + 20.0 * math.sin(2.0 * longitude * math.pi / 180.0)) * 2.0 / 3.0
    value += (20.0 * math.sin(latitude * math.pi / 180.0) + 40.0 * math.sin(latitude / 3.0 * math.pi / 180.0)) * 2.0 / 3.0
    value += (160.0 * math.sin(latitude / 12.0 * math.pi / 180.0) + 320.0 * math.sin(latitude * math.pi / 180.0 / 30.0)) * 2.0 / 3.0
    return value


def _lon_offset(longitude: float, latitude: float) -> float:
    value = 300.0 + longitude + 2.0 * latitude + 0.1 * longitude * longitude + 0.1 * longitude * latitude + 0.1 * math.sqrt(abs(longitude))
    value += (20.0 * math.sin(6.0 * longitude * math.pi / 180.0) + 20.0 * math.sin(2.0 * longitude * math.pi / 180.0)) * 2.0 / 3.0
    value += (20.0 * math.sin(longitude * math.pi / 180.0) + 40.0 * math.sin(longitude / 3.0 * math.pi / 180.0)) * 2.0 / 3.0
    value += (150.0 * math.sin(longitude / 12.0 * math.pi / 180.0) + 300.0 * math.sin(longitude / 30.0 * math.pi / 180.0)) * 2.0 / 3.0
    return value


def convert_wgs84_to_gcj02(longitude: float, latitude: float) -> dict[str, float]:
    if _is_out_of_china(longitude, latitude):
        return {"longitude": longitude, "latitude": latitude}
    a = 6378245.0
    ee = 0.00669342162296594323
    d_lat = _lat_offset(longitude - 105.0, latitude - 35.0)
    d_lon = _lon_offset(longitude - 105.0, latitude - 35.0)
    rad_lat = latitude / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return {"longitude": longitude + d_lon, "latitude": latitude + d_lat}


def convert_bd09_to_gcj02(longitude: float, latitude: float) -> dict[str, float]:
    x = longitude - 0.0065
    y = latitude - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi)
    return {"longitude": z * math.cos(theta), "latitude": z * math.sin(theta)}


def normalize_coordinates(coordinates: Any, default_system: str = "GCJ02") -> Optional[Dict[str, float]]:
    if coordinates is None:
        return None

    longitude: Optional[float] = None
    latitude: Optional[float] = None
    coordinate_system = default_system

    if isinstance(coordinates, str):
        parsed = split_location_string(coordinates)
        if not parsed:
            return None
        longitude = parsed["longitude"]
        latitude = parsed["latitude"]
    elif isinstance(coordinates, dict):
        coord_system_value = normalize_whitespace(coordinates.get("coordinate_system"))
        if coord_system_value:
            coordinate_system = coord_system_value
        for candidate in ("longitude", "lng", "x"):
            value = coordinates.get(candidate)
            if value is not None:
                longitude = float(value)
                break
        for candidate in ("latitude", "lat", "y"):
            value = coordinates.get(candidate)
            if value is not None:
                latitude = float(value)
                break
        if (longitude is None or latitude is None) and coordinates.get("location") is not None:
            return normalize_coordinates(coordinates["location"], default_system=coordinate_system)
    else:
        return None

    if longitude is None or latitude is None:
        return None

    system = coordinate_system.upper()
    if system == "WGS84":
        normalized = convert_wgs84_to_gcj02(longitude, latitude)
    elif system == "BD09":
        normalized = convert_bd09_to_gcj02(longitude, latitude)
    else:
        normalized = {"longitude": longitude, "latitude": latitude}

    return {
        "longitude": round(float(normalized["longitude"]), 6),
        "latitude": round(float(normalized["latitude"]), 6),
    }


def convert_map_vendor_api_response(source: str, response: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if source == "amap":
        if str(response.get("status")) != "1":
            return []
        for poi in response.get("pois", []):
            if not isinstance(poi, dict):
                continue
            items.append(
                {
                    "vendor_item_id": poi.get("id"),
                    "name": normalize_text(poi.get("name")),
                    "address": normalize_text(poi.get("address")),
                    "coordinates": normalize_coordinates(poi.get("location"), default_system="GCJ02"),
                    "phone": normalize_text(poi.get("tel")),
                    "category": normalize_text(poi.get("type")),
                    "administrative": {
                        "province": normalize_text(poi.get("pname")),
                        "city": normalize_text(poi.get("cityname")),
                        "district": normalize_text(poi.get("adname")),
                    },
                    "raw_data": poi,
                }
            )
        return items

    if source == "bmap":
        if str(response.get("status")) != "0":
            return []
        for poi in response.get("results", []):
            if not isinstance(poi, dict):
                continue
            detail_info = poi.get("detail_info") if isinstance(poi.get("detail_info"), dict) else {}
            items.append(
                {
                    "vendor_item_id": poi.get("uid"),
                    "name": normalize_text(poi.get("name")),
                    "address": normalize_text(poi.get("address")),
                    "coordinates": normalize_coordinates(poi.get("location"), default_system="BD09"),
                    "phone": normalize_text(poi.get("telephone")),
                    "category": normalize_text(detail_info.get("tag")),
                    "administrative": {
                        "province": None,
                        "city": normalize_text(poi.get("city")),
                        "district": normalize_text(poi.get("area")),
                    },
                    "raw_data": poi,
                }
            )
        return items

    if source == "qmap":
        if str(response.get("status")) != "0":
            return []
        for poi in response.get("data", []):
            if not isinstance(poi, dict):
                continue
            ad_info = poi.get("ad_info") if isinstance(poi.get("ad_info"), dict) else {}
            items.append(
                {
                    "vendor_item_id": poi.get("id"),
                    "name": normalize_text(poi.get("title")),
                    "address": normalize_text(poi.get("address")),
                    "coordinates": normalize_coordinates(poi.get("location"), default_system="GCJ02"),
                    "phone": normalize_text(poi.get("tel")),
                    "category": normalize_text(poi.get("category") or poi.get("type")),
                    "administrative": {
                        "province": normalize_text(ad_info.get("province")),
                        "city": normalize_text(ad_info.get("city")),
                        "district": normalize_text(ad_info.get("district")),
                    },
                    "raw_data": poi,
                }
            )
        return items

    raise ValueError(f"Unsupported map vendor: {source}")


def new_map_vendor_evidence_seed(poi: dict[str, Any], source: str, item: dict[str, Any], branch: str) -> dict[str, Any]:
    definition = get_map_vendor_definition(source)
    source_token = item.get("vendor_item_id") or item.get("name")
    data: dict[str, Any] = {"name": normalize_text(item.get("name"))}
    if normalize_text(item.get("address")):
        data["address"] = normalize_text(item.get("address"))
    if isinstance(item.get("coordinates"), dict):
        data["coordinates"] = item["coordinates"]
    if normalize_text(item.get("phone")):
        data["phone"] = normalize_text(item.get("phone"))
    if normalize_text(item.get("category")):
        data["category"] = normalize_text(item.get("category"))
    if isinstance(item.get("administrative"), dict):
        data["administrative"] = item["administrative"]
    if isinstance(item.get("raw_data"), dict):
        data["raw_data"] = item["raw_data"]

    authority_signals = collect_authority_signals((item.get("name"), item.get("category"), item.get("address")))
    return {
        "poi_id": str(poi["id"]),
        "source": {
            "source_id": new_source_id(definition["source_id_prefix"], source_token),
            "source_name": str(definition["name"]),
            "source_type": "map_vendor",
            "source_url": str(definition["url"]),
            "weight": float(definition["weight"]),
        },
        "collected_at": utc_iso_now(),
        "data": data,
        "verification": {
            "is_valid": True,
            "confidence": float(definition["weight"]),
        },
        "metadata": {
            "collection_method": "api",
            "collection_branch": branch,
            "map_source": source,
            "signal_origin": "map_vendor",
            "source_domain": extract_source_domain(definition["url"]),
            "page_title": limit_text(item.get("name"), 120),
            "text_snippet": limit_text(item.get("category") or item.get("address")),
            "authority_signals": authority_signals or None,
        },
    }


def new_generic_evidence_seed(poi: dict[str, Any], item: dict[str, Any], branch: str) -> dict[str, Any]:
    source_input = item.get("source") if isinstance(item.get("source"), dict) else {}
    source_type = source_input.get("source_type") or item.get("source_type") or item.get("type") or "other"
    if source_type not in ALLOWED_SOURCE_TYPES:
        source_type = "other"

    source_name = source_input.get("source_name") or item.get("source_name") or item.get("name") or branch
    source_url = source_input.get("source_url") or item.get("source_url") or item.get("url")
    source_id = source_input.get("source_id") or item.get("source_id") or new_source_id(source_type, source_name)
    weight = float(source_input.get("weight") or item.get("weight") or get_source_type_weight(source_type))

    if isinstance(item.get("data"), dict):
        data_input = item["data"]
    elif isinstance(item.get("normalized_data"), dict):
        data_input = item["normalized_data"]
    else:
        data_input = item

    name = data_input.get("name") or item.get("title")
    data: dict[str, Any] = {"name": normalize_text(name)}
    for field in ("address", "phone", "category", "status", "level"):
        if normalize_text(data_input.get(field)):
            data[field] = normalize_text(data_input.get(field))

    coordinates_input = data_input.get("coordinates")
    if coordinates_input is None:
        coordinates_input = item.get("coordinates")
    if coordinates_input is None:
        coordinates_input = item.get("location")
    coordinates = normalize_coordinates(coordinates_input, default_system="GCJ02")
    if coordinates is not None:
        data["coordinates"] = coordinates

    if isinstance(data_input.get("administrative"), dict):
        data["administrative"] = data_input["administrative"]

    if isinstance(data_input.get("raw_data"), dict):
        data["raw_data"] = data_input["raw_data"]
    else:
        data["raw_data"] = item

    verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
    if "confidence" not in verification:
        verification = {
            "is_valid": True,
            "confidence": weight,
        }

    metadata = dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
    metadata.setdefault("signal_origin", infer_signal_origin(branch))
    metadata.setdefault("source_domain", extract_source_domain(source_url))
    metadata.setdefault("page_title", limit_text(item.get("title") or item.get("page_title"), 120))
    metadata.setdefault(
        "text_snippet",
        limit_text(
            item.get("content")
            or item.get("snippet")
            or data_input.get("text_snippet")
            or data_input.get("address")
            or data_input.get("category")
        ),
    )
    metadata.setdefault("level_hint", normalize_level_hint(data_input.get("level_hint") or metadata.get("level_hint") or item.get("level_hint")))
    metadata.setdefault(
        "authority_signals",
        collect_authority_signals(
            (
                data_input.get("name"),
                data_input.get("category"),
                data_input.get("address"),
                metadata.get("page_title"),
                metadata.get("text_snippet"),
            )
        )
        or None,
    )
    metadata["collection_branch"] = branch
    if "collection_method" not in metadata:
        metadata["collection_method"] = "crawl" if branch in {"webfetch", "webreader"} else "manual"

    seed = {
        "poi_id": str(poi["id"]),
        "source": {
            "source_id": str(source_id),
            "source_name": normalize_text(source_name),
            "source_type": source_type,
            "weight": round(weight, 4),
        },
        "collected_at": item.get("collected_at") or utc_iso_now(),
        "data": data,
        "verification": verification,
        "metadata": metadata,
    }
    if normalize_whitespace(source_url):
        seed["source"]["source_url"] = str(source_url)
    return seed


def convert_yaml_scalar(value: Optional[str]) -> Any:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return ""
    if (trimmed.startswith('"') and trimmed.endswith('"')) or (trimmed.startswith("'") and trimmed.endswith("'")):
        return trimmed[1:-1]
    if trimmed in {"true", "false"}:
        return trimmed == "true"
    try:
        return float(trimmed)
    except ValueError:
        return trimmed


def get_type_config_sources(config_path: Union[str, Path]) -> List[Dict[str, Any]]:
    file_path = Path(config_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Type config not found: {file_path}")

    lines = file_path.read_text(encoding="utf-8-sig").splitlines()
    in_sources = False
    current: Optional[Dict[str, Any]] = None
    items: list[dict[str, Any]] = []

    for line in lines:
        if not in_sources:
            if re.match(r"^\s*sources:\s*$", line):
                in_sources = True
            continue
        if re.match(r"^\S", line):
            break
        match = re.match(r"^\s*-\s+name:\s*(.+?)\s*$", line)
        if match:
            if current is not None:
                items.append(current)
            current = {"name": convert_yaml_scalar(match.group(1))}
            continue
        if current is None:
            continue
        match = re.match(r"^\s+([A-Za-z_]+):\s*(.*?)\s*$", line)
        if match:
            current[match.group(1)] = convert_yaml_scalar(match.group(2))

    if current is not None:
        items.append(current)
    return items


def get_poi_type_mappings(mapping_path: Union[str, Path]) -> List[Dict[str, Any]]:
    file_path = Path(mapping_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"POI type mapping file not found: {file_path}")

    lines = file_path.read_text(encoding="utf-8-sig").splitlines()
    in_mappings = False
    collect_codes = False
    current: Optional[Dict[str, Any]] = None
    items: list[dict[str, Any]] = []

    for line in lines:
        if not in_mappings:
            if re.match(r"^\s*mappings:\s*$", line):
                in_mappings = True
            continue
        if re.match(r"^\S", line):
            break
        match = re.match(r"^\s{2}([a-z_]+):\s*$", line)
        if match:
            if current is not None:
                items.append(current)
            current = {"name": match.group(1), "type_codes": []}
            collect_codes = False
            continue
        if current is None:
            continue
        if re.match(r"^\s{4}type_codes:\s*$", line):
            collect_codes = True
            continue
        match = re.match(r'^\s{6}-\s*"?([0-9]+)"?\s*(?:#.*)?$', line)
        if collect_codes and match:
            current["type_codes"].append(match.group(1))
            continue
        if re.match(r"^\s{4}[A-Za-z_]+:", line):
            collect_codes = False

    if current is not None:
        items.append(current)
    return items


def resolve_poi_type_category(poi_type: str, mapping_path: Union[str, Path]) -> Optional[str]:
    for mapping in get_poi_type_mappings(mapping_path):
        type_codes = sorted(mapping["type_codes"], key=len, reverse=True)
        for code in type_codes:
            if poi_type == code:
                return str(mapping["name"])
        for code in type_codes:
            if poi_type.startswith(code):
                return str(mapping["name"])
    return None


def get_url_host_info(url: Optional[str]) -> Dict[str, Any]:
    result = {
        "raw_url": url,
        "host": None,
        "can_fetch_direct": False,
        "can_filter_domain": False,
    }
    if not normalize_whitespace(url):
        return result

    parsed = urllib.parse.urlparse(str(url))
    host = parsed.netloc or None
    result["host"] = host
    if host:
        has_template = bool(re.search(r"\{.+?\}", str(url)))
        result["can_fetch_direct"] = not has_template
        result["can_filter_domain"] = not bool(re.search(r"\{.+?\}", host))
    return result


def normalize_url_for_matching(url: Optional[str]) -> Optional[str]:
    normalized = normalize_whitespace(url)
    if not normalized:
        return None
    parsed = urllib.parse.urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return normalized

    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = []
    for key, value in query_pairs:
        token = key.lower()
        if token.startswith("utm_") or token in TRACKING_QUERY_KEYS:
            continue
        filtered_pairs.append((key, value))

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urllib.parse.urlencode(filtered_pairs),
            "",
        )
    )


def url_looks_like_homepage(url: Optional[str]) -> bool:
    normalized = normalize_url_for_matching(url)
    if not normalized:
        return False
    parsed = urllib.parse.urlparse(normalized)
    path = parsed.path or "/"
    if path in {"", "/"}:
        return True

    trimmed_path = path.rstrip("/")
    if not trimmed_path:
        return True

    last_segment = trimmed_path.rsplit("/", 1)[-1].lower()
    stem, dot, suffix = last_segment.partition(".")
    if stem in HOMEPAGE_FILE_NAMES:
        return True
    if suffix in {"html", "htm", "shtml", "php", "asp", "aspx"} and stem in HOMEPAGE_FILE_NAMES:
        return True
    return False


def extract_source_domain(url: Optional[str]) -> Optional[str]:
    host_info = get_url_host_info(url)
    host = normalize_whitespace(host_info.get("host"))
    return host.lower() if host else None


def limit_text(value: Any, limit: int = 280) -> Optional[str]:
    text = normalize_text(value)
    if not text:
        return None
    return text[:limit]


def normalize_level_hint(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if not text:
        return None
    mapping = {
        "国家级": ("国务院", "国家级"),
        "省级": ("省级", "自治区级", "直辖市级", "省人民政府", "自治区人民政府"),
        "地市级": ("地市级", "市级", "市人民政府"),
        "区县级": ("区县级", "区级", "县级", "区人民政府", "县人民政府"),
        "乡镇级": ("乡镇级", "乡级", "镇级", "乡人民政府", "镇人民政府", "街道", "街道办事处"),
        "乡镇以下级": ("乡镇以下级", "社区", "村委", "居委", "社区居民委员会", "村民委员会"),
    }
    for level_label, keys in mapping.items():
        if any(key in text for key in keys):
            return level_label
    return None


def collect_authority_signals(values: Iterable[Any]) -> list[str]:
    keywords = (
        "人民政府",
        "国务院",
        "公安局",
        "派出所",
        "人民检察院",
        "检察院",
        "人民法院",
        "中级人民法院",
        "高级人民法院",
        "基层人民法院",
        "街道办事处",
        "居民委员会",
        "村民委员会",
        "乡人民政府",
        "镇人民政府",
    )
    merged_text = " ".join(text for text in (normalize_text(value) for value in values) if text)
    if not merged_text:
        return []
    return [keyword for keyword in keywords if keyword in merged_text]


def infer_signal_origin(branch: Optional[str]) -> str:
    mapping = {
        "websearch": "websearch",
        "webfetch": "webfetch",
        "webreader": "webreader",
        "map_vendor": "map_vendor",
        "internal_proxy": "map_vendor",
        "vendor_fallback": "map_vendor",
    }
    return mapping.get(str(branch or "").strip(), "websearch")


def to_item_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_generic_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("evidence_list", "items", "records"):
            if key in payload:
                return to_item_array(payload[key])
    return []


def sanitize_evidence_seed(seed: dict[str, Any]) -> dict[str, Any]:
    source_in = seed.get("source") if isinstance(seed.get("source"), dict) else {}
    source_type = source_in.get("source_type") if source_in.get("source_type") in ALLOWED_SOURCE_TYPES else "other"
    source = {
        "source_id": source_in.get("source_id") or new_source_id(source_type, "UNKNOWN"),
        "source_name": normalize_text(source_in.get("source_name")),
        "source_type": source_type,
        "weight": float(source_in.get("weight", get_source_type_weight(source_type))),
    }
    if normalize_whitespace(source_in.get("source_url")):
        source["source_url"] = str(source_in["source_url"])

    data_in = seed.get("data") if isinstance(seed.get("data"), dict) else {}
    data = {"name": normalize_text(data_in.get("name"))}
    for field in ("address", "phone", "category", "status", "level"):
        if normalize_text(data_in.get(field)):
            data[field] = normalize_text(data_in.get(field))
    if isinstance(data_in.get("coordinates"), dict):
        normalized_coords = normalize_coordinates(data_in["coordinates"], default_system="GCJ02")
        if normalized_coords is not None:
            data["coordinates"] = normalized_coords
    if isinstance(data_in.get("administrative"), dict):
        data["administrative"] = data_in["administrative"]
    if isinstance(data_in.get("raw_data"), dict):
        data["raw_data"] = data_in["raw_data"]

    sanitized = {
        "poi_id": str(seed["poi_id"]),
        "source": source,
        "collected_at": seed.get("collected_at") or utc_iso_now(),
        "data": data,
    }
    for field in ("verification", "matching", "metadata"):
        if isinstance(seed.get(field), dict):
            sanitized[field] = seed[field]
    return sanitized


def test_evidence_seed(seed: dict[str, Any], poi_id: str, label: str, errors: list[str]) -> None:
    if str(seed.get("poi_id")) != poi_id:
        errors.append(f"{label}.poi_id must match input id")

    source = seed.get("source") if isinstance(seed.get("source"), dict) else {}
    for field in ("source_id", "source_name", "source_type"):
        if not normalize_whitespace(source.get(field)):
            errors.append(f"{label}.source.{field} is required")
    if source.get("source_type") not in ALLOWED_SOURCE_TYPES:
        errors.append(f"{label}.source.source_type is invalid")

    data = seed.get("data") if isinstance(seed.get("data"), dict) else {}
    if not normalize_whitespace(data.get("name")):
        errors.append(f"{label}.data.name is required")


def finalize_evidence_seed(seed: dict[str, Any], timestamp: str, index: int) -> dict[str, Any]:
    item = {
        "evidence_id": f"EVD_{timestamp}_{index + 1:03d}",
        "poi_id": str(seed["poi_id"]),
        "source": seed["source"],
        "collected_at": str(seed["collected_at"]),
        "data": seed["data"],
    }
    for field in ("verification", "matching", "metadata"):
        if field in seed:
            item[field] = seed[field]
    return item


def iter_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    result: list[str] = []
    for char in value:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == '#' and not in_single and not in_double:
            break
        result.append(char)
    return ''.join(result).rstrip()


def _clean_yaml_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = _strip_inline_comment(value).strip()
    return cleaned if cleaned else None


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_common_config_path(config_path: Optional[Union[str, Path]] = None) -> Path:
    if config_path is not None:
        return Path(config_path)
    return get_repo_root() / 'evidence-collection' / 'config' / 'common.yaml'


def get_common_config_lines(config_path: Optional[Union[str, Path]] = None) -> List[str]:
    path = get_common_config_path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Common config not found: {path}")
    return path.read_text(encoding='utf-8-sig').splitlines()


def get_internal_proxy_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    return get_named_section_config("internal_proxy", config_path=config_path)


def get_named_section_config(section_name: str, config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    lines = get_common_config_lines(config_path)
    in_section = False
    config: dict[str, Any] = {}
    for line in lines:
        if not in_section:
            if re.match(rf'^\s*{re.escape(section_name)}:\s*$', line):
                in_section = True
            continue
        if re.match(r'^\S', line):
            break
        match = re.match(r'^\s{2}([A-Za-z_]+):\s*(.*?)\s*$', line)
        if not match:
            continue
        key = match.group(1)
        raw_value = _clean_yaml_value(match.group(2))
        config[key] = convert_yaml_scalar(raw_value)
    return config


def get_internal_search_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    return get_named_section_config("internal_search", config_path=config_path)


def get_vendor_credentials(source: str, config_path: Optional[Union[str, Path]] = None) -> List[Dict[str, str]]:
    lines = get_common_config_lines(config_path)
    in_credentials = False
    in_vendor = False
    vendor_indent = None
    current: Optional[Dict[str, str]] = None
    credentials: list[dict[str, str]] = []

    for line in lines:
        if not in_credentials:
            if re.match(r'^\s*credentials:\s*$', line):
                in_credentials = True
            continue

        if re.match(r'^\S', line):
            break

        vendor_match = re.match(r'^\s{2}([A-Za-z0-9_]+):\s*$', line)
        if vendor_match:
            if current is not None and in_vendor:
                credentials.append(current)
                current = None
            in_vendor = vendor_match.group(1) == source
            vendor_indent = len(line) - len(line.lstrip(' '))
            continue

        if not in_vendor:
            continue

        indent = len(line) - len(line.lstrip(' '))
        if vendor_indent is not None and indent <= vendor_indent and line.strip():
            break

        entry_match = re.match(r'^\s*[-]\s*([A-Za-z_]+):\s*(.*?)\s*$', line)
        if entry_match:
            if current is not None:
                credentials.append(current)
            key = entry_match.group(1)
            raw_value = _clean_yaml_value(entry_match.group(2))
            current = {key: '' if raw_value is None else str(convert_yaml_scalar(raw_value))}
            continue

        field_match = re.match(r'^\s+([A-Za-z_]+):\s*(.*?)\s*$', line)
        if field_match and current is not None:
            key = field_match.group(1)
            raw_value = _clean_yaml_value(field_match.group(2))
            current[key] = '' if raw_value is None else str(convert_yaml_scalar(raw_value))

    if current is not None and in_vendor:
        credentials.append(current)
    return credentials


def get_vendor_credential(source: str, config_path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    credentials = get_vendor_credentials(source, config_path)
    if not credentials:
        raise ValueError(f"No credential configured for vendor: {source}")
    return credentials[0]
