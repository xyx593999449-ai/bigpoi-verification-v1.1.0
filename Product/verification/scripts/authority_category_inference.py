#!/usr/bin/env python3
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

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
    "130105": (
        re.compile(r"(乡|镇)人民政府"),
        re.compile(r"街道办事处"),
        re.compile(r"乡镇级"),
    ),
    "130106": (
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


def _extract_domain(url: Optional[str]) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(str(url))
    return str(parsed.netloc or "").lower()


def _item_weight(item: dict[str, Any]) -> float:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source_type = str(source.get("source_type") or "other")
    base = SOURCE_TYPE_WEIGHT.get(source_type, SOURCE_TYPE_WEIGHT["other"])
    signal_origin = str(metadata.get("signal_origin") or "").strip()
    source_domain = str(metadata.get("source_domain") or "").strip()
    page_title = str(metadata.get("page_title") or "").strip()
    text_snippet = str(metadata.get("text_snippet") or "").strip()

    # metadata 最小 contract 的缺失惩罚：显式拉开强主证据与弱辅证据的权重
    if not signal_origin:
        base *= 0.6
    if not source_domain:
        base *= 0.75
    if not page_title:
        base *= 0.9
    if not text_snippet:
        base *= 0.8

    # official 证据若缺核心 metadata，进一步降级为弱辅证
    if source_type == "official":
        if not source_domain:
            base *= 0.8
        if not (page_title or text_snippet):
            base *= 0.7
    return round(base, 4)


def _build_text_bundle(poi: Dict[str, Any], item: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
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


def _pick_top(scores: dict[str, float]) -> Tuple[Optional[str], float, float]:
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ordered:
        return None, 0.0, 0.0
    top_code, top_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    return top_code, round(top_score, 4), round(second_score, 4)


def _build_candidate_codes(family_scores: dict[str, float], level_scores: dict[str, float]) -> list[str]:
    candidates: list[str] = []
    sorted_families = [name for name, score in sorted(family_scores.items(), key=lambda kv: kv[1], reverse=True) if score > 0]
    for family in sorted_families:
        if family in FAMILY_TO_CODE:
            candidates.append(FAMILY_TO_CODE[family])
        elif family == "government":
            sorted_levels = [code for code, score in sorted(level_scores.items(), key=lambda kv: kv[1], reverse=True) if score > 0]
            candidates.extend(sorted_levels[:3])
    deduped: list[str] = []
    for code in candidates:
        if code not in deduped:
            deduped.append(code)
    return deduped[:5]


def _build_conflict_summary(family_scores: dict[str, float], level_scores: dict[str, float]) -> dict[str, Any]:
    top_families = sorted(family_scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_levels = sorted(level_scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return {
        "family_ranking": [{"family": name, "score": round(score, 4)} for name, score in top_families],
        "government_level_ranking": [{"code": code, "score": round(score, 4)} for code, score in top_levels],
    }


def _apply_model_adjudication(
    *,
    model_judgment: Optional[Dict[str, Any]],
    candidate_codes: List[str],
    input_code: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(model_judgment, dict):
        return None
    selected_code = _normalize_text(model_judgment.get("selected_code"))
    if not selected_code or selected_code not in AUTHORITY_CODES or selected_code not in candidate_codes:
        return None
    confidence = float(model_judgment.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    reason = _normalize_text(model_judgment.get("reason")) or "灰区模型裁决"
    evidence_refs = model_judgment.get("evidence_refs") if isinstance(model_judgment.get("evidence_refs"), list) else []
    result = "pass" if selected_code == input_code else "fail" if confidence >= 0.75 else "uncertain"
    return {
        "result": result,
        "confidence": round(confidence, 4),
        "selected_code": selected_code,
        "reason": reason,
        "evidence_refs": [str(ref) for ref in evidence_refs if str(ref).strip()],
    }


def infer_authority_category(
    poi: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    *,
    model_judgment: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
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
    selected_code: Optional[str] = None
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
    candidate_codes = _build_candidate_codes(family_scores, level_scores)
    conflict_summary = _build_conflict_summary(family_scores, level_scores)
    if not selected_code:
        model_decision = _apply_model_adjudication(
            model_judgment=model_judgment,
            candidate_codes=candidate_codes,
            input_code=input_code,
        )
        if model_decision:
            return {
                "result": model_decision["result"],
                "confidence": model_decision["confidence"],
                "selected_code": model_decision["selected_code"],
                "details": {
                    "expected_value": input_code,
                    "observed_value": model_decision["selected_code"],
                    "institution_family": institution_family,
                    "level_label": level_label,
                    "reason": model_decision["reason"],
                    "evidence_refs": sorted(set(evidence_refs + model_decision["evidence_refs"])),
                    "source_breakdown": {k: round(v, 4) for k, v in source_breakdown.items()},
                    "candidate_codes": candidate_codes,
                    "conflict_summary": conflict_summary,
                    "adjudication_source": "model_judgment",
                },
            }
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
                "candidate_codes": candidate_codes,
                "conflict_summary": conflict_summary,
                "adjudication_source": "rule_only",
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
                "candidate_codes": candidate_codes,
                "conflict_summary": conflict_summary,
                "adjudication_source": "rule_only",
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
            "candidate_codes": candidate_codes,
            "conflict_summary": conflict_summary,
            "adjudication_source": "rule_only",
        },
    }
