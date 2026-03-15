#!/usr/bin/env python3
"""
Ventilator Settings Foundation — Protocol Coverage (Vent Slice)

Deterministic extraction of ventilator setting parameters from raw
patient text with full raw_line_id traceability.

Parameters extracted:
  - vent_status      : "mechanical" | "niv" | None (from O2 Device / NIV headers)
  - vent_mode        : explicit ventilator mode label ("BiPAP", "CPAP", etc.)
  - fio2             : numeric FiO2 value (canonicalized to percent, 0-100;
                       if raw value <= 1.0, auto-converted via *100)
  - peep             : numeric PEEP value (cm H2O)
  - tidal_volume     : numeric tidal volume (mL)
  - resp_rate_set    : numeric set respiratory rate
  - ventilated_flag  : boolean from "Ventilated Patient?: Yes"
  - ipap             : numeric IPAP value (cm H2O) from NIV settings
  - epap             : numeric EPAP value (cm H2O) from NIV settings
  - niv_rate          : numeric NIV backup rate (breaths/min) from IPAP/EPAP context

Sources (structured, deterministic):
  Vent Settings block (flowsheet):
    "Vent Settings" header line, followed by:
      Resp Rate (Set): 24
      Vt (Set, ml): 460 ml
      PEEP/CPAP : 14 cm H20
      FIO2 : 60 %

  O2 Device: Ventilator / Non-Invasive Mechanical Ventilation headers

  Inline narrative:
    FiO2 50% peep is 12
    PEEP 14/ FiO2 70%
    PEEP 12 FiO2 70%

Raw evidence citations:
  Ronald_Bittner.txt:1164   — Placed on BiPAP (explicit mode)
  Ronald_Bittner.txt:654    — extubated and placed on BiPAP (explicit mode)
  Ronald_Bittner.txt:1443   — Recommend BiPAP (explicit mode)
  Ronald_Bittner.txt:14998  — Remained on BiPAP (explicit mode)
  Ronald_Bittner.txt:514    — O2 Device: Ventilator
  Ronald_Bittner.txt:5455-5459 — Vent Settings block (RR 24 / Vt 460 / PEEP 14 / FiO2 60)
  Ronald_Bittner.txt:5700   — Inline FiO2 50% peep is 12
  Ronald_Bittner.txt:14405  — O2 Device: Ventilator (flowsheet)
  Ronald_Bittner.txt:17658  — PEEP 14/ FiO@ 70%
  Ronald_Bittner.txt:18697  — PEEP 12 FiO2 70%
  Ronald_Bittner.txt:19706  — FiO2 40%, peep 8
  Lee_Woodard.txt:7999      — Non-Invasive Mechanical Ventilation header
  Jamie_Hunter.txt:21449    — Non-Invasive Mechanical Ventilation header
  Jamie_Hunter.txt:7989     — Daily Vent Weaning Worksheet
  Ronald_Bittner.txt:1443   — EPAP 8-10 for now (standalone EPAP)
  Ronald_Marshall.txt:10465 — IPAP 22, EPAP 8, rate of 16 (paired NIV settings + backup rate)

Design:
  - Deterministic, fail-closed.
  - No LLM, no ML, no clinical inference.
  - Every evidence item carries raw_line_id (SHA-256[:16]).
  - Range gates reject physiologically impossible values.

Output key: ventilator_settings_v1 (under features dict)
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


# ── raw_line_id generation ──────────────────────────────────────────

def _make_raw_line_id(
    param: str,
    day: str,
    line_num: Any,
    snippet: str,
) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of extraction coordinates."""
    key = f"{param}|{day}|{line_num}|{snippet}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ── Range gates (fail-closed) ──────────────────────────────────────

_RANGE_GATES = {
    "fio2": (20, 100),           # percent (post-canonicalization)
    "peep": (0, 30),             # cm H2O
    "tidal_volume": (50, 2000),  # mL
    "resp_rate_set": (1, 60),    # breaths/min
    "ipap": (4, 40),             # cm H2O
    "epap": (2, 25),             # cm H2O
    "niv_rate": (4, 40),          # breaths/min
}


