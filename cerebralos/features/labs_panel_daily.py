#!/usr/bin/env python3
"""
Labs panel lite: structured per-day lab panels for Daily Notes v4.

Takes the already-extracted labs daily data (from build_patient_features)
and reshapes it into standard clinical panels:
  - CBC:   WBC, Hgb, Hct, Plt
  - BMP:   Na, K, Cl, CO2, BUN, Cr, Glucose
  - Coags: INR, PT, PTT (if present)
  - Lactate
  - Base Deficit (only if validated in data)

For each component, uses the LAST (latest) value for that day.
Missing components → "DATA NOT AVAILABLE".

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- No invented values. Strictly reads from existing labs_daily output.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_DNA = "DATA NOT AVAILABLE"

# ── Component name mappings ─────────────────────────────────────────
# Maps our canonical short names → list of possible extracted component names
# (first match wins, case-insensitive comparison)

_CBC_MAP = {
    "WBC":  ["White Blood Cell Count", "WBC"],
    "Hgb":  ["Hemoglobin", "Hgb", "HGB"],
    "Hct":  ["Hematocrit", "Hct", "HCT"],
    "Plt":  ["Platelet Count", "Plt", "PLT", "Platelets"],
}

_BMP_MAP = {
    "Na":      ["Sodium", "Na"],
    "K":       ["Potassium", "K"],
    "Cl":      ["Chloride", "Cl"],
    "CO2":     ["Co2", "CO2", "Co2 Content"],
    "BUN":     ["Blood Urea Nitrogen", "BUN"],
    "Cr":      ["Creatinine", "Cr"],
    "Glucose": ["Glucose"],
}

_COAGS_MAP = {
    "INR": ["INR"],
    "PT":  ["PROTIME", "PT", "Pro Time"],
    "PTT": ["APTT", "PTT", "aPTT"],
}

_SINGLE_MAP = {
    "Lactate":      ["Lactate", "Lactic Acid"],
    "Base Deficit": ["Base Deficit", "Base Excess"],
}


def _find_component(
    daily_labs: Dict[str, Dict[str, Any]],
    series_labs: Dict[str, Any],
    candidates: list,
) -> Optional[Dict[str, Any]]:
    """
    Find the best match for a lab component from extracted data.
    Returns the daily summary dict if found (containing 'last', 'first', etc.)
    or None.

    Uses case-insensitive matching against the extracted component keys.
    """
    # Build a lowercase lookup for daily labs
    daily_lower = {k.lower(): v for k, v in daily_labs.items()}

    for candidate in candidates:
        key_lower = candidate.lower()
        if key_lower in daily_lower:
            return daily_lower[key_lower]
    return None


def build_labs_panel_daily(
    labs_block: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the labs panel lite from a single day's labs feature block.

    Parameters
    ----------
    labs_block : the day["labs"] dict from patient_features_v1.json
                 Expected keys: "daily", "series", "latest"

    Returns
    -------
    dict with keys:
      cbc:          {WBC, Hgb, Hct, Plt} → value or DATA NOT AVAILABLE
      bmp:          {Na, K, Cl, CO2, BUN, Cr, Glucose} → value or DNA
      coags:        {INR, PT, PTT} → value or DNA
      lactate:      value or DNA
      base_deficit: value or DNA
    """
    daily = labs_block.get("daily", {})
    series = labs_block.get("series", {})

    def _resolve(panel_map: Dict[str, list]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for short_name, candidates in panel_map.items():
            comp = _find_component(daily, series, candidates)
            if comp is not None and comp.get("last") is not None:
                result[short_name] = {
                    "value": comp["last"],
                    "first": comp.get("first"),
                    "delta": comp.get("delta"),
                    "abnormal": comp.get("abnormal_flag_present", False),
                    "n_values": comp.get("n_values", 1),
                }
            else:
                result[short_name] = _DNA
        return result

    cbc = _resolve(_CBC_MAP)
    bmp = _resolve(_BMP_MAP)
    coags = _resolve(_COAGS_MAP)

    # Single-value components
    def _resolve_single(candidates: list) -> Any:
        comp = _find_component(daily, series, candidates)
        if comp is not None and comp.get("last") is not None:
            return {
                "value": comp["last"],
                "abnormal": comp.get("abnormal_flag_present", False),
            }
        return _DNA

    lactate = _resolve_single(_SINGLE_MAP["Lactate"])
    base_deficit = _resolve_single(_SINGLE_MAP["Base Deficit"])

    return {
        "cbc": cbc,
        "bmp": bmp,
        "coags": coags,
        "lactate": lactate,
        "base_deficit": base_deficit,
    }
