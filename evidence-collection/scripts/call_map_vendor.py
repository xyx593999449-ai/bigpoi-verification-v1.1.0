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
    get_map_vendor_definition,
    get_vendor_credential,
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
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    parser.add_argument("-Credential")
    parser.add_argument("-Referer")
    parser.add_argument("-CommonConfigPath")
    parser.add_argument("-TimeoutSeconds", type=int, default=30)
    args = parser.parse_args()

    status = "error"
    items: list[dict] = []
    error_message = None

    try:
        referer = args.Referer
        credential = args.Credential
        if not credential:
            credential_info = get_vendor_credential(args.Source, args.CommonConfigPath)
            definition = get_map_vendor_definition(args.Source)
            credential_field = str(definition["credential_field"])
            credential = str(credential_info.get(credential_field) or credential_info.get("ak") or credential_info.get("key") or "").strip()
            if not credential:
                raise ValueError(f"Credential field {credential_field} is missing for vendor: {args.Source}")
            if not referer:
                referer = str(credential_info.get("referer") or "").strip() or None
        raw_response = fetch_vendor_response(args.Source, credential, args.City, args.PoiName, referer, args.TimeoutSeconds)
        items = convert_map_vendor_api_response(args.Source, raw_response)
        status = "ok" if items else "empty"
    except Exception as exc:
        error_message = str(exc)

    payload = {
        "status": status,
        "vendor": args.Source,
        "run_id": str(args.RunId or ""),
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
    if args.RunId and args.PoiId:
        payload = attach_context(payload, args.RunId, args.PoiId, task_id=args.TaskId)
    write_json_file(payload, args.OutputPath)

    result = {
        "status": status,
        "result_path": str(Path(args.OutputPath).resolve()),
        "vendor": args.Source,
        "run_id": str(args.RunId or ""),
        "result_count": len(items),
        "error": error_message,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
