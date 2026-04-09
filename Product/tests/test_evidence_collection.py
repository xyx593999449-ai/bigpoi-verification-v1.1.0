import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../evidence-collection/scripts")))

import call_internal_proxy
from evidence_collection_common import new_generic_evidence_seed
import websearch_adapter
import internal_search_client
import prepare_map_review_input
import validate_map_review_seed
import validate_websearch_review_seed
import write_websearch_review
import build_web_source_plan
import build_webreader_plan

FIXTURE_DIR = Path(__file__).resolve().parent


def load_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


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


def test_websearch_adapter_two_phase_parallel_fallback_scope(monkeypatch):
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
        calls.append((provider, query))
        if provider == "baidu":
            if query == "q-ok":
                return {"references": [{"url": "https://a.example.com", "title": "A", "snippet": "A"}]}
            if query == "q-empty":
                return {"references": []}
            raise TimeoutError("request timed out")
        if query == "q-empty":
            return {"results": [{"url": "https://b.example.com", "title": "B", "content": "B"}]}
        return {"results": []}

    monkeypatch.setattr(websearch_adapter, "search_with_provider", fake_search_with_provider)
    web_plan = {
        "official_sources": [
            {"source_name": "A", "source_type": "official", "source_url": "https://a.example.com", "query": "q-ok", "weight": 1.0},
            {"source_name": "B", "source_type": "official", "source_url": "https://b.example.com", "query": "q-empty", "weight": 1.0},
            {"source_name": "C", "source_type": "official", "source_url": "https://c.example.com", "query": "q-timeout", "weight": 1.0},
        ],
        "internet_sources": [],
    }

    payload = websearch_adapter.execute_websearch_plan(
        web_plan=web_plan,
        base_url="http://internal-search/api",
        default_count=5,
        default_time_range="30d",
        timeout_seconds=5,
    )

    assert ("tavily", "q-ok") not in calls
    assert ("tavily", "q-empty") in calls
    assert ("tavily", "q-timeout") in calls
    assert payload["query_count"] == 3
    assert payload["result_count"] == 2

    attempts_by_query = {item["query"]: item["attempts"] for item in payload["provider_attempts"]}
    assert [attempt["provider"] for attempt in attempts_by_query["q-ok"]] == ["baidu"]
    assert [attempt["provider"] for attempt in attempts_by_query["q-empty"]] == ["baidu", "tavily"]
    assert [attempt["provider"] for attempt in attempts_by_query["q-timeout"]] == ["baidu", "tavily"]
    assert attempts_by_query["q-timeout"][0]["status"] == "timeout"


