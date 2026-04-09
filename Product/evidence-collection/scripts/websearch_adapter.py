#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import socket
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
TITLE_SPLIT_PATTERN = re.compile(r"\s*[-_|｜/:：·•]+\s*")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ADDRESS_LABEL_PATTERN = re.compile(
    r"(?:办公地址|联系地址|地址|单位地址|驻地|驻址|办公地点|办公场所|办公地点位于|办公地址位于|位于)"
    r"[:： ]*"
    r"([^。；;|【】\[\]\n]{4,80})"
)
PHONE_PATTERN = re.compile(r"(?:\+?86[- ]?)?(?:0\d{2,3}-\d{7,8}|1\d{10})")
STOP_TOKENS = ("邮政编码", "邮编", "联系电话", "咨询电话", "电话", "邮箱", "电子邮箱", "工作时间", "办公时间")
AUTHORITY_KEYWORDS = (
    "人民政府",
    "公安局",
    "公安分局",
    "派出所",
    "人民检察院",
    "检察院",
    "人民法院",
    "法院",
    "街道办事处",
    "政务公开",
    "政府在线",
)


def log_progress(message: str) -> None:
    sys.stderr.write(f"[websearch] {message}\n")
    sys.stderr.flush()


def iter_plan_sources(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(plan.get("search_queries"), list):
        return [item for item in plan["search_queries"] if isinstance(item, dict)]
    result: List[Dict[str, Any]] = []
    for key in ("official_sources", "internet_sources"):
        items = plan.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                result.append(item)
    return result


def clean_search_text(value: Any) -> Optional[str]:
    text = normalize_whitespace(value)
    if not text:
        return None
    text = MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    text = re.sub(r"[#*_>`]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def limit_clean_text(value: Any, limit: int) -> Optional[str]:
    cleaned = clean_search_text(value)
    return limit_text(cleaned, limit) if cleaned else None


def canonicalize_result_url(url: Optional[str]) -> Optional[str]:
    if not normalize_whitespace(url):
        return None
    parsed = urllib.parse.urlparse(str(url))
    if not parsed.scheme or not parsed.netloc:
        return normalize_whitespace(url)
    filtered_query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_query = [
        (key, value)
        for key, value in filtered_query
        if key.lower() not in {"page", "page_index", "pn", "p", "pageindex"}
    ]
    normalized_path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            urllib.parse.urlencode(filtered_query),
            "",
        )
    )


def dedupe_signature(url: Optional[str], domain: Optional[str], title: Optional[str], snippet: Optional[str]) -> str:
    canonical_url = canonicalize_result_url(url)
    if canonical_url:
        return f"url::{canonical_url}"
    normalized_title = normalize_whitespace(title) or ""
    normalized_snippet = normalize_whitespace(snippet) or ""
    return f"text::{(domain or 'unknown').lower()}::{normalized_title.lower()}::{normalized_snippet[:80].lower()}"


def split_title_parts(title: Optional[str]) -> List[str]:
    cleaned = clean_search_text(title)
    if not cleaned:
        return []
    parts = [part for part in (normalize_whitespace(piece) for piece in TITLE_SPLIT_PATTERN.split(cleaned)) if part]
    ordered: List[str] = []
    for part in parts:
        if part not in ordered:
            ordered.append(part)
    return ordered


def choose_best_title_part(title: Optional[str], target_name: Optional[str]) -> Optional[str]:
    cleaned_title = clean_search_text(title)
    if not cleaned_title:
        return None
    normalized_target = normalize_whitespace(target_name)
    if normalized_target and normalized_target in cleaned_title:
        return normalized_target

    best_part: Optional[str] = None
    best_score = -10**9
    for part in split_title_parts(cleaned_title):
        score = 0
        if normalized_target:
            if part == normalized_target:
                score += 120
            elif normalized_target in part or part in normalized_target:
                score += 80
        if any(keyword in part for keyword in AUTHORITY_KEYWORDS):
            score += 40
        if "门户网站" in part:
            score -= 10
        if len(part) <= 3:
            score -= 25
        if score > best_score:
            best_part = part
            best_score = score
    return best_part or cleaned_title


def shorten_at_stop_token(text: str) -> str:
    result = text
    for token in STOP_TOKENS:
        if token in result:
            result = result.split(token, 1)[0]
    return result.strip(" ，,。；;:：")


