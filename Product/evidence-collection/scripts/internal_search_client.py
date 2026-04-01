#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def _to_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_item_list(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("references", "results", "items", "data"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_text(item: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        text = _to_string(item.get(key))
        if text:
            return text
    return None


def _extract_content(provider: str, item: Dict[str, Any]) -> Optional[str]:
    if provider == "baidu":
        return _pick_text(item, "snippet", "content", "summary")
    if provider == "tavily":
        return _pick_text(item, "content", "summary")
    return _pick_text(item, "content", "snippet", "summary")


def _extract_source_name(provider: str, item: Dict[str, Any]) -> Optional[str]:
    if provider == "baidu":
        return _pick_text(item, "website", "source_name", "source", "site")
    if provider == "tavily":
        return _pick_text(item, "source_name", "source", "site", "website")
    return _pick_text(item, "source_name", "source", "site", "website")


def normalize_search_items(provider: str, response: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for rank, item in enumerate(_to_item_list(response), start=1):
        normalized_item = {
            "url": _pick_text(item, "url", "link"),
            "title": _pick_text(item, "title", "name"),
            "content": _extract_content(provider, item),
            "published_at": _pick_text(item, "published_at", "publish_time", "date"),
            "source_name": _extract_source_name(provider, item),
            "source_type": _pick_text(item, "source_type", "type"),
            "provider": provider,
            "rank": rank,
        }
        provider_score = _to_float(item.get("score") or item.get("rerank_score") or item.get("authority_score"))
        if provider_score is not None:
            normalized_item["provider_score"] = provider_score
        normalized.append(normalized_item)
    return normalized


def search_with_provider(
    *,
    base_url: str,
    provider: str,
    query: str,
    domain: Optional[str] = None,
    block_domain: Optional[str] = None,
    count: Optional[int] = None,
    time_range: Optional[str] = None,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    params = {
        "source": provider,
        "query": query,
    }
    if domain:
        params["use_site"] = domain
        params["usesite"] = domain
    if block_domain:
        params["block_site"] = block_domain
        params["blocksite"] = block_domain
    if count is not None and int(count) > 0:
        params["count"] = int(count)
    if time_range:
        params["time_range"] = str(time_range)
    uri = f"{base_url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(uri, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("internal search response must be a JSON object")
    return payload
