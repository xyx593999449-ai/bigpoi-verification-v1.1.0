#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evidence_collection_common import (
    convert_map_vendor_api_response,
    ensure_stdout_utf8,
    get_map_vendor_definition,
    read_json_file,
    utc_iso_now,
    write_json_file,
)


def fetch_vendor_response(source: str, credential: str, city: str, poi_name: str, referer: str | None, timeout_seconds: int) -> dict:
    definition = get_map_vendor_definition(source)
    if source == "amap":
        params = {
            "key": credential,
            "keywords": poi_name,
            "city": city,
            "output": "json",
            "offset": 20,
            "page": 1,
        }
    elif source == "bmap":
        params = {
            "ak": credential,
            "query": poi_name,
            "region": city,
            "output": "json",
            "page_size": 20,
            "page_num": 0,
        }
    else:
        params = {
            "key": credential,
            "keyword": poi_name,
            "boundary": f"region({city},0)",
            "page_size": 20,
            "page_index": 1,
        }

    uri = f"{definition['endpoint']}?{urllib.parse.urlencode(params)}"
    headers = {}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(uri, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiName", required=True)
    parser.add_argument("-City", required=True)
    parser.add_argument("-Source", required=True, choices=["amap", "bmap", "qmap"])
    parser.add_argument("-Credential", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-Referer")
    parser.add_argument("-MockResponsePath")
    parser.add_argument("-TimeoutSeconds", type=int, default=30)
    args = parser.parse_args()

    status = "error"
    items: list[dict] = []
    error_message = None

    try:
        raw_response = read_json_file(args.MockResponsePath) if args.MockResponsePath else None
        if raw_response is None:
            raw_response = fetch_vendor_response(args.Source, args.Credential, args.City, args.PoiName, args.Referer, args.TimeoutSeconds)
        items = convert_map_vendor_api_response(args.Source, raw_response)
        status = "ok" if items else "empty"
    except Exception as exc:
        error_message = str(exc)

    payload = {
        "status": status,
        "vendor": args.Source,
        "query": {
            "city": args.City,
            "poi_name": args.PoiName,
        },
        "collected_at": utc_iso_now(),
        "requested_via": "direct_api",
        "result_count": len(items),
        "items": items,
        "error": error_message,
    }
    write_json_file(payload, args.OutputPath)

    result = {
        "status": status,
        "result_path": str(Path(args.OutputPath).resolve()),
        "vendor": args.Source,
        "result_count": len(items),
        "error": error_message,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