def extract_structured_address(snippet: Optional[str]) -> Optional[str]:
    cleaned = clean_search_text(snippet)
    if not cleaned:
        return None
    match = ADDRESS_LABEL_PATTERN.search(cleaned)
    if not match:
        return None
    candidate = shorten_at_stop_token(match.group(1))
    if len(candidate) < 4:
        return None
    return limit_text(candidate, 80)


def extract_structured_phone(snippet: Optional[str]) -> Optional[str]:
    cleaned = clean_search_text(snippet)
    if not cleaned:
        return None
    match = PHONE_PATTERN.search(cleaned)
    if not match:
        return None
    return match.group(0)


def derive_result_name(title: Optional[str], target_name: Optional[str], query: str) -> Optional[str]:
    title_name = choose_best_title_part(title, target_name)
    normalized_target = normalize_whitespace(target_name)
    if title_name:
        if normalized_target and title_name == normalized_target:
            return normalized_target
        if any(keyword in title_name for keyword in AUTHORITY_KEYWORDS):
            return title_name
        return title_name
    if normalized_target and normalized_target in (normalize_whitespace(query) or ""):
        return normalized_target
    return None


def normalize_websearch_item(result: Dict[str, Any], plan_source: Dict[str, Any], query: str, provider_attempts: List[str]) -> Dict[str, Any]:
    source_type = str(plan_source.get("source_type") or "other")
    source_url = result.get("url") or plan_source.get("source_url")
    target_name = normalize_whitespace(plan_source.get("target_poi_name"))
    title = limit_clean_text(result.get("title") or plan_source.get("source_name"), 120)
    snippet = limit_clean_text(result.get("content"), 280)
    result_name = derive_result_name(title, target_name, query)
    address = extract_structured_address(snippet)
    phone = extract_structured_phone(snippet)
    metadata: Dict[str, Any] = {
        "signal_origin": "websearch",
        "source_domain": extract_source_domain(source_url),
        "page_title": title,
        "text_snippet": snippet,
        "authority_signals": plan_source.get("authority_signals"),
        "provider": result.get("provider"),
        "provider_attempts": provider_attempts,
        "published_at": result.get("published_at"),
        "query": query,
        "canonical_url": canonicalize_result_url(source_url),
    }
    if result.get("provider_score") is not None:
        metadata["provider_score"] = result.get("provider_score")
    data: Dict[str, Any] = {
        "name": result_name or query,
    }
    if address:
        data["address"] = address
    if phone:
        data["phone"] = phone
    return {
        "source": {
            "source_id": f"WEBSEARCH_{source_type}_{result.get('provider')}_{result.get('rank')}",
            "source_name": result.get("source_name") or plan_source.get("source_name") or "websearch",
            "source_type": source_type,
            "source_url": source_url,
            "weight": float(plan_source.get("weight") or 0.6),
        },
        "data": data,
        "collected_at": utc_iso_now(),
        "metadata": metadata,
    }



def is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def execute_provider_batch(
    *,
    base_url: str,
    provider: str,
    queries: List[Dict[str, Any]],
    timeout_seconds: int,
) -> Dict[int, Dict[str, Any]]:
    results: Dict[int, Dict[str, Any]] = {}

    def _run_one(index: int, query_item: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        query = str(query_item.get("query") or "")
        domain = query_item.get("domain")
        count = query_item.get("count")
        time_range = query_item.get("time_range")
        try:
            response = search_with_provider(
                base_url=base_url,
                provider=provider,
                query=query,
                domain=domain,
                count=count,
                time_range=time_range,
                timeout_seconds=timeout_seconds,
            )
            normalized_items = normalize_search_items(provider, response)
            return index, {
                "attempt": {
                    "provider": provider,
                    "status": "ok" if normalized_items else "empty",
                    "result_count": len(normalized_items),
                },
                "items": normalized_items,
            }
        except Exception as exc:
            status = "timeout" if is_timeout_exception(exc) else "error"
            return index, {
                "attempt": {
                    "provider": provider,
                    "status": status,
                    "result_count": 0,
                    "error": str(exc),
                },
                "items": [],
            }

    if not queries:
        return results

    max_workers = min(max(len(queries), 1), 8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_run_one, index, query_item)
            for index, query_item in enumerate(queries)
        ]
        for future in concurrent.futures.as_completed(futures):
            index, query_result = future.result()
            results[index] = query_result
    return results