def _in_range(param: str, value: float) -> bool:
    """Return True if value is within valid physiological range."""
    lo, hi = _RANGE_GATES.get(param, (float("-inf"), float("inf")))
    return lo <= value <= hi


def _canonicalize_fio2(raw_val: float) -> float:
    """Canonicalize FiO2 to percent scale (0-100). Fraction <= 1.0 → *100."""
    if raw_val <= 1.0:
        return raw_val * 100
    return raw_val


# ── Regex patterns ──────────────────────────────────────────────────

# --- Structured flowsheet block ---
# "Vent Settings" header triggers block capture of next N lines
_RE_VENT_SETTINGS_HEADER = re.compile(
    r"^\s*Vent\s+Settings\s*$", re.IGNORECASE,
)

# Block fields (after "Vent Settings" header)
_RE_RESP_RATE_SET = re.compile(
    r"Resp\s+Rate\s*\(Set\)\s*:\s*(\d+)", re.IGNORECASE,
)
_RE_VT_SET = re.compile(
    r"Vt\s*\(Set,?\s*ml\)\s*:\s*(\d+)", re.IGNORECASE,
)
_RE_PEEP_CPAP = re.compile(
    r"PEEP/CPAP\s*:\s*(\d+)", re.IGNORECASE,
)
_RE_FIO2_BLOCK = re.compile(
    r"FIO2\s*:\s*(\d+\.?\d*)\s*%?", re.IGNORECASE,
)

# --- Standalone / flowsheet lines ---
_RE_O2_DEVICE_VENT = re.compile(
    r"O2\s+Device\s*:\s*Ventilator\b", re.IGNORECASE,
)
_RE_VENTILATED_PATIENT = re.compile(
    r"Ventilated\s+Patient\??\s*:\s*Yes", re.IGNORECASE,
)
_RE_NIV_HEADER = re.compile(
    r"Non-Invasive\s+Mechanical\s+Ventilation\b", re.IGNORECASE,
)

# --- Inline narrative patterns ---
# "FiO2 50% peep is 12" / "FiO2 50%, peep 12"
_RE_FIO2_PEEP_INLINE = re.compile(
    r"FiO2\s+(\d+\.?\d*)\s*%?\s*,?\s*(?:peep|PEEP)\s+(?:is\s+)?(\d+)",
    re.IGNORECASE,
)
# "PEEP 14/ FiO2 70%" / "PEEP 12 FiO2 70%"
_RE_PEEP_FIO2_INLINE = re.compile(
    r"(?:PEEP|peep)\s+(\d+)\s*[/,]?\s*FiO2?\s*@?\s+(\d+\.?\d*)\s*%?",
    re.IGNORECASE,
)
# "FiO2 40%, peep 8" (with comma separator)
_RE_FIO2_COMMA_PEEP = re.compile(
    r"FiO2\s+(\d+\.?\d*)\s*%?\s*,\s*(?:peep|PEEP)\s+(\d+)",
    re.IGNORECASE,
)

# --- Explicit ventilator mode patterns ---
# "Placed on BiPAP" / "placed back on BiPAP" / "placed on CPAP"
_RE_PLACED_ON_MODE = re.compile(
    r"placed\s+(?:back\s+)?on\s+(BiPAP|CPAP)\b",
    re.IGNORECASE,
)
# "Recommend BiPAP" (clinical recommendation)
_RE_RECOMMEND_MODE = re.compile(
    r"Recommend\s+(BiPAP|CPAP)\b",
    re.IGNORECASE,
)
# "Remained on BiPAP" / "remains on BiPAP"
_RE_REMAINED_ON_MODE = re.compile(
    r"Remain(?:ed|s)\s+on\s+(BiPAP|CPAP)\b",
    re.IGNORECASE,
)
# "extubated and placed on BiPAP"
_RE_EXTUBATED_TO_MODE = re.compile(
    r"extubated\s+and\s+placed\s+on\s+(BiPAP|CPAP)\b",
    re.IGNORECASE,
)
# "weaned to CPAP" / "weaned to BiPAP"
_RE_WEANED_TO_MODE = re.compile(
    r"wean(?:ed)?\s+to\s+(BiPAP|CPAP)\b",
    re.IGNORECASE,
)

