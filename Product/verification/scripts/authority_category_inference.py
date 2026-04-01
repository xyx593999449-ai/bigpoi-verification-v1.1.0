#!/usr/bin/env python3
from __future__ import annotations

import re
import urllib.parse
from typing import Any

AUTHORITY_CODES = {
    "130101",
    "130102",
    "130103",
    "130104",
    "130105",
    "130106",
    "130501",
    "130502",
    "130503",
}

FAMILY_TO_CODE = {
    "police": "130501",
    "procuratorate": "130502",
    "court": "130503",
}

SOURCE_TYPE_WEIGHT = {
    "official": 1.0,
    "internet": 0.75,
    "map_vendor": 0.55,
    "other": 0.4,
}

FAMILY_KEYWORDS = {
    "police": ("公安部", "公安厅", "公安局", "派出所", "公安分局"),
    "procuratorate": ("人民检察院", "检察院"),
    "court": ("人民法院", "高级人民法院", "中级人民法院", "基层人民法院"),
    "government": ("人民政府", "国务院", "街道办事处", "社区居民委员会", "村民委员会"),
}

FAMILY_DOMAINS = {
    "police": ("mps.gov.cn", ".gat.", ".gaj."),
    "procuratorate": ("spp.gov.cn", ".jcy.gov.cn"),
    "court": ("court.gov.cn", "chinacourt.gov.cn"),
    "government": (".gov.cn",),
}

GOV_LEVEL_PATTERNS = {
    "130101": (re.compile(r"国务院"), re.compile(r"国家级")),
    "130102": (
        re.compile(r"省人民政府"),
        re.compile(r"自治区人民政府"),
        re.compile(r"直辖市人民政府"),
        re.compile(r"(北京|上海|天津|重庆)市人民政府"),
    ),
    "130103": (re.compile(r"市人民政府"), re.compile(r"地市级")),
    "130104": (re.compile(r"(区|县)人民政府"), re.compile(r"区县级")),
    "130105": (re.compile(r"(乡|镇)人民政府"), re.compile(r"乡镇级")),
    "130106": (
        re.compile(r"街道办事处"),
        re.compile(r"社区居民委员会"),
        re.compile(r"居民委员会"),
        re.compile(r"村民委员会"),
        re.compile(r"乡镇以下级"),
    ),
}

