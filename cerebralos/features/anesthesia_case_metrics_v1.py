#!/usr/bin/env python3
"""
Anesthesia Case Metrics Extraction v1 for CerebralOS.

Deterministic extraction of per-case anesthesia physiologic metrics and
airway details from timeline items whose ``type`` maps to anesthesia or
operative categories.

**Consumed item kinds:**

  ANESTHESIA_PREPROCEDURE   → ASA, Mallampati, plan, diagnosis, pre-op temp
  ANESTHESIA_PROCEDURE      → airway device/size/difficulty/attempts/verification
  ANESTHESIA_POSTPROCEDURE  → anesthesia type, post-op temp, condition
  ANESTHESIA_FOLLOWUP       → PACU temp, consciousness, pain, complications
  ANESTHESIA_CONSULT        → consult details (e.g. nerve block request)
  OP_NOTE                   → EBL (Estimated Blood Loss)

**Per-case output shape:**

  case_label, anesthesia_type, asa_status, mallampati,
  preop_diagnosis, start_ts, stop_ts,
  airway {device, size, difficulty, atraumatic, attempts,
          placement_verification},
  temps [{value_f, source_phase, raw_line_id}],
  min_temp_f, or_hypothermia_flag,
  ebl_ml, ebl_raw,
  evidence[]

**OR Hypothermia flag:**

  Deterministic threshold: < 96.8 °F  (< 36.0 °C).
  Standard perioperative hypothermia definition per ASPAN/ASA guidelines.
  Flag is ``true`` only when an explicit temp below threshold is present
  in ANESTHESIA_POSTPROCEDURE or ANESTHESIA_FOLLOWUP items.
  If no temps are available, flag is ``null`` (DATA NOT AVAILABLE).

**Overlap with procedure_operatives_v1:**

  procedure_operatives_v1 extracts event-level chronology: label,
  status, milestones, and basic anesthesia_type + asa_status.
  *This* module extracts deeper CASE METRICS: airway details, temps,
  EBL, hypothermia flag.  Both modules read the same items but produce
  different, additive output shapes.  For anesthesia_type and asa_status,
  procedure_operatives_v1 is the event-timeline source of truth;
  this module provides case-level detail.

**Fail-closed:** returns empty cases[] when no ANESTHESIA items exist.
Every evidence entry carries ``raw_line_id``.

Output key: ``anesthesia_case_metrics_v1``
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Hypothermia threshold (deterministic) ───────────────────────────
# < 96.8 °F  ==  < 36.0 °C
OR_HYPOTHERMIA_THRESHOLD_F = 96.8

# ── Item kinds consumed ────────────────────────────────────────────

_ANESTHESIA_KINDS = frozenset({
    "ANESTHESIA_PREPROCEDURE",
    "ANESTHESIA_PROCEDURE",
    "ANESTHESIA_POSTPROCEDURE",
    "ANESTHESIA_FOLLOWUP",
    "ANESTHESIA_CONSULT",
})

_EBL_KINDS = frozenset({
    "OP_NOTE",
    "PROCEDURE",
    "ANESTHESIA_PROCEDURE",
    "ANESTHESIA_POSTPROCEDURE",
})

# ── Regex patterns ─────────────────────────────────────────────────

# ASA Status (e.g. "ASA Status: 3", "ASA: III", "ASA Physical Status: 2E")
_RE_ASA = re.compile(
    r"ASA\s+(?:Physical\s+)?Status\s*[:]\s*"
    r"(\d+\s*E?|I{1,4}V?\s*E?)",
    re.IGNORECASE,
)

# Mallampati score (e.g. "Mallampati: II", "Mallampati Class: 3")
_RE_MALLAMPATI = re.compile(
    r"Mallampati\s*(?:Class|Score)?\s*[:]\s*"
    r"(I{1,4}V?|\d+)",
    re.IGNORECASE,
)

# Anesthesia type/plan (e.g. "Anesthesia Plan: General",
#   "Anesthesia Type: General", "Type of Anesthesia: Spinal")
_RE_ANESTHESIA_TYPE = re.compile(
    r"(?:Anesthesia\s+(?:Plan|Type)|Type\s+of\s+Anesthesia)"
    r"\s*[:]\s*([A-Za-z /]+?)(?:\s*\||$)",
    re.IGNORECASE,
)

# Pre-op diagnosis (e.g. "Diagnosis: Metatarsal fracture",
#   "Pre-op Diagnoses: rib fractures")
_RE_PREOP_DX = re.compile(
    r"(?:Diagnosis|Pre[- ]?[Oo]p(?:erative)?\s+D(?:iagnos[ie]s|x))"
    r"\s*[:]\s*(.+?)(?:\s*\||$)",
    re.IGNORECASE,
)

# ── Airway regexes ─────────────────────────────────────────────────

# Airway device type (e.g. "Type of Airway: LMA", "Airway Device: ETT")
_RE_AIRWAY_DEVICE = re.compile(
    r"(?:Type\s+of\s+Airway|Airway\s+Device)\s*[:]\s*"
    r"([A-Za-z ]+?)(?:\s*\||$)",
    re.IGNORECASE,
)

# ETT/LMA size (e.g. "ETT/LMA Size: 5", "Tube Size: 7.5")
_RE_AIRWAY_SIZE = re.compile(
    r"(?:ETT/?LMA\s+Size|Tube\s+Size|Airway\s+Size)\s*[:]\s*"
    r"([\d.]+)",
    re.IGNORECASE,
)

# Difficult airway (e.g. "Difficult Airway?: airway not difficult",
#   "Airway Difficulty: Easy", "Difficult Airway: Yes")
_RE_AIRWAY_DIFFICULTY = re.compile(
    r"(?:Difficult\s+Airway\s*\??|Airway\s+Difficulty)\s*[:]\s*"
    r"(.+?)(?:\s*\||$)",
    re.IGNORECASE,
)

# Atraumatic (e.g. "Atraumatic: Yes")
_RE_ATRAUMATIC = re.compile(
    r"Atraumatic\s*[:]\s*(Yes|No)",
    re.IGNORECASE,
)

# Insertion attempts (e.g. "Insertion Attempts: 1")
_RE_ATTEMPTS = re.compile(
    r"(?:Insertion\s+)?Attempts?\s*[:]\s*(\d+)",
    re.IGNORECASE,
)

# Placement verification (e.g. "Placement verified by: Auscultation and Capnometry")
_RE_PLACEMENT_VERIFICATION = re.compile(
    r"(?:Placement\s+[Vv]erified\s+by|Verification\s+Method)\s*[:]\s*"
    r"(.+?)(?:\s*\||$)",
    re.IGNORECASE,
)

# ── Temperature regex ──────────────────────────────────────────────
# Matches: "Temp: 98.4", "Temp: 98.6 °F (37 °C)",
#           "Temp  Min: 97.7 °F (36.5 °C)"
# We require at least one digit to avoid false matches.
_RE_TEMP_F = re.compile(
    r"Temp(?:\s+Min|\s+Max)?\s*[:]\s*"
    r"(?:\(!\)\s*)?"  # optional alert flag
    r"(\d{2,3}(?:\.\d+)?)\s*(?:°?\s*F)?",
    re.IGNORECASE,
)

# ── EBL regex ──────────────────────────────────────────────────────
# Matches: "EBL: <5cc", "EBL: 20 ml", "EBL: 100cc",
#           "Estimated Blood Loss: 20 ml", "EBL: Minimal",
#           "Estimated blood loss: <2cc"
_RE_EBL = re.compile(
    r"(?:EBL|Estimated\s+[Bb]lood\s+[Ll]oss)\s*[:]\s*"
    r"(<?\s*\d+[\d,]*\.?\d*)\s*(?:cc|ml|mL)?",
    re.IGNORECASE,
)

# EBL textual (for cases like "EBL: Minimal" or "EBL: None")
_RE_EBL_TEXT = re.compile(
    r"(?:EBL|Estimated\s+[Bb]lood\s+[Ll]oss)\s*[:]\s*"
    r"([A-Za-z]+)",
    re.IGNORECASE,
)

# ── Nerve block details ───────────────────────────────────────────
# "Block type: Erector Spinae (ES)"
_RE_BLOCK_TYPE = re.compile(
    r"Block\s+type\s*[:]\s*(.+?)(?:\s*\||$)",
    re.IGNORECASE,
)

# ── Helpers ────────────────────────────────────────────────────────


def _normalise_text(raw: str) -> str:
    """Collapse whitespace and newlines into pipe-delimited string for regex."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "|".join(line.strip() for line in lines if line.strip())


