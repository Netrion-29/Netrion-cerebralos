#!/usr/bin/env python3
"""
Canonical vitals schema v1 — deterministic, audit-traceable.

Transforms existing per-metric vitals rollups into canonical vital records
per docs/contracts/vitals_canonical_v1.md.

Each canonical record represents one measurement event (grouped by timestamp,
source, and evidence line) with all vital parameters populated.

Design:
- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Every record maps to exactly one raw_line_id for audit traceability.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Optional

# ── Contract v1 abnormal thresholds (locked) ───────────────────────
# Any changes require a schema version bump.
CANONICAL_ABNORMAL_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "Hypotension":  {"metric": "sbp",    "op": "<",  "value": 90},
    "Severe_HTN":   {"metric": "sbp",    "op": ">=", "value": 180},
    "Tachycardia":  {"metric": "hr",     "op": ">",  "value": 120},
    "Bradycardia":  {"metric": "hr",     "op": "<",  "value": 50},
    "Fever":        {"metric": "temp_c", "op": ">=", "value": 38.0},
    "Hypothermia":  {"metric": "temp_c", "op": "<",  "value": 36.0},
    "Hypoxia":      {"metric": "spo2",   "op": "<",  "value": 90},
    "Tachypnea":    {"metric": "rr",     "op": ">",  "value": 24},
}

# ── Source type mapping (existing extraction → contract values) ─────
_SOURCE_MAP: Dict[str, str] = {
    "FLOWSHEET":    "FLOWSHEET",
    "ED_TRIAGE":    "ED_NOTE",
    "VISIT_VITALS": "TRAUMA_HP",
    "INLINE":       "NURSING_NOTE",
}

# ── Metric keys extracted by vitals_daily ──────────────────────────
_VITALS_METRICS = ("temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map")


# ── Helpers ─────────────────────────────────────────────────────────

def _temp_f_to_c(temp_f: float) -> float:
    """Convert Fahrenheit to Celsius, rounded to 1 decimal."""
    return round((temp_f - 32) * 5.0 / 9.0, 1)


def _make_raw_line_id(source_id: Any, dt: Optional[str], preview: str) -> str:
    """
    Deterministic raw_line_id from evidence coordinates.

    Produces a stable hex digest so records are traceable to source evidence.
    Uses SHA-256 truncated to 16 hex chars for compactness.
    """
    key = f"{source_id or ''}|{dt or ''}|{preview or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _check_abnormal_flags(record: Dict[str, Any]) -> List[str]:
    """Apply locked v1 abnormal thresholds, return sorted list of flag names."""
    flags: List[str] = []
    for flag_name, rule in CANONICAL_ABNORMAL_THRESHOLDS.items():
        metric_val = record.get(rule["metric"])
        if metric_val is None:
            continue
        op = rule["op"]
        threshold = rule["value"]
        triggered = False
        if op == "<" and metric_val < threshold:
            triggered = True
        elif op == ">" and metric_val > threshold:
            triggered = True
        elif op == ">=" and metric_val >= threshold:
            triggered = True
        elif op == "<=" and metric_val <= threshold:
            triggered = True
        if triggered:
            flags.append(flag_name)
    return sorted(flags)


def _compute_confidence(
    dt: Optional[str],
    source_type: str,
    time_missing: bool,
    has_numeric: bool,
) -> int:
    """
    Deterministic confidence scoring per contract §5.

    +40: Complete timestamp (date + time)
    +20: Structured source (TRAUMA_HP or FLOWSHEET)
    +10: Parsed numeric integrity validated
    -20: Time defaulted (0000)

    Clamped 0–100.
    """
    score = 0

    # +40: Complete timestamp (has full date + time, not missing)
    if dt and "T" in str(dt) and not time_missing:
        score += 40

    # +20: Structured source
    if source_type in ("TRAUMA_HP", "FLOWSHEET"):
        score += 20

    # +10: Parsed numeric integrity validated
    if has_numeric:
        score += 10

    # -20: Time defaulted
    if time_missing:
        score -= 20

    return max(0, min(100, score))


# ── Public API ──────────────────────────────────────────────────────

def build_canonical_vitals(
    day_obj: Dict[str, Any],
    arrival_ts: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build canonical vital records from a single day's vitals block.

    Parameters
    ----------
    day_obj : dict
        The vitals dict for one day, as produced by extract_vitals_for_day.
        Expected keys: temp_f, hr, rr, spo2, sbp, dbp, map — each with
        ``sources: [{source_type, source_id, preview, value, dt, abnormal,
        time_missing}]``.
    arrival_ts : str, optional
        Arrival ISO timestamp (reserved for future arrival selector logic;
        unused in v1).

    Returns
    -------
    list[dict]
        Canonical vital records per contract schema v1, sorted
        deterministically by (ts, source, raw_line_id).
    """
    if not day_obj:
        return []

    # ── Step 1: Collect all source entries, tagged with metric name ──
    tagged_sources: List[Dict[str, Any]] = []
    for metric in _VITALS_METRICS:
        metric_data = day_obj.get(metric, {})
        for src in metric_data.get("sources", []):
            tagged_sources.append({
                "metric": metric,
                "value": src.get("value"),
                "dt": src.get("dt"),
                "source_type": src.get("source_type", ""),
                "source_id": src.get("source_id"),
                "preview": src.get("preview", ""),
                "time_missing": src.get("time_missing", False),
            })

    if not tagged_sources:
        return []

    # ── Step 2: Group by (dt, source_type, source_id, preview) ──────
    # This reconstructs composite measurement events: all metrics
    # from the same evidence line/row are grouped into one record.
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for ts in tagged_sources:
        key = (
            ts["dt"] or "",
            ts["source_type"] or "",
            ts["source_id"] or "",
            ts["preview"] or "",
        )
        groups[key].append(ts)

    # ── Step 3: Build canonical records ─────────────────────────────
    records: List[Dict[str, Any]] = []

    for (dt_key, stype_key, sid_key, prev_key), entries in groups.items():
        dt_str = dt_key if dt_key else None
        day_str = dt_str[:10] if dt_str and len(dt_str) >= 10 else None

        # Map source type to contract values
        source = _SOURCE_MAP.get(stype_key, stype_key)
        time_missing = entries[0].get("time_missing", False)

        # Build deterministic raw_line_id
        raw_line_id = _make_raw_line_id(sid_key, dt_key, prev_key)

        # Collect metric values (first value per metric in group)
        metric_values: Dict[str, Optional[float]] = {m: None for m in _VITALS_METRICS}
        for entry in entries:
            m = entry["metric"]
            if m in metric_values and metric_values[m] is None:
                metric_values[m] = entry["value"]

        # Derive temp_c from temp_f
        temp_c: Optional[float] = None
        if metric_values["temp_f"] is not None:
            temp_c = _temp_f_to_c(metric_values["temp_f"])

        # Confidence scoring
        has_numeric = any(v is not None for v in metric_values.values())
        confidence = _compute_confidence(dt_str, source, time_missing, has_numeric)

        record: Dict[str, Any] = {
            "ts": dt_str,
            "day": day_str,
            "source": source,
            "confidence": confidence,
            "raw_line_id": raw_line_id,
            "sbp": metric_values["sbp"],
            "dbp": metric_values["dbp"],
            "map": metric_values["map"],
            "hr": metric_values["hr"],
            "rr": metric_values["rr"],
            "spo2": metric_values["spo2"],
            "temp_c": temp_c,
            "temp_f": metric_values["temp_f"],
            "o2_device": None,   # not yet extracted; reserved
            "o2_flow_lpm": None,
            "fio2": None,
            "position": None,
            "abnormal_flags": [],
            "abnormal_count": 0,
        }

        # Apply locked abnormal thresholds
        flags = _check_abnormal_flags(record)
        record["abnormal_flags"] = flags
        record["abnormal_count"] = len(flags)

        records.append(record)

    # ── Step 4: Sort deterministically ──────────────────────────────
    records.sort(key=lambda r: (r["ts"] or "", r["source"] or "", r["raw_line_id"]))

    return records