LEVEL_LABELS = {
    "130101": "国家级",
    "130102": "省/直辖市级",
    "130103": "地市级",
    "130104": "区县级",
    "130105": "乡镇级",
    "130106": "乡镇以下级",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_domain(url: str | None) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(str(url))
    return str(parsed.netloc or "").lower()


def _item_weight(item: dict[str, Any]) -> float:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source_type = str(source.get("source_type") or "other")
    base = SOURCE_TYPE_WEIGHT.get(source_type, SOURCE_TYPE_WEIGHT["other"])
    if not str(metadata.get("signal_origin") or "").strip():
        base *= 0.6
    return round(base, 4)


def _build_text_bundle(poi: dict[str, Any], item: dict[str, Any] | None = None) -> tuple[str, str]:
    if item is None:
        values = (poi.get("name"), poi.get("address"), poi.get("city"))
        return " ".join(value for value in (_normalize_text(v) for v in values) if value), ""

    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    values = (
        data.get("name"),
        data.get("category"),
        data.get("address"),
        source.get("source_name"),
        metadata.get("page_title"),
        metadata.get("text_snippet"),
        " ".join(metadata.get("authority_signals") or []),
        metadata.get("level_hint"),
    )
    text = " ".join(value for value in (_normalize_text(v) for v in values) if value)
    domain = _extract_domain(source.get("source_url")) or _normalize_text(metadata.get("source_domain")).lower()
    return text, domain


def _score_family(text: str, domain: str, weight: float, family_scores: dict[str, float], refs: dict[str, list[str]], evidence_id: str) -> None:
    for family, keywords in FAMILY_KEYWORDS.items():
        hit_count = sum(1 for keyword in keywords if keyword in text)
        if hit_count:
            family_scores[family] += weight * (1 + min(hit_count, 3) * 0.15)
            refs[family].append(evidence_id)
        domain_hits = FAMILY_DOMAINS[family]
        if domain and any(token in domain for token in domain_hits):
            family_scores[family] += weight * (1.1 if family != "government" else 0.6)
            refs[family].append(evidence_id)


def _score_government_level(text: str, weight: float, level_scores: dict[str, float], refs: dict[str, list[str]], evidence_id: str) -> None:
    for code, patterns in GOV_LEVEL_PATTERNS.items():
        hit_count = sum(1 for pattern in patterns if pattern.search(text))
        if hit_count:
            level_scores[code] += weight * (1 + min(hit_count, 3) * 0.2)
            refs[code].append(evidence_id)


def _pick_top(scores: dict[str, float]) -> tuple[str | None, float, float]:
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ordered:
        return None, 0.0, 0.0
    top_code, top_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    return top_code, round(top_score, 4), round(second_score, 4)


def infer_authority_category(poi: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    input_code = _normalize_text(poi.get("poi_type"))
    if input_code not in AUTHORITY_CODES:
        return None

    family_scores = {family: 0.0 for family in FAMILY_KEYWORDS}
    family_refs = {family: [] for family in FAMILY_KEYWORDS}
    level_scores = {code: 0.0 for code in LEVEL_LABELS}
    level_refs = {code: [] for code in LEVEL_LABELS}

    input_text, _ = _build_text_bundle(poi, None)
    _score_family(input_text, "", 0.5, family_scores, family_refs, "INPUT")
    _score_government_level(input_text, 0.5, level_scores, level_refs, "INPUT")

    source_breakdown = {"official": 0.0, "internet": 0.0, "map_vendor": 0.0, "other": 0.0}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        evidence_id = _normalize_text(item.get("evidence_id")) or "UNKNOWN"
        text, domain = _build_text_bundle(poi, item)
        weight = _item_weight(item)
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        source_type = _normalize_text(source.get("source_type")) or "other"
        if source_type not in source_breakdown:
            source_type = "other"
        source_breakdown[source_type] += weight
        _score_family(text, domain, weight, family_scores, family_refs, evidence_id)
        _score_government_level(text, weight, level_scores, level_refs, evidence_id)

    family_code, top_family_score, second_family_score = _pick_top(family_scores)
    family_gap = top_family_score - second_family_score
    family_confidence = min(0.98, 0.45 + top_family_score / 6.0 + max(family_gap, 0.0) / 4.0)
    uncertain_reason = ""
    selected_code: str | None = None
    institution_family = family_code
    level_label = None
    evidence_refs: list[str] = []

    if not family_code or top_family_score < 0.9 or family_gap < 0.12:
        uncertain_reason = "机构类别证据不足或冲突，无法稳定识别 authority 家族。"
    elif family_code != "government":
        selected_code = FAMILY_TO_CODE[family_code]
        evidence_refs = family_refs[family_code]
    else:
        level_code, top_level_score, second_level_score = _pick_top(level_scores)
        level_gap = top_level_score - second_level_score
        if not level_code or top_level_score < 0.85 or level_gap < 0.1:
            uncertain_reason = "政府层级证据不足或冲突，无法稳定定位到具体 6 位内部类型码。"
        else:
            selected_code = level_code
            level_label = LEVEL_LABELS.get(level_code)
            evidence_refs = level_refs[level_code]
            family_confidence = min(0.99, family_confidence + min(top_level_score / 8.0, 0.2))

    confidence = round(max(0.0, min(1.0, family_confidence)), 4)
    if not selected_code:
        return {
            "result": "uncertain",
            "confidence": min(confidence, 0.74),
            "selected_code": None,
            "details": {
                "expected_value": input_code,
                "observed_value": None,
                "institution_family": institution_family,
                "level_label": level_label,
                "reason": uncertain_reason or "authority 分类证据不足。",
                "evidence_refs": sorted(set(evidence_refs)),
                "source_breakdown": {k: round(v, 4) for k, v in source_breakdown.items()},
            },
        }

    if selected_code == input_code:
        return {
            "result": "pass",
            "confidence": confidence,
            "selected_code": selected_code,
            "details": {
                "expected_value": input_code,
                "observed_value": selected_code,
                "institution_family": institution_family,
                "level_label": level_label,
                "reason": "多源证据一致指向当前输入类型码。",
                "evidence_refs": sorted(set(evidence_refs)),
                "source_breakdown": {k: round(v, 4) for k, v in source_breakdown.items()},
            },
        }

    result = "fail" if confidence >= 0.75 else "uncertain"
    reason = "多源证据指向与输入不一致的 authority 类型码。"
    if result == "uncertain":
        reason = "存在类型冲突，但证据强度不足以形成稳定修正结论。"
    return {
        "result": result,
        "confidence": confidence,
        "selected_code": selected_code,
        "details": {
            "expected_value": input_code,
            "observed_value": selected_code,
            "institution_family": institution_family,
            "level_label": level_label,
            "reason": reason,
            "evidence_refs": sorted(set(evidence_refs)),
            "source_breakdown": {k: round(v, 4) for k, v in source_breakdown.items()},
        },
    }
