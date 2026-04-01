#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from internal_search_client import normalize_search_items, search_with_provider
from run_context import attach_context
from evidence_collection_common import (
    ensure_stdout_utf8,
    extract_source_domain,
    get_internal_proxy_config,
    get_internal_search_config,
    limit_text,
    normalize_whitespace,
    read_json_file,
    utc_iso_now,
    write_json_file,
)

PROVIDERS = ("baidu", "tavily")


def iter_plan_sources(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in ("official_sources", "internet_sources"):
        items = plan.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                result.append(item)
    return result


def normalize_websearch_item(result: dict[str, Any], plan_source: dict[str, Any], query: str, provider_attempts: list[str]) -> dict[str, Any]:
    source_type = str(plan_source.get("source_type") or "other")
    source_url = result.get("url") or plan_source.get("source_url")
    title = result.get("title") or plan_source.get("source_name")
    snippet = result.get("content")
    return {
        "source": {
            "source_id": f"WEBSEARCH_{source_type}_{result.get('provider')}_{result.get('rank')}",
            "source_name": result.get("source_name") or plan_source.get("source_name") or "websearch",
            "source_type": source_type,
            "source_url": source_url,
            "weight": float(plan_source.get("weight") or 0.6),
        },
        "data": {
            "name": title or query,
            "address": limit_text(snippet, 120),
        },
        "collected_at": utc_iso_now(),
        "metadata": {
            "signal_origin": "websearch",
            "source_domain": extract_source_domain(source_url),
            "page_title": limit_text(title, 120),
            "text_snippet": limit_text(snippet, 280),
            "authority_signals": plan_source.get("authority_signals"),
            "provider": result.get("provider"),
            "provider_attempts": provider_attempts,
            "published_at": result.get("published_at"),
            "query": query,
        },
    }


def search_with_fallback(
    *,
    base_url: str,
    query: str,
    domain: str | None,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    attempts: list[dict[str, Any]] = []
    effective_provider: str | None = None
    final_items: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        try:
            response = search_with_provider(
                base_url=base_url,
                provider=provider,
                query=query,
                domain=domain,
                timeout_seconds=timeout_seconds,
            )
            normalized_items = normalize_search_items(provider, response)
            attempts.append(
                {
                    "provider": provider,
                    "status": "ok" if normalized_items else "empty",
                    "result_count": len(normalized_items),
                }
            )
            if normalized_items:
                effective_provider = provider
                final_items = normalized_items
                break
        except Exception as exc:
            attempts.append(
                {
                    "provider": provider,
                    "status": "error",
                    "result_count": 0,
                    "error": str(exc),
                }
            )
    return attempts, final_items, effective_provider


def execute_websearch_plan(
    *,
    web_plan: dict[str, Any],
    base_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    aggregated_items: list[dict[str, Any]] = []
    provider_attempts: list[dict[str, Any]] = []
    effective_provider_counter: dict[str, int] = {"baidu": 0, "tavily": 0}
    for plan_source in iter_plan_sources(web_plan):
        query = normalize_whitespace(plan_source.get("query"))
        if not query:
            continue
        domain = normalize_whitespace(plan_source.get("domain"))
        attempts, raw_items, effective_provider = search_with_fallback(
            base_url=base_url,
            query=query,
            domain=domain,
            timeout_seconds=timeout_seconds,
        )
        provider_attempts.append(
            {
                "query": query,
                "domain": domain,
                "attempts": attempts,
                "effective_provider": effective_provider,
                "result_count": len(raw_items),
            }
        )
        if effective_provider:
            effective_provider_counter[effective_provider] += 1
        provider_trace = [attempt.get("provider") for attempt in attempts]
        for result in raw_items:
            aggregated_items.append(normalize_websearch_item(result, plan_source, query, provider_trace))

    success_count = sum(1 for item in provider_attempts if item["result_count"] > 0)
    status = "ok" if success_count == len(provider_attempts) else "partial" if success_count > 0 else "empty"
    return {
        "status": status,
        "collected_at": utc_iso_now(),
        "query_count": len(provider_attempts),
        "result_count": len(aggregated_items),
        "effective_provider": (
            "baidu"
            if effective_provider_counter["baidu"] > 0 and effective_provider_counter["tavily"] == 0
            else "tavily"
            if effective_provider_counter["tavily"] > 0 and effective_provider_counter["baidu"] == 0
            else "mixed"
            if effective_provider_counter["baidu"] > 0 and effective_provider_counter["tavily"] > 0
            else None
        ),
        "provider_attempts": provider_attempts,
        "items": aggregated_items,
        "context": {
            "source": "internal_search_proxy",
            "provider_order": list(PROVIDERS),
        },
    }


def resolve_search_runtime_config(common_config_path: str | None, cli_timeout_seconds: int | None) -> tuple[str, int]:
    search_config = get_internal_search_config(common_config_path)
    proxy_config = get_internal_proxy_config(common_config_path)
    base_url = normalize_whitespace(search_config.get("base_url")) or normalize_whitespace(proxy_config.get("search_base_url")) or normalize_whitespace(proxy_config.get("base_url"))
    if not base_url:
        raise ValueError("internal_search.base_url is required (or internal_proxy.search_base_url/base_url fallback)")
    timeout_seconds = cli_timeout_seconds if cli_timeout_seconds is not None else int(search_config.get("timeout") or proxy_config.get("timeout") or 30)
    return base_url, timeout_seconds


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-WebPlanPath", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-PoiId")
    parser.add_argument("-TaskId")
    parser.add_argument("-RunId")
    parser.add_argument("-CommonConfigPath")
    parser.add_argument("-TimeoutSeconds", type=int)
    args = parser.parse_args()

    web_plan = read_json_file(args.WebPlanPath)
    if not isinstance(web_plan, dict):
        raise ValueError("web plan must be a JSON object")
    base_url, timeout_seconds = resolve_search_runtime_config(args.CommonConfigPath, args.TimeoutSeconds)
    payload = execute_websearch_plan(web_plan=web_plan, base_url=base_url, timeout_seconds=timeout_seconds)
    if args.RunId and args.PoiId:
        payload = attach_context(payload, args.RunId, args.PoiId, task_id=args.TaskId)
    write_json_file(payload, args.OutputPath)

    result = {
        "status": payload["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "result_count": payload["result_count"],
        "query_count": payload["query_count"],
        "effective_provider": payload["effective_provider"],
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