# --- NIV pressure settings (IPAP / EPAP) ---
# "IPAP 22" — standalone or in pair
_RE_IPAP = re.compile(
    r"\bIPAP\s+(\d+)\b",
    re.IGNORECASE,
)
# "EPAP 8" — standalone or in pair; also handles range "EPAP 8-10" (takes first)
_RE_EPAP = re.compile(
    r"\bEPAP\s+(\d+)\b",
    re.IGNORECASE,
)

# --- NIV backup rate (only valid when paired with IPAP/EPAP on same line) ---
# "rate of 16" — backup rate for bilevel NIV
_RE_NIV_RATE = re.compile(
    r"\brate\s+of\s+(\d+)\b",
    re.IGNORECASE,
)
# Negative guard: reject "rate of N" when preceded by non-NIV qualifiers
_RE_NIV_RATE_FALSE_POSITIVE = re.compile(
    r"\b(?:heart|respiratory|pulse|infusion|flow|drip|metabolic|basal|filtration|sed(?:imentation)?)\b\s+\brate\b\s+of\s+\d+\b",
    re.IGNORECASE,
)


# ── Classification helpers ──────────────────────────────────────────

# Negative exclusion patterns (false positives)
_NOISE_PATTERNS = [
    re.compile(r"Saint\s+Louis\s+University\s+Mental\s+Status\s*\(SLUMS\)", re.IGNORECASE),
    re.compile(r"Isbt\s+Product\s+Code", re.IGNORECASE),
    re.compile(r"respiratory\s+rate\s+is\s+less\s+than\s+\d+\s+breaths", re.IGNORECASE),
    re.compile(r"administer\s+naloxone", re.IGNORECASE),
    # "AC" false-positive guards
    re.compile(r"\bAC\s+and\s+HS\b", re.IGNORECASE),  # insulin dosing (before meals)
    re.compile(r"\bAC/AP\s+medication", re.IGNORECASE),  # anticoag/antiplatelet
    re.compile(r"\bTID\s+AC\b", re.IGNORECASE),  # insulin TID AC dosing
]


def _is_noise(line: str) -> bool:
    """Return True if line matches a known false-positive pattern."""
    for pat in _NOISE_PATTERNS:
        if pat.search(line):
            return True
    return False


# ── Core extraction ────────────────────────────────────────────────

