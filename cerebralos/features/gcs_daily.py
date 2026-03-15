#!/usr/bin/env python3
"""
Per-day GCS extraction for CerebralOS features.

Extracts Glasgow Coma Scale values from timeline items per calendar day.

Output per day::

    gcs_daily: {
      arrival_gcs: {value, source, dt, timestamp_quality} | "DATA NOT AVAILABLE",
      arrival_gcs_value:               int | None,
      arrival_gcs_ts:                  str | None,
      arrival_gcs_source:              str | None,
      arrival_gcs_missing_in_trauma_hp: bool,
      arrival_gcs_source_rule_id:      str | None,
      best_gcs:    {value, source, dt, timestamp_quality} | "DATA NOT AVAILABLE",
      worst_gcs:   {value, source, dt, timestamp_quality} | "DATA NOT AVAILABLE",
      all_readings: [{value, source, dt, timestamp_quality, is_arrival}, ...],
      warnings: [...]
    }

Rules:
- arrival_gcs: First from TRAUMA_HP items, ONLY within the Primary Survey
  section (specifically the Disability line).  Hard priority.
- If TRAUMA_HP exists but no primary-survey GCS found:
    arrival_gcs_missing_in_trauma_hp = True
    arrival_gcs_source_rule_id = "trauma_hp_primary_survey_missing_fallback_ed"
    Fallback to ED_NOTE: earliest numeric GCS within 0–120 min of
    arrival_datetime.
- If neither exists → DATA NOT AVAILABLE.
- best_gcs / worst_gcs: across ALL readings for that day.
- Narrative-only neuro (alert/oriented, confused, etc.) → DATA NOT AVAILABLE.
  We never infer a numeric GCS from narrative descriptions.
- Questionnaire lines like "GCS 3-4?" or "GCS 13-15?" are excluded.
- "pupil and GCS changes" (no numeric value) → excluded.

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import re
from datetime import datetime as _dt, timedelta
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── GCS regex patterns ──────────────────────────────────────────────

# Pattern 1: "GCS: 15" or "GCS 15" or "GCS:  15" — simple total score
# Accepts optional T/t suffix (intubated marker).
# Must NOT be followed by a hyphen (which indicates a questionnaire range).
RE_GCS_SIMPLE = re.compile(
    r"\bGCS\s*:?\s*(\d{1,2})\s*([Tt])?"
    r"(?!\s*[-\u2013])"             # negative lookahead: not "GCS 3-4"
    r"(?!\s*\?)",                    # negative lookahead: not "GCS 15?"
    re.IGNORECASE,
)

# Pattern 2: Component form "GCS (E: 3 V: 1T M: 5) 9T"
RE_GCS_COMPONENT_PAREN = re.compile(
    r"\bGCS\s*\(\s*E\s*:?\s*(\d)\s*V\s*:?\s*(\d)\s*[Tt]?\s*M\s*:?\s*(\d)\s*\)\s*(\d{1,2})\s*([Tt])?",
    re.IGNORECASE,
)

# Pattern 3: Compact "E3vtm5 gcs 8t" or "E2vtm4 gcs 7t"
RE_GCS_COMPACT = re.compile(
    r"\bE(\d)\s*[Vv](\d?)\s*[Tt]\s*[Mm](\d)\s+[Gg][Cc][Ss]\s*(\d{1,2})\s*([Tt])?",
)

# Pattern 4: "GCS  E:1 V:1T, M:4, 6T" — GCS followed by components then total
RE_GCS_INLINE_COMPONENTS = re.compile(
    r"\bGCS\s+E\s*:?\s*(\d)\s*[,\s]*V\s*:?\s*(\d)\s*[Tt]?\s*[,\s]*M\s*:?\s*(\d)\s*[,\s]*(\d{1,2})\s*([Tt])?",
    re.IGNORECASE,
)

# Pattern for Primary Survey → Disability line (arrival GCS)
RE_DISABILITY_GCS = re.compile(
    r"Disability\s*:\s*(?:GCS\s*)?GCS\s*:?\s*(\d{1,2})\s*([Tt])?",
    re.IGNORECASE,
)

# Lines to EXCLUDE: questionnaire items with ranges
RE_GCS_QUESTIONNAIRE = re.compile(
    r"\bGCS\s+\d{1,2}\s*[-\u2013]\s*\d{1,2}\s*\?",
    re.IGNORECASE,
)

# Lines to EXCLUDE: narrative references without numeric values
RE_GCS_NARRATIVE_ONLY = re.compile(
    r"\bGCS\s+(changes|change|assessment|score\s+not|trending)",
    re.IGNORECASE,
)

# Pattern 5: "GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 15"
RE_GCS_DESC_COMPONENTS = re.compile(
    r"\bGCS\s*:\s*(\d)\s*\([^)]+\)\s*,\s*(\d)\s*\([^)]+\)\s*,\s*(\d)\s*\([^)]+\)\s*=\s*(\d{1,2})",
    re.IGNORECASE,
)

# Structured 4-line flowsheet block patterns
RE_FLOWSHEET_EYE = re.compile(r"^Eye Opening\s*:\s*(.+)", re.IGNORECASE)
RE_FLOWSHEET_VERBAL = re.compile(r"^Best Verbal Response\s*:\s*(.+)", re.IGNORECASE)
RE_FLOWSHEET_MOTOR = re.compile(r"^Best Motor Response\s*:\s*(.+)", re.IGNORECASE)
RE_FLOWSHEET_TOTAL = re.compile(
    r"^Glasgow Coma Scale Score\s*:?\s*(\d{1,2})", re.IGNORECASE,
)

# ── GCS component text→number mappings (deterministic) ──────────────

_EYE_MAP: Dict[str, int] = {
    "spontaneous": 4, "spontaneously": 4,
    "to speech": 3, "to voice": 3,
    "to pain": 2, "to pressure": 2,
    "none": 1, "no response": 1,
}

_VERBAL_MAP: Dict[str, int] = {
    "oriented": 5,
    "confused": 4,
    "inappropriate words": 3, "inappropriate": 3,
    "incomprehensible sounds": 2, "incomprehensible": 2,
    "none": 1, "no response": 1,
}

_MOTOR_MAP: Dict[str, int] = {
    "obeys commands": 6, "obeys": 6,
    "localizes pain": 5, "localizes": 5, "localizing": 5,
    "withdrawal": 4, "flexion withdrawal": 4, "normal flexion": 4,
    "abnormal flexion": 3, "flexion": 3,
    "extension": 2,
    "none": 1, "no response": 1,
}


def _lookup_component(text: str, mapping: Dict[str, int]) -> Optional[int]:
    """Map component description text to numeric GCS sub-score.
    Returns None if the text is not a recognized value (fail-closed)."""
    return mapping.get(text.strip().lower())


def _extract_gcs_from_text(
    text: str,
    dt: Optional[str],
    source_type: str,
    source_id: Optional[str],
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Extract GCS readings from a text block.

    Returns (all_readings, arrival_gcs_reading).
    arrival_gcs_reading is non-None only if source_type == TRAUMA_HP and
    the value comes from the Primary Survey Disability line.
    """
    readings: List[Dict[str, Any]] = []
    arrival: Optional[Dict[str, Any]] = None
    seen_values: set = set()  # dedup within same text block

    timestamp_quality = "full" if dt and "T" in str(dt) else "date_only" if dt else "missing"

    lines = text.split("\n")

    # ── Check for Primary Survey arrival GCS (TRAUMA_HP only) ──
    in_primary_survey = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"Primary\s+Survey\s*:", stripped, re.IGNORECASE):
            in_primary_survey = True
            continue
        # End of primary survey section: a new major section header
        if in_primary_survey and re.match(
            r"(Secondary\s+Survey|PMH|Past\s+Medical|ROS|HPI|Allergies)\s*:",
            stripped,
            re.IGNORECASE,
        ):
            in_primary_survey = False
            continue

        if in_primary_survey and source_type == "TRAUMA_HP":
            m = RE_DISABILITY_GCS.search(stripped)
            if m:
                val = int(m.group(1))
                if 3 <= val <= 15:
                    intubated = bool(m.group(2))
                    reading = {
                        "value": val,
                        "intubated": intubated,
                        "source": f"TRAUMA_HP:Primary_Survey:Disability",
                        "dt": dt,
                        "timestamp_quality": timestamp_quality,
                        "is_arrival": True,
                        "line_preview": stripped[:120],
                    }
                    arrival = reading
                    readings.append(reading)
                    seen_values.add(("arrival", val, dt))

    # ── Scan for structured 4-line flowsheet blocks ──
    for i in range(len(lines)):
        stripped_blk = lines[i].strip()
        m_eye = RE_FLOWSHEET_EYE.match(stripped_blk)
        if not m_eye or i + 3 >= len(lines):
            continue
        verbal_line = lines[i + 1].strip()
        motor_line = lines[i + 2].strip()
        total_line = lines[i + 3].strip()
        m_verbal = RE_FLOWSHEET_VERBAL.match(verbal_line)
        m_motor = RE_FLOWSHEET_MOTOR.match(motor_line)
        m_total = RE_FLOWSHEET_TOTAL.match(total_line)
        if not (m_verbal and m_motor and m_total):
            continue
        eye_val = _lookup_component(m_eye.group(1), _EYE_MAP)
        verbal_val = _lookup_component(m_verbal.group(1), _VERBAL_MAP)
        motor_val = _lookup_component(m_motor.group(1), _MOTOR_MAP)
        total_val = int(m_total.group(1))
        if (eye_val is None or verbal_val is None or motor_val is None
                or not 3 <= total_val <= 15
                or eye_val + verbal_val + motor_val != total_val):
            continue  # fail-closed: skip if components don't validate
        dedup_key = (total_val, dt, total_line[:80])
        if dedup_key in seen_values:
            continue
        seen_values.add(dedup_key)
        readings.append({
            "value": total_val,
            "intubated": False,
            "eye": eye_val,
            "verbal": verbal_val,
            "motor": motor_val,
            "source": f"{source_type}:structured_block",
            "dt": dt,
            "timestamp_quality": timestamp_quality,
            "is_arrival": False,
            "line_preview": total_line[:120],
        })

    # ── Scan all lines for GCS values ──
    for line in lines:
        stripped = line.strip()

        # Skip questionnaire lines
        if RE_GCS_QUESTIONNAIRE.search(stripped):
            continue
        # Skip narrative-only references
        if RE_GCS_NARRATIVE_ONLY.search(stripped):
            continue
        # Skip lines that are just "pupil and GCS changes" etc.
        if re.search(r"\bGCS\s+(changes|change)\b", stripped, re.IGNORECASE):
            continue

        val: Optional[int] = None
        intubated: bool = False
        source_label = f"{source_type}"
        eye_comp: Optional[int] = None
        verbal_comp: Optional[int] = None
        motor_comp: Optional[int] = None

        # Try component-parenthesized form first (most specific)
        m = RE_GCS_COMPONENT_PAREN.search(stripped)
        if m:
            val = int(m.group(4))
            intubated = bool(m.group(5))
            source_label = f"{source_type}:component_paren"
            eye_comp = int(m.group(1))
            verbal_comp = int(m.group(2))
            motor_comp = int(m.group(3))
        else:
            # Try inline components form
            m = RE_GCS_INLINE_COMPONENTS.search(stripped)
            if m:
                val = int(m.group(4))
                intubated = bool(m.group(5))
                source_label = f"{source_type}:inline_components"
                eye_comp = int(m.group(1))
                verbal_comp = int(m.group(2))
                motor_comp = int(m.group(3))
            else:
                # Try compact form
                m = RE_GCS_COMPACT.search(stripped)
                if m:
                    val = int(m.group(4))
                    intubated = True  # compact form has internal 't' (Vt) marking intubation; trailing T is optional
                    source_label = f"{source_type}:compact"
                    if m.group(2):  # V digit captured
                        eye_comp = int(m.group(1))
                        verbal_comp = int(m.group(2))
                        motor_comp = int(m.group(3))
                else:
                    # Try descriptive components form
                    m = RE_GCS_DESC_COMPONENTS.search(stripped)
                    if m:
                        val = int(m.group(4))
                        source_label = f"{source_type}:desc_components"
                        eye_comp = int(m.group(1))
                        verbal_comp = int(m.group(2))
                        motor_comp = int(m.group(3))
                    else:
                        # Try simple form (no components)
                        m = RE_GCS_SIMPLE.search(stripped)
                        if m:
                            val = int(m.group(1))
                            intubated = bool(m.group(2))
                            source_label = f"{source_type}:simple"

        if val is not None and 3 <= val <= 15:
            dedup_key = (val, dt, stripped[:80])
            if dedup_key not in seen_values:
                seen_values.add(dedup_key)
                reading = {
                    "value": val,
                    "intubated": intubated,
                    "source": source_label,
                    "dt": dt,
                    "timestamp_quality": timestamp_quality,
                    "is_arrival": False,
                    "line_preview": stripped[:120],
                }
                if (eye_comp is not None and verbal_comp is not None
                        and motor_comp is not None
                        and eye_comp + verbal_comp + motor_comp == val):
                    reading["eye"] = eye_comp
                    reading["verbal"] = verbal_comp
                    reading["motor"] = motor_comp
                readings.append(reading)

    return readings, arrival