def test_websearch_adapter_fallback_from_baidu_error_to_tavily(monkeypatch):
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
        calls.append((provider, query))
        if provider == "baidu":
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return {
            "results": [
                {
                    "url": "https://www.example.gov.cn/a",
                    "title": "某市人民政府",
                    "content": "某市人民政府官网信息",
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

    assert calls == [("baidu", "某市人民政府 官网"), ("tavily", "某市人民政府 官网")]
    assert payload["result_count"] == 1
    assert payload["effective_provider"] == "tavily"
    attempts = payload["provider_attempts"][0]["attempts"]
    assert [attempt["provider"] for attempt in attempts] == ["baidu", "tavily"]
    assert attempts[0]["status"] == "error"


def test_internal_search_client_normalizes_baidu_minimal_fields():
    payload = load_fixture("baidu.json.txt")
    items = internal_search_client.normalize_search_items("baidu", payload)

    assert len(items) == 5
    assert items[0]["source_name"] == "宝安区政府在线"
    assert "raw_content" not in items[0]
    assert "website" not in items[0]
    assert items[0]["content"].startswith("招考招聘人才补贴")


def test_websearch_adapter_deduplicates_and_extracts_structured_fields(monkeypatch):
    baidu_payload = load_fixture("baidu.json.txt")

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
        assert provider == "baidu"
        return baidu_payload

    monkeypatch.setattr(websearch_adapter, "search_with_provider", fake_search_with_provider)
    web_plan = {
        "official_sources": [
            {
                "source_name": "政府官网",
                "source_type": "official",
                "source_url": "https://www.baoan.gov.cn/",
                "query": "深圳市 深圳市宝安区人民政府 官网",
                "target_poi_name": "深圳市宝安区人民政府",
                "weight": 1.0,
            }
        ],
        "internet_sources": [],
    }

    payload = websearch_adapter.execute_websearch_plan(
        web_plan=web_plan,
        base_url="http://internal-search/api",
        default_count=5,
        default_time_range="OneYear",
        timeout_seconds=5,
    )

    assert payload["result_count"] == 4
    assert payload["dedupe_summary"]["duplicate_count"] == 1

    homepage_item = next(item for item in payload["items"] if item["source"]["source_url"] == "http://www.baoan.gov.cn/")
    assert homepage_item["data"]["name"] == "深圳市宝安区人民政府"
    assert "address" not in homepage_item["data"]

    office_item = next(item for item in payload["items"] if item["source"]["source_url"] == "http://www.baoan.gov.cn/xxgk/")
    assert office_item["data"]["address"] == "深圳市宝安区创业一路1号"
    assert office_item["metadata"]["canonical_url"] == "http://www.baoan.gov.cn/xxgk"


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


def test_call_internal_proxy_retries_timeout_then_succeeds(monkeypatch):
    calls = []

    def fake_fetch(base_url, vendor, city, poi_name, timeout_seconds):
        calls.append(timeout_seconds)
        if len(calls) == 1:
            raise TimeoutError("request timed out")
        return {"pois": []}

    monkeypatch.setattr(call_internal_proxy, "fetch_proxy_response", fake_fetch)

    result = call_internal_proxy.fetch_proxy_response_with_retry(
        "http://internal-proxy/mapapi",
        "amap",
        "深圳市",
        "福保街道办事处",
        10,
        60,
    )

    assert result == {"pois": []}
    assert calls == [10, 60]


def test_call_internal_proxy_raises_after_second_timeout(monkeypatch):
    calls = []

    def fake_fetch(base_url, vendor, city, poi_name, timeout_seconds):
        calls.append(timeout_seconds)
        raise TimeoutError("request timed out")

    monkeypatch.setattr(call_internal_proxy, "fetch_proxy_response", fake_fetch)

    with pytest.raises(TimeoutError, match="timed out twice"):
        call_internal_proxy.fetch_proxy_response_with_retry(
            "http://internal-proxy/mapapi",
            "bmap",
            "深圳市",
            "福保街道办事处",
            10,
            60,
        )

    assert calls == [10, 60]


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


def test_write_websearch_review_outputs_mergeable_items(tmp_path: Path):
    raw_payload = {
        "status": "ok",
        "items": [
            {
                "source": {
                    "source_id": "WEBSEARCH_OFFICIAL_BAIDU_1",
                    "source_name": "宝安区政府在线",
                    "source_type": "official",
                    "source_url": "http://www.baoan.gov.cn/xxgk/",
                    "weight": 1.0,
                },
                "data": {
                    "name": "深圳市宝安区人民政府",
                    "address": "深圳市宝安区创业一路1号",
                },
                "metadata": {
                    "signal_origin": "websearch",
                    "source_domain": "www.baoan.gov.cn",
                    "page_title": "政务公开-宝安区人民政府门户网站",
                    "text_snippet": "部门名称:宝安区人民政府政务公开办公室 联系地址:深圳市宝安区创业一路1号",
                },
            }
        ],
        "context": {
            "run_id": "run_mock",
            "poi_id": "poi_mock",
            "task_id": "task_mock",
            "created_at": "2026-04-01T00:00:00Z",
        },
    }
    review_seed = {
        "items": [
                {
                    "result_id": "WEB_001",
                    "is_relevant": True,
                    "confidence": 0.91,
                    "reason": "标题和摘要均指向目标政府机关",
                    "source_type": "official",
                    "entity_relation": "poi_body",
                    "evidence_ready": True,
                    "should_fetch": True,
                    "fetch_url": "http://www.baoan.gov.cn/xxgk/",
                    "extracted": {
                        "name": "深圳市宝安区人民政府",
                        "address": "深圳市宝安区创业一路1号",
                    "category_hint": "区县级政府",
                },
            }
        ]
    }

    raw_path = tmp_path / "websearch-raw.json"
    review_seed_path = tmp_path / "websearch-review-seed.json"
    out_path = tmp_path / "websearch-reviewed.json"
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False), encoding="utf-8")
    review_seed_path.write_text(json.dumps(review_seed, ensure_ascii=False), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "write_websearch_review.py",
            "-WebSearchRawPath",
            str(raw_path),
            "-ReviewSeedPath",
            str(review_seed_path),
            "-OutputPath",
            str(out_path),
        ],
    ):
        assert write_websearch_review.main() == 0

    reviewed = json.loads(out_path.read_text(encoding="utf-8"))
    assert reviewed["status"] == "ok"
    assert reviewed["items"][0]["data"]["name"] == "深圳市宝安区人民政府"
    assert reviewed["items"][0]["metadata"]["should_fetch"] is True
    assert reviewed["items"][0]["metadata"]["fetch_url"] == "http://www.baoan.gov.cn/xxgk/"


