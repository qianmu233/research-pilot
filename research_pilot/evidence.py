"""Evidence identity and syntactic citation validation."""
from __future__ import annotations

import re

CITATION_PATTERN = re.compile(r"\[(S\d+)\]")


def merge_sources(previous: list[dict], new_sources: list[dict], limit: int) -> list[dict]:
    """Bounded, stable identity across rounds. Exact duplicate excerpts deduplicated."""
    merged = [dict(item) for item in previous]
    unique = {(item["locator"], item["excerpt"]) for item in merged}
    for item in new_sources:
        identity = (item["locator"], item["excerpt"])
        if identity in unique or len(merged) >= limit:
            continue
        unique.add(identity)
        merged.append({**item, "source_id": f"S{len(merged) + 1}"})
    return merged


def validate_citations(report: str, sources: list[dict]) -> tuple[bool, str]:
    """Validate citation identity only. NOT entailment/factual correctness."""
    allowed = {item["source_id"] for item in sources}
    used = set(CITATION_PATTERN.findall(report))
    unknown = used - allowed
    if unknown:
        return False, "UNKNOWN_CITATION_ID"
    if sources and not used:
        return False, "MISSING_CITATIONS"
    if len(report) > 20000:
        return False, "REPORT_TOO_LARGE"
    return True, "OK"
