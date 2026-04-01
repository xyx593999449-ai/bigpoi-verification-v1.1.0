import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection/scripts")))

from evidence_collection_common import new_generic_evidence_seed
import websearch_adapter


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

    def fake_search_with_provider(*, base_url, provider, query, domain=None, timeout_seconds=30):
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
    payload = websearch_adapter.execute_websearch_plan(web_plan=web_plan, base_url="http://internal-search/api", timeout_seconds=5)

    assert calls == ["baidu", "tavily"]
    assert payload["result_count"] == 1
    assert payload["effective_provider"] == "tavily"
    assert payload["items"][0]["metadata"]["provider_attempts"] == ["baidu", "tavily"]
