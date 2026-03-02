#!/usr/bin/env python3
"""
CerebralOS — PI Daily Notes Renderer (v4)

Clinically self-sufficient daily notes using deterministic extraction.
Adds structured sections per day built from features JSON:
  - Vitals Trending: Temp hi/low, HR hi/low, SBP hi/low, lowest MAP, lowest SpO2
  - GCS: arrival + best/worst per day
  - Labs Panel Lite: CBC, BMP, Coags, Lactate, Base Deficit (latest per day)
  - Device Day Counts: consecutive days present + totals

Input:  outputs/features/<PAT>/patient_features_v1.json
        outputs/timeline/<PAT>/patient_days_v1.json
Output: outputs/reporting/<PAT>/TRAUMA_DAILY_NOTES_v4.txt

Design:
- Deterministic, fail-closed.
- Missing data renders as "DATA NOT AVAILABLE".
- No invented timestamps or values. No inference.
- Does NOT replace v3 — standalone additive output.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_DNA = "DATA NOT AVAILABLE"

# ── Device labels for display ───────────────────────────────────────
_DEVICE_LABELS = {
    "foley": "Foley catheter",
    "central_line": "Central line",
    "ett_vent": "ETT/Ventilator",
    "bipap_niv": "BiPAP/NIV",
    "chest_tube": "Chest tube",
    "drain": "Drain",
}

_TRACKED_DEVICES = ("foley", "central_line", "ett_vent", "bipap_niv", "chest_tube", "drain")


# ── Helpers ─────────────────────────────────────────────────────────

def _fmt_val(val: Any, decimals: int = 1) -> str:
    """Format a numeric value for display, or return DNA."""
    if val is None:
        return _DNA
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _fmt_lab_entry(entry: Any) -> str:
    """Format a single lab panel entry."""
    if entry == _DNA or entry is None:
        return _DNA
    if isinstance(entry, dict):
        v = entry.get("value")
        if v is None:
            return _DNA
        abnormal = entry.get("abnormal", False)
        flag = " (!)" if abnormal else ""
        return f"{_fmt_val(v)}{flag}"
    return str(entry)


def _render_vitals_trending(vitals: Dict[str, Any]) -> List[str]:
    """Render vitals trending section for one day."""
    lines: List[str] = []
    if not vitals or not isinstance(vitals, dict):
        lines.append(f"  {_DNA}")
        return lines

    def _metric_line(label: str, metric_key: str, show_range: bool = True) -> str:
        m = vitals.get(metric_key, {})
        if not m or not isinstance(m, dict):
            return f"  {label}: {_DNA}"
        mn = m.get("min")
        mx = m.get("max")
        if mn is None and mx is None:
            return f"  {label}: {_DNA}"
        if show_range:
            return f"  {label}: {_fmt_val(mn)} – {_fmt_val(mx)}"
        else:
            return f"  {label}: {_fmt_val(mn)}"

    lines.append(_metric_line("Temp (°F)", "temp_f"))
    lines.append(_metric_line("HR", "hr"))
    lines.append(_metric_line("SBP", "sbp"))

    # Lowest MAP
    map_data = vitals.get("map", {})
    if map_data and isinstance(map_data, dict) and map_data.get("min") is not None:
        lines.append(f"  Lowest MAP: {_fmt_val(map_data['min'])}")
    else:
        lines.append(f"  Lowest MAP: {_DNA}")

    # Lowest SpO2
    spo2_data = vitals.get("spo2", {})
    if spo2_data and isinstance(spo2_data, dict) and spo2_data.get("min") is not None:
        lines.append(f"  Lowest SpO2: {_fmt_val(spo2_data['min'])}")
    else:
        lines.append(f"  Lowest SpO2: {_DNA}")

    # RR range
    lines.append(_metric_line("RR", "rr"))

    # First abnormal vital
    first_abnormal = _find_first_abnormal(vitals)
    if first_abnormal:
        lines.append(f"  First Abnormal: {first_abnormal}")

    return lines


def _find_first_abnormal(vitals: Dict[str, Any]) -> Optional[str]:
    """Find the first abnormal vital reading across all metrics for the day."""
    earliest_dt: Optional[str] = None
    earliest_desc: Optional[str] = None

    for metric_key in ("sbp", "map", "hr", "rr", "spo2", "temp_f"):
        m = vitals.get(metric_key, {})
        if not m or not isinstance(m, dict):
            continue
        sources = m.get("sources", [])
        for src in sources:
            if src.get("abnormal"):
                src_dt = src.get("dt", "")
                if earliest_dt is None or (src_dt and src_dt < earliest_dt):
                    earliest_dt = src_dt
                    val = src.get("value", "?")
                    earliest_desc = f"{metric_key.upper()}={val} at {src_dt or 'unknown time'}"

    return earliest_desc


def _render_gcs(gcs: Dict[str, Any]) -> List[str]:
    """Render GCS section for one day, including arrival precedence fields."""
    lines: List[str] = []
    if not gcs or not isinstance(gcs, dict):
        lines.append(f"  {_DNA}")
        return lines

    # Arrival GCS
    arrival = gcs.get("arrival_gcs", _DNA)
    if arrival == _DNA or arrival is None:
        lines.append(f"  Arrival GCS: {_DNA}")
    elif isinstance(arrival, dict):
        val = arrival.get("value", _DNA)
        src = arrival.get("source", "")
        dt = arrival.get("dt", "")
        intub = " (T)" if arrival.get("intubated") else ""
        lines.append(f"  Arrival GCS: {val}{intub}  [{src}] {dt}")
    else:
        lines.append(f"  Arrival GCS: {arrival}")

    # Structured arrival fields
    src_label = gcs.get("arrival_gcs_source", None) or _DNA
    missing_hp = gcs.get("arrival_gcs_missing_in_trauma_hp", False)
    rule_id = gcs.get("arrival_gcs_source_rule_id", None) or _DNA
    lines.append(f"  arrival_gcs_source: {src_label}")
    lines.append(f"  arrival_gcs_missing_in_trauma_hp: {missing_hp}")
    lines.append(f"  arrival_gcs_source_rule_id: {rule_id}")

    # Best GCS
    best = gcs.get("best_gcs", _DNA)
    if best == _DNA or best is None:
        lines.append(f"  Best GCS: {_DNA}")
    elif isinstance(best, dict):
        val = best.get("value", _DNA)
        intub = " (T)" if best.get("intubated") else ""
        dt = best.get("dt", "")
        lines.append(f"  Best GCS: {val}{intub}  {dt}")
    else:
        lines.append(f"  Best GCS: {best}")

    # Worst GCS
    worst = gcs.get("worst_gcs", _DNA)
    if worst == _DNA or worst is None:
        lines.append(f"  Worst GCS: {_DNA}")
    elif isinstance(worst, dict):
        val = worst.get("value", _DNA)
        intub = " (T)" if worst.get("intubated") else ""
        dt = worst.get("dt", "")
        lines.append(f"  Worst GCS: {val}{intub}  {dt}")
    else:
        lines.append(f"  Worst GCS: {worst}")

    return lines


def _render_labs_panel(panel: Dict[str, Any]) -> List[str]:
    """Render labs panel lite section for one day."""
    lines: List[str] = []
    if not panel or not isinstance(panel, dict):
        lines.append(f"  {_DNA}")
        return lines

    # CBC
    cbc = panel.get("cbc", {})
    if isinstance(cbc, dict):
        parts = []
        for k in ("WBC", "Hgb", "Hct", "Plt"):
            parts.append(f"{k}: {_fmt_lab_entry(cbc.get(k, _DNA))}")
        lines.append(f"  CBC: {' | '.join(parts)}")
    else:
        lines.append(f"  CBC: {_DNA}")

    # BMP
    bmp = panel.get("bmp", {})
    if isinstance(bmp, dict):
        parts = []
        for k in ("Na", "K", "Cl", "CO2", "BUN", "Cr", "Glucose"):
            parts.append(f"{k}: {_fmt_lab_entry(bmp.get(k, _DNA))}")
        lines.append(f"  BMP: {' | '.join(parts)}")
    else:
        lines.append(f"  BMP: {_DNA}")

    # Coags
    coags = panel.get("coags", {})
    if isinstance(coags, dict):
        parts = []
        for k in ("INR", "PT", "PTT"):
            parts.append(f"{k}: {_fmt_lab_entry(coags.get(k, _DNA))}")
        lines.append(f"  Coags: {' | '.join(parts)}")
    else:
        lines.append(f"  Coags: {_DNA}")

    # Lactate
    lactate = panel.get("lactate", _DNA)
    lines.append(f"  Lactate: {_fmt_lab_entry(lactate)}")

    # Base Deficit
    bd = panel.get("base_deficit", _DNA)
    lines.append(f"  Base Deficit: {_fmt_lab_entry(bd)}")

    return lines


def _render_device_day_counts(counts: Dict[str, Any]) -> List[str]:
    """Render device day counts section for one day."""
    lines: List[str] = []
    if not counts or not isinstance(counts, dict):
        lines.append(f"  {_DNA}")
        return lines

    any_present = False
    for dev_key in _TRACKED_DEVICES:
        consec_key = f"{dev_key}_consecutive_days"
        val = counts.get(consec_key, 0)
        label = _DEVICE_LABELS.get(dev_key, dev_key)
        if val and val > 0:
            lines.append(f"  {label}: Day {val}")
            any_present = True

    # Totals
    totals = counts.get("totals", {})
    if isinstance(totals, dict):
        n_present = totals.get("devices_present_count", 0)
        n_inferred = totals.get("inferred_count", 0)
        if n_present > 0:
            inf_note = f" ({n_inferred} inferred)" if n_inferred > 0 else ""
            lines.append(f"  Active devices: {n_present}{inf_note}")

    if not any_present:
        lines.append(f"  No tracked devices present")

    return lines


# ── Main Renderer ───────────────────────────────────────────────────

def render_v4(
    features_data: Dict[str, Any],
    days_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Render Daily Notes v4 text from features JSON.

    Parameters
    ----------
    features_data : loaded patient_features_v1.json
    days_data     : loaded patient_days_v1.json (optional, for metadata)
    """
    # Extract metadata
    patient_id = features_data.get("patient_id", _DNA)
    meta = {}
    if days_data:
        meta = days_data.get("meta", {})

    feature_days = features_data.get("days", {})
    day_keys = sorted(k for k in feature_days.keys() if k != "__UNDATED__")

    out: List[str] = []
    out.append("PI DAILY NOTES (v4)")
    out.append("=" * 60)
    out.append(f"Patient ID: {patient_id}")
    out.append(f"Arrival: {meta.get('arrival_datetime', _DNA)}")
    out.append(f"Timezone: {meta.get('timezone', _DNA)}")
    out.append(f"Days covered: {len(day_keys)}")
    out.append(f"Build: deterministic extraction — no inference")
    out.append("=" * 60)
    out.append("")

    prev_date: Optional[date] = None
    for dk in day_keys:
        # ── Evidence gap detection ──
        try:
            cur_date = date.fromisoformat(dk)
        except ValueError:
            cur_date = None
        if prev_date is not None and cur_date is not None:
            gap_days = (cur_date - prev_date).days
            if gap_days > 1:
                out.append(f"--- EVIDENCE GAP: {gap_days - 1} day(s) with no dated documentation detected ---")
                out.append("")
        if cur_date is not None:
            prev_date = cur_date

        day = feature_days.get(dk, {})
        out.append(f"===== {dk} =====")
        out.append("")

        # ── Vitals Trending ──
        out.append("Vitals Trending:")
        vitals = day.get("vitals", {})
        out.extend(_render_vitals_trending(vitals))
        out.append("")

        # ── GCS ──
        out.append("GCS:")
        gcs = day.get("gcs_daily", {})
        out.extend(_render_gcs(gcs))
        out.append("")

        # ── Labs Panel Lite ──
        out.append("Labs Panel Lite:")
        labs_panel = day.get("labs_panel_daily", {})
        out.extend(_render_labs_panel(labs_panel))
        out.append("")

        # ── Device Day Counts ──
        out.append("Device Day Counts:")
        dev_counts = day.get("device_day_counts", {})
        out.extend(_render_device_day_counts(dev_counts))
        out.append("")

    # ── Undated section (if present) ──
    if "__UNDATED__" in feature_days:
        out.append("===== __UNDATED__ =====")
        out.append("(undated items not rendered in v4 — see v3 for detail)")
        out.append("")

    # ── Footer ──
    out.append("=" * 60)
    out.append("END OF PI DAILY NOTES (v4)")
    out.append(f"Generated by CerebralOS — deterministic, fail-closed")
    out.append("=" * 60)

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render PI Daily Notes v4 from patient_features_v1.json",
    )
    ap.add_argument("--features", dest="features_path", required=True,
                    help="Path to patient_features_v1.json")
    ap.add_argument("--days", dest="days_path", required=False, default=None,
                    help="Path to patient_days_v1.json (optional, for metadata)")
    ap.add_argument("--out", dest="out_path", required=True,
                    help="Path for output TRAUMA_DAILY_NOTES_v4.txt")
    args = ap.parse_args()

    features_path = Path(args.features_path).expanduser().resolve()
    out_path = Path(args.out_path).expanduser().resolve()

    if not features_path.is_file():
        print(f"FAIL: features file not found: {features_path}")
        return 1

    with open(features_path, encoding="utf-8", errors="replace") as f:
        features_data = json.load(f)

    days_data = None
    if args.days_path:
        days_path = Path(args.days_path).expanduser().resolve()
        if days_path.is_file():
            with open(days_path, encoding="utf-8", errors="replace") as f:
                days_data = json.load(f)

    text = render_v4(features_data, days_data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"OK \u2705 Wrote daily notes v4: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