def _extract_from_lines(
    raw_lines: List[str],
    day: str,
) -> List[Dict[str, Any]]:
    """
    Extract ventilator setting events from a list of raw text lines.

    Returns a list of event dicts, each with:
      param, value, day, line_index, snippet, raw_line_id
    """
    events: List[Dict[str, Any]] = []
    in_vent_block = False
    block_remaining = 0

    for line_idx, raw_line in enumerate(raw_lines):
        if not isinstance(raw_line, str):
            continue

        line = raw_line.strip()
        if not line:
            continue

        if _is_noise(line):
            continue

        # --- Vent Settings block header ---
        if _RE_VENT_SETTINGS_HEADER.match(line):
            in_vent_block = True
            block_remaining = 4  # capture next 4 lines for block fields
            continue

        # --- Inside Vent Settings block ---
        if in_vent_block and block_remaining > 0:
            block_remaining -= 1
            if block_remaining == 0:
                in_vent_block = False

            m = _RE_RESP_RATE_SET.search(line)
            if m:
                val = float(m.group(1))
                if _in_range("resp_rate_set", val):
                    events.append(_make_event(
                        "resp_rate_set", val, day, line_idx, line,
                        source="vent_settings_block",
                    ))

            m = _RE_VT_SET.search(line)
            if m:
                val = float(m.group(1))
                if _in_range("tidal_volume", val):
                    events.append(_make_event(
                        "tidal_volume", val, day, line_idx, line,
                        source="vent_settings_block",
                    ))

            m = _RE_PEEP_CPAP.search(line)
            if m:
                val = float(m.group(1))
                if _in_range("peep", val):
                    events.append(_make_event(
                        "peep", val, day, line_idx, line,
                        source="vent_settings_block",
                    ))

            m = _RE_FIO2_BLOCK.search(line)
            if m:
                val = _canonicalize_fio2(float(m.group(1)))
                if _in_range("fio2", val):
                    events.append(_make_event(
                        "fio2", val, day, line_idx, line,
                        source="vent_settings_block",
                    ))
            continue

        # --- O2 Device: Ventilator ---
        if _RE_O2_DEVICE_VENT.search(line):
            events.append(_make_event(
                "vent_status", "mechanical", day, line_idx, line,
                source="o2_device_flowsheet",
            ))

        # --- Ventilated Patient?: Yes ---
        if _RE_VENTILATED_PATIENT.search(line):
            events.append(_make_event(
                "ventilated_flag", True, day, line_idx, line,
                source="ventilated_patient_flowsheet",
            ))

        # --- Non-Invasive Mechanical Ventilation ---
        if _RE_NIV_HEADER.search(line):
            events.append(_make_event(
                "vent_status", "niv", day, line_idx, line,
                source="niv_header",
            ))

        # --- Inline FiO2 + PEEP patterns ---
        m = _RE_FIO2_PEEP_INLINE.search(line)
        if m:
            fio2_val = _canonicalize_fio2(float(m.group(1)))
            peep_val = float(m.group(2))
            if _in_range("fio2", fio2_val):
                events.append(_make_event(
                    "fio2", fio2_val, day, line_idx, line,
                    source="inline_narrative",
                ))
            if _in_range("peep", peep_val):
                events.append(_make_event(
                    "peep", peep_val, day, line_idx, line,
                    source="inline_narrative",
                ))
            continue  # already captured both

        m = _RE_PEEP_FIO2_INLINE.search(line)
        if m:
            peep_val = float(m.group(1))
            fio2_val = _canonicalize_fio2(float(m.group(2)))
            if _in_range("peep", peep_val):
                events.append(_make_event(
                    "peep", peep_val, day, line_idx, line,
                    source="inline_narrative",
                ))
            if _in_range("fio2", fio2_val):
                events.append(_make_event(
                    "fio2", fio2_val, day, line_idx, line,
                    source="inline_narrative",
                ))
            continue  # already captured both

        m = _RE_FIO2_COMMA_PEEP.search(line)
        if m:
            fio2_val = _canonicalize_fio2(float(m.group(1)))
            peep_val = float(m.group(2))
            if _in_range("fio2", fio2_val):
                events.append(_make_event(
                    "fio2", fio2_val, day, line_idx, line,
                    source="inline_narrative",
                ))
            if _in_range("peep", peep_val):
                events.append(_make_event(
                    "peep", peep_val, day, line_idx, line,
                    source="inline_narrative",
                ))
            continue

        # --- Standalone FIO2 from flowsheet (not in block) ---
        m = _RE_FIO2_BLOCK.search(line)
        if m and not in_vent_block:
            val = _canonicalize_fio2(float(m.group(1)))
            if _in_range("fio2", val):
                events.append(_make_event(
                    "fio2", val, day, line_idx, line,
                    source="fio2_flowsheet",
                ))

        # --- Explicit ventilator mode patterns ---
        for mode_re, src_tag in [
            (_RE_EXTUBATED_TO_MODE, "extubated_to_mode"),
            (_RE_PLACED_ON_MODE, "placed_on_mode"),
            (_RE_RECOMMEND_MODE, "recommend_mode"),
            (_RE_REMAINED_ON_MODE, "remained_on_mode"),
            (_RE_WEANED_TO_MODE, "weaned_to_mode"),
        ]:
            m = mode_re.search(line)
            if m:
                mode_val = m.group(1)
                # Canonicalize to title-case
                canon = mode_val.upper() if mode_val.upper() in (
                    "BIPAP", "CPAP",
                ) else mode_val
                if canon == "BIPAP":
                    canon = "BiPAP"
                events.append(_make_event(
                    "vent_mode", canon, day, line_idx, line,
                    source=src_tag,
                ))
                break  # one mode event per line

        # --- NIV pressure settings (IPAP / EPAP) ---
        has_ipap = _RE_IPAP.search(line)
        has_epap = _RE_EPAP.search(line)

        if has_ipap:
            val = float(has_ipap.group(1))
            if _in_range("ipap", val):
                events.append(_make_event(
                    "ipap", val, day, line_idx, line,
                    source="niv_pressure_setting",
                ))

        if has_epap:
            val = float(has_epap.group(1))
            if _in_range("epap", val):
                events.append(_make_event(
                    "epap", val, day, line_idx, line,
                    source="niv_pressure_setting",
                ))

        # --- NIV backup rate (only when IPAP or EPAP present on same line) ---
        if has_ipap or has_epap:
            m_rate = _RE_NIV_RATE.search(line)
            if m_rate and not _RE_NIV_RATE_FALSE_POSITIVE.search(line):
                rate_val = float(m_rate.group(1))
                if _in_range("niv_rate", rate_val):
                    events.append(_make_event(
                        "niv_rate", rate_val, day, line_idx, line,
                        source="niv_backup_rate",
                    ))

    return events