def execute_websearch_plan(
    *,
    web_plan: Dict[str, Any],
    base_url: str,
    default_count: Optional[int],
    default_time_range: Optional[str],
    timeout_seconds: int,
) -> Dict[str, Any]:
    aggregated_items: List[Dict[str, Any]] = []
    provider_attempts: List[Dict[str, Any]] = []
    seen_signatures: Set[str] = set()
    duplicate_count = 0
    skipped_invalid_count = 0
    effective_provider_counter: Dict[str, int] = {"baidu": 0, "tavily": 0}

    planned_queries: List[Dict[str, Any]] = []
    for plan_source in iter_plan_sources(web_plan):
        query = normalize_whitespace(plan_source.get("query"))
        if not query:
            continue
        domain = normalize_whitespace(plan_source.get("domain"))
        count = int(plan_source.get("count") or default_count or 0) or None
        time_range = normalize_whitespace(plan_source.get("time_range") or default_time_range)
        planned_queries.append(
            {
                "plan_source": plan_source,
                "query": query,
                "domain": domain,
                "count": count,
                "time_range": time_range,
            }
        )

    if planned_queries:
        log_progress(f"第一阶段并发查询 provider=baidu query_count={len(planned_queries)}")
    baidu_results = execute_provider_batch(
        base_url=base_url,
        provider="baidu",
        queries=planned_queries,
        timeout_seconds=timeout_seconds,
    )

    fallback_indexes: List[int] = []
    query_states: List[Dict[str, Any]] = []
    for index, query_item in enumerate(planned_queries):
        baidu_result = baidu_results.get(index) or {
            "attempt": {"provider": "baidu", "status": "error", "result_count": 0, "error": "missing result"},
            "items": [],
        }
        attempt = baidu_result["attempt"]
        effective_provider = "baidu" if attempt["status"] == "ok" else None
        raw_items = baidu_result["items"] if effective_provider else []
        if attempt["status"] in {"empty", "timeout", "error"}:
            fallback_indexes.append(index)
        query_states.append(
            {
                "plan_source": query_item["plan_source"],
                "query": query_item["query"],
                "domain": query_item["domain"],
                "count": query_item["count"],
                "time_range": query_item["time_range"],
                "attempts": [attempt],
                "effective_provider": effective_provider,
                "raw_items": raw_items,
            }
        )

    fallback_queries = [planned_queries[index] for index in fallback_indexes]
    if fallback_queries:
        log_progress(f"第二阶段并发查询 provider=tavily fallback_query_count={len(fallback_queries)}")
        tavily_results = execute_provider_batch(
            base_url=base_url,
            provider="tavily",
            queries=fallback_queries,
            timeout_seconds=timeout_seconds,
        )
        for local_index, global_index in enumerate(fallback_indexes):
            state = query_states[global_index]
            tavily_result = tavily_results.get(local_index) or {
                "attempt": {"provider": "tavily", "status": "error", "result_count": 0, "error": "missing result"},
                "items": [],
            }
            tavily_attempt = tavily_result["attempt"]
            state["attempts"].append(tavily_attempt)
            if tavily_attempt["status"] == "ok":
                state["effective_provider"] = "tavily"
                state["raw_items"] = tavily_result["items"]

    for state in query_states:
        query = state["query"]
        domain = state["domain"]
        count = state["count"]
        time_range = state["time_range"]
        attempts = state["attempts"]
        raw_items = state["raw_items"]
        effective_provider = state["effective_provider"]
        plan_source = state["plan_source"]

        log_progress(
            f"查询完成: query={query} effective_provider={effective_provider or 'none'} result_count={len(raw_items)}"
        )
        provider_attempts.append(
            {
                "query": query,
                "domain": domain,
                "count": count,
                "time_range": time_range,
                "attempts": attempts,
                "effective_provider": effective_provider,
                "result_count": len(raw_items),
            }
        )
        if effective_provider:
            effective_provider_counter[effective_provider] += 1
        provider_trace = [attempt.get("provider") for attempt in attempts]
        for result in raw_items:
            source_url = result.get("url") or plan_source.get("source_url")
            title = limit_clean_text(result.get("title") or plan_source.get("source_name"), 120)
            snippet = limit_clean_text(result.get("content"), 280)
            signature = dedupe_signature(source_url, extract_source_domain(source_url), title, snippet)
            if signature in seen_signatures:
                duplicate_count += 1
                continue
            item = normalize_websearch_item(result, plan_source, query, provider_trace)
            if not normalize_whitespace(item.get("data", {}).get("name")):
                skipped_invalid_count += 1
                continue
            seen_signatures.add(signature)
            aggregated_items.append(item)

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
        "dedupe_summary": {
            "duplicate_count": duplicate_count,
            "skipped_invalid_count": skipped_invalid_count,
            "retained_count": len(aggregated_items),
        },
        "items": aggregated_items,
        "context": {
            "source": "internal_search_proxy",
            "provider_order": list(PROVIDERS),
        },
    }


