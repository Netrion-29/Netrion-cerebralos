#!/usr/bin/env python3
"""
Structured Labs Foundation — Protocol Coverage Slice C

Provides deterministic, typed, per-panel structured lab extraction with
full raw_line_id traceability for protocol coverage and NTDS analysis.

Panels:
  CBC:     Hgb / Hct / WBC / Plt
  BMP:     Na / K / Cl / CO2 / BUN / Cr / Glucose
  Coag:    PT / INR / PTT / Fibrinogen
  ABG:     pH / pCO2 / pO2 / Base Deficit / Lactate
  Cardiac: Troponin_T / BNP
  Sepsis:  Procalcitonin
  P/F ratio: computed when PaO2 + FiO2 are both explicit

For each panel, produces per-day structured values with:
  - first/last numeric values
  - full series with timestamps + raw_line_id
  - abnormal flag propagation
  - panel-level completeness flag

P/F ratio:
  Computed only when BOTH PaO2 and FiO2 are explicitly present in the
  same day's lab data as numeric lab components.  FiO2 is accepted from
  any numeric lab row matching _FIO2_CANDIDATES (e.g. "FIO2", "FiO2 (%)").
  Values >1.0 are treated as percentages and normalized to fractions.
  Fail-closed: missing or non-numeric FiO2 -> P/F not computed.

Raw evidence citations:
  Anna_Dennis.txt:144-147   — CBC in Recent Labs matrix (WBC/HGB/HCT/PLT)
  Anna_Dennis.txt:151-153   — BMP in Recent Labs matrix (CO2/BUN/CREATININE)
  Timothy_Cowan.txt:194-200 — BMP via tab-delimited table (Glucose/Cr/Na/K/Cl/Co2)
  Timothy_Cowan.txt:215     — Coag via tab-delimited (APTT)
  Timothy_Cowan.txt:219-224 — ABG via tab-delimited (pH/pCO2/pO2/Base Deficit)
  Timothy_Cowan.txt:266-267 — Coag via tab-delimited (PROTIME/INR)
  Timothy_Nachtwey.txt:173-179 — BMP via tab-delimited (Glucose/Cr/Na/K/Cl/Co2)
  Timothy_Nachtwey.txt:194  — Coag via tab-delimited (APTT)
  Timothy_Nachtwey.txt:204-209 — ABG via tab-delimited (pH/pCO2/pO2/Base Deficit)
  Timothy_Nachtwey.txt:251-252 — Coag via tab-delimited (PROTIME/INR)
  Timothy_Nachtwey.txt:1140 — FiO2 from flowsheet (FIO2 : 30 %)
  William_Simmons.txt:343-349 — CBC in newline-delimited Recent Labs matrix
  Ronald_Bittner.txt:265    — Cardiac: TROPONIN T 11, 0-21 NG/L
  Ronald_Bittner.txt:266    — Cardiac: PRO BNP <36, 0-125 PG/ML
  Roscella_Weatherly.txt:258 — Cardiac: Troponin T(Highly Sensitive) 3.8 pg/mL
  James_Eaton.txt:253       — Cardiac: TROPONIN T 8, 0-21 NG/L
  Ronald_Bittner.txt:880    — Sepsis: Procalcitonin 0.08, <0.10 NG/ML
  Lee_Woodard.txt:7283      — Sepsis: Procalcitonin 0.07

Design:
  Deterministic, fail-closed.
  No LLM, no ML, no clinical inference.
  Ambiguous units/contexts -> skip.
  All output entries include raw_line_id for traceability.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple


# ── Panel component mappings ───────────────────────────────────────
# Maps canonical short name -> list of extracted component name
# candidates (case-insensitive match, first hit wins).

_CBC_COMPONENTS: Dict[str, List[str]] = {
    "Hgb": ["Hemoglobin", "Hgb", "HGB"],
    "Hct": ["Hematocrit", "Hct", "HCT"],
    "WBC": ["White Blood Cell Count", "WBC"],
    "Plt": ["Platelet Count", "Plt", "PLT", "Platelets"],
}

_BMP_COMPONENTS: Dict[str, List[str]] = {
    "Na":      ["Sodium", "Na", "NA"],
    "K":       ["Potassium", "K"],
    "Cl":      ["Chloride", "Cl", "CL"],
    "CO2":     ["Co2", "CO2", "Co2 Content", "Renal CO2", "Bicarbonate"],
    "BUN":     ["Blood Urea Nitrogen", "BUN"],
    "Cr":      ["Creatinine", "Cr", "CREATININE"],
    "Glucose": ["Glucose", "GLU", "GLUCOSE"],
}

_COAG_COMPONENTS: Dict[str, List[str]] = {
    "PT":         ["PROTIME", "PT", "Pro Time"],
    "INR":        ["INR"],
    "PTT":        ["APTT", "PTT", "aPTT"],
    "Fibrinogen": ["Fibrinogen", "FIBRINOGEN"],
}

_ABG_COMPONENTS: Dict[str, List[str]] = {
    "pH":           ["pH Arterial", "pH", "PH"],
    "pCO2":         ["pCO2 Arterial", "pCO2", "PCO2"],
    "pO2":          ["Po2 Arterial", "pO2", "PO2", "Po2"],
    "Base_Deficit": ["Base Deficit", "Base Excess", "BD"],
    "Lactate":      ["Lactate", "Lactic Acid", "LACTATE"],
}

_CARDIAC_COMPONENTS: Dict[str, List[str]] = {
    "Troponin_T": ["TROPONIN T", "Troponin T", "Troponin T(Highly Sensitive)"],
    "BNP":        ["PRO BNP", "PRO BRAIN NATRIURETIC PEPTIDE (BNP)", "BNP"],
}

_SEPSIS_COMPONENTS: Dict[str, List[str]] = {
    "Procalcitonin": ["Procalcitonin", "PROCALCITONIN"],
}

# FiO2 candidates — used for P/F ratio computation only.
# Only numeric lab components are supported; non-numeric qualitative
# entries (e.g. "ROOM AIR" text) are excluded because the upstream
# lab pipeline filters rows where value_num is None.
_FIO2_CANDIDATES: List[str] = [
    "FIO2", "FiO2", "FiO2 (%)", "FiO2 (%) **",
]

# Value sanity ranges — values outside these are rejected (fail-closed).
_RANGE_GATES: Dict[str, Tuple[float, float]] = {
    "Hgb":           (1.0, 30.0),
    "Hct":           (5.0, 80.0),
    "WBC":           (0.1, 200.0),
    "Plt":           (1.0, 2000.0),
    "Na":            (100.0, 200.0),
    "K":             (1.0, 15.0),
    "Cl":            (60.0, 160.0),
    "CO2":           (5.0, 60.0),
    "BUN":           (1.0, 300.0),
    "Cr":            (0.1, 30.0),
    "Glucose":       (10.0, 2000.0),
    "PT":            (5.0, 200.0),
    "INR":           (0.5, 20.0),
    "PTT":           (10.0, 250.0),
    "Fibrinogen":    (30.0, 2000.0),
    "pH":            (6.5, 8.0),
    "pCO2":          (5.0, 150.0),
    "pO2":           (10.0, 700.0),
    "Base_Deficit":  (-30.0, 30.0),
    "Lactate":       (0.1, 30.0),
    "Troponin_T":    (0.0, 50000.0),
    "BNP":           (0.0, 100000.0),
    "Procalcitonin": (0.0, 1000.0),
}

# P/F acceptable FiO2 range (fraction, 0-1 scale).
_FIO2_MIN = 0.21
_FIO2_MAX = 1.0

_DNA = "DATA NOT AVAILABLE"


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(comp: str, dt: Optional[str], value: Any, source_line: Any) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of lab coordinates."""
    key = f"{comp}|{dt or ''}|{value}|{source_line or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _in_range(canonical: str, value: float) -> bool:
    """Check if value is within sanity range for this component."""
    bounds = _RANGE_GATES.get(canonical)
    if bounds is None:
        return True
    return bounds[0] <= value <= bounds[1]


