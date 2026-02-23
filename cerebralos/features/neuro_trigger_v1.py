#!/usr/bin/env python3
"""
Neuro Emergency Trigger Detection — Tier 2 Feature (Roadmap Step 7, neuro only)

Deterministic neuro emergency trigger based on existing structured GCS
outputs from gcs_daily (per-day extraction with arrival priority logic).

Trigger rule (deterministic, fail-closed):
  - neuro_gcs_lt9: arrival GCS < 9

Fail-closed behavior:
  - If arrival day's gcs_daily.arrival_gcs_value is None → neuro_triggered = "DATA NOT AVAILABLE"
  - If no days present in feature_days → neuro_triggered = "DATA NOT AVAILABLE"
  - If arrival day cannot be determined → neuro_triggered = "DATA NOT AVAILABLE"

Evidence traceability:
  Where gcs_daily provides line_preview + dt + source, a deterministic
  raw_line_id is synthesised (SHA-256[:16]) so every evidence entry
  carries a non-empty raw_line_id per AGENTS.md §5.

Output key: ``neuro_trigger_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "neuro_triggered": "yes" | "no" | "DATA NOT AVAILABLE",
      "trigger_rule_id": "neuro_gcs_lt9" | null,
      "trigger_ts": "<ISO datetime>" | null,
      "trigger_inputs": {
          "arrival_gcs_value": <int | null>,
          "arrival_gcs_source": <str | null>,
          "arrival_gcs_source_rule_id": <str | null>,
          "arrival_gcs_intubated": <bool | null>,
      } | null,
      "evidence": [
          {
              "raw_line_id": "...",
              "source": "gcs_daily",
              "ts": "..." | null,
              "snippet": "...",
              "role": "primary"
          }, ...
      ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every stored evidence entry.
- Consumes only already-computed per-day gcs_daily outputs.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

_DNA = "DATA NOT AVAILABLE"

# ── Locked threshold ────────────────────────────────────────────────

GCS_NEURO_THRESHOLD = 9   # arrival GCS < 9 → neuro emergency trigger


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source: str, dt: Optional[str], preview: str) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source}|{dt or ''}|{preview.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _make_dna_result(reason: str) -> Dict[str, Any]:
    """Build DATA NOT AVAILABLE stub."""
    return {
        "neuro_triggered": _DNA,
        "trigger_rule_id": None,
        "trigger_ts": None,
        "trigger_inputs": None,
        "evidence": [],
        "notes": [reason],
        "warnings": [],
    }


# ── Core extraction ─────────────────────────────────────────────────

def extract_neuro_trigger(
    feature_days: Dict[str, Dict[str, Any]],
    arrival_ts: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Deterministic neuro emergency trigger from existing GCS outputs.

    Consumes:
      - feature_days[arrival_day].gcs_daily (arrival GCS priority logic)

    Parameters
    ----------
    feature_days : dict
        The ``days`` dict from patient_features_v1, containing per-day
        feature blocks each with a ``gcs_daily`` sub-dict.
    arrival_ts : str, optional
        Arrival ISO timestamp string; used to determine arrival day.
        If None, falls back to first dated day.

    Returns
    -------
    dict
        neuro_trigger_v1 contract output.
    """
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    if not feature_days:
        return _make_dna_result("no feature days available")

    # ── Determine arrival day ───────────────────────────────────
    dated_keys = sorted(k for k in feature_days if k != "__UNDATED__")
    if not dated_keys:
        return _make_dna_result("no dated days available")

    if arrival_ts and len(arrival_ts) >= 10:
        arrival_day = arrival_ts[:10]
    else:
        # Fallback: use earliest dated day
        arrival_day = dated_keys[0]
        notes.append(
            f"arrival_ts not available; using earliest day ({arrival_day}) "
            "as arrival day for neuro trigger evaluation"
        )

    if arrival_day not in feature_days:
        return _make_dna_result(
            f"arrival day {arrival_day} not found in feature days"
        )

    # ── Extract arrival GCS from gcs_daily ──────────────────────
    gcs_block = feature_days[arrival_day].get("gcs_daily", {})

    if isinstance(gcs_block, str):
        # gcs_daily is "DATA NOT AVAILABLE" string
        return _make_dna_result("gcs_daily is DATA NOT AVAILABLE on arrival day")

    arrival_gcs_value = gcs_block.get("arrival_gcs_value")
    arrival_gcs_ts = gcs_block.get("arrival_gcs_ts")
    arrival_gcs_source = gcs_block.get("arrival_gcs_source")
    arrival_gcs_source_rule_id = gcs_block.get("arrival_gcs_source_rule_id")

    # Check structured arrival_gcs dict for intubated flag
    arrival_gcs_dict = gcs_block.get("arrival_gcs")
    arrival_gcs_intubated: Optional[bool] = None
    arrival_line_preview: Optional[str] = None
    if isinstance(arrival_gcs_dict, dict):
        arrival_gcs_intubated = arrival_gcs_dict.get("intubated")
        # line_preview may be on individual readings; try arrival_gcs dict
        # (not always present at this level — check all_readings below)

    if arrival_gcs_value is None:
        return _make_dna_result(
            "arrival GCS value is null; cannot evaluate neuro trigger"
        )

    if not isinstance(arrival_gcs_value, (int, float)):
        return _make_dna_result(
            f"arrival GCS value is not numeric ({type(arrival_gcs_value).__name__}); "
            "cannot evaluate neuro trigger"
        )

    # ── Build evidence entry ────────────────────────────────────
    # Find best line_preview from all_readings matching the arrival GCS
    all_readings = gcs_block.get("all_readings", [])
    line_preview = ""
    for r in all_readings:
        if r.get("is_arrival") or (
            r.get("value") == arrival_gcs_value
            and r.get("dt") == arrival_gcs_ts
        ):
            line_preview = r.get("line_preview", "")
            if arrival_gcs_intubated is None:
                arrival_gcs_intubated = r.get("intubated")
            break

    if not line_preview:
        line_preview = f"GCS {arrival_gcs_value}"
        if arrival_gcs_intubated:
            line_preview += "T"

    raw_line_id = _make_raw_line_id(
        arrival_gcs_source or "gcs_daily",
        arrival_gcs_ts,
        line_preview,
    )

    snippet = (
        f"arrival GCS={arrival_gcs_value}"
        f"{' (intubated)' if arrival_gcs_intubated else ''}"
        f" source={arrival_gcs_source or 'unknown'}"
        f" (rule: GCS<{GCS_NEURO_THRESHOLD})"
    )

    evidence.append({
        "raw_line_id": raw_line_id,
        "source": "gcs_daily",
        "ts": arrival_gcs_ts,
        "snippet": snippet,
        "role": "primary",
    })

    # ── Note if GCS came from ED fallback ───────────────────────
    if arrival_gcs_source_rule_id and "fallback" in arrival_gcs_source_rule_id:
        notes.append(
            f"arrival GCS sourced via fallback rule: {arrival_gcs_source_rule_id}"
        )

    # ── Note if ED fallback was missing in trauma HP ────────────
    if gcs_block.get("arrival_gcs_missing_in_trauma_hp"):
        warnings.append(
            "arrival_gcs_missing_in_trauma_hp: GCS not found in "
            "TRAUMA_HP Primary Survey; ED fallback used"
        )

    # ── Evaluate trigger ────────────────────────────────────────
    gcs_int = int(arrival_gcs_value)
    neuro_triggered = gcs_int < GCS_NEURO_THRESHOLD

    if neuro_triggered:
        trigger_rule_id = "neuro_gcs_lt9"
        trigger_ts = arrival_gcs_ts
        if arrival_gcs_intubated:
            notes.append(
                f"arrival GCS={gcs_int}T (intubated); trigger fires but "
                "intubated V-score may lower composite"
            )
    else:
        trigger_rule_id = None
        trigger_ts = None

    return {
        "neuro_triggered": "yes" if neuro_triggered else "no",
        "trigger_rule_id": trigger_rule_id,
        "trigger_ts": trigger_ts,
        "trigger_inputs": {
            "arrival_gcs_value": gcs_int,
            "arrival_gcs_source": arrival_gcs_source,
            "arrival_gcs_source_rule_id": arrival_gcs_source_rule_id,
            "arrival_gcs_intubated": arrival_gcs_intubated,
        },
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
