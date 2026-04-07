#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "evidence-collection" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from run_context import attach_context
from evidence_collection_common import (
    ensure_stdout_utf8,
    get_named_section_config,
    limit_text,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)


def log_progress(message: str) -> None:
    sys.stderr.write(f"[webreader] {message}\n")
    sys.stderr.flush()


def _http_get_json(uri: str, timeout_seconds: int) -> Dict[str, Any]:
    context = ssl._create_unverified_context()
    request = urllib.request.Request(uri, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("webreader response must be a JSON object")
    return payload


def _build_request_uri(
    *,
    base_url: str,
    source: str,
    target_url: str,
    timeout_seconds: int,
    user_query: Optional[str],
) -> str:
    params: Dict[str, Any] = {
        "url": target_url,
        "source": source,
        "timeout": timeout_seconds,
    }
    if source == "tavily" and normalize_whitespace(user_query):
        params["user_query"] = normalize_whitespace(user_query)
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def _normalize_jina_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    title = normalize_whitespace(data.get("title"))
    description = normalize_whitespace(data.get("description"))
    content = normalize_whitespace(data.get("content"))
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    external = data.get("external") if isinstance(data.get("external"), dict) else {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    status_value = payload.get("status")
    code_value = payload.get("code")
    ok = (
        str(code_value) in {"200", "20000"}
        and str(status_value) in {"200", "20000"}
        and bool(content)
    )
    if not ok:
        error_reason = f"jina_failed code={code_value} status={status_value}"
        if str(code_value) in {"200", "20000"} and str(status_value) in {"200", "20000"} and not content:
            error_reason = "jina_empty_content"
        return {
            "status": "failed",
            "error_message": error_reason,
            "title": title,
            "description": description,
            "content": content,
            "metadata": metadata,
            "external": external,
            "tokens": usage.get("tokens"),
            "url": normalize_whitespace(data.get("url")),
        }
    return {
        "status": "ok",
        "title": title,
        "description": description,
        "content": content,
        "metadata": metadata,
        "external": external,
        "tokens": usage.get("tokens"),
        "url": normalize_whitespace(data.get("url")),
    }


def _normalize_tavily_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    first_result = results[0] if results and isinstance(results[0], dict) else {}
    title = normalize_whitespace(first_result.get("title"))
    content = normalize_whitespace(first_result.get("raw_content"))
    if not content:
        return {
            "status": "failed",
            "error_message": "tavily_empty_content",
            "title": title,
            "description": None,
            "content": None,
            "metadata": {},
            "external": {},
            "tokens": None,
            "url": normalize_whitespace(first_result.get("url")),
            "request_id": normalize_whitespace(payload.get("request_id")),
        }
    return {
        "status": "ok",
        "title": title,
        "description": None,
        "content": content,
        "metadata": {"images": first_result.get("images")},
        "external": {},
        "tokens": None,
        "url": normalize_whitespace(first_result.get("url")),
        "request_id": normalize_whitespace(payload.get("request_id")),
    }


def _normalize_provider_result(provider: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if provider == "jina":
        return _normalize_jina_result(payload)
    if provider == "tavily":
        return _normalize_tavily_result(payload)
    raise ValueError(f"unsupported provider: {provider}")


def _execute_one_target(
    *,
    base_url: str,
    provider: str,
    target: Dict[str, Any],
    timeout_seconds: int,
) -> Dict[str, Any]:
    read_url = str(target.get("source_url"))
    read_intents = target.get("read_intents") if isinstance(target.get("read_intents"), list) else []
    tavily_user_query = "；".join([str(item) for item in read_intents if normalize_whitespace(item)]) if provider == "tavily" else None
    request_uri = _build_request_uri(
        base_url=base_url,
        source=provider,
        target_url=read_url,
        timeout_seconds=timeout_seconds,
        user_query=tavily_user_query,
    )
    try:
        response_payload = _http_get_json(request_uri, timeout_seconds)
        normalized = _normalize_provider_result(provider, response_payload)
    except Exception as exc:
        normalized = {
            "status": "failed",
            "error_message": str(exc),
            "title": None,
            "description": None,
            "content": None,
            "metadata": {},
            "external": {},
            "tokens": None,
            "url": read_url,
        }

    metadata: Dict[str, Any] = {
        "signal_origin": "webreader_raw",
        "webreader_provider": provider,
        "webreader_request_url": request_uri,
        "read_reason": target.get("read_reason"),
        "read_intents": read_intents or None,
        "enhances_result_id": target.get("enhances_result_id"),
        "source_domain": urllib.parse.urlparse(read_url).netloc or None,
        "page_title": normalized.get("title"),
        "text_snippet": limit_text(normalized.get("description") or normalized.get("content"), 280),
    }
    if normalized.get("tokens") is not None:
        metadata["webreader_tokens"] = normalized.get("tokens")
    if normalized.get("request_id") is not None:
        metadata["request_id"] = normalized.get("request_id")

    return {
        "read_id": target.get("read_id"),
        "source": {
            "source_id": f"WEBREADER_{target.get('read_id')}",
            "source_name": target.get("source_name") or "webreader",
            "source_type": target.get("source_type") or "internet",
            "source_url": read_url,
            "weight": 0.65,
        },
        "metadata": metadata,
        "raw_page": {
            "url": normalized.get("url") or read_url,
            "title": normalized.get("title"),
            "description": normalized.get("description"),
            "content": normalized.get("content"),
            "metadata": normalized.get("metadata"),
            "external": normalized.get("external"),
        },
        "status": normalized.get("status"),
        "error_message": normalized.get("error_message"),
        "provider": provider,
        "collected_at": utc_iso_now(),
    }


def _execute_provider_batch(
    *,
    base_url: str,
    provider: str,
    targets: List[Dict[str, Any]],
    timeout_seconds: int,
    max_workers: int,
) -> List[Dict[str, Any]]:
    if not targets:
        return []
    workers = min(max(1, len(targets)), max(1, max_workers))
    results: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _execute_one_target,
                base_url=base_url,
                provider=provider,
                target=target,
                timeout_seconds=timeout_seconds,
            )
            for target in targets
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    result_map = {str(item.get("read_id")): item for item in results}
    return [result_map[str(target.get("read_id"))] for target in targets if str(target.get("read_id")) in result_map]


def _resolve_runtime_config(
    common_config_path: Optional[str],
    cli_timeout_seconds: Optional[int],
    cli_max_workers: Optional[int],
) -> Tuple[str, int, int, str, str]:
    reader_config = get_named_section_config("internal_webreader", config_path=common_config_path)
    base_url = normalize_whitespace(reader_config.get("base_url"))
    if not base_url:
        raise ValueError("internal_webreader.base_url is required")
    timeout_seconds = cli_timeout_seconds if cli_timeout_seconds is not None else int(reader_config.get("timeout") or 30)
    max_workers = cli_max_workers if cli_max_workers is not None else int(reader_config.get("max_workers") or 8)
    preferred_source = normalize_whitespace(reader_config.get("preferred_source")) or "jina"
    fallback_source = normalize_whitespace(reader_config.get("fallback_source")) or "tavily"
    return base_url, timeout_seconds, max_workers, preferred_source, fallback_source


def execute_webreader_plan(
    *,
    webreader_plan: Dict[str, Any],
    base_url: str,
    timeout_seconds: int,
    max_workers: int,
    preferred_source: str,
    fallback_source: str,
) -> Dict[str, Any]:
    read_targets = webreader_plan.get("read_targets") if isinstance(webreader_plan.get("read_targets"), list) else []
    normalized_targets = [target for target in read_targets if isinstance(target, dict) and normalize_whitespace(target.get("source_url"))]
    if not normalized_targets:
        return {
            "status": "empty",
            "collected_at": utc_iso_now(),
            "items": [],
            "failed_items": [],
            "provider_attempts": [],
        }

    log_progress(f"第一阶段并发读取 provider={preferred_source} target_count={len(normalized_targets)}")
    first_results = _execute_provider_batch(
        base_url=base_url,
        provider=preferred_source,
        targets=normalized_targets,
        timeout_seconds=timeout_seconds,
        max_workers=max_workers,
    )
    failed_targets = [
        target
        for target, result in zip(normalized_targets, first_results)
        if str(result.get("status")) != "ok"
    ]
    provider_attempts: List[Dict[str, Any]] = []
    provider_attempts.extend(
        [
            {
                "read_id": item.get("read_id"),
                "provider": preferred_source,
                "status": item.get("status"),
                "error_message": item.get("error_message"),
            }
            for item in first_results
        ]
    )

    merged_result_map = {str(item.get("read_id")): item for item in first_results}
    fallback_results: List[Dict[str, Any]] = []
    if failed_targets:
        log_progress(f"第二阶段并发回退 provider={fallback_source} fallback_target_count={len(failed_targets)}")
        fallback_results = _execute_provider_batch(
            base_url=base_url,
            provider=fallback_source,
            targets=failed_targets,
            timeout_seconds=timeout_seconds,
            max_workers=max_workers,
        )
        provider_attempts.extend(
            [
                {
                    "read_id": item.get("read_id"),
                    "provider": fallback_source,
                    "status": item.get("status"),
                    "error_message": item.get("error_message"),
                }
                for item in fallback_results
            ]
        )
        for item in fallback_results:
            if str(item.get("status")) == "ok":
                merged_result_map[str(item.get("read_id"))] = item

    ordered_results = [
        merged_result_map[str(target.get("read_id"))]
        for target in normalized_targets
        if str(target.get("read_id")) in merged_result_map
    ]
    success_items = [item for item in ordered_results if str(item.get("status")) == "ok"]
    failed_items = [item for item in ordered_results if str(item.get("status")) != "ok"]
    status = "ok" if len(success_items) == len(ordered_results) else "partial" if success_items else "empty"
    return {
        "status": status,
        "collected_at": utc_iso_now(),
        "items": success_items,
        "failed_items": failed_items,
        "provider_attempts": provider_attempts,
    }


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-WebReaderPlanPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    parser.add_argument("-CommonConfigPath")
    parser.add_argument("-TimeoutSeconds", type=int)
    parser.add_argument("-MaxWorkers", type=int)
    parser.add_argument("-DebugLogPath")
    args = parser.parse_args()

    webreader_plan = read_json_file(args.WebReaderPlanPath)
    if not isinstance(webreader_plan, dict):
        raise ValueError("webreader plan must be a JSON object")

    base_url, timeout_seconds, max_workers, preferred_source, fallback_source = _resolve_runtime_config(
        args.CommonConfigPath,
        args.TimeoutSeconds,
        args.MaxWorkers,
    )
    payload = execute_webreader_plan(
        webreader_plan=webreader_plan,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_workers=max_workers,
        preferred_source=preferred_source,
        fallback_source=fallback_source,
    )
    payload["runtime"] = {
        "base_url": base_url,
        "timeout_seconds": timeout_seconds,
        "max_workers": max_workers,
        "preferred_source": preferred_source,
        "fallback_source": fallback_source,
    }
    if args.RunId and args.PoiId:
        payload = attach_context(payload, args.RunId, args.PoiId, task_id=args.TaskId)
    write_json_file(payload, args.OutputPath)

    if args.DebugLogPath:
        write_json_file(
            {
                "status": payload["status"],
                "result_path": str(Path(args.OutputPath).resolve()),
                "item_count": len(payload.get("items") or []),
                "failed_count": len(payload.get("failed_items") or []),
                "provider_attempts": payload.get("provider_attempts", []),
                "runtime": payload.get("runtime", {}),
            },
            args.DebugLogPath,
        )

    result = {
        "status": payload["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "item_count": len(payload.get("items") or []),
        "failed_count": len(payload.get("failed_items") or []),
        "summary_text": (
            f"webreader 完成：成功 {len(payload.get('items') or [])} 条，"
            f"失败 {len(payload.get('failed_items') or [])} 条，状态={payload['status']}。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["status"] in {"ok", "partial", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
