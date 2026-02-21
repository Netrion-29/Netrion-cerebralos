#!/usr/bin/env python3
"""
Base Deficit Monitoring — Tier 1 Metric #3 (Deaconess Protocol)

Reference policy: "Monitoring Base Deficit" (Revised June 2023).

For Category I trauma patients:
  - Initial base deficit should be drawn unless cancelled by surgeon.
  - If BD > 4: monitor q2h until improving, then q4h until BD < 4
    or otherwise resuscitated.

Definitions (deterministic)
───────────────────────────
Base Deficit value:
  Accept "Base Deficit" and "Base Excess" (BD = -BE when explicitly
  labeled as base excess).  Reject values outside [-30, +30].

Specimen source:
  Prefer arterial if explicit ABG / arterial / "Art POC" context on
  the same line.  Otherwise "venous" if venous context, else "unknown".
  Do NOT infer arterial from timing alone.

Trigger:
  Activates if ANY BD value > 4 (per policy).

Improving:
  Two consecutive BD values that are strictly decreasing, OR a single
  subsequent BD at least 1 point lower than the prior value.
  (Rule: "improving" = bd[i] < bd[i-1] for two consecutive pairs.)

Cadence:
  q2h phase: expected interval ≤ 2.5 h (allow small charting slack).
  q4h phase: expected interval ≤ 4.5 h.

Stop conditions:
  q4h phase ends once BD < 4 (first time) OR no further labs
  (end_ts = null).

Design:
  Deterministic, fail-closed.  No LLM, no ML, no clinical inference.
  All outputs preserve raw_line_id traceability for each BD value.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ───────────────────────────────────────────────────────

# BD range sanity check — reject values outside this range.
_BD_MIN = -30.0
_BD_MAX = 30.0

# Trigger threshold per Deaconess protocol.
_BD_TRIGGER_THRESHOLD = 4.0

# Cadence thresholds (hours) — includes charting slack.
_Q2H_MAX_INTERVAL = 2.5
_Q4H_MAX_INTERVAL = 4.5

# ── Component name matching ─────────────────────────────────────────

# Patterns that identify a Base Deficit lab component (case-insensitive).
_BD_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^base\s*deficit", re.IGNORECASE),
    re.compile(r"^bd\b", re.IGNORECASE),
]

# Patterns that identify a Base Excess lab component (case-insensitive).
_BE_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^base\s*excess", re.IGNORECASE),
    re.compile(r"^be\b", re.IGNORECASE),
]

# Arterial context indicators on the same line / component name.
_ARTERIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bABG\b", re.IGNORECASE),
    re.compile(r"\barterial\b", re.IGNORECASE),
    re.compile(r"\bArt\s*POC\b", re.IGNORECASE),
]

# Venous context indicators.
_VENOUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bVBG\b", re.IGNORECASE),
    re.compile(r"\bvenous\b", re.IGNORECASE),
]


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: Any, dt: Optional[str], preview: str) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of evidence coordinates."""
    key = f"{source_id or ''}|{dt or ''}|{preview or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse a datetime string, tolerating multiple common formats."""
    if not dt_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def _is_bd_component(component: str) -> bool:
    """Return True if component name matches Base Deficit."""
    for pat in _BD_COMPONENT_PATTERNS:
        if pat.search(component):
            return True
    return False


def _is_be_component(component: str) -> bool:
    """Return True if component name matches Base Excess."""
    for pat in _BE_COMPONENT_PATTERNS:
        if pat.search(component):
            return True
    return False


def _infer_specimen(component: str, source_line: str) -> str:
    """Infer specimen source from component name and source line context."""
    combined = f"{component} {source_line}"
    for pat in _ARTERIAL_PATTERNS:
        if pat.search(combined):
            return "arterial"
    for pat in _VENOUS_PATTERNS:
        if pat.search(combined):
            return "venous"
    return "unknown"


def _extract_bd_value(
    component: str,
    value_num: Optional[float],
    value_raw: Optional[str],
) -> Optional[float]:
    """
    Extract the BD value from a lab row.

    If component is Base Excess, compute BD = -BE.
    Reject values outside [-30, +30].
    """
    if value_num is None:
        # Try to parse from value_raw
        if value_raw is not None:
            # Strip flags like "(H)", "(L)", "High", "Low"
            cleaned = re.sub(r"\s*\(.*?\)\s*", "", str(value_raw)).strip()
            cleaned = re.sub(r"\s*(High|Low|Critical|Final)\s*$", "", cleaned,
                             flags=re.IGNORECASE).strip()
            try:
                value_num = float(cleaned)
            except (ValueError, TypeError):
                return None
        else:
            return None

    # If Base Excess, convert: BD = -BE
    if _is_be_component(component):
        value_num = -value_num

    # Sanity check
    if value_num < _BD_MIN or value_num > _BD_MAX:
        return None

    return round(value_num, 2)