def test_prepare_map_review_input_compacts_candidates():
    poi = {"id": "poi_1", "name": "西丽街道办事处", "poi_type": "130105", "city": "深圳市"}
    raw_payload = {
        "vendors": {
            "amap": {
                "vendor": "amap",
                "source_name": "高德地图",
                "requested_via": "internal_proxy",
                "items": [
                    {
                        "vendor_item_id": "A1",
                        "name": "西丽街道办事处",
                        "address": "深圳市南山区留仙大道2015号",
                        "category": "政府机构及社会团体;政府机关;乡镇级政府及事业单位",
                        "coordinates": {"longitude": 113.95, "latitude": 22.57},
                        "administrative": {"province": "广东省", "city": "深圳市", "district": "南山区"},
                        "raw_data": {"very": "large"},
                    }
                ],
            }
        }
    }

    output = prepare_map_review_input.build_output(poi, raw_payload)
    candidate = output["vendors"]["amap"]["candidates"][0]

    assert candidate["candidate_key"] == "A1"
    assert candidate["name"] == "西丽街道办事处"
    assert "raw_data" not in candidate
    assert "街道办事处" in candidate["authority_signals"]


def test_validate_map_review_seed_rejects_partial_coverage():
    candidate_catalog = {
        "amap": [
            {"candidate_key": "A1", "name": "西丽街道办事处"},
            {"candidate_key": "A2", "name": "西丽街道办事处-北门"},
        ]
    }
    review_seed = {
        "vendors": {
            "amap": {
                "candidate_decisions": [
                    {"candidate_key": "A1", "is_relevant": True, "reason": "主条目"},
                ]
            }
        }
    }

    with pytest.raises(ValueError, match="missing candidate decisions"):
        validate_map_review_seed.validate_map_review_seed_against_catalog(candidate_catalog, review_seed)


def test_validate_websearch_review_seed_rejects_unstructured_relevant_items():
    catalog = {
        "WEB_001": {
            "source_type": "official",
            "source_url": "https://www.example.gov.cn",
            "page_title": "示例页面",
        }
    }
    review_seed = {
        "items": [
            {
                "result_id": "WEB_001",
                "is_relevant": True,
                "confidence": 0.9,
                "reason": "看起来相关",
                "source_type": "official",
                "entity_relation": "mention_only",
                "evidence_ready": False,
                "should_fetch": False,
                "fetch_url": None,
                "extracted": {},
            }
        ]
    }

    with pytest.raises(ValueError, match="extracted.name is required"):
        validate_websearch_review_seed.validate_websearch_review_seed_against_catalog(catalog, review_seed)


