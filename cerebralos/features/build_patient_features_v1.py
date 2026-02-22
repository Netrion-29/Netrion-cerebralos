#!/usr/bin/env python3
"""
Build patient_features_v1.json from patient_days_v1.json.

Layer 2 orchestrator: reads the timeline, runs each feature extractor
per-day, and assembles the composite feature JSON.

Input:  outputs/timeline/<PAT>/patient_days_v1.json
Output: outputs/features/<PAT>/patient_features_v1.json

Feature sub-modules called per day:
  - labs_extract.extract_labs_from_lines  + compute_daily_latest_and_deltas
  - devices_extract.extract_devices_for_day
  - services_tag.tag_services_for_day

Canonical output contract (for downstream NTDS / protocol engines):
  days[date]["labs"]["daily"]          ← canonical for delta-based rules
      (first / last / delta / big_change / abnormal_flag_present)
      "latest" and "series" are supporting evidence only.
  days[date]["devices"]["canonical"]   ← canonical device tri-state
      dict with keys: foley, central_line, ett_vent, chest_tube, drain
      values: PRESENT | NOT_PRESENT | UNKNOWN
      "present", "episodes", "tri_state", "evidence" kept for
      backwards compat but NOT the supported input for new logic.
  days[date]["services"]              ← "tags" + "notes_by_service"

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

# ── sibling imports ─────────────────────────────────────────────────
from cerebralos.features.labs_extract import (
    extract_labs_from_lines,
    compute_daily_latest,
)
from cerebralos.features.devices_extract import extract_devices_for_day
from cerebralos.features.services_tag import tag_services_for_day

# ── v2 feature modules (config-driven, per-day rollups) ────────────
from cerebralos.features.config_loader import (
    load_labs_thresholds,
    load_devices_patterns,
    load_services_patterns,
    load_vitals_patterns,
)
from cerebralos.features.labs_daily import build_daily_labs
from cerebralos.features.devices_day import evaluate_devices_for_day
from cerebralos.features.devices_carry_forward import compute_carry_forward_and_day_counts
from cerebralos.features.services_daily import tag_services_daily
from cerebralos.features.vitals_daily import extract_vitals_for_day
from cerebralos.features.gcs_daily import extract_gcs_for_day
from cerebralos.features.labs_panel_daily import build_labs_panel_daily
from cerebralos.features.vitals_canonical_v1 import build_canonical_vitals, select_arrival_vitals
from cerebralos.features.dvt_prophylaxis_v1 import extract_dvt_prophylaxis
from cerebralos.features.gi_prophylaxis_v1 import extract_gi_prophylaxis
from cerebralos.features.base_deficit_monitoring_v1 import extract_base_deficit_monitoring
from cerebralos.features.inr_normalization_v1 import extract_inr_normalization
from cerebralos.features.fast_exam_v1 import extract_fast_exam
from cerebralos.features.category_activation_v1 import build_category_activation_v1


# ── helpers ─────────────────────────────────────────────────────────

def _items_to_evidence_lines(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert timeline items into the 'line-dict' format expected by
    labs_extract.extract_labs_from_lines.

    Each line dict needs at minimum: {"text": <str>, "ts": <str|None>}
    We split each item's payload text into individual lines so the
    lab-table regex can match row-by-row.
    """
    lines: List[Dict[str, Any]] = []
    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        ts = item.get("dt")
        item_type = item.get("type")
        for row in text.split("\n"):
            lines.append({"text": row, "ts": ts, "item_type": item_type})
    return lines


# ── main ────────────────────────────────────────────────────────────

