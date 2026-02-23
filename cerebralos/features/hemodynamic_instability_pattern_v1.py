#!/usr/bin/env python3
"""
Hemodynamic Instability Pattern Detection — Tier 1 Feature

Deterministic hemodynamic instability pattern extraction from canonical
vitals records (vitals_canonical_v1).

Detects three independent patterns across all hospital days:
  - Hypotension:  SBP < 90 mmHg   (abnormal flag: Hypotension)
  - MAP low:      MAP < 65 mmHg   (direct numeric check)
  - Tachycardia:  HR  > 120 bpm   (abnormal flag: Tachycardia)

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- Consumes only canonical vitals (vitals_canonical_v1.days).
- raw_line_id required on every evidence entry.
- Each detected reading becomes an evidence entry; downstream consumers
  use reading_count to apply their own severity thresholds.
- pattern_present = "yes" if ANY pattern has >= 1 qualifying reading.

Output key: ``hemodynamic_instability_pattern_v1`` (under ``features`` dict)

Output schema::

    {
      "pattern_present": "yes" | "no" | "DATA NOT AVAILABLE",
      "hypotension_pattern": {
          "detected": true | false,
          "reading_count": <int>,
          "days_affected": <int>,
          "threshold": "SBP < 90",
          "source_rule_id": "hemo_sbp_lt90"
      },
      "map_low_pattern": {
          "detected": true | false,
          "reading_count": <int>,
          "days_affected": <int>,
          "threshold": "MAP < 65",
          "source_rule_id": "hemo_map_lt65"
      },
      "tachycardia_pattern": {
          "detected": true | false,
          "reading_count": <int>,
          "days_affected": <int>,
          "threshold": "HR > 120",
          "source_rule_id": "hemo_hr_gt120"
      },
      "patterns_detected": ["hypotension", "map_low", "tachycardia"],
      "total_abnormal_readings": <int>,
      "total_vitals_readings": <int>,
      "source_rule_id": "hemodynamic_instability_pattern_canonical_vitals",
      "evidence": [
          {
              "raw_line_id": "...",
              "ts": "..." | null,
              "day": "..." | null,
              "pattern": "hypotension" | "map_low" | "tachycardia",
              "value": <float>,
              "threshold": "SBP < 90" | "MAP < 65" | "HR > 120",
              "snippet": "..."
          }, ...
      ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }
"""

from __future__ import annotations

from typing import Any, Dict, List

_DNA = "DATA NOT AVAILABLE"

# ── Locked thresholds ───────────────────────────────────────────────
SBP_HYPOTENSION_THRESHOLD = 90    # SBP < 90 mmHg
MAP_LOW_THRESHOLD = 65            # MAP < 65 mmHg
HR_TACHYCARDIA_THRESHOLD = 120    # HR  > 120 bpm

SOURCE_RULE_ID = "hemodynamic_instability_pattern_canonical_vitals"


# ── Helpers ─────────────────────────────────────────────────────────

def _snippet(pattern: str, metric: str, value: float, threshold: str) -> str:
    """Build a deterministic evidence snippet."""
    return f"{metric}={value} ({pattern}: {threshold})"


def _make_dna_result(reason: str) -> Dict[str, Any]:
    """Build DATA NOT AVAILABLE stub."""
    return {
        "pattern_present": _DNA,
        "hypotension_pattern": {
            "detected": False,
            "reading_count": 0,
            "days_affected": 0,
            "threshold": f"SBP < {SBP_HYPOTENSION_THRESHOLD}",
            "source_rule_id": "hemo_sbp_lt90",
        },
        "map_low_pattern": {
            "detected": False,
            "reading_count": 0,
            "days_affected": 0,
            "threshold": f"MAP < {MAP_LOW_THRESHOLD}",
            "source_rule_id": "hemo_map_lt65",
        },
        "tachycardia_pattern": {
            "detected": False,
            "reading_count": 0,
            "days_affected": 0,
            "threshold": f"HR > {HR_TACHYCARDIA_THRESHOLD}",
            "source_rule_id": "hemo_hr_gt120",
        },
        "patterns_detected": [],
        "total_abnormal_readings": 0,
        "total_vitals_readings": 0,
        "source_rule_id": SOURCE_RULE_ID,
        "evidence": [],
        "notes": [reason],
        "warnings": [],
    }


# ── Core extraction ─────────────────────────────────────────────────

