#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from run_context import attach_context
from evidence_collection_common import (
    convert_map_vendor_api_response,
    ensure_stdout_utf8,
    get_internal_proxy_config,
    get_map_vendor_definition,
    utc_iso_now,
    write_json_file,
)


VENDORS = ("amap", "bmap", "qmap")


def fetch_proxy_response(base_url: str, vendor: str, city: str, poi_name: str, timeout_seconds: int) -> dict:
    definition = get_map_vendor_definition(vendor)
    params = {
        "source": definition["proxy_source"],
        "method": "text",
        "city": city,
        "keyword": poi_name,
    }
    uri = f"{base_url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(uri, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiName", required=True)
    parser.add_argument("-City", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    parser.add_argument("-CommonConfigPath")
    parser.add_argument("-TimeoutSeconds", type=int)
    args = parser.parse_args()

    proxy_config = get_internal_proxy_config(args.CommonConfigPath)
    base_url = str(proxy_config.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("internal_proxy.base_url is required in common.yaml")
    timeout_seconds = args.TimeoutSeconds if args.TimeoutSeconds is not None else int(proxy_config.get("timeout") or 30)

    vendor_results: dict[str, dict] = {}
    missing_vendors: list[str] = []
    successful_vendors = 0

    for vendor in VENDORS:
        definition = get_map_vendor_definition(vendor)
        vendor_status = "error"
        items: list[dict] = []
        error_message = None

        try:
            raw_response = fetch_proxy_response(base_url, vendor, args.City, args.PoiName, timeout_seconds)
            items = convert_map_vendor_api_response(vendor, raw_response)
            vendor_status = "ok" if items else "empty"
            if vendor_status == "ok":
                successful_vendors += 1
        except Exception as exc:
            error_message = str(exc)

        if vendor_status != "ok":
            missing_vendors.append(vendor)

        vendor_results[vendor] = {
            "vendor": vendor,
            "source_name": str(definition["name"]),
            "requested_via": "internal_proxy",
            "status": vendor_status,
            "result_count": len(items),
            "items": items,
            "error": error_message,
        }

    status = "error" if successful_vendors == 0 else "partial" if missing_vendors else "ok"
    payload = {
        "status": status,
        "query": {
            "city": args.City,
            "poi_name": args.PoiName,
        },
        "collected_at": utc_iso_now(),
        "vendors": vendor_results,
        "missing_vendors": missing_vendors,
    }
    if args.RunId and args.PoiId:
        payload = attach_context(payload, args.RunId, args.PoiId, task_id=args.TaskId)
    write_json_file(payload, args.OutputPath)

    result = {
        "status": status,
        "result_path": str(Path(args.OutputPath).resolve()),
        "missing_vendors": missing_vendors,
        "run_id": str(args.RunId or ""),
        "vendor_counts": {
            "amap": int(vendor_results["amap"]["result_count"]),
            "bmap": int(vendor_results["bmap"]["result_count"]),
            "qmap": int(vendor_results["qmap"]["result_count"]),
        },
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
