import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection/scripts")))

from evidence_collection_common import new_generic_evidence_seed
import websearch_adapter
import internal_search_client


def test_generic_seed_includes_authority_metadata_contract():
    poi = {"id": "poi_1"}
    item = {
        "source_type": "official",
        "source_name": "某市人民政府",
        "source_url": "https://www.example.gov.cn/page",
        "title": "某市人民政府",
        "content": "某市人民政府主办，负责全市行政管理",
        "data": {"name": "某市人民政府"},
    }
    seed = new_generic_evidence_seed(poi, item, "websearch")
    metadata = seed["metadata"]

    assert metadata["signal_origin"] == "websearch"
    assert metadata["source_domain"] == "www.example.gov.cn"
    assert metadata["page_title"] == "某市人民政府"
    assert metadata["text_snippet"].startswith("某市人民政府主办")
    assert "人民政府" in (metadata.get("authority_signals") or [])


def test_websearch_adapter_fallback_from_baidu_to_tavily(monkeypatch):
    calls = []

    def fake_search_with_provider(
        *,
        base_url,
        provider,
        query,
        domain=None,
        block_domain=None,
        count=None,
        time_range=None,
        timeout_seconds=30,
    ):
        calls.append(provider)
        if provider == "baidu":
            return {"references": []}
        return {
            "results": [
                {
                    "url": "https://www.example.gov.cn/a",
                    "title": "某市人民政府",
                    "snippet": "某市人民政府官网信息",
                    "source": "某市人民政府",
                }
            ]
        }

    monkeypatch.setattr(websearch_adapter, "search_with_provider", fake_search_with_provider)
    web_plan = {
        "official_sources": [
            {
                "source_name": "政府官网",
                "source_type": "official",
                "source_url": "https://www.example.gov.cn/",
                "query": "某市人民政府 官网",
                "weight": 1.0,
            }
        ],
        "internet_sources": [],
    }
    payload = websearch_adapter.execute_websearch_plan(
        web_plan=web_plan,
        base_url="http://internal-search/api",
        default_count=20,
        default_time_range="30d",
        timeout_seconds=5,
    )

    assert calls == ["baidu", "tavily"]
    assert payload["result_count"] == 1
    assert payload["effective_provider"] == "tavily"
    assert payload["items"][0]["metadata"]["provider_attempts"] == ["baidu", "tavily"]


def test_internal_search_client_uses_protocol_params():
    captured = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"references":[]}'

    def fake_urlopen(uri, timeout=30):
        captured["uri"] = uri
        captured["timeout"] = timeout
        return _FakeResp()

    with patch("internal_search_client.urllib.request.urlopen", side_effect=fake_urlopen):
        internal_search_client.search_with_provider(
            base_url="http://internal-search/api",
            provider="baidu",
            query="某市人民政府",
            domain="www.example.gov.cn",
            block_domain="foo.example.com",
            count=15,
            time_range="7d",
            timeout_seconds=12,
        )

    assert "source=baidu" in captured["uri"]
    assert "query=%E6%9F%90%E5%B8%82%E4%BA%BA%E6%B0%91%E6%94%BF%E5%BA%9C" in captured["uri"]
    assert "use_site=www.example.gov.cn" in captured["uri"]
    assert "usesite=www.example.gov.cn" in captured["uri"]
    assert "block_site=foo.example.com" in captured["uri"]
    assert "blocksite=foo.example.com" in captured["uri"]
    assert "count=15" in captured["uri"]
    assert "time_range=7d" in captured["uri"]
    assert captured["timeout"] == 12


def test_websearch_empty_status_is_non_blocking(tmp_path: Path):
    web_plan = {"official_sources": [{"query": "xxx"}], "internet_sources": []}
    web_plan_path = tmp_path / "web_plan.json"
    out_path = tmp_path / "websearch.json"
    web_plan_path.write_text('{"official_sources":[{"query":"xxx"}],"internet_sources":[]}', encoding="utf-8")

    with patch("websearch_adapter.read_json_file", return_value=web_plan), patch(
        "websearch_adapter.resolve_search_runtime_config", return_value=("http://internal-search/api", 10, 20, "30d")
    ), patch(
        "websearch_adapter.execute_websearch_plan",
        return_value={"status": "empty", "result_count": 0, "query_count": 1, "effective_provider": None, "items": []},
    ), patch(
        "sys.argv",
        ["websearch_adapter.py", "-WebPlanPath", str(web_plan_path), "-OutputPath", str(out_path)],
    ):
        assert websearch_adapter.main() == 0