def extract_hemodynamic_instability_pattern(
    features: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic hemodynamic instability pattern detection from
    canonical vitals records.

    Consumes:
      - features.vitals_canonical_v1.days (per-day canonical vitals records)

    Parameters
    ----------
    features : dict
        The ``features`` dict from patient_features_v1.json, containing
        vitals_canonical_v1 with its ``days`` sub-dict.

    Returns
    -------
    dict
        hemodynamic_instability_pattern_v1 contract output.
    """
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    # ── Get canonical vitals days ───────────────────────────────
    vc = features.get("vitals_canonical_v1", {})
    vc_days = vc.get("days", {})

    if not vc_days:
        return _make_dna_result(
            "vitals_canonical_v1.days is empty or missing; "
            "cannot evaluate hemodynamic patterns"
        )

    # ── Scan all records across all days ────────────────────────
    total_readings = 0
    hypo_readings = 0
    hypo_days: set = set()
    map_readings = 0
    map_days: set = set()
    tachy_readings = 0
    tachy_days: set = set()

    for day_iso in sorted(vc_days.keys()):
        day_data = vc_days[day_iso]
        if not isinstance(day_data, dict):
            continue

        records = day_data.get("records", [])
        for rec in records:
            if not isinstance(rec, dict):
                continue

            total_readings += 1
            raw_line_id = rec.get("raw_line_id")
            ts = rec.get("ts")
            rec_day = rec.get("day") or day_iso

            if not raw_line_id:
                warnings.append(
                    f"vitals_record_missing_raw_line_id: "
                    f"day={day_iso} ts={ts}"
                )
                continue

            # ── Hypotension check: SBP < 90 ────────────────────
            sbp = rec.get("sbp")
            if sbp is not None and isinstance(sbp, (int, float)):
                if sbp < SBP_HYPOTENSION_THRESHOLD:
                    hypo_readings += 1
                    hypo_days.add(rec_day)
                    evidence.append({
                        "raw_line_id": raw_line_id,
                        "ts": ts,
                        "day": rec_day,
                        "pattern": "hypotension",
                        "value": sbp,
                        "threshold": f"SBP < {SBP_HYPOTENSION_THRESHOLD}",
                        "snippet": _snippet(
                            "Hypotension", "SBP", sbp,
                            f"SBP < {SBP_HYPOTENSION_THRESHOLD}",
                        ),
                    })

            # ── MAP low check: MAP < 65 ────────────────────────
            map_val = rec.get("map")
            if map_val is not None and isinstance(map_val, (int, float)):
                if map_val < MAP_LOW_THRESHOLD:
                    map_readings += 1
                    map_days.add(rec_day)
                    evidence.append({
                        "raw_line_id": raw_line_id,
                        "ts": ts,
                        "day": rec_day,
                        "pattern": "map_low",
                        "value": map_val,
                        "threshold": f"MAP < {MAP_LOW_THRESHOLD}",
                        "snippet": _snippet(
                            "MAP_low", "MAP", map_val,
                            f"MAP < {MAP_LOW_THRESHOLD}",
                        ),
                    })

            # ── Tachycardia check: HR > 120 ────────────────────
            hr = rec.get("hr")
            if hr is not None and isinstance(hr, (int, float)):
                if hr > HR_TACHYCARDIA_THRESHOLD:
                    tachy_readings += 1
                    tachy_days.add(rec_day)
                    evidence.append({
                        "raw_line_id": raw_line_id,
                        "ts": ts,
                        "day": rec_day,
                        "pattern": "tachycardia",
                        "value": hr,
                        "threshold": f"HR > {HR_TACHYCARDIA_THRESHOLD}",
                        "snippet": _snippet(
                            "Tachycardia", "HR", hr,
                            f"HR > {HR_TACHYCARDIA_THRESHOLD}",
                        ),
                    })

    # ── Build pattern sub-results ───────────────────────────────
    hypo_detected = hypo_readings > 0
    map_detected = map_readings > 0
    tachy_detected = tachy_readings > 0

    patterns_detected: List[str] = []
    if hypo_detected:
        patterns_detected.append("hypotension")
    if map_detected:
        patterns_detected.append("map_low")
    if tachy_detected:
        patterns_detected.append("tachycardia")

    total_abnormal = hypo_readings + map_readings + tachy_readings

    if total_readings == 0:
        return _make_dna_result(
            "vitals_canonical_v1 has days but zero vitals records; "
            "cannot evaluate hemodynamic patterns"
        )

    pattern_present = "yes" if patterns_detected else "no"

    return {
        "pattern_present": pattern_present,
        "hypotension_pattern": {
            "detected": hypo_detected,
            "reading_count": hypo_readings,
            "days_affected": len(hypo_days),
            "threshold": f"SBP < {SBP_HYPOTENSION_THRESHOLD}",
            "source_rule_id": "hemo_sbp_lt90",
        },
        "map_low_pattern": {
            "detected": map_detected,
            "reading_count": map_readings,
            "days_affected": len(map_days),
            "threshold": f"MAP < {MAP_LOW_THRESHOLD}",
            "source_rule_id": "hemo_map_lt65",
        },
        "tachycardia_pattern": {
            "detected": tachy_detected,
            "reading_count": tachy_readings,
            "days_affected": len(tachy_days),
            "threshold": f"HR > {HR_TACHYCARDIA_THRESHOLD}",
            "source_rule_id": "hemo_hr_gt120",
        },
        "patterns_detected": patterns_detected,
        "total_abnormal_readings": total_abnormal,
        "total_vitals_readings": total_readings,
        "source_rule_id": SOURCE_RULE_ID,
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