def _make_event(
    param: str,
    value: Any,
    day: str,
    line_idx: int,
    snippet: str,
    source: str = "unknown",
) -> Dict[str, Any]:
    """Construct a single vent setting event dict."""
    raw_line_id = _make_raw_line_id(param, day, line_idx, snippet[:200])
    return {
        "param": param,
        "value": value,
        "day": day,
        "line_index": line_idx,
        "snippet": snippet[:200],
        "raw_line_id": raw_line_id,
        "source": source,
    }


# ── Result assembly ────────────────────────────────────────────────

def _empty_result() -> Dict[str, Any]:
    """Return empty/default result dict."""
    return {
        "events": [],
        "summary": {
            "total_events": 0,
            "days_with_vent_data": 0,
            "mechanical_vent_days": [],
            "niv_days": [],
            "params_found": [],
            "vent_modes_found": [],
        },
    }


def _build_result(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble final result from event list."""
    if not events:
        return _empty_result()

    mechanical_days: set = set()
    niv_days: set = set()
    all_days: set = set()
    params_found: set = set()
    vent_modes_found: set = set()

    for ev in events:
        all_days.add(ev["day"])
        params_found.add(ev["param"])
        if ev["param"] == "vent_status":
            if ev["value"] == "mechanical":
                mechanical_days.add(ev["day"])
            elif ev["value"] == "niv":
                niv_days.add(ev["day"])
        if ev["param"] == "vent_mode":
            vent_modes_found.add(ev["value"])

    return {
        "events": events,
        "summary": {
            "total_events": len(events),
            "days_with_vent_data": len(all_days),
            "mechanical_vent_days": sorted(mechanical_days),
            "niv_days": sorted(niv_days),
            "params_found": sorted(params_found),
            "vent_modes_found": sorted(vent_modes_found),
        },
    }


# ── Public API ──────────────────────────────────────────────────────

def extract_ventilator_settings(
    pat_features: Dict[str, Any],
    days_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extract ventilator setting parameters from raw patient text.

    Parameters
    ----------
    pat_features : dict
        Accepted for API consistency with other feature
        extractors; not consumed by this module.
    days_data : dict, optional
        Full days_json with raw text lines under
        days_data["days"][date]["raw_lines"].

    Returns
    -------
    dict
        Ventilator settings summary with evidence list,
        per-parameter values, and day-level flags.
    """
    events: List[Dict[str, Any]] = []
    seen_hashes: set = set()

    if days_data is None:
        return _empty_result()

    raw_days = days_data.get("days", {})
    if not isinstance(raw_days, dict):
        return _empty_result()

    for day_iso, day_obj in sorted(raw_days.items()):
        if not isinstance(day_obj, dict):
            continue
        raw_lines = day_obj.get("raw_lines", [])
        if not isinstance(raw_lines, list):
            continue

        day_events = _extract_from_lines(raw_lines, day_iso)

        for ev in day_events:
            raw_line_id = ev["raw_line_id"]
            if raw_line_id in seen_hashes:
                continue
            seen_hashes.add(raw_line_id)
            events.append(ev)

    return _build_result(events)
