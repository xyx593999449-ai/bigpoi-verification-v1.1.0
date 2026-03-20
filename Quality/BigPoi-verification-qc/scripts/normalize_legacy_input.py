#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将旧版平铺输入归一化为 BigPOI QC 的标准输入结构。

支持两种输入：
1. 标准 canonical 输入：直接原样返回
2. legacy flat 输入：转换为 record / evidence_data / upstream_decision
"""

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


LEGACY_HINT_FIELDS = {
    'task_id',
    'name',
    'address',
    'x_coord',
    'y_coord',
    'poi_type',
    'evidence_record',
}

MANUAL_REVIEW_KEYWORDS = ('人工', 'manual_review', 'downgraded')
REJECT_KEYWORDS = ('不通过', '驳回', '拒绝', '不存在', '无效', 'rejected')
PASS_KEYWORDS = ('通过', 'accepted', 'adopt')
REQUIRED_UPSTREAM_DIMS = ('existence', 'name', 'location', 'administrative', 'category')
ANCILLARY_NAME_KEYWORDS = (
    '东门',
    '西门',
    '南门',
    '北门',
    '正门',
    '后门',
    '侧门',
    '北侧门',
    '南侧门',
    '入口',
    '出口',
    '出入口',
    '停车场',
    '地下停车场',
    '停车楼',
    '门岗',
    '门卫',
)
GOVERNMENT_MAIN_ENTITY_KEYWORDS = ('人民政府', '政府')
GOVERNMENT_AFFILIATED_FACILITY_KEYWORDS = (
    '政务中心',
    '政务服务中心',
    '办事大厅',
    '便民服务中心',
    '市民中心',
    '服务中心',
)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == '':
            continue
        return value
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_probability(value: Any, default: float = 0.5) -> float:
    number = _to_float(value)
    if number is None:
        return default
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def _parse_location_string(value: Any) -> Tuple[Optional[float], Optional[float]]:
    if not isinstance(value, str):
        return None, None
    parts = [part.strip() for part in value.split(',')]
    if len(parts) != 2:
        return None, None
    return _to_float(parts[0]), _to_float(parts[1])


def _copy_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return {}


def _normalize_name_text(value: Any) -> str:
    text = str(value or '').strip().lower()
    if not text:
        return ''
    return re.sub(r'[\s\-\_()（）\[\]【】,，、.;；:：/\\]+', '', text)


def _strip_ancillary_suffix(name: str) -> str:
    stripped = name
    changed = True
    while changed and stripped:
        changed = False
        for keyword in sorted(ANCILLARY_NAME_KEYWORDS, key=len, reverse=True):
            if stripped.endswith(keyword):
                stripped = stripped[: -len(keyword)]
                changed = True
                break
    return stripped


def _contains_any_keyword(text: str, keywords: Tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _invalid_evidence_reason(record: Dict[str, Any], evidence: Dict[str, Any]) -> Optional[str]:
    verification = _copy_json_dict(evidence.get('verification'))
    if not bool(verification.get('is_valid', True)):
        return 'verification_marked_invalid'

    record_name = str(_copy_json_dict(record).get('name') or '')
    evidence_name = str(_copy_json_dict(evidence.get('data')).get('name') or '')
    if not record_name or not evidence_name:
        return None

    normalized_record_name = _normalize_name_text(record_name)
    normalized_evidence_name = _normalize_name_text(evidence_name)
    if not normalized_record_name or not normalized_evidence_name:
        return None
    if normalized_record_name == normalized_evidence_name:
        return None

    if _strip_ancillary_suffix(normalized_evidence_name) == normalized_record_name:
        return 'ancillary_entry_or_facility_name'

    if (
        _contains_any_keyword(record_name, GOVERNMENT_MAIN_ENTITY_KEYWORDS)
        and _contains_any_keyword(evidence_name, GOVERNMENT_AFFILIATED_FACILITY_KEYWORDS)
        and normalized_record_name not in normalized_evidence_name
    ):
        return 'government_affiliated_facility_not_primary_entity'

    return None


def _preprocess_evidence_data(
    record: Dict[str, Any], evidence_data: Iterable[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    retained: List[Dict[str, Any]] = []
    filtered: List[Dict[str, Any]] = []

    for item in evidence_data:
        reason = _invalid_evidence_reason(record, item)
        if reason is None:
            retained.append(item)
            continue

        filtered.append(
            {
                'evidence_id': str(_first_non_empty(item.get('evidence_id'), '')),
                'reason': reason,
                'name': str(_copy_json_dict(item.get('data')).get('name') or ''),
            }
        )

    summary = {
        'input_evidence_count': len(list(evidence_data)) if not isinstance(evidence_data, list) else len(evidence_data),
        'retained_evidence_count': len(retained),
        'filtered_evidence_count': len(filtered),
        'filtered_evidence': filtered,
    }
    return retained, summary


def is_canonical_input(payload: Dict[str, Any]) -> bool:
    return all(key in payload for key in ('record', 'evidence_data', 'upstream_decision'))


def is_legacy_flat_input(payload: Dict[str, Any]) -> bool:
    return not is_canonical_input(payload) and any(field in payload for field in LEGACY_HINT_FIELDS)


def _normalize_dimension_result(result: Any) -> str:
    value = str(result or '').strip().lower()
    if value in ('pass', 'fail', 'uncertain'):
        return value
    if value == 'risk':
        return 'uncertain'
    return 'uncertain'


def _normalize_dimension_details(details: Any) -> Dict[str, Any]:
    if isinstance(details, dict):
        return copy.deepcopy(details)
    if isinstance(details, str) and details.strip():
        return {'summary': details}
    return {}


def _normalize_upstream_dimension(value: Any) -> Dict[str, Any]:
    dim = _copy_json_dict(value)
    confidence = _to_probability(dim.get('confidence'))
    score = _to_probability(dim.get('score'), default=confidence)
    evidence_refs = dim.get('evidence_refs')
    if not isinstance(evidence_refs, list):
        evidence_refs = []

    return {
        'result': _normalize_dimension_result(dim.get('result')),
        'confidence': confidence,
        'score': score,
        'evidence_refs': [str(item) for item in evidence_refs if item not in (None, '')],
        'details': _normalize_dimension_details(dim.get('details')),
    }


def _derive_record_existence(payload: Dict[str, Any]) -> bool:
    verify_info = _copy_json_dict(payload.get('verify_info'))
    existence_info = _copy_json_dict(verify_info.get('existence'))
    existence_result = _normalize_dimension_result(existence_info.get('result'))
    if existence_result == 'pass':
        return True
    if existence_result == 'fail':
        return False

    poi_status = payload.get('poi_status')
    if poi_status in (0, '0', False):
        return False
    if poi_status in (1, '1', True):
        return True

    signal_text = ' '.join(
        str(_first_non_empty(payload.get('verify_result'), payload.get('quality_status'), '')).split()
    ).lower()
    if any(keyword in signal_text for keyword in REJECT_KEYWORDS):
        return False
    return True


def _normalize_evidence_item(item: Dict[str, Any]) -> Dict[str, Any]:
    evidence = copy.deepcopy(item)
    source = _copy_json_dict(evidence.get('source'))
    data = _copy_json_dict(evidence.get('data'))
    verification = _copy_json_dict(evidence.get('verification'))

    raw_data = _copy_json_dict(data.get('raw_data'))
    raw_core = _copy_json_dict(raw_data.get('data'))

    coordinates = _copy_json_dict(data.get('coordinates'))
    location = _copy_json_dict(data.get('location'))
    lon = _first_non_empty(coordinates.get('longitude'), location.get('longitude'))
    lat = _first_non_empty(coordinates.get('latitude'), location.get('latitude'))
    if lon is None or lat is None:
        parsed_lon, parsed_lat = _parse_location_string(raw_core.get('location'))
        lon = _first_non_empty(lon, parsed_lon)
        lat = _first_non_empty(lat, parsed_lat)

    normalized_location = {}
    lon_value = _to_float(lon)
    lat_value = _to_float(lat)
    address_value = _first_non_empty(data.get('address'), location.get('address'), raw_core.get('address'))
    if lon_value is not None:
        normalized_location['longitude'] = lon_value
    if lat_value is not None:
        normalized_location['latitude'] = lat_value
    if address_value is not None:
        normalized_location['address'] = str(address_value)
    if normalized_location:
        data['location'] = normalized_location

    if _first_non_empty(data.get('name'), raw_core.get('name')) is not None:
        data['name'] = str(_first_non_empty(data.get('name'), raw_core.get('name')))

    category_value = _first_non_empty(
        raw_core.get('typecode'),
        data.get('category'),
        raw_core.get('type'),
    )
    if category_value is not None:
        data['category'] = str(category_value)

    administrative = _copy_json_dict(data.get('administrative'))
    province = _first_non_empty(administrative.get('province'), raw_core.get('pname'))
    city = _first_non_empty(administrative.get('city'), raw_core.get('cityname'))
    district = _first_non_empty(administrative.get('district'), raw_core.get('adname'))
    if province is not None or city is not None or district is not None:
        data['administrative'] = {
            'province': str(province or ''),
            'city': str(city or ''),
            'district': str(district or ''),
        }

    if 'existence' not in data:
        data['existence'] = bool(verification.get('is_valid', True))

    verification['is_valid'] = bool(verification.get('is_valid', True))
    verification['confidence'] = _to_probability(verification.get('confidence'), default=1.0)

    evidence['source'] = source
    evidence['data'] = data
    evidence['verification'] = verification
    if _first_non_empty(evidence.get('evidence_id')) is not None:
        evidence['evidence_id'] = str(evidence['evidence_id'])
    return evidence


def _normalize_evidence_data(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    items = payload.get('evidence_record')
    if not isinstance(items, list) or not items:
        items = payload.get('evidence_data')
    if not isinstance(items, list):
        return []
    return [_normalize_evidence_item(item) for item in items if isinstance(item, dict)]


def _derive_administrative(payload: Dict[str, Any], evidence_data: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    province = payload.get('province')
    city = payload.get('city')
    district = payload.get('district')

    for item in evidence_data:
        evidence_admin = _copy_json_dict(item.get('data', {}).get('administrative'))
        province = _first_non_empty(province, evidence_admin.get('province'))
        city = _first_non_empty(city, evidence_admin.get('city'))
        district = _first_non_empty(district, evidence_admin.get('district'))
        if province and city and district:
            break

    return {
        'province': str(province or ''),
        'city': str(city or ''),
        'district': str(district or ''),
    }


def _build_upstream_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    verify_info = _copy_json_dict(payload.get('verify_info'))

    signal_text = ' '.join(
        str(_first_non_empty(payload.get('verify_result'), payload.get('quality_status'), '')).split()
    ).lower()
    if any(keyword in signal_text for keyword in MANUAL_REVIEW_KEYWORDS):
        status = 'manual_review'
        action = 'manual_review'
        is_downgraded = True
    elif any(keyword in signal_text for keyword in REJECT_KEYWORDS):
        status = 'rejected'
        action = 'reject'
        is_downgraded = False
    else:
        status = 'accepted'
        action = 'adopt'
        is_downgraded = False

    dimensions = {}
    confidences = []
    for dim_name in REQUIRED_UPSTREAM_DIMS:
        normalized = _normalize_upstream_dimension(verify_info.get(dim_name))
        dimensions[dim_name] = normalized
        confidences.append(normalized['confidence'])

    overall_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.5

    return {
        'decision_id': str(_first_non_empty(payload.get('batch_id'), payload.get('task_id'), '')),
        'poi_id': str(_first_non_empty(payload.get('poi_id'), payload.get('id'), '')),
        'overall': {
            'status': status,
            'confidence': overall_confidence,
            'action': action,
            'summary': str(_first_non_empty(payload.get('verify_result'), payload.get('quality_status'), 'legacy flat input normalized')),
        },
        'dimensions': dimensions,
        'downgrade_info': {
            'is_downgraded': is_downgraded,
            'reason_code': 'legacy_flat_input',
            'reason_description': str(_first_non_empty(payload.get('verify_result'), payload.get('quality_status'), 'legacy flat input normalized')),
        },
    }


def normalize_legacy_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_evidence_data = list(_normalize_evidence_data(payload))
    preliminary_record = {
        'task_id': str(_first_non_empty(payload.get('task_id'), '')),
        'poi_id': str(_first_non_empty(payload.get('poi_id'), payload.get('id'), '')),
        'name': str(_first_non_empty(payload.get('name'), '')),
        'location': {
            'longitude': _to_float(payload.get('x_coord')),
            'latitude': _to_float(payload.get('y_coord')),
            'address': str(_first_non_empty(payload.get('address'), '')),
        },
        'category': str(_first_non_empty(payload.get('poi_type'), '')),
        'administrative': {
            'province': str(_first_non_empty(payload.get('province'), '')),
            'city': str(_first_non_empty(payload.get('city'), '')),
            'district': str(_first_non_empty(payload.get('district'), '')),
        },
        'existence': _derive_record_existence(payload),
    }
    evidence_data, preprocessing_summary = _preprocess_evidence_data(preliminary_record, raw_evidence_data)
    administrative = _derive_administrative(payload, evidence_data)

    return {
        'record': {
            'task_id': preliminary_record['task_id'],
            'poi_id': preliminary_record['poi_id'],
            'name': preliminary_record['name'],
            'location': preliminary_record['location'],
            'category': preliminary_record['category'],
            'administrative': administrative,
            'existence': preliminary_record['existence'],
            'preprocessing': preprocessing_summary,
        },
        'evidence_data': evidence_data,
        'upstream_decision': _build_upstream_decision(payload),
    }


def preprocess_canonical_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(payload)
    record = _copy_json_dict(normalized.get('record'))
    raw_evidence_data = [_normalize_evidence_item(item) for item in normalized.get('evidence_data', []) if isinstance(item, dict)]
    filtered_evidence_data, preprocessing_summary = _preprocess_evidence_data(record, raw_evidence_data)
    record['preprocessing'] = preprocessing_summary
    normalized['record'] = record
    normalized['evidence_data'] = filtered_evidence_data
    return normalized


def normalize_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    if is_canonical_input(payload):
        return preprocess_canonical_input(payload)
    if is_legacy_flat_input(payload):
        return normalize_legacy_input(payload)
    raise ValueError('输入既不符合 canonical 结构，也不符合 legacy flat 结构')


def main() -> None:
    parser = argparse.ArgumentParser(description='Normalize BigPOI QC legacy flat input to canonical input')
    parser.add_argument('input_json', type=str, help='输入 JSON 文件路径')
    parser.add_argument('--output-json', type=str, default=None, help='输出 JSON 文件路径')
    parser.add_argument(
        '--output-format',
        type=str,
        choices=['json', 'text'],
        default='json',
        help='输出格式，默认 json',
    )
    args = parser.parse_args()

    input_path = Path(args.input_json)
    with open(input_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    normalized = normalize_input(payload)

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

    if args.output_format == 'json':
        print(json.dumps(normalized, ensure_ascii=False, indent=2))
    else:
        print('input_type:', 'canonical' if is_canonical_input(payload) else 'legacy_flat')
        print('task_id:', normalized.get('record', {}).get('task_id'))
        print('evidence_count:', len(normalized.get('evidence_data', [])))
        print('overall_status:', normalized.get('upstream_decision', {}).get('overall', {}).get('status'))


if __name__ == '__main__':
    main()
