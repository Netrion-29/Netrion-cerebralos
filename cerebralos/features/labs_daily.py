#!/usr/bin/env python3
"""
Per-day lab series, first/last/delta, and big-change flagging.

Takes raw extracted lab rows (from labs_extract) and config thresholds,
produces per-day structured lab summaries:
  - series: ordered list of all numeric values per component
  - daily: first/last/delta/delta_pct/big_change/abnormal_flag_present

Design:
- Deterministic, fail-closed.
- big_change only from numeric delta vs configured abs threshold.
- abnormal_flag_present only if explicit H/L/HH/LL flags in data.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_daily_labs(
    labs_all: List[Dict[str, Any]],
    day_iso: str,
    thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build per-day lab summary from extracted lab rows.

    Parameters
    ----------
    labs_all : list of lab row dicts from extract_labs_from_lines
    day_iso  : 'YYYY-MM-DD'
    thresholds : loaded labs_thresholds_v1 config

    Returns
    -------
    dict with keys:
      series: {component: [{observed_dt, value_num, value_raw, flags, source_line}, ...]}
      daily:  {component: {first, last, delta, delta_pct, big_change, abnormal_flag_present}}
    """
    default_thresh = thresholds.get("_default", {})

    # ── collect rows for this day, grouped by component ──
    by_component: Dict[str, List[Dict[str, Any]]] = {}
    for row in labs_all:
        obs = row.get("observed_dt")
        if not obs or not isinstance(obs, str) or not obs.startswith(day_iso):
            continue
        comp = (row.get("component") or "").strip()
        if not comp:
            continue
        if row.get("value_num") is None:
            continue  # skip non-numeric rows for series/daily
        by_component.setdefault(comp, []).append(row)

    # ── build series and daily per component ──
    series: Dict[str, List[Dict[str, Any]]] = {}
    daily: Dict[str, Dict[str, Any]] = {}

    for comp, rows in sorted(by_component.items()):
        # Sort by (observed_dt, source_line) for deterministic ordering
        rows_sorted = sorted(
            rows,
            key=lambda r: (r.get("observed_dt") or "", r.get("source_line", 0)),
        )

        # Build series entries
        series_entries: List[Dict[str, Any]] = []
        for r in rows_sorted:
            series_entries.append({
                "observed_dt": r.get("observed_dt"),
                "value_num": r["value_num"],
                "value_raw": r.get("value_raw", ""),
                "flags": r.get("flags", []),
                "source_line": r.get("source_line"),
            })
        series[comp] = series_entries

        # Build daily summary
        first_val: float = rows_sorted[0]["value_num"]
        last_val: float = rows_sorted[-1]["value_num"]
        delta: Optional[float] = None
        delta_pct: Optional[float] = None
        big_change: bool = False

        if len(rows_sorted) >= 2:
            delta = round(last_val - first_val, 4)
            if first_val != 0:
                delta_pct = round(delta / abs(first_val) * 100, 2)

            # Check big_change against threshold
            comp_thresh = thresholds.get(comp, default_thresh)
            abs_thresh = comp_thresh.get("abs") if isinstance(comp_thresh, dict) else None
            if abs_thresh is not None and delta is not None:
                big_change = abs(delta) >= abs_thresh

        # abnormal_flag_present: True only if any row has explicit flags
        any_flags = any(
            bool(r.get("flags"))
            for r in rows_sorted
        )

        daily[comp] = {
            "first": first_val,
            "last": last_val,
            "delta": delta,
            "delta_pct": delta_pct,
            "big_change": big_change,
            "abnormal_flag_present": any_flags,
            "n_values": len(rows_sorted),
        }

    return {
        "series": series,
        "daily": daily,
    }
