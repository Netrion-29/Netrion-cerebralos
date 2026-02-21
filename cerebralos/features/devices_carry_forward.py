#!/usr/bin/env python3
"""
Device carry-forward and consecutive-day counting for CerebralOS.

Takes the per-day canonical tri-state produced by devices_day.py and adds:
  carry_forward  – inferred state accounting for gaps (PRESENT_INFERRED)
  day_counts     – consecutive-day counters per tracked device + totals

Rules:
  - PRESENT or NOT_PRESENT in canonical → carry_forward = same value.
  - UNKNOWN in canonical:
      • if last carry_forward was PRESENT and no NOT_PRESENT has been seen
        since, AND we are within the configurable max_carry_forward_days
        window → PRESENT_INFERRED.
      • otherwise → UNKNOWN.
  - NOT_PRESENT immediately breaks the carry-forward chain.
  - After max_carry_forward_days consecutive UNKNOWN days, revert to
    UNKNOWN even if the chain was previously active.

Design:
  - Deterministic, fail-closed.
  - Config-driven from devices_patterns_v1.json ("_carry_forward" key).
  - No LLM, no ML, no clinical inference beyond the stated rules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# ── tracked devices (must match canonical keys) ────────────────────
_TRACKED_DEVICES = ("foley", "central_line", "ett_vent", "chest_tube", "drain")

_DEFAULT_MAX_CARRY_DAYS = 7


def _get_max_carry_days(config: Dict[str, Any]) -> int:
    """Read max_carry_forward_days from the config, with sensible default."""
    cf_block = config.get("_carry_forward", {})
    val = cf_block.get("max_carry_forward_days", _DEFAULT_MAX_CARRY_DAYS)
    if not isinstance(val, int) or val < 1:
        return _DEFAULT_MAX_CARRY_DAYS
    return val


def compute_carry_forward_and_day_counts(
    sorted_day_keys: List[str],
    days_devices: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """
    Compute carry_forward states and consecutive-day counts across all days.

    Parameters
    ----------
    sorted_day_keys : list of 'YYYY-MM-DD' strings in chronological order.
                      Should not include '__UNDATED__'.
    days_devices    : mapping day_iso → devices dict. Each must contain
                      'canonical' with device tri-state values.
    config          : the loaded devices_patterns_v1 config dict.

    Returns
    -------
    (enrichment_per_day, warnings)
        enrichment_per_day: {day_iso: {"carry_forward": {...}, "day_counts": {...}, "warnings": [...]}}
        warnings: aggregated list of warning strings
    """
    max_carry = _get_max_carry_days(config)
    warnings: List[str] = []

    # Per-device running state trackers
    # last_state[dev]: the last carry_forward value (PRESENT, PRESENT_INFERRED, NOT_PRESENT, UNKNOWN)
    last_state: Dict[str, str] = {dev: "UNKNOWN" for dev in _TRACKED_DEVICES}
    # gap_count[dev]: number of consecutive UNKNOWN days since last concrete evidence
    gap_count: Dict[str, int] = {dev: 0 for dev in _TRACKED_DEVICES}
    # consecutive[dev]: running count of days the device is considered present
    #                   (PRESENT or PRESENT_INFERRED in carry_forward)
    consecutive: Dict[str, int] = {dev: 0 for dev in _TRACKED_DEVICES}

    enrichment: Dict[str, Dict[str, Any]] = {}

    for day_iso in sorted_day_keys:
        dev_block = days_devices.get(day_iso, {})
        canonical = dev_block.get("canonical", {})
        cf: Dict[str, str] = {}
        day_warnings: List[str] = []

        for dev in _TRACKED_DEVICES:
            canon_val = canonical.get(dev, "UNKNOWN")

            if canon_val == "PRESENT":
                cf[dev] = "PRESENT"
                gap_count[dev] = 0
                consecutive[dev] += 1
                last_state[dev] = "PRESENT"

            elif canon_val == "NOT_PRESENT":
                cf[dev] = "NOT_PRESENT"
                gap_count[dev] = 0
                consecutive[dev] = 0
                last_state[dev] = "NOT_PRESENT"

            else:
                # UNKNOWN in canonical
                if last_state[dev] in ("PRESENT", "PRESENT_INFERRED"):
                    gap_count[dev] += 1
                    if gap_count[dev] <= max_carry:
                        cf[dev] = "PRESENT_INFERRED"
                        consecutive[dev] += 1
                        last_state[dev] = "PRESENT_INFERRED"
                    else:
                        cf[dev] = "UNKNOWN"
                        consecutive[dev] = 0
                        last_state[dev] = "UNKNOWN"
                        day_warnings.append(
                            f"carry_forward_expired:{dev}:{day_iso}:exceeded_{max_carry}_day_window"
                        )
                else:
                    cf[dev] = "UNKNOWN"
                    gap_count[dev] = 0
                    consecutive[dev] = 0
                    last_state[dev] = "UNKNOWN"

        # Build day_counts
        day_counts: Dict[str, Any] = {}
        for dev in _TRACKED_DEVICES:
            day_counts[f"{dev}_consecutive_days"] = consecutive[dev]

        # Totals
        day_counts["totals"] = {
            "any_device_present": any(
                cf[d] in ("PRESENT", "PRESENT_INFERRED") for d in _TRACKED_DEVICES
            ),
            "devices_present_count": sum(
                1 for d in _TRACKED_DEVICES
                if cf[d] in ("PRESENT", "PRESENT_INFERRED")
            ),
            "inferred_count": sum(
                1 for d in _TRACKED_DEVICES if cf[d] == "PRESENT_INFERRED"
            ),
        }

        warnings.extend(day_warnings)
        enrichment[day_iso] = {
            "carry_forward": cf,
            "day_counts": day_counts,
            "warnings": day_warnings,
        }

    return enrichment, warnings