# ── helpers for ED fallback window ───────────────────────────────────

_ED_FALLBACK_WINDOW_MINUTES = 120  # 0–120 min after arrival_datetime

def _parse_iso_dt(raw: Optional[str]) -> Optional[_dt]:
    """Parse ISO-ish datetime string → datetime, or None."""
    if not raw or raw == "DATA_NOT_AVAILABLE":
        return None
    raw = raw.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return _dt.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def extract_gcs_for_day(
    items: List[Dict[str, Any]],
    day_iso: str,
    arrival_datetime: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Extract GCS values for a single calendar day.

    Parameters
    ----------
    items              : timeline items for the day
    day_iso            : 'YYYY-MM-DD'
    arrival_datetime   : ISO string for arrival (used for ED fallback window)

    Returns
    -------
    (result_dict, warnings)
        result_dict has keys: arrival_gcs, best_gcs, worst_gcs,
                              arrival_gcs_value, arrival_gcs_ts,
                              arrival_gcs_source, arrival_gcs_missing_in_trauma_hp,
                              arrival_gcs_source_rule_id,
                              all_readings, warnings
    """
    warnings: List[str] = []
    all_readings: List[Dict[str, Any]] = []
    arrival_gcs: Optional[Dict[str, Any]] = None
    has_trauma_hp = False

    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue
        dt = item.get("dt")
        item_type = item.get("type", "")
        source_id = item.get("source_id")

        if item_type == "TRAUMA_HP":
            has_trauma_hp = True

        readings, item_arrival = _extract_gcs_from_text(
            text, dt, item_type, source_id,
        )
        all_readings.extend(readings)

        # arrival_gcs: only from TRAUMA_HP Primary Survey
        if item_arrival is not None and arrival_gcs is None:
            arrival_gcs = item_arrival

    # ── Arrival GCS precedence logic ──
    arrival_gcs_missing_in_trauma_hp = False
    arrival_gcs_source_rule_id: Optional[str] = None

    if arrival_gcs is not None:
        # Found in TRAUMA_HP Primary Survey — best case
        arrival_gcs_source_rule_id = "trauma_hp_primary_survey"
    elif has_trauma_hp:
        # TRAUMA_HP exists but no Primary Survey GCS → attempt ED fallback
        arrival_gcs_missing_in_trauma_hp = True
        arrival_gcs_source_rule_id = "trauma_hp_primary_survey_missing_fallback_ed"
        warnings.append("arrival_gcs_missing_in_trauma_hp")

        arrival_dt_parsed = _parse_iso_dt(arrival_datetime)
        if arrival_dt_parsed is not None:
            ed_candidates: List[Dict[str, Any]] = []
            for r in all_readings:
                if not r.get("source", "").startswith("ED_NOTE"):
                    continue
                r_dt = _parse_iso_dt(r.get("dt"))
                if r_dt is None:
                    continue
                delta_min = (r_dt - arrival_dt_parsed).total_seconds() / 60.0
                if 0.0 <= delta_min <= _ED_FALLBACK_WINDOW_MINUTES:
                    ed_candidates.append((delta_min, r))
            if ed_candidates:
                ed_candidates.sort(key=lambda x: x[0])
                arrival_gcs = ed_candidates[0][1]
                warnings.append("arrival_gcs_ed_fallback_used")
            else:
                warnings.append("arrival_gcs_ed_fallback_no_candidates")
        else:
            warnings.append("arrival_gcs_ed_fallback_no_arrival_dt")
    else:
        # No TRAUMA_HP at all
        arrival_gcs_source_rule_id = None

    # ── Build structured arrival fields ──
    if arrival_gcs is not None and isinstance(arrival_gcs, dict):
        arrival_gcs_value = arrival_gcs.get("value")
        arrival_gcs_ts = arrival_gcs.get("dt")
        arrival_gcs_source = arrival_gcs.get("source")
    else:
        arrival_gcs_value = None
        arrival_gcs_ts = None
        arrival_gcs_source = None

    # ── Compute best/worst across all readings ──
    numeric_vals = [r for r in all_readings if isinstance(r.get("value"), int)]

    if not numeric_vals:
        return {
            "arrival_gcs": _DNA,
            "arrival_gcs_value": arrival_gcs_value,
            "arrival_gcs_ts": arrival_gcs_ts,
            "arrival_gcs_source": arrival_gcs_source,
            "arrival_gcs_missing_in_trauma_hp": arrival_gcs_missing_in_trauma_hp,
            "arrival_gcs_source_rule_id": arrival_gcs_source_rule_id,
            "best_gcs": _DNA,
            "worst_gcs": _DNA,
            "all_readings": [],
            "warnings": warnings,
        }, warnings

    best_reading = max(numeric_vals, key=lambda r: (r["value"], r.get("dt") or ""))
    worst_reading = min(numeric_vals, key=lambda r: (r["value"], r.get("dt") or "9999"))

    def _fmt(r: Dict[str, Any]) -> Dict[str, Any]:
        d = {
            "value": r["value"],
            "intubated": r.get("intubated", False),
            "source": r["source"],
            "dt": r["dt"],
            "timestamp_quality": r["timestamp_quality"],
        }
        for comp in ("eye", "verbal", "motor"):
            if comp in r:
                d[comp] = r[comp]
        return d

    return {
        "arrival_gcs": _fmt(arrival_gcs) if arrival_gcs else _DNA,
        "arrival_gcs_value": arrival_gcs_value,
        "arrival_gcs_ts": arrival_gcs_ts,
        "arrival_gcs_source": arrival_gcs_source,
        "arrival_gcs_missing_in_trauma_hp": arrival_gcs_missing_in_trauma_hp,
        "arrival_gcs_source_rule_id": arrival_gcs_source_rule_id,
        "best_gcs": _fmt(best_reading),
        "worst_gcs": _fmt(worst_reading),
        "all_readings": [
            {
                "value": r["value"],
                "intubated": r.get("intubated", False),
                "source": r["source"],
                "dt": r["dt"],
                "timestamp_quality": r["timestamp_quality"],
                **{k: r[k] for k in ("eye", "verbal", "motor") if k in r},
            }
            for r in all_readings
        ],
        "warnings": warnings,
    }, warnings
