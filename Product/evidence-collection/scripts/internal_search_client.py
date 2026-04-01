#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


def _to_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_item_list(response: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("references", "results", "items", "data"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def normalize_search_items(provider: str, response: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for rank, item in enumerate(_to_item_list(response), start=1):
        normalized.append(
            {
                "url": _to_string(item.get("url") or item.get("link")),
                "title": _to_string(item.get("title") or item.get("name")),
                "content": _to_string(item.get("content") or item.get("snippet") or item.get("summary")),
                "published_at": _to_string(item.get("published_at") or item.get("publish_time") or item.get("date")),
                "source_name": _to_string(item.get("source_name") or item.get("source") or item.get("site")),
                "source_type": _to_string(item.get("source_type") or item.get("type")),
                "provider": provider,
                "rank": rank,
            }
        )
    return normalized


def search_with_provider(
    *,
    base_url: str,
    provider: str,
    query: str,
    domain: str | None = None,
    block_domain: str | None = None,
    count: int | None = None,
    time_range: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
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