def _find_series_for_component(
    series: Dict[str, List[Dict[str, Any]]],
    candidates: List[str],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Find series entries matching any candidate name (case-insensitive).

    Iterates candidates in priority order; returns entries for the FIRST
    matching key that contains at least one entry with a non-null
    value_num.  If a candidate key exists but all its entries have
    value_num=None, it is skipped so later candidates can match.
    Sorting is deferred to the caller (_build_component_block).

    Returns (entries_for_first_viable_match, matched_series_key | None).
    """
    series_lower = {k.lower(): (k, v) for k, v in series.items()}
    for candidate in candidates:
        key_lower = candidate.lower()
        if key_lower in series_lower:
            orig_key, vals = series_lower[key_lower]
            if any(e.get("value_num") is not None for e in vals):
                return vals, orig_key
    return [], None


def _build_component_block(
    canonical: str,
    series: Dict[str, List[Dict[str, Any]]],
    candidates: List[str],
) -> Dict[str, Any]:
    """
    Build structured component block for one canonical lab component.

    Returns dict with:
      status: "available" | "DATA NOT AVAILABLE"
      first / last / delta / n_values
      series: list of {observed_dt, value, flags, raw_line_id}
      abnormal: bool
    """
    entries, _ = _find_series_for_component(series, candidates)
    if not entries:
        return {"status": _DNA}

    # Filter to valid numeric values within range gate
    valid: List[Dict[str, Any]] = []
    for e in entries:
        val = e.get("value_num")
        if val is None:
            continue
        if not _in_range(canonical, val):
            continue
        valid.append(e)

    if not valid:
        return {"status": _DNA}

    # Sort by (observed_dt, source_line) for deterministic order
    valid.sort(key=lambda r: (r.get("observed_dt") or "", r.get("source_line", 0)))

    # Build output series with raw_line_id
    out_series: List[Dict[str, Any]] = []
    has_abnormal = False
    for v in valid:
        flags = v.get("flags") or []
        if flags:
            has_abnormal = True
        out_series.append({
            "observed_dt": v.get("observed_dt"),
            "value": v["value_num"],
            "flags": flags,
            "raw_line_id": _make_raw_line_id(
                canonical,
                v.get("observed_dt"),
                v["value_num"],
                v.get("source_line"),
            ),
        })

    first_val = out_series[0]["value"]
    last_val = out_series[-1]["value"]
    delta = round(last_val - first_val, 4) if len(out_series) > 1 else 0.0

    return {
        "status": "available",
        "first": first_val,
        "last": last_val,
        "delta": delta,
        "n_values": len(out_series),
        "abnormal": has_abnormal,
        "series": out_series,
    }


def _build_panel(
    panel_map: Dict[str, List[str]],
    series: Dict[str, List[Dict[str, Any]]],
    day_iso: str,
) -> Dict[str, Any]:
    """Build a full panel block (CBC, BMP, etc.) from series data."""
    components: Dict[str, Any] = {}
    available_count = 0
    total_count = len(panel_map)

    for canonical, candidates in panel_map.items():
        block = _build_component_block(canonical, series, candidates)
        components[canonical] = block
        if block.get("status") == "available":
            available_count += 1

    return {
        "components": components,
        "complete": available_count == total_count,
        "available_count": available_count,
        "total_count": total_count,
    }


def _compute_pf_ratio(
    abg_panel: Dict[str, Any],
    series: Dict[str, List[Dict[str, Any]]],
    day_iso: str,
) -> Dict[str, Any]:
    """
    Compute P/F ratio when BOTH PaO2 and FiO2 are explicitly available
    as numeric lab components.

    FiO2 is sourced from numeric lab rows matching _FIO2_CANDIDATES.
    Values > 1.0 are treated as percentages and normalized to fractions
    (e.g. 30 -> 0.30).  Only rows with non-null value_num are considered
    (the upstream pipeline filters non-numeric rows).

    Fail-closed: if FiO2 cannot be determined, returns DATA NOT AVAILABLE.
    """
    # Check if PaO2 is available from ABG panel
    po2_block = abg_panel.get("components", {}).get("pO2", {})
    if po2_block.get("status") != "available":
        return {"status": _DNA, "reason": "pO2_not_available"}

    # Try to find FiO2 value
    fio2_value: Optional[float] = None
    fio2_source: Optional[str] = None

    # Search for FiO2 lab components
    series_lower = {k.lower(): (k, v) for k, v in series.items()}

    for candidate in _FIO2_CANDIDATES:
        key_lower = candidate.lower()
        if key_lower not in series_lower:
            continue
        orig_key, vals = series_lower[key_lower]

        for entry in vals:
            val = entry.get("value_num")
            if val is None:
                continue
            # Normalize: if > 1, assume percentage
            if val > 1.0:
                val = val / 100.0
            if _FIO2_MIN <= val <= _FIO2_MAX:
                fio2_value = val
                fio2_source = orig_key
                break
        if fio2_value is not None:
            break

    if fio2_value is None:
        return {"status": _DNA, "reason": "fio2_not_available"}

    # Use the LAST PaO2 value for P/F computation
    po2_series = po2_block.get("series", [])
    if not po2_series:
        return {"status": _DNA, "reason": "pO2_series_empty"}

    last_po2 = po2_series[-1]["value"]
    pf_ratio = round(last_po2 / fio2_value, 1)

    return {
        "status": "available",
        "pf_ratio": pf_ratio,
        "pao2": last_po2,
        "fio2": round(fio2_value, 2),
        "fio2_source": fio2_source,
        "raw_line_id": _make_raw_line_id(
            "P/F",
            po2_series[-1].get("observed_dt"),
            pf_ratio,
            po2_series[-1].get("raw_line_id"),
        ),
    }


# ── Main extraction ────────────────────────────────────────────────

def extract_structured_labs(
    pat_features: Dict[str, Any],
    days_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extract structured lab panels from patient feature days.

    Parameters
    ----------
    pat_features : dict with "days" key containing per-day feature data.
                   Each day has labs.series with extracted lab values.
    days_data    : unused, accepted for API consistency with other modules.

    Returns
    -------
    dict with keys:
      panels_by_day: {day_iso: {cbc, bmp, coag, abg, pf_ratio}}
      summary: {days_with_labs, panels_complete_count, pf_available_count}
      parse_warnings: list of warning strings
      notes: list of informational strings
    """
    feature_days = pat_features.get("days", {})
    warnings: List[str] = []
    notes: List[str] = []

    panels_by_day: Dict[str, Dict[str, Any]] = {}
    days_with_labs = 0
    panels_complete_total = 0
    pf_available_count = 0

    for day_iso in sorted(feature_days.keys()):
        if day_iso == "__UNDATED__":
            continue

        labs_block = feature_days[day_iso].get("labs", {})
        series = labs_block.get("series", {})

        if not series:
            continue

        days_with_labs += 1

        # Build each panel
        cbc = _build_panel(_CBC_COMPONENTS, series, day_iso)
        bmp = _build_panel(_BMP_COMPONENTS, series, day_iso)
        coag = _build_panel(_COAG_COMPONENTS, series, day_iso)
        abg = _build_panel(_ABG_COMPONENTS, series, day_iso)
        cardiac = _build_panel(_CARDIAC_COMPONENTS, series, day_iso)
        sepsis = _build_panel(_SEPSIS_COMPONENTS, series, day_iso)

        # P/F ratio
        pf_ratio = _compute_pf_ratio(abg, series, day_iso)
        if pf_ratio.get("status") == "available":
            pf_available_count += 1

        # Count completeness
        for panel in (cbc, bmp, coag, abg, cardiac, sepsis):
            if panel["complete"]:
                panels_complete_total += 1

        panels_by_day[day_iso] = {
            "cbc": cbc,
            "bmp": bmp,
            "coag": coag,
            "abg": abg,
            "cardiac": cardiac,
            "sepsis_markers": sepsis,
            "pf_ratio": pf_ratio,
        }

    return {
        "panels_by_day": panels_by_day,
        "summary": {
            "days_with_labs": days_with_labs,
            "panels_complete_count": panels_complete_total,
            "pf_available_count": pf_available_count,
        },
        "parse_warnings": warnings,
        "notes": notes,
    }
