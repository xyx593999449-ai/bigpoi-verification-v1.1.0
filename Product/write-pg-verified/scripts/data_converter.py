#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data conversion helpers for verified POI writes."""

from typing import Any, Dict, List, Optional

try:
    from logger_config import get_logger
except ImportError:
    from .logger_config import get_logger

logger = get_logger(__name__)


class DataConverter:
    """Convert upstream verification artifacts into poi_verified row payloads."""

    STATUS_MAP = {
        "accepted": "\u6838\u5b9e\u901a\u8fc7",
        "downgraded": "\u9700\u4eba\u5de5\u6838\u5b9e",
        "manual_review": "\u9700\u4eba\u5de5\u6838\u5b9e",
        "rejected": "\u9700\u4eba\u5de5\u6838\u5b9e",
    }

    POI_STATUS_MAP = {
        "pass": 1,
        "uncertain": 4,
        "fail": 5,
        "upgrade": 2,
        "downgrade": 3,
        "split": 6,
    }

    def decision_to_db_format(
        self,
        decision: Dict,
        evidence: List[Dict],
        poi_data: Dict,
        task_id: Optional[str] = None,
        record: Optional[Dict] = None,
    ) -> Dict:
        logger.debug("start converting decision payload to db format")

        overall = decision.get("overall", {})
        overall_status = overall.get("status", "manual_review")
        verify_result = self.STATUS_MAP.get(overall_status, "\u9700\u4eba\u5de5\u6838\u5b9e")

        dimensions = decision.get("dimensions", {})
        existence_result = dimensions.get("existence", {}).get("result", "uncertain")
        poi_status = self.POI_STATUS_MAP.get(existence_result, 4)

        final_changes = self._extract_changes(record, decision)
        verification_notes = str(overall.get("summary") or "").strip()

        db_data = {
            "task_id": task_id if task_id else decision.get("poi_id", poi_data.get("id", "")),
            "id": poi_data.get("id", ""),
            "name": poi_data.get("name", ""),
            "x_coord": poi_data.get("x_coord"),
            "y_coord": poi_data.get("y_coord"),
            "poi_type": poi_data.get("poi_type"),
            "address": poi_data.get("address"),
            "city": poi_data.get("city"),
            "city_adcode": poi_data.get("city_adcode"),
            "verify_result": verify_result,
            "overall_confidence": overall.get("confidence"),
            "poi_status": poi_status,
            "verify_info": self._convert_dimensions(dimensions),
            "evidence_record": self._convert_evidence(evidence),
            "changes_made": final_changes,
            "verification_notes": verification_notes,
            "verify_status": "\u5df2\u6838\u5b9e" if verify_result == "\u6838\u5b9e\u901a\u8fc7" else "\u9700\u4eba\u5de5\u6838\u5b9e",
        }

        logger.debug(
            "converted db payload: task_id=%s verify_result=%s poi_status=%s changes=%s",
            db_data["task_id"],
            verify_result,
            poi_status,
            len(final_changes or []),
        )
        return db_data

    def _convert_dimensions(self, dimensions: Dict) -> Dict:
        if not dimensions:
            return {}
        return dimensions if isinstance(dimensions, dict) else {}

    def _convert_evidence(self, evidence: List[Dict]) -> List[Dict]:
        if not evidence:
            return []
        if isinstance(evidence, list):
            return evidence
        return [evidence] if isinstance(evidence, dict) else []

    def _extract_changes(self, record: Optional[Dict], decision: Dict) -> Optional[List[Dict]]:
        record_changes = self._extract_record_changes(record)
        if record_changes:
            return record_changes
        return self._convert_corrections(decision.get("corrections"))

    def _extract_record_changes(self, record: Optional[Dict]) -> Optional[List[Dict]]:
        if not isinstance(record, dict):
            return None
        verification_result = record.get("verification_result")
        if not isinstance(verification_result, dict):
            return None
        changes = verification_result.get("changes")
        if not isinstance(changes, list):
            return None

        normalized: List[Dict] = []
        for item in changes:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            old_value = item.get("old_value")
            new_value = item.get("new_value")
            reason = str(item.get("reason") or "").strip()
            if not field or new_value in (None, "") or not reason:
                continue
            normalized.append({"field": field, "old_value": old_value, "new_value": new_value, "reason": reason})
        return normalized or None

    def _convert_corrections(self, corrections: Any) -> Optional[List[Dict]]:
        if not corrections or not isinstance(corrections, dict):
            return None

        normalized: List[Dict] = []
        for field, item in corrections.items():
            if not isinstance(item, dict):
                continue
            suggested = item.get("suggested")
            reason = str(item.get("reason") or "").strip()
            if suggested is None or suggested == "" or not reason:
                continue
            normalized.append({"field": field, "old_value": item.get("original"), "new_value": suggested, "reason": reason})
        return normalized or None

    def direct_data_to_db_format(self, data: Dict) -> Dict:
        verify_result = data.get("verify_result", "\u9700\u4eba\u5de5\u6838\u5b9e")
        return {
            "task_id": data.get("task_id", ""),
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "x_coord": data.get("x_coord"),
            "y_coord": data.get("y_coord"),
            "poi_type": data.get("poi_type"),
            "address": data.get("address"),
            "city": data.get("city"),
            "city_adcode": data.get("city_adcode"),
            "verify_result": verify_result,
            "overall_confidence": data.get("overall_confidence"),
            "poi_status": data.get("poi_status", 1),
            "verify_info": data.get("verify_info", {}),
            "evidence_record": data.get("evidence_record", {}),
            "changes_made": data.get("changes_made"),
            "verification_notes": data.get("verification_notes", ""),
            "verify_status": "\u5df2\u6838\u5b9e" if verify_result == "\u6838\u5b9e\u901a\u8fc7" else "\u9700\u4eba\u5de5\u6838\u5b9e",
        }

    def validate_db_format(self, data: Dict) -> bool:
        required_fields = ["task_id", "id", "verify_result"]
        for field in required_fields:
            if field not in data or not data[field]:
                raise ValueError(f"\u6570\u636e\u5e93\u683c\u5f0f\u6570\u636e\u7f3a\u5c11\u5fc5\u9700\u5b57\u6bb5: {field}")

        valid_results = ["\u6838\u5b9e\u901a\u8fc7", "\u9700\u4eba\u5de5\u6838\u5b9e"]
        if data["verify_result"] not in valid_results:
            raise ValueError(f"verify_result \u503c\u65e0\u6548: {data['verify_result']}")
        return True

    def merge_with_poi_init_data(self, db_data: Dict, poi_init_data: Optional[Dict] = None) -> Dict:
        if not poi_init_data:
            return db_data
        merge_fields = ["name", "x_coord", "y_coord", "poi_type", "address", "city", "city_adcode"]
        for field in merge_fields:
            if db_data.get(field) is None and field in poi_init_data:
                db_data[field] = poi_init_data[field]
        return db_data

    def extract_statistics_from_decision(self, decision: Dict) -> Dict[str, Any]:
        overall = decision.get("overall", {})
        dimensions = decision.get("dimensions", {})
        correction_source = decision.get("corrections", {})
        correction_count = len(correction_source) if isinstance(correction_source, dict) else 0
        return {
            "overall_status": overall.get("status", ""),
            "overall_confidence": overall.get("confidence", 0.0),
            "existence_result": dimensions.get("existence", {}).get("result", ""),
            "name_result": dimensions.get("name", {}).get("result", ""),
            "address_result": dimensions.get("address", {}).get("result", dimensions.get("location", {}).get("result", "")),
            "coordinates_result": dimensions.get("coordinates", {}).get("result", dimensions.get("location", {}).get("result", "")),
            "location_result": dimensions.get("location", {}).get("result", ""),
            "category_result": dimensions.get("category", {}).get("result", ""),
            "has_corrections": correction_count > 0,
            "correction_count": correction_count,
        }