def _first_match(pattern: re.Pattern, text: str) -> Optional[str]:
    """Return first regex match group(1), stripped."""
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _make_item_ref(day_iso: str, item_idx: int) -> str:
    return f"{day_iso}:item_{item_idx}"


def _get_item_text(item: Dict[str, Any]) -> str:
    """
    Extract text from a timeline item.

    Real data stores text in ``payload.text``; test data may use ``text``
    directly.  Try payload first, fall back to item-level text.
    """
    payload = item.get("payload") or {}
    text = payload.get("text", "")
    if not text:
        text = item.get("text", "")
    return text


def _parse_ebl(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Parse EBL from text.

    Returns (ebl_ml, ebl_raw) where ebl_ml is numeric (or None) and
    ebl_raw is the matched text for audit trail.
    """
    m = _RE_EBL.search(text)
    if m:
        raw_val = m.group(1).strip()
        # Handle "<5" → 5, "<2" → 2 (upper bound)
        cleaned = raw_val.replace("<", "").replace(",", "").strip()
        try:
            return float(cleaned), raw_val
        except ValueError:
            return None, raw_val
    # Check textual EBL
    m2 = _RE_EBL_TEXT.search(text)
    if m2:
        word = m2.group(1).strip().lower()
        if word in ("minimal", "none", "negligible"):
            return None, word
    return None, None


def _extract_airway(text: str) -> Dict[str, Optional[str]]:
    """Extract airway details from ANESTHESIA_PROCEDURE text."""
    return {
        "device": _first_match(_RE_AIRWAY_DEVICE, text),
        "size": _first_match(_RE_AIRWAY_SIZE, text),
        "difficulty": _first_match(_RE_AIRWAY_DIFFICULTY, text),
        "atraumatic": _first_match(_RE_ATRAUMATIC, text),
        "attempts": _first_match(_RE_ATTEMPTS, text),
        "placement_verification": _first_match(_RE_PLACEMENT_VERIFICATION, text),
    }


def _extract_temps(text: str, phase: str, raw_line_id: str) -> List[Dict[str, Any]]:
    """
    Extract all temperature readings from text.

    Returns list of {value_f, source_phase, raw_line_id}.
    Only captures values in plausible clinical range (90–110 °F).
    """
    temps: List[Dict[str, Any]] = []
    for m in _RE_TEMP_F.finditer(text):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        # Only accept clinically plausible range
        if 90.0 <= val <= 110.0:
            temps.append({
                "value_f": val,
                "source_phase": phase,
                "raw_line_id": raw_line_id,
            })
    return temps


# ── Case grouping ──────────────────────────────────────────────────


def _group_items_into_cases(
    items_by_day: List[Tuple[str, int, Dict[str, Any]]],
) -> List[List[Tuple[str, int, Dict[str, Any]]]]:
    """
    Group anesthesia items into logical cases.

    Strategy: items are grouped by calendar day.  All ANESTHESIA_*
    items on the same day belong to the same case (a patient typically
    has one surgical/anesthesia case per day).  Items on different days
    are separate cases.

    Each item tuple is (day_iso, item_idx, item_dict).
    """
    if not items_by_day:
        return []

    cases_by_day: Dict[str, List[Tuple[str, int, Dict[str, Any]]]] = {}
    for day_iso, idx, item in items_by_day:
        cases_by_day.setdefault(day_iso, []).append((day_iso, idx, item))

    # Return sorted by day
    return [cases_by_day[d] for d in sorted(cases_by_day.keys())]


# ── Main extraction function ──────────────────────────────────────


def extract_anesthesia_case_metrics(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract anesthesia case metrics from timeline data.

    Parameters
    ----------
    pat_features : dict
        Partial patient-features dict (needs ``days`` key for day-level data).
    days_data : dict
        Full patient_days_v1.json (meta + days list).

    Returns
    -------
    dict
        {cases: [...], case_count: int, or_hypothermia_any: bool|null,
         flags: [...], warnings: [...], notes: [...], evidence: [...],
         source_rule_id: "anesthesia_case_metrics_v1"}
    """
    warnings: List[str] = []
    notes: List[str] = []
    evidence: List[Dict[str, Any]] = []
    flags: List[str] = []

    days = days_data.get("days", {})

    # ── Collect all qualifying items ───────────────────────────────
    anes_items: List[Tuple[str, int, Dict[str, Any]]] = []
    ebl_items: List[Tuple[str, int, Dict[str, Any]]] = []

    # days may be dict {date_str: {items: [...]}} or list [{date, items}]
    if isinstance(days, dict):
        days_iter = [(d, days[d]) for d in sorted(days.keys())]
    elif isinstance(days, list):
        days_iter = [(day_obj.get("date", "unknown"), day_obj) for day_obj in days]
    else:
        days_iter = []

    for day_iso, day_obj in days_iter:
        items = day_obj.get("items", []) if isinstance(day_obj, dict) else []
        for idx, item in enumerate(items):
            kind = (item.get("type") or "").upper().strip()
            if kind in _ANESTHESIA_KINDS:
                anes_items.append((day_iso, idx, item))
            if kind in _EBL_KINDS:
                ebl_items.append((day_iso, idx, item))

    if not anes_items:
        notes.append("no_anesthesia_items_found")
        return {
            "cases": [],
            "case_count": 0,
            "or_hypothermia_any": None,
            "flags": [],
            "warnings": [],
            "notes": notes,
            "evidence": [],
            "source_rule_id": "anesthesia_case_metrics_v1",
        }

    # ── Group into cases ───────────────────────────────────────────
    grouped_cases = _group_items_into_cases(anes_items)

    # Build EBL lookup by day for cross-referencing OP_NOTE EBL
    ebl_by_day: Dict[str, List[Tuple[Optional[float], Optional[str], str]]] = {}
    for day_iso, idx, item in ebl_items:
        raw_text = _get_item_text(item)
        text_norm = _normalise_text(raw_text)
        ebl_ml, ebl_raw = _parse_ebl(text_norm)
        if ebl_raw is not None:
            raw_line_id = item.get("raw_line_id") or _make_item_ref(day_iso, idx)
            ebl_by_day.setdefault(day_iso, []).append((ebl_ml, ebl_raw, raw_line_id))

    # ── Process each case ──────────────────────────────────────────
    cases: List[Dict[str, Any]] = []
    any_hypothermia = None  # tri-state: None=no data, True/False=result

    for case_items in grouped_cases:
        case_day = case_items[0][0]  # day_iso of first item in case

        case_label: Optional[str] = None
        anesthesia_type: Optional[str] = None
        asa_status: Optional[str] = None
        mallampati: Optional[str] = None
        preop_diagnosis: Optional[str] = None
        start_ts: Optional[str] = None
        stop_ts: Optional[str] = None
        airway: Dict[str, Optional[str]] = {}
        temps: List[Dict[str, Any]] = []
        case_evidence: List[Dict[str, Any]] = []
        case_ebl_ml: Optional[float] = None
        case_ebl_raw: Optional[str] = None
        block_type: Optional[str] = None

        for day_iso, idx, item in case_items:
            kind = (item.get("type") or "").upper().strip()
            raw_text = _get_item_text(item)
            text_norm = _normalise_text(raw_text)
            ts_raw = item.get("dt") or item.get("ts") or None
            raw_line_id = item.get("raw_line_id") or _make_item_ref(day_iso, idx)

            # Track case timing from item timestamps
            if ts_raw:
                if start_ts is None or ts_raw < start_ts:
                    start_ts = ts_raw
                if stop_ts is None or ts_raw > stop_ts:
                    stop_ts = ts_raw

            # ── Phase-specific extraction ──────────────────────────

            if kind == "ANESTHESIA_PREPROCEDURE":
                # ASA, Mallampati, plan, diagnosis, pre-op temp
                asa_status = asa_status or _first_match(_RE_ASA, text_norm)
                mallampati = mallampati or _first_match(_RE_MALLAMPATI, text_norm)
                anesthesia_type = anesthesia_type or _first_match(
                    _RE_ANESTHESIA_TYPE, text_norm,
                )
                preop_diagnosis = preop_diagnosis or _first_match(
                    _RE_PREOP_DX, text_norm,
                )
                temps.extend(_extract_temps(text_norm, "preprocedure", raw_line_id))

            elif kind == "ANESTHESIA_PROCEDURE":
                # Airway details
                if not airway:
                    airway = _extract_airway(text_norm)
                # Also check for anesthesia type if not yet captured
                anesthesia_type = anesthesia_type or _first_match(
                    _RE_ANESTHESIA_TYPE, text_norm,
                )
                # Block type for nerve blocks
                block_type = block_type or _first_match(_RE_BLOCK_TYPE, text_norm)
                # EBL can occasionally be in procedure item
                if case_ebl_raw is None:
                    case_ebl_ml, case_ebl_raw = _parse_ebl(text_norm)

            elif kind == "ANESTHESIA_POSTPROCEDURE":
                # Anesthesia type, post-op temp, condition
                anesthesia_type = anesthesia_type or _first_match(
                    _RE_ANESTHESIA_TYPE, text_norm,
                )
                temps.extend(_extract_temps(text_norm, "postprocedure", raw_line_id))

            elif kind == "ANESTHESIA_FOLLOWUP":
                # PACU temp, consciousness, no complications
                temps.extend(_extract_temps(text_norm, "followup", raw_line_id))

            elif kind == "ANESTHESIA_CONSULT":
                # Consult — may have block type, diagnosis
                block_type = block_type or _first_match(_RE_BLOCK_TYPE, text_norm)
                preop_diagnosis = preop_diagnosis or _first_match(
                    _RE_PREOP_DX, text_norm,
                )

            # Build evidence for every item consumed
            snippet = raw_text[:120].replace("\n", " ").strip()
            case_evidence.append({
                "role": "anesthesia_case_metric",
                "snippet": snippet,
                "raw_line_id": raw_line_id,
                "source_kind": kind,
            })

        # ── Cross-reference OP_NOTE EBL for same day ───────────────
        if case_ebl_raw is None and case_day in ebl_by_day:
            for eml, eraw, elid in ebl_by_day[case_day]:
                case_ebl_ml = eml
                case_ebl_raw = eraw
                case_evidence.append({
                    "role": "ebl_from_op_note",
                    "snippet": f"EBL: {eraw}",
                    "raw_line_id": elid,
                    "source_kind": "OP_NOTE",
                })
                break  # take first EBL found

        # ── Build case label ───────────────────────────────────────
        if block_type:
            case_label = f"Nerve Block: {block_type}"
        elif preop_diagnosis:
            case_label = preop_diagnosis
        else:
            case_label = anesthesia_type or _DNA

        # ── Temperature analysis ───────────────────────────────────
        # Deduplicate temps (same value + phase)
        seen_temps = set()
        unique_temps: List[Dict[str, Any]] = []
        for t in temps:
            key = (t["value_f"], t["source_phase"])
            if key not in seen_temps:
                seen_temps.add(key)
                unique_temps.append(t)

        min_temp_f: Optional[float] = None
        or_hypothermia_flag: Optional[bool] = None

        # Only use post-procedure and followup temps for hypothermia check
        # (pre-procedure temp is baseline, not OR temp)
        periop_temps = [
            t for t in unique_temps
            if t["source_phase"] in ("postprocedure", "followup")
        ]
        if periop_temps:
            min_temp_f = min(t["value_f"] for t in periop_temps)
            or_hypothermia_flag = min_temp_f < OR_HYPOTHERMIA_THRESHOLD_F
            if or_hypothermia_flag:
                flags.append(f"or_hypothermia_case_{len(cases)+1}")
                if any_hypothermia is None:
                    any_hypothermia = True
                else:
                    any_hypothermia = True
            else:
                if any_hypothermia is None:
                    any_hypothermia = False

        # ── Airway — compact: omit all-None ────────────────────────
        airway_out: Optional[Dict[str, Optional[str]]] = None
        if any(v is not None for v in airway.values()):
            airway_out = airway

        # ── Assemble case ──────────────────────────────────────────
        case: Dict[str, Any] = {
            "case_index": len(cases) + 1,
            "case_day": case_day,
            "case_label": case_label,
            "anesthesia_type": anesthesia_type or _DNA,
            "asa_status": asa_status or _DNA,
            "mallampati": mallampati or _DNA,
            "preop_diagnosis": preop_diagnosis or _DNA,
            "start_ts": start_ts,
            "stop_ts": stop_ts,
        }
        if airway_out:
            case["airway"] = airway_out
        if unique_temps:
            case["temps"] = unique_temps
        case["min_temp_f"] = min_temp_f
        case["or_hypothermia_flag"] = or_hypothermia_flag

        if case_ebl_raw is not None:
            case["ebl_ml"] = case_ebl_ml
            case["ebl_raw"] = case_ebl_raw
        else:
            case["ebl_ml"] = None
            case["ebl_raw"] = _DNA

        case["evidence"] = case_evidence
        cases.append(case)

        # Add to top-level evidence
        evidence.append({
            "role": "anesthesia_case",
            "snippet": (
                f"Case {case['case_index']}: {case_label} "
                f"({anesthesia_type or '?'}, ASA {asa_status or '?'})"
            )[:120],
            "raw_line_id": case_evidence[0]["raw_line_id"] if case_evidence else _DNA,
        })

    # ── Summary ────────────────────────────────────────────────────
    if not cases:
        notes.append("no_anesthesia_cases_assembled")

    return {
        "cases": cases,
        "case_count": len(cases),
        "or_hypothermia_any": any_hypothermia,
        "flags": flags,
        "warnings": warnings,
        "notes": notes,
        "evidence": evidence,
        "source_rule_id": "anesthesia_case_metrics_v1",
    }