def resolve_search_runtime_config(
    common_config_path: Optional[str],
    cli_timeout_seconds: Optional[int],
    cli_default_count: Optional[int],
    cli_default_time_range: Optional[str],
) -> Tuple[str, int, Optional[int], Optional[str]]:
    search_config = get_internal_search_config(common_config_path)
    proxy_config = get_internal_proxy_config(common_config_path)
    base_url = normalize_whitespace(search_config.get("base_url")) or normalize_whitespace(proxy_config.get("search_base_url"))
    if not base_url:
        raise ValueError("internal_search.base_url is required (or internal_proxy.search_base_url fallback)")
    timeout_seconds = cli_timeout_seconds if cli_timeout_seconds is not None else int(search_config.get("timeout") or proxy_config.get("timeout") or 30)
    default_count = cli_default_count if cli_default_count is not None else int(search_config.get("count") or 0) or None
    default_time_range = normalize_whitespace(cli_default_time_range) or normalize_whitespace(search_config.get("time_range"))
    return base_url, timeout_seconds, default_count, default_time_range


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
    parser.add_argument("-DefaultCount", type=int)
    parser.add_argument("-DefaultTimeRange")
    parser.add_argument("-DebugLogPath")
    args = parser.parse_args()

    web_plan = read_json_file(args.WebPlanPath)
    if not isinstance(web_plan, dict):
        raise ValueError("web plan must be a JSON object")
    base_url, timeout_seconds, default_count, default_time_range = resolve_search_runtime_config(
        args.CommonConfigPath,
        args.TimeoutSeconds,
        args.DefaultCount,
        args.DefaultTimeRange,
    )
    payload = execute_websearch_plan(
        web_plan=web_plan,
        base_url=base_url,
        default_count=default_count,
        default_time_range=default_time_range,
        timeout_seconds=timeout_seconds,
    )
    payload["runtime"] = {
        "base_url": base_url,
        "timeout_seconds": timeout_seconds,
        "default_count": default_count,
        "default_time_range": default_time_range,
    }
    if args.RunId and args.PoiId:
        payload = attach_context(payload, args.RunId, args.PoiId, task_id=args.TaskId)
    write_json_file(payload, args.OutputPath)
    if args.DebugLogPath:
        write_json_file(
            {
                "status": payload["status"],
                "result_path": str(Path(args.OutputPath).resolve()),
                "runtime": payload.get("runtime"),
                "query_count": payload["query_count"],
                "result_count": payload["result_count"],
                "effective_provider": payload["effective_provider"],
                "dedupe_summary": payload.get("dedupe_summary"),
                "provider_attempts": payload.get("provider_attempts", []),
            },
            args.DebugLogPath,
        )

    result = {
        "status": payload["status"],
        "result_path": str(Path(args.OutputPath).resolve()),
        "result_count": payload["result_count"],
        "query_count": payload["query_count"],
        "effective_provider": payload["effective_provider"],
        "dedupe_summary": payload.get("dedupe_summary"),
        "summary_text": (
            f"websearch 完成：共执行 {payload['query_count']} 条查询，"
            f"命中 {payload['result_count']} 条结果，"
            f"去重 {payload.get('dedupe_summary', {}).get('duplicate_count', 0)} 条，"
            f"provider={payload['effective_provider'] or 'none'}，"
            f"状态={payload['status']}。"
        ),
    }
    log_progress(result["summary_text"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    # empty 在主流程中属于可降级场景，不应阻断 evidence 产出链路
    return 0 if payload["status"] in {"ok", "partial", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
