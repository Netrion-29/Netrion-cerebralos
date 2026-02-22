#!/usr/bin/env python3
"""
INR Normalization v1 — Tier 1 Metric #4

Deterministic INR extraction normalization for CerebralOS.

Takes structured lab data already extracted by labs_extract + labs_daily
and applies normalization / validation:

  1. Identify INR values vs PT (prothrombin time) seconds.
  2. Sanity-gate INR values: 0.5 ≤ INR ≤ 20.0.
  3. Reject PT seconds masquerading as INR (PT is typically 9–40 sec,
     INR is typically 0.8–4.0; overlap region 4–9 resolved by
     component name).
  4. Preserve traceability via raw_line_id.

Output key: inr_normalization_v1
Design: Deterministic, fail-closed.  No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ───────────────────────────────────────────────────────

# Sane INR range.  Clinical INR is typically 0.8–4.0 for warfarin patients.
# We allow 0.5–20.0 to catch severe coagulopathy but reject gross errors.
_INR_MIN = 0.5
_INR_MAX = 20.0

# PT seconds sanity range.  Normal PT is roughly 9.5–13.8 sec.
# On anticoagulants can be 15–35+.  Values > 40 are extreme.
_PT_MIN = 5.0
_PT_MAX = 100.0

# Component names that are explicitly INR (case-insensitive).
_INR_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^INR$", re.IGNORECASE),
    re.compile(r"^INR\b", re.IGNORECASE),
]

# Component names that are explicitly PT / prothrombin time (NOT INR).
_PT_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^PROTIME$", re.IGNORECASE),
    re.compile(r"^Pro\s*Time$", re.IGNORECASE),
    re.compile(r"^PT$", re.IGNORECASE),
    re.compile(r"^Prothrombin\s*Time$", re.IGNORECASE),
]


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: Any, dt: Optional[str], preview: str) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of evidence coordinates."""
    key = f"{source_id or ''}|{dt or ''}|{preview or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _is_inr_component(comp: str) -> bool:
    """Return True if comp matches an INR component name."""
    for pat in _INR_COMPONENT_PATTERNS:
        if pat.search(comp):
            return True
    return False


def _is_pt_component(comp: str) -> bool:
    """Return True if comp matches a PT/PROTIME component name."""
    for pat in _PT_COMPONENT_PATTERNS:
        if pat.search(comp):
            return True
    return False


