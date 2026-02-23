#!/usr/bin/env python3
"""
Shock Trigger Detection — Tier 2 Feature (Roadmap Step 7, shock only)

Deterministic shock trigger based on existing structured outputs:
  - Arrival vitals (SBP) from vitals_canonical_v1.arrival_vitals
  - Base deficit from base_deficit_monitoring_v1

Trigger rules (deterministic, fail-closed):
  - Primary rule (shock_sbp_lt90): SBP < 90 on arrival vitals
  - Supporting rule (shock_bd_gt6): initial BD > 6 (arterial preferred;
    venous/unknown marked uncertain)
  - Combined trigger: SBP < 90 alone is sufficient; BD > 6 alone
    triggers with type "indeterminate"; both → "hemorrhagic_likely"

Fail-closed behavior:
  - If arrival vitals status is DATA NOT AVAILABLE → shock_triggered = "DATA NOT AVAILABLE"
  - If arrival SBP is null → shock_triggered = "DATA NOT AVAILABLE"
  - If BD is unavailable, trigger is evaluated on SBP only (BD is supporting, not required)

Output key: ``shock_trigger_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "shock_triggered": "yes" | "no" | "DATA NOT AVAILABLE",
      "trigger_rule_id": "shock_sbp_lt90" | "shock_bd_gt6"
                        | "shock_sbp_lt90+bd_gt6" | null,
      "trigger_ts": "<ISO datetime>" | null,
      "trigger_vitals": {
          "sbp": <float | null>,
          "map": <float | null>,
          "bd_value": <float | null>,
          "bd_specimen": "arterial" | "venous" | "unknown" | null,
      } | null,
      "shock_type": "hemorrhagic_likely" | "indeterminate" | null,
      "evidence": [
          {
              "raw_line_id": "...",
              "source": "arrival_vitals" | "base_deficit_monitoring",
              "ts": "..." | null,
              "snippet": "...",
              "role": "primary" | "supporting"
          }, ...
      ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every stored evidence entry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_DNA = "DATA NOT AVAILABLE"

# ── Locked thresholds ───────────────────────────────────────────────

SBP_SHOCK_THRESHOLD = 90       # SBP < 90 mmHg → hypotension trigger
BD_SHOCK_THRESHOLD = 6.0       # BD > 6 → metabolic shock support


# ── Helpers ─────────────────────────────────────────────────────────

def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _make_dna_result(reason: str) -> Dict[str, Any]:
    """Build DATA NOT AVAILABLE stub."""
    return {
        "shock_triggered": _DNA,
        "trigger_rule_id": None,
        "trigger_ts": None,
        "trigger_vitals": None,
        "shock_type": None,
        "evidence": [],
        "notes": [reason],
        "warnings": [],
    }


# ── Core extraction ─────────────────────────────────────────────────

def extract_shock_trigger(
    features: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic shock trigger detection from existing feature outputs.

    Consumes:
      - features.vitals_canonical_v1.arrival_vitals (SBP)
      - features.base_deficit_monitoring_v1 (initial BD value + specimen)

    Parameters
    ----------
    features : dict
        The ``features`` dict from patient_features_v1.json, containing
        vitals_canonical_v1 and base_deficit_monitoring_v1 sub-dicts.

    Returns
    -------
    dict
        shock_trigger_v1 contract output.
    """
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    # ── Extract arrival SBP ─────────────────────────────────────
    vc = features.get("vitals_canonical_v1", {})
    arrival = vc.get("arrival_vitals", {})

    arrival_status = arrival.get("status")
    if arrival_status != "selected":
        return _make_dna_result(
            f"arrival_vitals status is '{arrival_status or _DNA}'; "
            "cannot evaluate shock trigger"
        )

    sbp = arrival.get("sbp")
    map_val = arrival.get("map")
    arrival_ts = arrival.get("ts")
    arrival_raw_line_id = arrival.get("raw_line_id")

    if sbp is None:
        return _make_dna_result(
            "arrival SBP is null; cannot evaluate SBP-based shock trigger"
        )

    sbp_triggered = sbp < SBP_SHOCK_THRESHOLD

    # Build arrival evidence entry
    sbp_snippet = f"arrival SBP={sbp}"
    if map_val is not None:
        sbp_snippet += f", MAP={map_val}"
    sbp_snippet += f" (rule: SBP<{SBP_SHOCK_THRESHOLD})"

    if arrival_raw_line_id:
        evidence.append({
            "raw_line_id": arrival_raw_line_id,
            "source": "arrival_vitals",
            "ts": arrival_ts,
            "snippet": sbp_snippet,
            "role": "primary",
        })

    # ── Extract initial BD ──────────────────────────────────────
    bdm = features.get("base_deficit_monitoring_v1", {})
    initial_bd = bdm.get("initial_bd_value")
    initial_bd_ts = bdm.get("initial_bd_ts")
    bd_specimen = bdm.get("initial_bd_source")  # arterial | venous | unknown
    bd_series = bdm.get("bd_series", [])

    bd_triggered = False
    bd_value_used: Optional[float] = None
    bd_specimen_used: Optional[str] = None

    if initial_bd is not None and isinstance(initial_bd, (int, float)):
        bd_value_used = initial_bd
        bd_specimen_used = bd_specimen

        if initial_bd > BD_SHOCK_THRESHOLD:
            bd_triggered = True

            # Find the raw_line_id for the initial BD from bd_series
            bd_raw_line_id = None
            if bd_series and isinstance(bd_series, list) and len(bd_series) > 0:
                bd_raw_line_id = bd_series[0].get("raw_line_id")

            bd_snippet = f"initial BD={initial_bd} (specimen={bd_specimen or 'unknown'})"
            bd_snippet += f" (rule: BD>{BD_SHOCK_THRESHOLD})"

            if bd_raw_line_id:
                evidence.append({
                    "raw_line_id": bd_raw_line_id,
                    "source": "base_deficit_monitoring",
                    "ts": initial_bd_ts,
                    "snippet": bd_snippet,
                    "role": "supporting",
                })
            else:
                warnings.append(
                    "bd_evidence_missing_raw_line_id: initial BD triggered "
                    "but no raw_line_id available"
                )
    else:
        notes.append("initial BD not available; shock evaluation based on SBP only")

    # ── Determine trigger result ────────────────────────────────
    if sbp_triggered and bd_triggered:
        shock_triggered = "yes"
        trigger_rule_id = "shock_sbp_lt90+bd_gt6"
        shock_type = "hemorrhagic_likely"
        if bd_specimen_used and bd_specimen_used != "arterial":
            warnings.append(
                f"bd_specimen_not_arterial: BD specimen is '{bd_specimen_used}', "
                "not arterial; hemorrhagic classification is less certain"
            )
    elif sbp_triggered:
        shock_triggered = "yes"
        trigger_rule_id = "shock_sbp_lt90"
        shock_type = "indeterminate"
        if bd_value_used is not None and not bd_triggered:
            notes.append(
                f"SBP<{SBP_SHOCK_THRESHOLD} triggered but BD={bd_value_used} "
                f"<= {BD_SHOCK_THRESHOLD}; classified as indeterminate"
            )
    elif bd_triggered:
        shock_triggered = "yes"
        trigger_rule_id = "shock_bd_gt6"
        shock_type = "indeterminate"
        notes.append(
            f"BD>{BD_SHOCK_THRESHOLD} without SBP<{SBP_SHOCK_THRESHOLD} "
            f"(arrival SBP={sbp}); classified as indeterminate"
        )
    else:
        shock_triggered = "no"
        trigger_rule_id = None
        shock_type = None

    # Trigger timestamp: use arrival timestamp (primary signal source)
    trigger_ts = arrival_ts if shock_triggered == "yes" else None

    return {
        "shock_triggered": shock_triggered,
        "trigger_rule_id": trigger_rule_id,
        "trigger_ts": trigger_ts,
        "trigger_vitals": {
            "sbp": sbp,
            "map": map_val,
            "bd_value": bd_value_used,
            "bd_specimen": bd_specimen_used,
        },
        "shock_type": shock_type,
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
