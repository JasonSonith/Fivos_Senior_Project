from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class ComparisonValidator:
    def __init__(self) -> None:
        self.fields_to_compare = [
            "device_name",
            "manufacturer",
            "model_number",
            "catalog_number",
            "device_description",
            "dimensions",
        ]

    def compare_records(
        self, harvested: Dict[str, Any], gudid: Dict[str, Any]
    ) -> Dict[str, Any]:
        field_results: Dict[str, Dict[str, Any]] = {}

        for field in self.fields_to_compare:
            harvested_value = harvested.get(field)
            gudid_value = gudid.get(field)

            status = self.compare_field(field, harvested_value, gudid_value)

            field_results[field] = {
                "harvested": harvested_value,
                "gudid": gudid_value,
                "status": status,
            }

        overall_status = self.get_overall_status(field_results)
        summary = self.build_summary(field_results)

        return {
            "fields": field_results,
            "overall_status": overall_status,
            "summary": summary,
        }

    def compare_field(
        self, field_name: str, harvested_value: Any, gudid_value: Any
    ) -> str:
        if self.is_missing(harvested_value) or self.is_missing(gudid_value):
            return "missing"

        if field_name == "dimensions":
            return self.compare_dimensions(harvested_value, gudid_value)

        return self.compare_text_values(harvested_value, gudid_value)

    def compare_dimensions(self, harvested_value: Any, gudid_value: Any) -> str:
        h_norm = self.normalize_dimension_text(harvested_value)
        g_norm = self.normalize_dimension_text(gudid_value)

        if h_norm is None or g_norm is None:
            return self.compare_text_values(harvested_value, gudid_value)

        if h_norm == g_norm:
            return "match"

        if h_norm in g_norm or g_norm in h_norm:
            return "partial"

        return "mismatch"

    def compare_text_values(self, harvested_value: Any, gudid_value: Any) -> str:
        if self.is_missing(harvested_value) or self.is_missing(gudid_value):
            return "missing"

        norm_harvested = self.normalize_text(harvested_value)
        norm_gudid = self.normalize_text(gudid_value)

        if norm_harvested == norm_gudid:
            return "match"

        if self.is_partial_match(norm_harvested, norm_gudid):
            return "partial"

        return "mismatch"

    def normalize_text(self, value: Any) -> str:
        text = str(value).lower().strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^a-z0-9.\- ]", "", text)
        return text

    def normalize_dimension_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).lower().strip()
        text = re.sub(r"\s+", "", text)

        if text == "":
            return None

        return text

    def is_partial_match(self, a: str, b: str) -> bool:
        if not a or not b:
            return False

        if a in b or b in a:
            return True

        a_words = set(a.split())
        b_words = set(b.split())

        if not a_words or not b_words:
            return False

        overlap = a_words.intersection(b_words)
        smaller_size = min(len(a_words), len(b_words))

        return len(overlap) >= 1 and len(overlap) >= max(1, smaller_size // 2)

    def is_missing(self, value: Any) -> bool:
        return value is None or str(value).strip() == ""

    def get_overall_status(self, field_results: Dict[str, Dict[str, Any]]) -> str:
        statuses: List[str] = [info["status"] for info in field_results.values()]

        if statuses and all(status == "match" for status in statuses):
            return "match"

        if any(status == "mismatch" for status in statuses):
            return "mismatch"

        return "partial"

    def build_summary(self, field_results: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
        summary = {
            "matches": 0,
            "partials": 0,
            "mismatches": 0,
            "missing": 0,
        }

        for info in field_results.values():
            status = info["status"]
            if status == "match":
                summary["matches"] += 1
            elif status == "partial":
                summary["partials"] += 1
            elif status == "mismatch":
                summary["mismatches"] += 1
            elif status == "missing":
                summary["missing"] += 1

        return summary