def test_validate_websearch_review_seed_rejects_non_poi_body_relevant_items():
    catalog = {
        "WEB_001": {
            "source_type": "official",
            "source_url": "https://www.example.gov.cn",
            "page_title": "示例页面",
        }
    }
    review_seed = {
        "items": [
            {
                "result_id": "WEB_001",
                "is_relevant": True,
                "confidence": 0.82,
                "reason": "正文里提到了目标机构",
                "source_type": "official",
                "entity_relation": "mention_only",
                "evidence_ready": True,
                "should_fetch": False,
                "fetch_url": None,
                "extracted": {"name": "某街道办事处"},
            }
        ]
    }

    with pytest.raises(ValueError, match="entity_relation must be poi_body"):
        validate_websearch_review_seed.validate_websearch_review_seed_against_catalog(catalog, review_seed)


def test_websearch_adapter_prefers_search_queries_block(monkeypatch):
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
        calls.append((provider, query, domain))
        return {"references": [{"url": "https://www.example.gov.cn/a", "title": "某市人民政府", "snippet": "某市人民政府"}]}

    monkeypatch.setattr(websearch_adapter, "search_with_provider", fake_search_with_provider)
    payload = websearch_adapter.execute_websearch_plan(
        web_plan={
            "official_sources": [
                {"source_name": "旧字段", "source_type": "official", "source_url": "https://legacy.example.com", "query": "legacy query"},
            ],
            "search_queries": [
                {
                    "source_name": "新字段",
                    "source_type": "official",
                    "source_url": "https://www.example.gov.cn",
                    "query": "深圳市 南山区人民政府 办公地址",
                    "query_intent": "office_address",
                    "domain": "www.example.gov.cn",
                    "weight": 1.0,
                }
            ],
        },
        base_url="http://internal-search/api",
        default_count=5,
        default_time_range="OneYear",
        timeout_seconds=5,
    )

    assert payload["query_count"] == 1
    assert payload["result_count"] == 1
    assert calls[0][1] == "深圳市 南山区人民政府 办公地址"
    assert calls[0][2] == "www.example.gov.cn"


def test_write_websearch_review_outputs_should_read_and_legacy_fetch(tmp_path: Path):
    raw_payload = {
        "status": "ok",
        "items": [
            {
                "source": {
                    "source_id": "WEBSEARCH_OFFICIAL_BAIDU_1",
                    "source_name": "宝安区政府在线",
                    "source_type": "official",
                    "source_url": "http://www.baoan.gov.cn/xxgk/",
                    "weight": 1.0,
                },
                "data": {"name": "深圳市宝安区人民政府"},
                "metadata": {"signal_origin": "websearch"},
            }
        ],
        "context": {"run_id": "run_mock", "poi_id": "poi_mock", "created_at": "2026-04-01T00:00:00Z"},
    }
    review_seed = {
        "items": [
            {
                "result_id": "WEB_001",
                "is_relevant": True,
                "confidence": 0.91,
                "reason": "标题和摘要均指向目标政府机关",
                "source_type": "official",
                "entity_relation": "poi_body",
                "evidence_ready": True,
                "should_read": True,
                "read_url": "http://www.baoan.gov.cn/xxgk/",
                "extracted": {"name": "深圳市宝安区人民政府"},
            }
        ]
    }

    raw_path = tmp_path / "websearch-raw.json"
    review_seed_path = tmp_path / "websearch-review-seed.json"
    out_path = tmp_path / "websearch-reviewed.json"
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False), encoding="utf-8")
    review_seed_path.write_text(json.dumps(review_seed, ensure_ascii=False), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "write_websearch_review.py",
            "-WebSearchRawPath",
            str(raw_path),
            "-ReviewSeedPath",
            str(review_seed_path),
            "-OutputPath",
            str(out_path),
        ],
    ):
        assert write_websearch_review.main() == 0

    reviewed = json.loads(out_path.read_text(encoding="utf-8"))
    metadata = reviewed["items"][0]["metadata"]
    assert metadata["should_read"] is True
    assert metadata["read_url"] == "http://www.baoan.gov.cn/xxgk/"
    assert metadata["should_fetch"] is True
    assert metadata["fetch_url"] == "http://www.baoan.gov.cn/xxgk/"


