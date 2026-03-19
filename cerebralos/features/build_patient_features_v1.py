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
import re
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
from cerebralos.features.vitals_daily import extract_vitals_for_day, extract_arrival_vitals
from cerebralos.features.gcs_daily import extract_gcs_for_day
from cerebralos.features.labs_panel_daily import build_labs_panel_daily
from cerebralos.features.vitals_canonical_v1 import build_canonical_vitals, select_arrival_vitals
from cerebralos.features.dvt_prophylaxis_v1 import extract_dvt_prophylaxis
from cerebralos.features.gi_prophylaxis_v1 import extract_gi_prophylaxis
from cerebralos.features.base_deficit_monitoring_v1 import extract_base_deficit_monitoring
from cerebralos.features.inr_normalization_v1 import extract_inr_normalization
from cerebralos.features.fast_exam_v1 import extract_fast_exam
from cerebralos.features.etoh_uds_v1 import extract_etoh_uds
from cerebralos.features.impression_plan_drift_v1 import extract_impression_plan_drift
from cerebralos.features.category_activation_v1 import build_category_activation_v1
from cerebralos.features.shock_trigger_v1 import extract_shock_trigger
from cerebralos.features.neuro_trigger_v1 import extract_neuro_trigger
from cerebralos.features.age_extraction_v1 import extract_patient_age
from cerebralos.features.mechanism_region_v1 import extract_mechanism_region
from cerebralos.features.radiology_findings_v1 import extract_radiology_findings
from cerebralos.features.sbirt_screening_v1 import extract_sbirt_screening
from cerebralos.features.hemodynamic_instability_pattern_v1 import extract_hemodynamic_instability_pattern
from cerebralos.features.note_sections_v1 import extract_note_sections
from cerebralos.features.incentive_spirometry_v1 import extract_incentive_spirometry
from cerebralos.features.anticoag_context_v1 import extract_anticoag_context
from cerebralos.features.pmh_social_allergies_v1 import extract_pmh_social_allergies
from cerebralos.features.adt_transfer_timeline_v1 import extract_adt_transfer_timeline
from cerebralos.features.procedure_operatives_v1 import extract_procedure_operatives
from cerebralos.features.anesthesia_case_metrics_v1 import extract_anesthesia_case_metrics
from cerebralos.features.spine_clearance_v1 import extract_spine_clearance
from cerebralos.features.note_index_events_v1 import extract_note_index_events
from cerebralos.features.patient_movement_v1 import extract_patient_movement
from cerebralos.features.consultant_events_v1 import extract_consultant_events
from cerebralos.features.consultant_plan_items_v1 import extract_consultant_plan_items
from cerebralos.features.consultant_plan_actionables_v1 import extract_consultant_plan_actionables
from cerebralos.features.lda_events_v1 import extract_lda_events
from cerebralos.features.urine_output_events_v1 import extract_urine_output_events
from cerebralos.features.structured_labs_v1 import extract_structured_labs
from cerebralos.features.transfusion_blood_products_v1 import extract_transfusion_blood_products
from cerebralos.features.ventilator_settings_v1 import extract_ventilator_settings
from cerebralos.features.trauma_daily_plan_by_day_v1 import extract_trauma_daily_plan_by_day
from cerebralos.features.seizure_prophylaxis_v1 import extract_seizure_prophylaxis
from cerebralos.features.consultant_day_plans_by_day_v1 import extract_consultant_day_plans_by_day
from cerebralos.features.non_trauma_team_day_plans_v1 import extract_non_trauma_team_day_plans


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
    # Validate that arrival_ts starts with a valid ISO date before slicing
    arrival_day_iso = None
    if arrival_ts_str and len(arrival_ts_str) >= 10:
        _candidate = arrival_ts_str[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", _candidate):
            arrival_day_iso = _candidate
    next_day_iso = None
    if arrival_day_iso:
        next_day_iso = (
            date.fromisoformat(arrival_day_iso) + timedelta(days=1)
        ).isoformat()

    # Gather candidate records: arrival day + next calendar day.
    # Cross-midnight transfers (late-evening arrival, note documented
    # after midnight) place vitals on the next calendar day.  The
    # selector's time-window logic decides which records qualify.
    arrival_day_records: List[Dict[str, Any]] = []
    if arrival_day_iso:
        arrival_day_records = list(
            vitals_canonical_days.get(arrival_day_iso, {}).get("records", [])
        )
        if next_day_iso:
            arrival_day_records += (
                vitals_canonical_days.get(next_day_iso, {}).get("records", [])
            )

    arrival_vitals = select_arrival_vitals(arrival_day_records, arrival_ts_str)

    # ── arrival vitals hardened (item-type-aware, PRIMARY_SURVEY priority) ──
    arrival_day_items: List[Dict[str, Any]] = []
    if arrival_day_iso:
        arrival_day_items = list(days_map.get(arrival_day_iso, {}).get("items") or [])
    arrival_vitals_hardened = extract_arrival_vitals(
        arrival_day_items, arrival_day_iso or "", vitals_config,
    )
    # Cross-midnight fallback: if arrival-day items produce DNA, retry on the
    # next calendar day items using next_day_iso for parser date alignment.
    if (
        arrival_vitals_hardened.get("status") != "selected"
        and next_day_iso
    ):
        next_day_items = list(days_map.get(next_day_iso, {}).get("items") or [])
        if next_day_items:
            next_day_hardened = extract_arrival_vitals(
                next_day_items, next_day_iso, vitals_config,
            )
            if next_day_hardened.get("status") == "selected":
                arrival_vitals_hardened = next_day_hardened

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

    # ── ETOH + UDS v1 (additive, patient-level) ────────────────
    etoh_uds = extract_etoh_uds(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Impression/Plan drift v1 (additive, cross-day) ─────────
    impression_plan_drift = extract_impression_plan_drift(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Category I Trauma Activation v1 (additive, patient-level) ─
    category_activation = build_category_activation_v1(days_data)

    # ── Mechanism + Body Region v1 (additive, patient-level) ──
    mechanism_region = extract_mechanism_region(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Radiology Findings v1 (additive, patient-level) ──
    radiology_findings = extract_radiology_findings(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── SBIRT Screening v1 (additive, patient-level) ──
    sbirt_screening = extract_sbirt_screening(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Note Sections v1 (additive, patient-level) ──
    note_sections = extract_note_sections(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Incentive Spirometry v1 (additive, patient-level) ──
    incentive_spirometry = extract_incentive_spirometry(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Anticoag Context v1 (additive, patient-level) ──
    anticoag_context = extract_anticoag_context(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── PMH / Social / Allergies v1 (additive, patient-level) ──
    pmh_social_allergies = extract_pmh_social_allergies(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── ADT Transfer Timeline v1 (additive, patient-level) ──
    adt_transfer_timeline = extract_adt_transfer_timeline(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Procedure / Operative Events v1 (additive, patient-level) ──
    procedure_operatives = extract_procedure_operatives(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Anesthesia Case Metrics v1 (additive, patient-level) ──
    anesthesia_case_metrics = extract_anesthesia_case_metrics(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Spine Clearance v1 (additive, patient-level) ──
    spine_clearance = extract_spine_clearance(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Note Index Events v1 (additive, patient-level) ──
    note_index_events = extract_note_index_events(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Patient Movement v1 (additive, patient-level) ──
    patient_movement = extract_patient_movement(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── LDA Events v1 (additive, patient-level) ──
    lda_events = extract_lda_events(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Urine Output Events v1 (additive, patient-level) ──
    urine_output_events = extract_urine_output_events(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Trauma Daily Plan by Day v1 (cross-day, patient-level) ──
    trauma_daily_plan_by_day = extract_trauma_daily_plan_by_day(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Structured Labs v1 (cross-day, protocol Slice C) ──
    structured_labs = extract_structured_labs(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Seizure Prophylaxis v1 (cross-day, TBI protocol data element) ──
    seizure_prophylaxis = extract_seizure_prophylaxis(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )

    # ── Assemble features dict (all feature modules live here) ──
    features: Dict[str, Any] = {
        "vitals_canonical_v1": {
            "days": vitals_canonical_days,
            "arrival_vitals": arrival_vitals,
            "arrival_vitals_hardened": arrival_vitals_hardened,
        },
        "dvt_prophylaxis_v1": dvt_prophylaxis,
        "gi_prophylaxis_v1": gi_prophylaxis,
        "base_deficit_monitoring_v1": base_deficit_monitoring,
        "inr_normalization_v1": inr_normalization,
        "fast_exam_v1": fast_exam,
        "etoh_uds_v1": etoh_uds,
        "impression_plan_drift_v1": impression_plan_drift,
        "category_activation_v1": category_activation,
        "mechanism_region_v1": mechanism_region,
        "radiology_findings_v1": radiology_findings,
        "sbirt_screening_v1": sbirt_screening,
        "note_sections_v1": note_sections,
        "incentive_spirometry_v1": incentive_spirometry,
        "anticoag_context_v1": anticoag_context,
        "pmh_social_allergies_v1": pmh_social_allergies,
        "adt_transfer_timeline_v1": adt_transfer_timeline,
        "procedure_operatives_v1": procedure_operatives,
        "anesthesia_case_metrics_v1": anesthesia_case_metrics,
        "spine_clearance_v1": spine_clearance,
        "note_index_events_v1": note_index_events,
        "patient_movement_v1": patient_movement,
        "lda_events_v1": lda_events,
        "urine_output_events_v1": urine_output_events,
        "trauma_daily_plan_by_day_v1": trauma_daily_plan_by_day,
        "structured_labs_v1": structured_labs,
        "seizure_prophylaxis_v1": seizure_prophylaxis,
        "vitals_qa": agg_vitals_qa,
    }

    # ── Shock trigger v1 (must run AFTER features dict is assembled
    #    because it consumes arrival_vitals + base_deficit_monitoring) ──
    shock_trigger = extract_shock_trigger(features)
    features["shock_trigger_v1"] = shock_trigger

    # ── Hemodynamic instability pattern v1 (consumes vitals_canonical_v1.days) ──
    hemodynamic_instability = extract_hemodynamic_instability_pattern(features)
    features["hemodynamic_instability_pattern_v1"] = hemodynamic_instability

    # ── Neuro trigger v1 (consumes per-day gcs_daily from feature_days) ──
    neuro_trigger = extract_neuro_trigger(
        feature_days,
        arrival_ts=arrival_ts_str,
    )
    features["neuro_trigger_v1"] = neuro_trigger

    # ── Consultant Events v1 (consumes note_index_events_v1 from features) ──
    consultant_events = extract_consultant_events(features, days_data)
    features["consultant_events_v1"] = consultant_events

    # ── Consultant Plan Items v1 (consumes consultant_events_v1 + note_index + timeline) ──
    consultant_plan_items = extract_consultant_plan_items(features, days_data)
    features["consultant_plan_items_v1"] = consultant_plan_items

    # ── Consultant Plan Actionables v1 (consumes consultant_plan_items_v1) ──
    consultant_plan_actionables = extract_consultant_plan_actionables(features)
    features["consultant_plan_actionables_v1"] = consultant_plan_actionables

    # ── Consultant Day Plans by Day v1 (consumes consultant_plan_items_v1 + events) ──
    consultant_day_plans = extract_consultant_day_plans_by_day(features)
    features["consultant_day_plans_by_day_v1"] = consultant_day_plans

    # ── Non-Trauma Team Day Plans v1 (cross-day, patient-level) ──
    non_trauma_day_plans = extract_non_trauma_team_day_plans(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )
    features["non_trauma_team_day_plans_v1"] = non_trauma_day_plans

    # ── Age extraction v1 (patient metadata from timeline text) ──
    age_extraction = extract_patient_age(days_data)
    features["age_extraction_v1"] = age_extraction

    # ── Transfusion / Blood Products v1 (cross-day, protocol Slice B) ──
    transfusion_blood_products = extract_transfusion_blood_products(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )
    features["transfusion_blood_products_v1"] = transfusion_blood_products

    # ── Ventilator Settings v1 (cross-day, vent slice foundation) ──
    ventilator_settings = extract_ventilator_settings(
        {"days": feature_days},  # pat_features subset
        days_data,                # full days_json for raw text access
    )
    features["ventilator_settings_v1"] = ventilator_settings

    # ── Demographics v1 (sex from evidence header) ──
    sex_raw = meta.get("sex")  # injected by main() from evidence header
    features["demographics_v1"] = {
        "sex": sex_raw if sex_raw in ("Male", "Female") else None,
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

    # ── Inject raw_header_lines from evidence JSON (for ADT extraction) ──
    # Derive evidence path: timeline/<slug>/patient_days_v1.json
    #                    →  evidence/<slug>/patient_evidence_v1.json
    slug = in_path.parent.name
    evidence_path = in_path.parent.parent.parent / "evidence" / slug / "patient_evidence_v1.json"
    if evidence_path.is_file():
        try:
            with open(evidence_path, encoding="utf-8", errors="replace") as ef:
                ev_data = json.load(ef)
            raw_header = (ev_data.get("raw") or {}).get("first_50_lines", [])
            if raw_header:
                days_data.setdefault("meta", {})["raw_header_lines"] = raw_header
            # Inject source_file path for raw-file features (note_index_events)
            ev_source = (ev_data.get("meta") or {}).get("source_file")
            if ev_source:
                days_data.setdefault("meta", {})["source_file"] = ev_source
            # Inject evidence-level trauma_category for category_activation_v1
            ev_trauma_cat = (ev_data.get("meta") or {}).get("trauma_category")
            if ev_trauma_cat:
                days_data.setdefault("meta", {})["evidence_trauma_category"] = ev_trauma_cat
            # Inject evidence-level sex for demographics_v1
            ev_sex = (ev_data.get("header") or {}).get("SEX")
            if ev_sex:
                days_data.setdefault("meta", {})["sex"] = ev_sex
        except (json.JSONDecodeError, OSError):
            pass  # fail-closed: no header lines available

    # ── Fallback: derive source_file from slug when evidence didn't provide it ──
    # Ensures raw-file features (LDA, note_index, urine_output) can still
    # extract data even if the evidence JSON was absent or incomplete.
    if not (days_data.get("meta") or {}).get("source_file"):
        project_root = in_path.parent.parent.parent.parent
        for candidate_name in (slug.replace("_", " "), slug):
            candidate = project_root / "data_raw" / f"{candidate_name}.txt"
            if candidate.is_file():
                days_data.setdefault("meta", {})["source_file"] = str(candidate)
                break

    features = build_patient_features(days_data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(features, indent=2, ensure_ascii=False) + "\n")

    print(f"OK \u2705 Wrote patient_features: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
