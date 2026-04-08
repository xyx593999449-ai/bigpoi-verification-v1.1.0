#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

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


def log_progress(message: str) -> None:
    sys.stderr.write(f"[map-proxy] {message}\n")
    sys.stderr.flush()


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


def is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def fetch_proxy_response_with_retry(
    base_url: str,
    vendor: str,
    city: str,
    poi_name: str,
    timeout_seconds: int,
    retry_timeout_seconds: int,
) -> dict:
    try:
        return fetch_proxy_response(base_url, vendor, city, poi_name, timeout_seconds)
    except Exception as exc:
        if not is_timeout_exception(exc):
            raise
        log_progress(
            f"图商请求超时，准备重试: vendor={vendor} initial_timeout={timeout_seconds}s retry_timeout={retry_timeout_seconds}s"
        )
        try:
            return fetch_proxy_response(base_url, vendor, city, poi_name, retry_timeout_seconds)
        except Exception as retry_exc:
            if is_timeout_exception(retry_exc):
                raise TimeoutError(
                    f"internal proxy timed out twice for vendor={vendor}: "
                    f"initial_timeout={timeout_seconds}s retry_timeout={retry_timeout_seconds}s"
                ) from retry_exc
            raise


def emit_result(
    *,
    payload: dict,
    output_path: str,
    run_id: str,
) -> int:
    vendor_results = payload.get("vendors") if isinstance(payload.get("vendors"), dict) else {}
    missing_vendors = payload.get("missing_vendors") if isinstance(payload.get("missing_vendors"), list) else []
    write_json_file(payload, output_path)

    result = {
        "status": payload.get("status") or "ok",
        "result_path": str(Path(output_path).resolve()),
        "missing_vendors": missing_vendors,
        "run_id": run_id,
        "vendor_counts": {
            "amap": int((vendor_results.get("amap") or {}).get("result_count") or 0),
            "bmap": int((vendor_results.get("bmap") or {}).get("result_count") or 0),
            "qmap": int((vendor_results.get("qmap") or {}).get("result_count") or 0),
        },
        "summary_text": (
            "图商代理完成："
            f"amap={int((vendor_results.get('amap') or {}).get('result_count') or 0)}，"
            f"bmap={int((vendor_results.get('bmap') or {}).get('result_count') or 0)}，"
            f"qmap={int((vendor_results.get('qmap') or {}).get('result_count') or 0)}，"
            f"缺失图商={','.join(missing_vendors) or 'none'}。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if str(payload.get("status") or "").strip() == "error" else 0


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
    timeout_seconds = args.TimeoutSeconds if args.TimeoutSeconds is not None else int(proxy_config.get("timeout") or 10)
    retry_timeout_seconds = int(proxy_config.get("retry_timeout") or 60)

    vendor_results: dict[str, dict] = {}
    missing_vendors: list[str] = []
    successful_vendors = 0

    for vendor in VENDORS:
        definition = get_map_vendor_definition(vendor)
        vendor_status = "error"
        items: list[dict] = []
        error_message = None
        log_progress(f"请求图商: vendor={vendor} city={args.City} name={args.PoiName}")

        try:
            raw_response = fetch_proxy_response_with_retry(
                base_url,
                vendor,
                args.City,
                args.PoiName,
                timeout_seconds,
                retry_timeout_seconds,
            )
            items = convert_map_vendor_api_response(vendor, raw_response)
            vendor_status = "ok" if items else "empty"
            if vendor_status == "ok":
                successful_vendors += 1
        except Exception as exc:
            if is_timeout_exception(exc):
                raise
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
        log_progress(f"图商完成: vendor={vendor} status={vendor_status} result_count={len(items)}")

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
    return emit_result(payload=payload, output_path=args.OutputPath, run_id=str(args.RunId or ""))


if __name__ == "__main__":
    raise SystemExit(main())