def test_build_webreader_plan_combines_direct_read_and_followup(tmp_path: Path):
    web_plan = {
        "direct_read_sources": [
            {
                "source_name": "官网",
                "source_type": "official",
                "source_url": "https://www.szns.gov.cn/",
                "read_intents": ["办公地址", "联系电话"],
            }
        ]
    }
    websearch_reviewed = {
        "items": [
            {
                "source": {"source_name": "搜索页", "source_type": "official", "source_url": "https://www.szns.gov.cn/xxgk"},
                "metadata": {"result_id": "WEB_001", "should_read": True, "read_url": "https://www.szns.gov.cn/xxgk"},
            }
        ]
    }
    web_plan_path = tmp_path / "web-plan.json"
    websearch_reviewed_path = tmp_path / "websearch-reviewed.json"
    out_path = tmp_path / "webreader-plan.json"
    web_plan_path.write_text(json.dumps(web_plan, ensure_ascii=False), encoding="utf-8")
    websearch_reviewed_path.write_text(json.dumps(websearch_reviewed, ensure_ascii=False), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "build_webreader_plan.py",
            "-WebPlanPath",
            str(web_plan_path),
            "-WebSearchReviewedPath",
            str(websearch_reviewed_path),
            "-OutputPath",
            str(out_path),
        ],
    ):
        assert build_webreader_plan.main() == 0

    plan = json.loads(out_path.read_text(encoding="utf-8"))
    assert plan["status"] == "ok"
    assert len(plan["read_targets"]) == 2
    assert {item["read_reason"] for item in plan["read_targets"]} == {"direct_read", "search_followup"}


def test_build_web_source_plan_keeps_config_sources_in_search_only(tmp_path: Path):
    poi = {
        "id": "poi_gov_1",
        "name": "福保街道办事处",
        "poi_type": "130105",
        "city": "深圳市",
    }
    poi_path = tmp_path / "poi.json"
    out_path = tmp_path / "web-plan.json"
    poi_path.write_text(json.dumps(poi, ensure_ascii=False), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "build_web_source_plan.py",
            "-PoiPath",
            str(poi_path),
            "-OutputPath",
            str(out_path),
        ],
    ):
        assert build_web_source_plan.main() == 0

    plan = json.loads(out_path.read_text(encoding="utf-8"))
    assert plan["status"] == "ok"
    assert plan["direct_read_sources"] == []
    assert len(plan["search_queries"]) > 0


def test_validate_websearch_review_seed_allows_relevant_non_poi_body():
    catalog = {
        "WEB_001": {
            "source_type": "official",
            "source_url": "https://www.example.gov.cn/detail",
            "page_title": "机构职责",
        }
    }
    review_seed = {
        "items": [
            {
                "result_id": "WEB_001",
                "is_relevant": True,
                "confidence": 0.72,
                "reason": "页面提到目标街道办，但主办单位不是目标 POI 本体。",
                "source_type": "official",
                "entity_relation": "subordinate_org",
                "evidence_ready": False,
                "should_read": False,
                "extracted": {
                    "name": "福保街道办事处",
                },
            }
        ]
    }

    result = validate_websearch_review_seed.validate_websearch_review_seed_against_catalog(catalog, review_seed)
    assert result["status"] == "ok"
    assert result["relevant_count"] == 1