# ── Core extraction ─────────────────────────────────────────────────

def extract_base_deficit_monitoring(
    pat_features: Dict[str, Any],
    days_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract base deficit monitoring data from patient features and timeline.

    Parameters
    ----------
    pat_features : dict
        The patient_features_v1 dict (with "days" key containing per-day
        feature blocks including labs).
    days_json : dict
        The patient_days_v1 dict (for raw text access if needed).

    Returns
    -------
    dict : base_deficit_monitoring_v1 output contract.
    """
    feat_days = pat_features.get("days") or {}
    tl_days = days_json.get("days") or {}

    # ── Step 1: Collect all BD values from structured labs ───────
    bd_series: List[Dict[str, Any]] = []

    for day_iso in sorted(feat_days.keys()):
        day_block = feat_days[day_iso]
        labs = day_block.get("labs", {})

        # Walk the series dict — each component has a list of observations
        series = labs.get("series", {})
        for comp_name, obs_list in series.items():
            is_bd = _is_bd_component(comp_name)
            is_be = _is_be_component(comp_name)
            if not is_bd and not is_be:
                continue

            for obs in obs_list:
                obs_dt = obs.get("observed_dt") or obs.get("dt")
                value_num = obs.get("value_num")
                value_raw = obs.get("value_raw")
                source_line = obs.get("source_line") or ""

                bd_val = _extract_bd_value(comp_name, value_num, value_raw)
                if bd_val is None:
                    continue

                specimen = _infer_specimen(comp_name, source_line)

                # Build raw_line_id from source coordinates
                raw_line_id = obs.get("raw_line_id")
                if not raw_line_id:
                    raw_line_id = _make_raw_line_id(
                        obs.get("source_id", ""),
                        obs_dt,
                        _snippet(source_line, 80),
                    )

                bd_series.append({
                    "ts": obs_dt,
                    "value": bd_val,
                    "specimen": specimen,
                    "raw_line_id": raw_line_id,
                    "snippet": _snippet(source_line),
                })

        # Also check daily dict for components that might only appear there
        daily = labs.get("daily", {})
        for comp_name, comp_info in daily.items():
            is_bd = _is_bd_component(comp_name)
            is_be = _is_be_component(comp_name)
            if not is_bd and not is_be:
                continue

            # Only use daily if we didn't already get this from series
            # (check if we already have entries for this day)
            day_already_covered = any(
                e["ts"] and e["ts"].startswith(day_iso) for e in bd_series
            ) if bd_series else False

            if day_already_covered:
                continue

            # Try the "last" value from daily summary
            last_val = comp_info.get("last")
            first_val = comp_info.get("first")
            source_line = comp_info.get("source_line") or comp_name

            for val_candidate in [last_val, first_val]:
                if val_candidate is None:
                    continue
                # val_candidate might be numeric or string
                try:
                    raw_num = float(val_candidate)
                except (ValueError, TypeError):
                    continue

                bd_val = _extract_bd_value(comp_name, raw_num, str(val_candidate))
                if bd_val is None:
                    continue

                specimen = _infer_specimen(comp_name, source_line)
                raw_line_id = _make_raw_line_id("daily", day_iso, comp_name)

                bd_series.append({
                    "ts": day_iso + "T00:00:00" if day_iso else None,
                    "value": bd_val,
                    "specimen": specimen,
                    "raw_line_id": raw_line_id,
                    "snippet": f"daily_{comp_name}_{val_candidate}",
                })
                break  # only one entry per day from daily fallback

    # ── Also scan raw timeline items for BD values not captured ──
    # This catches labs that the structured extractor might miss
    # (e.g., POC variant names, unusual formatting)
    _scan_raw_timeline_for_bd(tl_days, bd_series)

    # ── Deduplicate by raw_line_id ──────────────────────────────
    bd_series = _dedup_by_line_id(bd_series)

    # ── Sort by timestamp ───────────────────────────────────────
    bd_series.sort(key=lambda e: e.get("ts") or "")

    # ── Handle empty series ─────────────────────────────────────
    if not bd_series:
        return _empty_result("DATA NOT AVAILABLE: no BD values found")

    # ── Step 2: Identify initial BD ─────────────────────────────
    initial = bd_series[0]

    # ── Step 3: Check trigger ───────────────────────────────────
    trigger_bd_gt4 = any(e["value"] > _BD_TRIGGER_THRESHOLD for e in bd_series)
    first_trigger_ts: Optional[str] = None
    first_trigger_idx: Optional[int] = None
    if trigger_bd_gt4:
        for i, e in enumerate(bd_series):
            if e["value"] > _BD_TRIGGER_THRESHOLD:
                first_trigger_ts = e["ts"]
                first_trigger_idx = i
                break

    # ── Step 4: Build monitoring windows ────────────────────────
    monitoring_windows: List[Dict[str, Any]] = []
    noncompliance_reasons: List[str] = []
    notes: List[str] = []

    if not trigger_bd_gt4:
        notes.append("BD never exceeded 4; no monitoring protocol triggered")
    else:
        assert first_trigger_idx is not None
        # Monitoring starts from the first trigger observation
        monitoring_series = bd_series[first_trigger_idx:]

        if len(monitoring_series) < 2:
            notes.append("Only one BD value after trigger; cannot assess cadence compliance")
            monitoring_windows.append({
                "phase": "q2h_until_improving",
                "start_ts": monitoring_series[0]["ts"],
                "end_ts": None,
                "expected_interval_hours": 2,
                "observations": 1,
                "max_gap_hours": None,
                "compliant": None,
                "violations": [],
            })
        else:
            # Determine phase transitions
            windows = _build_monitoring_windows(monitoring_series)
            monitoring_windows = windows

            # Collect violations
            for w in monitoring_windows:
                for v in w.get("violations", []):
                    noncompliance_reasons.append(
                        f"{w['phase']}: gap {v['gap_hours']:.1f}h "
                        f"({v['from_ts']} -> {v['to_ts']})"
                    )

    # ── Step 5: Compute overall compliance ──────────────────────
    overall_compliant: Optional[bool] = None
    if not trigger_bd_gt4:
        overall_compliant = None  # No monitoring required
    elif monitoring_windows:
        # Compliant if all windows are compliant (or None)
        compliant_flags = [w["compliant"] for w in monitoring_windows]
        if all(f is None for f in compliant_flags):
            overall_compliant = None
        elif any(f is False for f in compliant_flags):
            overall_compliant = False
        else:
            overall_compliant = True
    else:
        overall_compliant = None

    # Max gap across all windows
    max_gap_hours: Optional[float] = None
    for w in monitoring_windows:
        wg = w.get("max_gap_hours")
        if wg is not None:
            if max_gap_hours is None or wg > max_gap_hours:
                max_gap_hours = wg

    return {
        "initial_bd_ts": initial["ts"],
        "initial_bd_value": initial["value"],
        "initial_bd_source": initial["specimen"],
        "initial_bd_raw_line_id": initial["raw_line_id"],

        "trigger_bd_gt4": trigger_bd_gt4,
        "first_trigger_ts": first_trigger_ts,

        "bd_series": bd_series,

        "monitoring_windows": monitoring_windows,

        "overall_compliant": overall_compliant,
        "noncompliance_reasons": noncompliance_reasons,
        "notes": notes,
    }


# ── Window builder ──────────────────────────────────────────────────

def _build_monitoring_windows(
    series: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build monitoring windows from a BD series starting at trigger.

    Phase logic:
      1. Start in q2h_until_improving.
      2. "Improving" = two consecutive strictly decreasing BD values.
         i.e., series[i] > series[i+1] AND series[i+1] > series[i+2]
         for the first two consecutive decreases.
      3. Once improving detected, transition to q4h_until_lt4.
      4. q4h phase ends when BD < 4 or no more data.
    """
    windows: List[Dict[str, Any]] = []

    # Find improving point: index where two consecutive decreases occur
    improving_idx: Optional[int] = None
    for i in range(len(series) - 2):
        if series[i]["value"] > series[i + 1]["value"] > series[i + 2]["value"]:
            improving_idx = i + 2  # transition happens after the second decrease
            break

    # Build q2h window
    if improving_idx is not None:
        q2h_series = series[:improving_idx + 1]
        q2h_window = _build_single_window(
            q2h_series, "q2h_until_improving", 2, _Q2H_MAX_INTERVAL,
        )
        windows.append(q2h_window)

        # Build q4h window from improving_idx onward
        q4h_series = series[improving_idx:]

        # Find where BD < 4 in q4h phase
        lt4_idx: Optional[int] = None
        for j in range(len(q4h_series)):
            if q4h_series[j]["value"] < _BD_TRIGGER_THRESHOLD:
                lt4_idx = j
                break

        if lt4_idx is not None:
            q4h_sub = q4h_series[:lt4_idx + 1]
        else:
            q4h_sub = q4h_series

        q4h_window = _build_single_window(
            q4h_sub, "q4h_until_lt4", 4, _Q4H_MAX_INTERVAL,
        )
        if lt4_idx is None:
            q4h_window["end_ts"] = None  # still monitoring
        windows.append(q4h_window)
    else:
        # Never reached improving — entire series is q2h
        q2h_window = _build_single_window(
            series, "q2h_until_improving", 2, _Q2H_MAX_INTERVAL,
        )
        windows.append(q2h_window)

    return windows


def _build_single_window(
    series: List[Dict[str, Any]],
    phase: str,
    expected_interval: int,
    max_allowed_gap: float,
) -> Dict[str, Any]:
    """Build a single monitoring window from a BD sub-series."""
    if not series:
        return {
            "phase": phase,
            "start_ts": None,
            "end_ts": None,
            "expected_interval_hours": expected_interval,
            "observations": 0,
            "max_gap_hours": None,
            "compliant": None,
            "violations": [],
        }

    violations: List[Dict[str, Any]] = []
    max_gap: Optional[float] = None

    for i in range(len(series) - 1):
        dt1 = _parse_datetime(series[i]["ts"])
        dt2 = _parse_datetime(series[i + 1]["ts"])
        if dt1 is None or dt2 is None:
            continue
        gap_hours = (dt2 - dt1).total_seconds() / 3600.0
        gap_hours = round(gap_hours, 2)

        if max_gap is None or gap_hours > max_gap:
            max_gap = gap_hours

        if gap_hours > max_allowed_gap:
            violations.append({
                "gap_hours": gap_hours,
                "from_ts": series[i]["ts"],
                "to_ts": series[i + 1]["ts"],
                "note": (
                    f"Gap {gap_hours:.1f}h exceeds {phase} threshold "
                    f"of {max_allowed_gap}h"
                ),
            })

    compliant: Optional[bool] = None
    if len(series) >= 2:
        # Can assess compliance only if we have at least 2 timestamped values
        ts_count = sum(1 for e in series if _parse_datetime(e["ts"]) is not None)
        if ts_count >= 2:
            compliant = len(violations) == 0

    return {
        "phase": phase,
        "start_ts": series[0]["ts"],
        "end_ts": series[-1]["ts"],
        "expected_interval_hours": expected_interval,
        "observations": len(series),
        "max_gap_hours": max_gap,
        "compliant": compliant,
        "violations": violations,
    }


# ── Raw timeline scanner (supplementary) ───────────────────────────


def _scan_raw_timeline_for_bd(
    tl_days: Dict[str, Any],
    existing_series: List[Dict[str, Any]],
) -> None:
    """
    Scan raw timeline items for BD values not already in the series.
    Appends new entries in-place to existing_series.
    """
    existing_ids = {e["raw_line_id"] for e in existing_series}

    for day_iso in sorted(tl_days.keys()):
        day_info = tl_days[day_iso]
        for item in day_info.get("items") or []:
            item_type = item.get("type", "")
            if item_type != "LAB":
                continue

            item_dt = item.get("dt")
            source_id = item.get("source_id", "")
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            for line in text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue

                # Check if this line mentions Base Deficit / BD
                if not re.search(r"\b(base\s*deficit|BD)\b", stripped, re.IGNORECASE):
                    continue

                raw_line_id = _make_raw_line_id(source_id, item_dt, _snippet(stripped, 80))
                if raw_line_id in existing_ids:
                    continue

                # Try to extract a numeric value
                bd_val = _try_parse_bd_from_line(stripped)
                if bd_val is None:
                    continue

                # Range check
                if bd_val < _BD_MIN or bd_val > _BD_MAX:
                    continue

                specimen = _infer_specimen("Base Deficit", stripped)

                existing_series.append({
                    "ts": item_dt,
                    "value": round(bd_val, 2),
                    "specimen": specimen,
                    "raw_line_id": raw_line_id,
                    "snippet": _snippet(stripped),
                })
                existing_ids.add(raw_line_id)


def _try_parse_bd_from_line(line: str) -> Optional[float]:
    """Try to extract a BD numeric value from a raw text line."""
    # Pattern: "Base Deficit    0.1 (H)" or "Base Deficit, Art POC    3.0 High"
    m = re.search(
        r"(?:base\s*deficit|BD)"
        r"(?:[,\s]*(?:Art\s*POC)?)?"
        r"\s+"
        r"(?:\d{1,2}/\d{1,2}/\d{4}\s+)?"  # optional date
        r"([+-]?\d+\.?\d*)",
        line,
        re.IGNORECASE,
    )
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            pass
    return None


# ── Utility ─────────────────────────────────────────────────────────

def _dedup_by_line_id(
    series: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Deduplicate by raw_line_id, preserving order."""
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for e in series:
        rid = e.get("raw_line_id", "")
        if rid not in seen:
            seen.add(rid)
            result.append(e)
    return result


def _empty_result(note: str) -> Dict[str, Any]:
    """Return the output contract with all-null/empty values."""
    return {
        "initial_bd_ts": None,
        "initial_bd_value": None,
        "initial_bd_source": "unknown",
        "initial_bd_raw_line_id": None,

        "trigger_bd_gt4": None,
        "first_trigger_ts": None,

        "bd_series": [],

        "monitoring_windows": [],

        "overall_compliant": None,
        "noncompliance_reasons": [],
        "notes": [note],
    }