def _classify_coag_value(
    comp: str,
    value_num: Optional[float],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Classify a coagulation value as INR or PT based on component name
    and value range.

    Returns (classification, parse_warning).

    Classification:
      - "inr" — confirmed INR
      - "pt_seconds" — confirmed prothrombin time in seconds
      - None — rejected / unclassifiable

    parse_warning:
      - None if clean
      - Descriptive string if ambiguous or rejected
    """
    if value_num is None:
        return None, "value is null"

    # Component name takes priority
    if _is_inr_component(comp):
        # Known INR component — validate range
        if _INR_MIN <= value_num <= _INR_MAX:
            return "inr", None
        elif value_num > _INR_MAX:
            return None, f"INR value {value_num} exceeds max {_INR_MAX}; rejected"
        elif value_num < _INR_MIN:
            return None, f"INR value {value_num} below min {_INR_MIN}; rejected"

    if _is_pt_component(comp):
        # Known PT component — never treat as INR
        return "pt_seconds", None

    # Unrecognized component — reject (fail-closed)
    return None, f"component '{comp}' not recognized as INR or PT; skipped"


# ── Core extraction ─────────────────────────────────────────────────

def extract_inr_normalization(
    pat_features: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract and normalize INR values from patient features.

    Scans structured labs across all days for INR components.
    Applies sanity gates and classifies INR vs PT deterministically.

    Parameters
    ----------
    pat_features : dict
        The patient_features_v1 dict (with "days" key).

    Returns
    -------
    dict : inr_normalization_v1 output contract.
    """
    feat_days = pat_features.get("days") or {}

    inr_series: List[Dict[str, Any]] = []
    parse_warnings: List[str] = []

    for day_iso in sorted(feat_days.keys()):
        day_block = feat_days[day_iso]
        labs = day_block.get("labs", {})

        # Walk the series dict
        series = labs.get("series", {})
        for comp_name, obs_list in series.items():
            classification, warn = _classify_coag_value(
                comp_name, None,  # pre-screen component name
            )

            # Only process INR-classified components
            if not _is_inr_component(comp_name):
                continue

            for obs in obs_list:
                obs_dt = obs.get("observed_dt") or obs.get("dt")
                value_num = obs.get("value_num")
                value_raw = obs.get("value_raw", "")
                source_line = obs.get("source_line")

                # Parse value if not numeric
                if value_num is None and value_raw:
                    cleaned = re.sub(
                        r"\s*\(.*?\)\s*", "", str(value_raw),
                    ).strip()
                    cleaned = re.sub(
                        r"\s*(High|Low|Critical|Final|Abnormal)\s*$",
                        "", cleaned, flags=re.IGNORECASE,
                    ).strip()
                    cleaned = cleaned.rstrip("*").strip()
                    # Strip < and > qualifiers (e.g. "<0.5", ">20")
                    cleaned = cleaned.replace("<", "").replace(">", "").strip()
                    try:
                        value_num = float(cleaned)
                    except (ValueError, TypeError):
                        parse_warnings.append(
                            f"unparseable INR value_raw '{value_raw}' "
                            f"on {obs_dt}"
                        )
                        continue

                # Classify and validate
                cls, cls_warn = _classify_coag_value(comp_name, value_num)
                if cls_warn:
                    parse_warnings.append(cls_warn)
                if cls != "inr":
                    continue

                # Build raw_line_id
                raw_line_id = obs.get("raw_line_id")
                if not raw_line_id:
                    raw_line_id = _make_raw_line_id(
                        obs.get("source_id", ""),
                        obs_dt,
                        str(value_raw)[:80],
                    )

                inr_series.append({
                    "ts": obs_dt,
                    "inr_value": round(value_num, 2),
                    "source_lab": comp_name,
                    "raw_line_id": raw_line_id,
                    "parse_warning": cls_warn,
                    "ts_granularity": "datetime",
                })

    # Also check daily dict as fallback
    for day_iso in sorted(feat_days.keys()):
        day_block = feat_days[day_iso]
        labs = day_block.get("labs", {})
        daily = labs.get("daily", {})

        for comp_name, comp_info in daily.items():
            if not _is_inr_component(comp_name):
                continue

            # Check if this day already covered from series
            day_already_covered = any(
                e["ts"] and e["ts"].startswith(day_iso) for e in inr_series
            ) if inr_series else False

            if day_already_covered:
                continue

            last_val = comp_info.get("last")
            if last_val is None:
                continue

            try:
                value_num = float(last_val)
            except (ValueError, TypeError):
                parse_warnings.append(
                    f"unparseable INR daily value '{last_val}' on {day_iso}"
                )
                continue

            cls, cls_warn = _classify_coag_value(comp_name, value_num)
            if cls_warn:
                parse_warnings.append(cls_warn)
            if cls != "inr":
                continue

            # Daily fallback: raw_line_id is synthetic (no line-level
            # evidence coordinates).  ts is day-level only (no time).
            raw_line_id = _make_raw_line_id(
                "daily_fallback", day_iso, comp_name,
            )

            inr_series.append({
                "ts": day_iso,
                "inr_value": round(value_num, 2),
                "source_lab": comp_name,
                "raw_line_id": raw_line_id,
                "parse_warning": cls_warn,
                "ts_granularity": "day",
            })

    # Dedup by raw_line_id
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for e in inr_series:
        rid = e.get("raw_line_id", "")
        if rid not in seen:
            seen.add(rid)
            deduped.append(e)
    inr_series = deduped

    # Sort by timestamp
    inr_series.sort(key=lambda e: e.get("ts") or "")

    if not inr_series:
        return {
            "initial_inr_ts": None,
            "initial_inr_value": None,
            "initial_inr_source_lab": None,
            "inr_series": [],
            "inr_count": 0,
            "parse_warnings": parse_warnings or ["DATA NOT AVAILABLE: no INR values found"],
            "notes": ["DATA NOT AVAILABLE: no INR values found"],
        }

    initial = inr_series[0]

    return {
        "initial_inr_ts": initial["ts"],
        "initial_inr_value": initial["inr_value"],
        "initial_inr_source_lab": initial["source_lab"],
        "inr_series": inr_series,
        "inr_count": len(inr_series),
        "parse_warnings": parse_warnings,
        "notes": [],
    }