def build_patient_features(days_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Core logic: given the parsed patient_days_v1 dict, produce the
    patient_features_v1 dict.
    """
    meta = days_data.get("meta") or {}
    days_map = days_data.get("days") or {}

    # ── load v2 configs (fail-closed if missing) ────────────────
    labs_thresholds = load_labs_thresholds()
    devices_config = load_devices_patterns()
    services_config = load_services_patterns()
    vitals_config = load_vitals_patterns()

    all_warnings: List[str] = []
    warning_counter: Counter = Counter()
    feature_days: Dict[str, Dict[str, Any]] = {}

    # ── PASS 1: Global lab extraction across ALL days ──────────
    # Matrix-format LAB items on one day can contain columns for other
    # days.  Extract once from every LAB item, then let each day's
    # build_daily_labs pick rows by their true observed_dt.
    global_lab_items: List[Dict[str, Any]] = []
    for day_iso_pre in sorted(days_map.keys()):
        for it in days_map[day_iso_pre].get("items") or []:
            if it.get("type") == "LAB":
                global_lab_items.append(it)

    global_evidence_lines = _items_to_evidence_lines(global_lab_items)
    global_labs_all, global_lab_warnings = extract_labs_from_lines(
        global_evidence_lines, _all_lab_context=True,
    )
    all_warnings.extend(global_lab_warnings)
    for w in global_lab_warnings:
        warning_counter[w] += 1

    if os.environ.get("CEREBRAL_DEBUG_LABS") == "1":
        # Per-parser breakdown
        _parser_counts: Counter = Counter()
        for lr in global_labs_all:
            _parser_counts[lr.get("source_block_type", "unknown")] += 1
        print(f"  [DEBUG_LABS] global extraction: {len(global_labs_all)} raw rows")
        for _pk, _pv in sorted(_parser_counts.items()):
            print(f"    parser={_pk}: {_pv} rows")
        # Per-day breakdown
        _day_counts: Counter = Counter()
        for lr in global_labs_all:
            obs = lr.get("observed_dt")
            _day_counts[obs[:10] if obs else "__NONE__"] += 1
        for _dk in sorted(_day_counts.keys()):
            print(f"    day={_dk}: {_day_counts[_dk]} rows")

    # ── PASS 2: Per-day feature extraction ─────────────────────
    for day_iso in sorted(days_map.keys()):
        day_info = days_map[day_iso]
        items: List[Dict[str, Any]] = day_info.get("items") or []

        # ── propagate upstream per-item warnings ────────────
        for it in items:
            for w in it.get("warnings") or ():
                warning_counter[w] += 1

        # ── labs: daily latest (legacy, uses only this day's items) ─
        day_evidence_lines = _items_to_evidence_lines(
            [it for it in items if it.get("type") in ("LAB",)]
        )
        day_labs_local, _ = extract_labs_from_lines(
            day_evidence_lines, _all_lab_context=True,
        )
        labs_daily = compute_daily_latest(day_labs_local, day_iso)

        # ── labs v2: per-day series using GLOBAL extraction ─────
        labs_v2 = build_daily_labs(global_labs_all, day_iso, labs_thresholds)
        labs_daily["series"] = labs_v2["series"]
        labs_daily["daily"] = labs_v2["daily"]

        if os.environ.get("CEREBRAL_DEBUG_LABS") == "1":
            _n_series = sum(len(v) for v in labs_v2["series"].values())
            _n_daily = len(labs_v2["daily"])
            print(
                f"  [DEBUG_LABS] {day_iso}: daily components={_n_daily}, "
                f"series values={_n_series}, "
                f"legacy latest={len(labs_daily.get('latest', {}))}"
            )

        # ── devices (existing) ──────────────────────────────────
        devices, dev_warnings = extract_devices_for_day(items, day_iso)
        all_warnings.extend(dev_warnings)
        for w in dev_warnings:
            warning_counter[w] += 1

        # ── devices v2: tri-state per day ───────────────────────
        devices_v2, dev_v2_warnings = evaluate_devices_for_day(
            items, day_iso, devices_config,
        )
        all_warnings.extend(dev_v2_warnings)
        for w in dev_v2_warnings:
            warning_counter[w] += 1
        devices["tri_state"] = devices_v2["tri_state"]
        devices["evidence"] = devices_v2["evidence"]
        # canonical: single supported input for NTDS/protocol engines
        devices["canonical"] = dict(devices_v2["tri_state"])

        # ── services (existing) ─────────────────────────────────
        services, svc_warnings = tag_services_for_day(items, day_iso)
        all_warnings.extend(svc_warnings)
        for w in svc_warnings:
            warning_counter[w] += 1

        # ── services v2: per-day grouped notes ──────────────────
        services_v2, svc_v2_warnings = tag_services_daily(
            items, day_iso, services_config,
        )
        all_warnings.extend(svc_v2_warnings)
        for w in svc_v2_warnings:
            warning_counter[w] += 1
        services["notes_by_service"] = services_v2["notes_by_service"]

        # ── vitals: per-day extraction ──────────────────────────
        vitals, vitals_warnings = extract_vitals_for_day(
            items, day_iso, vitals_config,
        )
        all_warnings.extend(vitals_warnings)
        for w in vitals_warnings:
            warning_counter[w] += 1

        # ── GCS: per-day extraction ─────────────────────────────
        arrival_datetime_str = meta.get("arrival_datetime")
        gcs, gcs_warnings = extract_gcs_for_day(
            items, day_iso, arrival_datetime=arrival_datetime_str,
        )
        all_warnings.extend(gcs_warnings)
        for w in gcs_warnings:
            warning_counter[w] += 1

        feature_days[day_iso] = {
            "labs": labs_daily,
            "devices": devices,
            "services": services,
            "vitals": vitals,
            "gcs_daily": gcs,
        }

    # ── device carry-forward + day counts (cross-day pass) ──────
    dated_keys = sorted(k for k in feature_days if k != "__UNDATED__")
    days_devices_map = {k: feature_days[k].get("devices", {}) for k in dated_keys}
    cf_enrichment, cf_warnings = compute_carry_forward_and_day_counts(
        dated_keys, days_devices_map, devices_config,
    )
    all_warnings.extend(cf_warnings)
    for w in cf_warnings:
        warning_counter[w] += 1
    for day_iso in dated_keys:
        enrich = cf_enrichment.get(day_iso, {})
        dev_block = feature_days[day_iso].setdefault("devices", {})
        dev_block["carry_forward"] = enrich.get("carry_forward", {})
        dev_block["day_counts"] = enrich.get("day_counts", {})
        # Append per-day carry-forward warnings to per-day device warnings
        for cfw in enrich.get("warnings", []):
            dev_block.setdefault("warnings", []).append(cfw)

    # ── labs panel lite + device day counts (post carry-forward) ──
    for day_iso in dated_keys:
        # labs_panel_daily: structured clinical panels from extracted labs
        labs_block = feature_days[day_iso].get("labs", {})
        feature_days[day_iso]["labs_panel_daily"] = build_labs_panel_daily(labs_block)

        # device_day_counts: consecutive days present per device + totals
        dev_block = feature_days[day_iso].get("devices", {})
        feature_days[day_iso]["device_day_counts"] = dev_block.get("day_counts", {})

    # ── canonical vitals v1 (additive, per-day) ─────────────────
    vitals_canonical_days: Dict[str, Dict[str, Any]] = {}
    for day_iso in sorted(feature_days.keys()):
        day_vitals = feature_days[day_iso].get("vitals", {})
        canonical_records = build_canonical_vitals(
            day_vitals, arrival_ts=meta.get("arrival_datetime"),
        )
        abnormal_total = sum(r["abnormal_count"] for r in canonical_records)
        vitals_canonical_days[day_iso] = {
            "records": canonical_records,
            "count": len(canonical_records),
            "abnormal_total": abnormal_total,
        }

    # ── arrival vitals selector (deterministic hierarchy) ───────
    arrival_ts_str = meta.get("arrival_datetime")
    arrival_day_iso = arrival_ts_str[:10] if arrival_ts_str else None
    arrival_day_records = (
        vitals_canonical_days.get(arrival_day_iso, {}).get("records", [])
        if arrival_day_iso else []
    )
    arrival_vitals = select_arrival_vitals(arrival_day_records, arrival_ts_str)

    # ── evidence gap-day detection ───────────────────────────────
    evidence_gaps: List[Dict[str, Any]] = []
    if len(dated_keys) >= 2:
        for i in range(len(dated_keys) - 1):
            d1 = date.fromisoformat(dated_keys[i])
            d2 = date.fromisoformat(dated_keys[i + 1])
            gap_days = (d2 - d1).days
            if gap_days > 1:
                evidence_gaps.append({
                    "from": dated_keys[i],
                    "to": dated_keys[i + 1],
                    "gap_days": gap_days,
                })
    if evidence_gaps:
        all_warnings.append("evidence_gap_detected")
        warning_counter["evidence_gap_detected"] += 1

    # Merge upstream item-level warning codes into the warnings list
    # (deduplicated, but keep all_warnings from extractors as-is for audit)
    upstream_codes = {w for w in warning_counter if w not in set(all_warnings)}
    combined_warnings = all_warnings + sorted(upstream_codes)

    # ── Aggregate vitals QA metrics across all days ─────────────
    agg_vitals_qa: Dict[str, int] = {
        "vitals_readings_total": 0,
        "vitals_readings_with_full_ts": 0,
        "vitals_readings_missing_time": 0,
        "vitals_readings_missing_date": 0,
        "undated_vitals_count": 0,
    }
    for day_iso_qa in feature_days:
        vqa = feature_days[day_iso_qa].get("vitals", {}).get("vitals_qa", {})
        for k in ("vitals_readings_total", "vitals_readings_with_full_ts",
                  "vitals_readings_missing_time", "vitals_readings_missing_date"):
            agg_vitals_qa[k] += vqa.get(k, 0)
        if day_iso_qa == "__UNDATED__":
            agg_vitals_qa["undated_vitals_count"] += vqa.get("vitals_readings_total", 0)

    max_gap = max((g["gap_days"] for g in evidence_gaps), default=0)

    # ── DVT prophylaxis v1 (additive, cross-day) ────────────────
    dvt_prophylaxis = extract_dvt_prophylaxis(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── GI prophylaxis v1 (additive, cross-day) ─────────────────
    gi_prophylaxis = extract_gi_prophylaxis(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Base deficit monitoring v1 (additive, cross-day) ────────
    base_deficit_monitoring = extract_base_deficit_monitoring(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── INR normalization v1 (additive, cross-day) ──────────────
    inr_normalization = extract_inr_normalization(
        {"days": feature_days},  # pat_features subset
    )

    # ── FAST exam v1 (additive, patient-level) ─────────────────
    fast_exam = extract_fast_exam(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Category I Trauma Activation v1 (additive, patient-level) ─
    category_activation = build_category_activation_v1(days_data)

    # ── Assemble features dict (all feature modules live here) ──
    features: Dict[str, Any] = {
        "vitals_canonical_v1": {
            "days": vitals_canonical_days,
            "arrival_vitals": arrival_vitals,
        },
        "dvt_prophylaxis_v1": dvt_prophylaxis,
        "gi_prophylaxis_v1": gi_prophylaxis,
        "base_deficit_monitoring_v1": base_deficit_monitoring,
        "inr_normalization_v1": inr_normalization,
        "fast_exam_v1": fast_exam,
        "category_activation_v1": category_activation,
        "vitals_qa": agg_vitals_qa,
    }

    return {
        "patient_id": meta.get("patient_id", "unknown"),
        "build": {
            "version": "v1",
        },
        "days": feature_days,
        "evidence_gaps": {
            "gap_count": len(evidence_gaps),
            "max_gap_days": max_gap,
            "gaps": evidence_gaps,
        },
        "features": features,
        "warnings": combined_warnings,
        "warnings_summary": dict(sorted(warning_counter.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build patient_features_v1.json from patient_days_v1.json",
    )
    ap.add_argument("--in", dest="in_path", required=True,
                    help="Path to patient_days_v1.json")
    ap.add_argument("--out", dest="out_path", required=True,
                    help="Path for output patient_features_v1.json")
    args = ap.parse_args()

    in_path = Path(args.in_path).expanduser().resolve()
    out_path = Path(args.out_path).expanduser().resolve()

    if not in_path.is_file():
        print(f"FAIL: input not found: {in_path}", file=sys.stderr)
        return 1

    with open(in_path, encoding="utf-8", errors="replace") as f:
        days_data = json.load(f)

    features = build_patient_features(days_data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(features, indent=2, ensure_ascii=False) + "\n")

    print(f"OK \u2705 Wrote patient_features: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
