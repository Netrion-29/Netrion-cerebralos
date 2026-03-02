#!/usr/bin/env python3
"""
CerebralOS — PI Daily Notes Renderer (v5)

Feature-layer-driven clinical daily narrative.  Renders a single
unified report per patient with:

  - Patient Summary (once, top of report)
  - Established Injury Catalog (radiology findings)
  - Admission / Movement Summary (ADT + patient movement)
  - Procedure / OR / Anesthesia Summary
  - Consultant Summary (services + plan items)
  - Prophylaxis Status (DVT + GI)
  - Trigger / Hemodynamic Status
  - Per-day Clinical Status (vitals, GCS, labs, devices, BD, INR,
    ETOH/UDS, incentive spirometry, spine clearance, impression/plan,
    hemodynamic patterns, note sections)

Design:
  - Deterministic, fail-closed.
  - Missing data renders as "DATA NOT AVAILABLE" — never silently omitted.
  - Feature-first: all values sourced from patient_features_v1.json.
  - Additive: does NOT replace v3 or v4 outputs.

Input:  outputs/features/<PAT>/patient_features_v1.json
        outputs/timeline/<PAT>/patient_days_v1.json  (metadata only)
Output: outputs/reporting/<PAT>/TRAUMA_DAILY_NOTES_v5.txt
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constants ───────────────────────────────────────────────────────
_DNA = "DATA NOT AVAILABLE"

_DEVICE_LABELS = {
    "foley": "Foley catheter",
    "central_line": "Central line",
    "ett_vent": "ETT/Ventilator",
    "chest_tube": "Chest tube",
    "drain": "Drain",
}
_TRACKED_DEVICES = ("foley", "central_line", "ett_vent", "chest_tube", "drain")

# Deterministic truncation limit for consultant plan items per service
_MAX_PLAN_ITEMS_PER_SERVICE = 15

# Deterministic truncation for actionable items per category per service
_MAX_ACTIONABLE_ITEMS_PER_CATEGORY = 10

# Deterministic truncation for procedure events
_MAX_PROCEDURE_EVENTS = 30

# Deterministic cap for LDA device list
_MAX_LDA_DEVICES = 25

# Deterministic cap for urine output event samples
_MAX_URINE_SAMPLES = 8

# Max length for a single plan item display line
_MAX_PLAN_ITEM_LEN = 120

# ── B7 Narrative Integration Constants ───────────────────────────

# Timeline item types that carry clinically useful narrative text,
# ordered by clinical priority (higher priority first for display).
_NARRATIVE_SOURCE_TYPES = (
    "TRAUMA_HP",
    "PHYSICIAN_NOTE",
    "CONSULT_NOTE",
    "OP_NOTE",
    "PROCEDURE",
    "SIGNIFICANT_EVENT",
    "ANESTHESIA_CONSULT",
    "ANESTHESIA_PROCEDURE",
    "ED_NOTE",
    "CASE_MGMT",
    "NURSING_NOTE",
    "DISCHARGE",
    "DISCHARGE_SUMMARY",
)

# Item types to exclude from narrative (no clinical story value)
_NARRATIVE_SKIP_TYPES = frozenset({
    "LAB", "RADIOLOGY", "REMOVED", "MAR", "TRIAGE",
    "IS_FLOWSHEET", "PRE_PROCEDURE", "RT_ORDER", "ED_NURSING",
})

# Deterministic cap for narrative lines per day
_MAX_NARRATIVE_LINES_PER_DAY = 40

# Deterministic cap for narrative lines per single source note
_MAX_NARRATIVE_LINES_PER_NOTE = 25

# Max number of source notes rendered per day
_MAX_NARRATIVE_NOTES_PER_DAY = 6

# ── Formatting Helpers ──────────────────────────────────────────────

def _fv(val: Any, decimals: int = 1) -> str:
    """Format a numeric value for display, or return DNA."""
    if val is None:
        return _DNA
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _fb(val: Any) -> str:
    """Format a boolean-like value as Yes/No/DNA."""
    if val is None or val == _DNA:
        return _DNA
    if isinstance(val, bool):
        return "Yes" if val else "No"
    s = str(val).lower()
    if s in ("true", "yes"):
        return "Yes"
    if s in ("false", "no"):
        return "No"
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
        return f"{_fv(v)}{flag}"
    return str(entry)


def _indent(lines: List[str], prefix: str = "  ") -> List[str]:
    """Indent a list of lines."""
    return [prefix + ln for ln in lines]


# ════════════════════════════════════════════════════════════════════
# §1  PATIENT SUMMARY  (once, top of report)
# ════════════════════════════════════════════════════════════════════


def _gcs_summary_fallback(
    feature_days: Optional[Dict[str, Any]],
) -> tuple:
    """
    Fallback GCS lookup for the patient summary.

    When neuro_trigger_v1 returns DATA NOT AVAILABLE, scan gcs_daily on the
    arrival day (and the next day for cross-midnight) for any available GCS
    reading.  Checks ``arrival_gcs_value`` first, then ``best_gcs``.

    Returns (value, source_label) or (None, None).
    """
    if not feature_days:
        return None, None

    day_keys = sorted(k for k in feature_days if k != "__UNDATED__")
    if not day_keys:
        return None, None

    # Scan arrival day and next day
    scan_days = [day_keys[0]]
    if len(day_keys) > 1:
        scan_days.append(day_keys[1])

    for dk in scan_days:
        gcs = feature_days.get(dk, {}).get("gcs_daily", {})
        if not isinstance(gcs, dict):
            continue
        # Prefer arrival_gcs_value (formal priority GCS)
        agv = gcs.get("arrival_gcs_value")
        if agv is not None:
            src = gcs.get("arrival_gcs_source", "gcs_daily")
            return agv, src
        # Fall back to best_gcs on arrival day
        if dk == day_keys[0]:
            best = gcs.get("best_gcs")
            if isinstance(best, dict) and best.get("value") is not None:
                return best["value"], f"{best.get('source', 'gcs_daily')}:best_reading_fallback"

    return None, None

def _render_patient_summary(
    feats: Dict[str, Any],
    feature_days: Optional[Dict[str, Any]] = None,
) -> List[str]:
    out: List[str] = []
    out.append("PATIENT SUMMARY")
    out.append("-" * 60)

    # Age
    age = feats.get("age_extraction_v1", {})
    age_val = age.get("age_years")
    age_src = age.get("age_source_rule_id", _DNA)
    out.append(f"  Age:              {_fv(age_val, 0) if age_val is not None else _DNA} years  (source: {age_src})")

    # Category activation
    cat = feats.get("category_activation_v1", {})
    if cat.get("detected"):
        cat_label = cat.get("category", "I")
        cat_source = cat.get("source_rule_id", "")
        out.append(f"  Category:         {cat_label}")
    elif cat:
        out.append(f"  Category:         Not detected")
    else:
        out.append(f"  Category:         {_DNA}")

    # Mechanism / body regions
    mech = feats.get("mechanism_region_v1", {})
    mech_primary = mech.get("mechanism_primary", _DNA)
    mech_labels = mech.get("mechanism_labels", [])
    penetrating = mech.get("penetrating_mechanism")
    body_regions = mech.get("body_region_labels", [])
    out.append(f"  Mechanism:        {mech_primary}")
    if mech_labels:
        out.append(f"                    Labels: {', '.join(mech_labels)}")
    out.append(f"  Penetrating:      {_fb(penetrating)}")
    out.append(f"  Body Regions:     {', '.join(body_regions) if body_regions else _DNA}")

    # Arrival vitals
    vc = feats.get("vitals_canonical_v1", {})
    av = vc.get("arrival_vitals", {})
    if av and isinstance(av, dict) and av.get("status") != "no_arrival_vitals":
        sbp = _fv(av.get("sbp"))
        m = _fv(av.get("map"))
        hr = _fv(av.get("hr"))
        spo2 = _fv(av.get("spo2"))
        temp_f = _fv(av.get("temp_f"))
        rr = _fv(av.get("rr"))
        out.append(f"  Arrival Vitals:   SBP={sbp}  MAP={m}  HR={hr}  SpO2={spo2}  Temp={temp_f}°F  RR={rr}")
        selector = av.get("selector_rule", "")
        if selector:
            out.append(f"                    Selector: {selector}")
    else:
        out.append(f"  Arrival Vitals:   {_DNA}")

    # Arrival GCS (from neuro_trigger or first day gcs_daily)
    neuro = feats.get("neuro_trigger_v1", {})
    ti = neuro.get("trigger_inputs") or {}
    arrival_gcs_val = ti.get("arrival_gcs_value")
    arrival_gcs_src = ti.get("arrival_gcs_source", _DNA)
    if arrival_gcs_val is not None:
        intub = " (T)" if ti.get("arrival_gcs_intubated") else ""
        out.append(f"  Arrival GCS:      {arrival_gcs_val}{intub}  (source: {arrival_gcs_src})")
    else:
        # ── Fallback: read gcs_daily directly from feature_days ────
        # Covers cases where neuro_trigger returned DNA but gcs_daily
        # has readings from non-priority sources (CONSULT_NOTE, etc.)
        fallback_val, fallback_src = _gcs_summary_fallback(feature_days)
        if fallback_val is not None:
            out.append(f"  Arrival GCS:      {fallback_val}  (source: {fallback_src})")
        else:
            out.append(f"  Arrival GCS:      {_DNA}")

    # FAST exam
    fast = feats.get("fast_exam_v1", {})
    fast_result = fast.get("fast_result")
    fast_ts = fast.get("fast_ts")
    if fast.get("fast_performed"):
        ts_str = f" at {fast_ts}" if fast_ts else ""
        # When FAST was performed but result is null/None/DNA, say so clearly
        if fast_result and fast_result != _DNA and str(fast_result) != "None":
            out.append(f"  FAST:             {fast_result}{ts_str}")
        else:
            performed_str = f"Performed{ts_str} — result not documented"
            out.append(f"  FAST:             {performed_str}")
    elif fast:
        out.append(f"  FAST:             Not documented")
    else:
        out.append(f"  FAST:             {_DNA}")

    # ETOH / UDS
    eu = feats.get("etoh_uds_v1", {})
    etoh_val = eu.get("etoh_value")
    etoh_ts = eu.get("etoh_ts")
    if etoh_val is not None:
        out.append(f"  ETOH:             {etoh_val} at {etoh_ts or '?'}")
    else:
        out.append(f"  ETOH:             {_DNA}")
    uds_performed = eu.get("uds_performed")
    uds_panel = eu.get("uds_panel", {})
    if uds_performed:
        if isinstance(uds_panel, dict) and uds_panel:
            positives = [k for k, v in uds_panel.items() if v and str(v).lower() not in ("negative", "not detected", "none")]
            if positives:
                out.append(f"  UDS:              Positive: {', '.join(sorted(positives))}")
            else:
                out.append(f"  UDS:              All negative")
        else:
            out.append(f"  UDS:              Performed (panel details unavailable)")
    else:
        out.append(f"  UDS:              {_DNA}")

    # SBIRT
    sbirt = feats.get("sbirt_screening_v1", {})
    sbirt_present = sbirt.get("sbirt_screening_present")
    if sbirt_present:
        instruments = sbirt.get("instruments_detected", [])
        inst_str = ", ".join(instruments) if instruments else "instrument type not documented"
        out.append(f"  SBIRT Screening:  Present (instruments: {inst_str})")
        # AUDIT-C score
        audit_c = sbirt.get("audit_c", {})
        if audit_c and audit_c.get("completion_status") != "not_found":
            score = audit_c.get("explicit_score", _DNA)
            out.append(f"                    AUDIT-C: {score}")
    elif sbirt_present is False:
        out.append(f"  SBIRT Screening:  Not documented")
    else:
        out.append(f"  SBIRT Screening:  {_DNA}")

    # Anticoag / antiplatelet context
    ac = feats.get("anticoag_context_v1", {})
    ac_present = ac.get("anticoag_present")
    if ac_present and ac_present != _DNA:
        meds = ac.get("home_anticoagulants", [])
        med_names = [m.get("name", m.get("normalized_name", str(m))) if isinstance(m, dict) else str(m) for m in meds]
        med_str = ", ".join(med_names) if med_names else "present (unspecified)"
        out.append(f"  Anticoagulants:   {med_str}")
    else:
        out.append(f"  Anticoagulants:   {ac_present if ac_present else _DNA}")
    ap_present = ac.get("antiplatelet_present")
    if ap_present and ap_present != _DNA:
        meds = ac.get("home_antiplatelets", [])
        med_names = [m.get("name", m.get("normalized_name", str(m))) if isinstance(m, dict) else str(m) for m in meds]
        med_str = ", ".join(med_names) if med_names else "present (unspecified)"
        out.append(f"  Antiplatelets:    {med_str}")
    else:
        out.append(f"  Antiplatelets:    {ap_present if ap_present else _DNA}")

    # PMH / Allergies / Social highlights
    psa = feats.get("pmh_social_allergies_v1", {})
    pmh_items = psa.get("pmh_items", [])
    if pmh_items:
        labels = [p.get("label", "?") for p in pmh_items[:10]]
        out.append(f"  PMH:              {'; '.join(labels)}")
        if len(pmh_items) > 10:
            out.append(f"                    (+{len(pmh_items) - 10} more)")
    else:
        out.append(f"  PMH:              {_DNA}")

    allergy_status = psa.get("allergy_status", _DNA)
    allergies = psa.get("allergies", [])
    if allergies:
        allergy_strs = []
        for a in allergies[:8]:
            allergen = a.get("allergen", "?")
            reaction = a.get("reaction")
            if reaction:
                allergy_strs.append(f"{allergen} ({reaction})")
            else:
                allergy_strs.append(allergen)
        out.append(f"  Allergies:        {'; '.join(allergy_strs)}")
    else:
        out.append(f"  Allergies:        {allergy_status}")

    sh = psa.get("social_history", {})
    if sh and isinstance(sh, dict):
        parts = []
        for k in ("smoking_status", "alcohol_use", "drug_use"):
            v = sh.get(k)
            if v and v != _DNA:
                # Handle dict-valued fields (e.g., drug_use={'status': 'Never'})
                if isinstance(v, dict):
                    v = v.get("status", str(v))
                parts.append(f"{k.replace('_', ' ').title()}: {v}")
        if parts:
            out.append(f"  Social:           {'; '.join(parts)}")
        else:
            out.append(f"  Social:           {_DNA}")
    else:
        out.append(f"  Social:           {_DNA}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §2  ESTABLISHED INJURY CATALOG
# ════════════════════════════════════════════════════════════════════

def _render_injury_catalog(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    rad = feats.get("radiology_findings_v1", {})
    if not rad or not rad.get("findings_present"):
        out.append("ESTABLISHED INJURY CATALOG")
        out.append("-" * 60)
        out.append(f"  {_DNA}")
        out.append("")
        return out

    def _any_present(items: Any) -> bool:
        """Check if any item in a findings list/dict is marked present.

        Handles both scalar dicts (pneumothorax, hemothorax, etc.) and
        list-of-dicts (solid_organ_injuries, intracranial_hemorrhage, etc.).
        """
        if not items:
            return False
        # Scalar finding dict — e.g. {"present": True, "subtype": "tension"}
        if isinstance(items, dict):
            return bool(items.get("present"))
        # List of finding dicts
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("present"):
                    return True
        return False

    out.append("ESTABLISHED INJURY CATALOG")
    out.append("-" * 60)
    labels = rad.get("findings_labels", [])
    if labels:
        out.append(f"  Findings:         {', '.join(labels)}")

    # Intracranial
    ich = rad.get("intracranial_hemorrhage", [])
    if isinstance(ich, list):
        subtypes = [e.get("subtype", "unspecified") for e in ich if isinstance(e, dict) and e.get("present")]
        if subtypes:
            out.append(f"  Intracranial:     {', '.join(subtypes)}")

    # Pneumothorax
    if _any_present(rad.get("pneumothorax")):
        out.append(f"  Pneumothorax:     present")

    # Hemothorax
    if _any_present(rad.get("hemothorax")):
        out.append(f"  Hemothorax:       present")

    # Rib fracture
    if _any_present(rad.get("rib_fracture")):
        out.append(f"  Rib Fractures:    present")

    # Flail chest
    if _any_present(rad.get("flail_chest")):
        out.append(f"  Flail Chest:      present")

    # Solid organ
    if _any_present(rad.get("solid_organ_injuries")):
        out.append(f"  Solid Organ:      present")

    # Pelvic fracture
    if _any_present(rad.get("pelvic_fracture")):
        out.append(f"  Pelvic Fracture:  present")

    # Spinal fracture
    if _any_present(rad.get("spinal_fracture")):
        out.append(f"  Spinal Fracture:  present")

    # Extremity / long-bone fracture
    ext_fx = rad.get("extremity_fracture", [])
    if isinstance(ext_fx, list):
        bones = sorted({e.get("bone", "unspecified") for e in ext_fx
                        if isinstance(e, dict) and e.get("present")})
        if bones:
            out.append(f"  Extremity Fx:     {', '.join(bones)}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §3  ADMISSION / MOVEMENT SUMMARY
# ════════════════════════════════════════════════════════════════════

def _render_movement_summary(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    out.append("ADMISSION / MOVEMENT SUMMARY")
    out.append("-" * 60)

    # ADT transfer timeline
    adt = feats.get("adt_transfer_timeline_v1", {})
    adt_summary = adt.get("summary", {})
    adt_events = adt.get("events", [])

    if adt_summary:
        admit_ts = adt_summary.get("first_admission_ts", _DNA)
        discharge_ts = adt_summary.get("discharge_ts", _DNA)
        los = adt_summary.get("los_hours")
        transfers = adt_summary.get("transfer_count", 0)
        units = adt_summary.get("units_visited", [])

        out.append(f"  Admission:        {admit_ts}")
        out.append(f"  Discharge:        {discharge_ts if discharge_ts else 'Not yet discharged'}")
        if los is not None:
            out.append(f"  LOS:              {_fv(los, 1)} hours")
        out.append(f"  Transfers:        {transfers}")
        if units:
            out.append(f"  Units:            {' -> '.join(units)}")
    else:
        out.append(f"  ADT Timeline:     {_DNA}")

    # Patient movement (richer detail)
    pm = feats.get("patient_movement_v1", {})
    pm_summary = pm.get("summary", {})
    pm_entries = pm.get("entries", [])

    if pm_summary:
        loc_list = pm_summary.get("levels_of_care", [])
        svc_list = pm_summary.get("services_seen", [])
        if loc_list:
            out.append(f"  Levels of Care:   {' -> '.join(loc_list)}")
        if svc_list:
            out.append(f"  Services:         {', '.join(svc_list)}")

    # Chronological movement entries (compact)
    if pm_entries:
        out.append("")
        out.append("  Movement Chronology:")
        for entry in pm_entries:
            etype = entry.get("event_type", "?")
            unit = entry.get("unit", "?")
            loc = entry.get("level_of_care", "")
            svc = entry.get("service", "")
            dt_raw = entry.get("date_raw", "")
            tm_raw = entry.get("time_raw", "")
            ts_str = f"{dt_raw} {tm_raw}".strip()
            loc_str = f" ({loc})" if loc else ""
            svc_str = f" [{svc}]" if svc else ""
            out.append(f"    {ts_str:16s}  {etype:15s}  {unit}{loc_str}{svc_str}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §4  PROCEDURE / OR / ANESTHESIA SUMMARY
# ════════════════════════════════════════════════════════════════════

def _render_procedure_summary(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    proc = feats.get("procedure_operatives_v1", {})
    anes = feats.get("anesthesia_case_metrics_v1", {})

    proc_count = proc.get("procedure_event_count", 0)
    oper_count = proc.get("operative_event_count", 0)
    anes_count = proc.get("anesthesia_event_count", 0)
    categories = proc.get("categories_present", [])

    has_proc = proc_count > 0 or oper_count > 0 or anes_count > 0
    has_anes = (anes.get("case_count", 0) or 0) > 0

    if not has_proc and not has_anes:
        out.append("PROCEDURE / OR / ANESTHESIA SUMMARY")
        out.append("-" * 60)
        out.append(f"  No procedures, operatives, or anesthesia cases documented.")
        out.append("")
        return out

    out.append("PROCEDURE / OR / ANESTHESIA SUMMARY")
    out.append("-" * 60)
    out.append(f"  Procedure events:   {proc_count}")
    out.append(f"  Operative events:   {oper_count}")
    out.append(f"  Anesthesia events:  {anes_count}")
    if categories:
        out.append(f"  Categories:         {', '.join(categories)}")

    # Procedure/operative event list
    events = proc.get("events", [])
    if events:
        out.append("")
        out.append("  Procedure / Operative Events:")
        for i, e in enumerate(events[:_MAX_PROCEDURE_EVENTS]):
            cat = e.get("category", "?")
            label = e.get("label") or ""
            # Suppress literal "None" string from upstream extraction
            if not label or label == "None":
                label = "(description not documented)"
            ts = e.get("ts", "?")
            out.append(f"    {i+1:2d}. [{cat}] {label}  ({ts})")
        if len(events) > _MAX_PROCEDURE_EVENTS:
            out.append(f"    ... +{len(events) - _MAX_PROCEDURE_EVENTS} more (truncated)")

    # Anesthesia cases
    cases = anes.get("cases", [])
    if cases:
        out.append("")
        out.append("  Anesthesia Cases:")
        for i, c in enumerate(cases):
            anes_type = c.get("anesthesia_type", _DNA)
            asa = c.get("asa_class", _DNA)
            airway = c.get("airway_management", _DNA)
            ebl = c.get("ebl_ml")
            min_temp = c.get("min_temp_c")
            hypothermia = c.get("hypothermia_flag")
            out.append(f"    Case {i+1}:")
            out.append(f"      Anesthesia Type: {anes_type}")
            out.append(f"      ASA Class:       {asa}")
            out.append(f"      Airway:          {airway}")
            if ebl is not None:
                out.append(f"      EBL:             {ebl} mL")
            if min_temp is not None:
                hypo_str = f"  (hypothermia: {'Yes' if hypothermia else 'No'})" if hypothermia is not None else ""
                out.append(f"      Min Temp:        {_fv(min_temp)}°C{hypo_str}")

    # Overall hypothermia flag
    hypo_any = anes.get("or_hypothermia_any")
    if hypo_any is not None:
        out.append(f"  OR Hypothermia (any): {_fb(hypo_any)}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §5  LDA / DEVICE LIFECYCLE SUMMARY
# ════════════════════════════════════════════════════════════════════

def _render_lda_summary(feats: Dict[str, Any]) -> List[str]:
    """Render concise LDA device lifecycle summary from lda_events_v1.

    Shows device inventory by category, placement/removal lifecycle,
    and active device count.  Not a raw dump — this is a clinical
    summary of key devices placed/removed during the encounter.
    """
    out: List[str] = []
    lda = feats.get("lda_events_v1", {})
    if not lda:
        return out  # Omit section entirely if feature absent

    device_count = lda.get("lda_device_count", 0)
    active_count = lda.get("active_devices_count", 0)
    categories = lda.get("categories_present", [])
    devices = lda.get("devices", [])

    if device_count == 0 and not devices:
        return out  # No devices documented

    out.append("LDA / DEVICE LIFECYCLE SUMMARY")
    out.append("-" * 60)
    out.append(f"  Total devices:    {device_count}")
    out.append(f"  Active (at d/c):  {active_count}")
    out.append(f"  Categories:       {', '.join(sorted(categories)) if categories else _DNA}")

    # Category breakdown: count per category, sorted deterministically
    cat_counts: Dict[str, int] = {}
    for dev in devices:
        cat = dev.get("category", "Unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    if cat_counts:
        out.append("  Breakdown:")
        for cat_name in sorted(cat_counts.keys()):
            out.append(f"    {cat_name}: {cat_counts[cat_name]}")

    # Device inventory (concise, capped)
    if devices:
        out.append("")
        out.append("  Device Inventory:")
        for i, dev in enumerate(devices[:_MAX_LDA_DEVICES]):
            dtype = dev.get("device_type", "Unknown")
            placed = dev.get("placed_ts", _DNA)
            removed = dev.get("removed_ts")
            duration = dev.get("duration_text", "")
            status = "active" if removed is None else f"removed {removed}"
            dur_str = f"  ({duration})" if duration else ""
            # Suppress "placed DATA NOT AVAILABLE" clutter
            placed_str = f"placed {placed}" if placed and placed != _DNA else "placement time unknown"
            out.append(f"    - {dtype}: {placed_str}, {status}{dur_str}")
        if len(devices) > _MAX_LDA_DEVICES:
            out.append(f"    ... +{len(devices) - _MAX_LDA_DEVICES} more (truncated)")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §6  URINE OUTPUT SUMMARY
# ════════════════════════════════════════════════════════════════════

def _render_urine_output(feats: Dict[str, Any]) -> List[str]:
    """Render urine output summary from urine_output_events_v1.

    Shows total explicit volume, event count, source types, and
    subtype breakdown.  Does NOT render raw event details — only
    aggregate statistics and a small sample of events.
    """
    out: List[str] = []
    uo = feats.get("urine_output_events_v1", {})
    if not uo:
        return out  # Omit section entirely if feature absent

    event_count = uo.get("urine_output_event_count", 0)
    if event_count == 0:
        return out  # No urine output documented — omit silently

    total_ml = uo.get("total_urine_output_ml", 0)
    first_ts = uo.get("first_urine_output_ts", _DNA)
    last_ts = uo.get("last_urine_output_ts", _DNA)
    source_types = uo.get("source_types_present", [])
    events = uo.get("events", [])

    out.append("URINE OUTPUT SUMMARY")
    out.append("-" * 60)
    out.append(f"  Event count:      {event_count}")
    out.append(f"  Total output:     {total_ml} mL (explicit measurements only)")
    out.append(f"  First recorded:   {first_ts}")
    out.append(f"  Last recorded:    {last_ts}")
    out.append(f"  Source types:     {', '.join(sorted(source_types)) if source_types else _DNA}")

    # Subtype breakdown (Voided vs Catheter etc.)
    subtype_counts: Dict[str, int] = {}
    subtype_ml: Dict[str, int] = {}
    for ev in events:
        st = ev.get("source_subtype", "Unknown")
        subtype_counts[st] = subtype_counts.get(st, 0) + 1
        ml = ev.get("output_ml")
        if ml is not None:
            subtype_ml[st] = subtype_ml.get(st, 0) + ml
    if subtype_counts:
        out.append("  By source:")
        for st_name in sorted(subtype_counts.keys()):
            ml_str = f"  {subtype_ml.get(st_name, 0)} mL"
            out.append(f"    {st_name}: {subtype_counts[st_name]} events{ml_str}")

    # Small event sample for context (capped)
    measured_events = [e for e in events if e.get("output_ml") is not None]
    if measured_events:
        out.append("")
        out.append(f"  Recent measured outputs (up to {_MAX_URINE_SAMPLES}):")
        # Show last N measured events (most recent clinically relevant)
        sample = measured_events[-_MAX_URINE_SAMPLES:]
        for ev in sample:
            ts = ev.get("ts", "?")
            ml = ev.get("output_ml", "?")
            src = ev.get("source_subtype", "")
            color = ev.get("urine_color", "")
            parts = [f"{ml} mL"]
            if src:
                parts.append(f"[{src}]")
            if color:
                parts.append(f"color={color}")
            out.append(f"    {ts}: {' '.join(parts)}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §7  CONSULTANT SUMMARY
# ════════════════════════════════════════════════════════════════════

# Display order for actionable categories — deterministic, clinically
# meaningful: protocol-critical categories first, then supportive.
_CATEGORY_DISPLAY_ORDER = [
    "imaging",
    "procedure",
    "medication",
    "monitoring_labs",
    "brace_immobilization",
    "activity",
    "follow_up",
    "discharge",
    "recommendation",
]

# Human-readable labels for actionable categories
_CATEGORY_LABELS = {
    "imaging": "Imaging",
    "procedure": "Procedure",
    "medication": "Medication",
    "monitoring_labs": "Monitoring / Labs",
    "brace_immobilization": "Brace / Immobilization",
    "activity": "Activity / Mobility",
    "follow_up": "Follow-Up",
    "discharge": "Discharge",
    "recommendation": "Recommendation",
}


def _render_consultant_summary(feats: Dict[str, Any]) -> List[str]:
    """Render consultant summary using actionables when available,
    falling back to plan_items_v1 for older feature outputs."""
    out: List[str] = []
    ce = feats.get("consultant_events_v1", {})
    cpa = feats.get("consultant_plan_actionables_v1", {})
    cpi = feats.get("consultant_plan_items_v1", {})

    consultant_present = ce.get("consultant_present")
    services = ce.get("consultant_services", [])
    actionables = cpa.get("actionables", [])
    actionable_count = cpa.get("actionable_count", 0)

    # If no consultant data at all → short-circuit
    if not services and not actionables and not cpi.get("items"):
        out.append("CONSULTANT SUMMARY")
        out.append("-" * 60)
        if consultant_present == _DNA:
            out.append(f"  {_DNA}")
        else:
            out.append(f"  No consultant services documented.")
        out.append("")
        return out

    out.append("CONSULTANT SUMMARY")
    out.append("-" * 60)
    out.append(f"  Services consulted: {len(services)}")

    # Service list with timing (from consultant_events_v1 — always shown)
    for svc in services:
        sname = svc.get("service", "?")
        first = svc.get("first_ts", "?")
        ncount = svc.get("note_count", 0)
        authors = svc.get("authors", [])
        author_str = f"  by {', '.join(authors)}" if authors else ""
        out.append(f"    - {sname} (first: {first}, {ncount} note(s){author_str})")

    # ── Actionable-based rendering (preferred path) ──
    if actionable_count > 0:
        svc_counts = cpa.get("category_counts", {})
        svc_list = cpa.get("services_with_actionables", [])

        out.append("")
        out.append(f"  Actionable Plan Items: {actionable_count} across {len(svc_list)} service(s)")

        # Category summary line
        cat_parts = []
        for cat in _CATEGORY_DISPLAY_ORDER:
            cnt = svc_counts.get(cat, 0)
            if cnt > 0:
                label = _CATEGORY_LABELS.get(cat, cat)
                cat_parts.append(f"{label}: {cnt}")
        if cat_parts:
            out.append(f"  Categories: {', '.join(cat_parts)}")

        # Group actionables by service, then by category
        acts_by_svc: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for act in actionables:
            svc = act.get("service", "Unknown")
            cat = act.get("category", "recommendation")
            acts_by_svc.setdefault(svc, {}).setdefault(cat, []).append(act)

        for svc_name in sorted(acts_by_svc.keys()):
            svc_cats = acts_by_svc[svc_name]
            total = sum(len(v) for v in svc_cats.values())
            out.append("")
            out.append(f"    [{svc_name}] ({total} actionable(s)):")

            for cat in _CATEGORY_DISPLAY_ORDER:
                if cat not in svc_cats:
                    continue
                cat_items = svc_cats[cat]
                label = _CATEGORY_LABELS.get(cat, cat)
                out.append(f"      {label}:")
                for j, act in enumerate(cat_items[:_MAX_ACTIONABLE_ITEMS_PER_CATEGORY]):
                    atext = act.get("action_text", "?")
                    author = act.get("author_name", "")
                    if len(atext) > _MAX_PLAN_ITEM_LEN:
                        atext = atext[:_MAX_PLAN_ITEM_LEN - 3] + "..."
                    author_tag = f"  [{author}]" if author else ""
                    out.append(f"        - {atext}{author_tag}")
                if len(cat_items) > _MAX_ACTIONABLE_ITEMS_PER_CATEGORY:
                    out.append(f"        ... +{len(cat_items) - _MAX_ACTIONABLE_ITEMS_PER_CATEGORY} more (truncated)")

    # ── Fallback: plan_items_v1 rendering (no actionables available) ──
    elif cpi.get("items"):
        plan_items = cpi["items"]
        plan_count = cpi.get("item_count", len(plan_items))
        plan_services = cpi.get("services_with_plan_items", [])

        out.append("")
        out.append(f"  Plan Items: {plan_count} total across {len(plan_services)} service(s)")

        # Group by service, deterministic order
        items_by_svc: Dict[str, List[Dict[str, Any]]] = {}
        for item in plan_items:
            svc = item.get("service", "Unknown")
            items_by_svc.setdefault(svc, []).append(item)

        for svc_name in sorted(items_by_svc.keys()):
            svc_items = items_by_svc[svc_name]

            # Deduplicate by item_text within each service
            seen_texts: set = set()
            unique_items: List[Dict[str, Any]] = []
            for it in svc_items:
                txt = it.get("item_text", "")
                if txt not in seen_texts:
                    seen_texts.add(txt)
                    unique_items.append(it)

            dedup_note = ""
            if len(unique_items) < len(svc_items):
                dedup_note = f", {len(svc_items) - len(unique_items)} duplicate(s) suppressed"

            out.append(f"    [{svc_name}] ({len(unique_items)} items{dedup_note}):")
            for j, it in enumerate(unique_items[:_MAX_PLAN_ITEMS_PER_SERVICE]):
                itype = it.get("item_type", "?")
                itext = it.get("item_text", "?")
                author = it.get("author_name", "")
                if len(itext) > _MAX_PLAN_ITEM_LEN:
                    itext = itext[:_MAX_PLAN_ITEM_LEN - 3] + "..."
                author_tag = f"  [{author}]" if author else ""
                out.append(f"      - ({itype}) {itext}{author_tag}")
            if len(unique_items) > _MAX_PLAN_ITEMS_PER_SERVICE:
                out.append(f"      ... +{len(unique_items) - _MAX_PLAN_ITEMS_PER_SERVICE} more (truncated)")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §6  PROPHYLAXIS STATUS
# ════════════════════════════════════════════════════════════════════

def _render_prophylaxis(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    out.append("PROPHYLAXIS STATUS")
    out.append("-" * 60)

    # DVT
    dvt = feats.get("dvt_prophylaxis_v1", {})
    if dvt:
        excluded = dvt.get("excluded_reason")
        if excluded:
            out.append(f"  DVT:  Excluded ({excluded})")
        else:
            pharm_ts = dvt.get("pharm_first_ts", _DNA)
            mech_ts = dvt.get("mech_first_ts", _DNA)
            delay = dvt.get("delay_hours")
            delay_flag = dvt.get("delay_flag_24h")
            first_ts = dvt.get("first_ts", _DNA)
            out.append(f"  DVT:  First action at {first_ts}")
            if delay is not None:
                out.append(f"        Delay: {_fv(delay, 1)} hrs post-arrival")
            out.append(f"        Delay flag (>24h): {_fb(delay_flag)}")
            if pharm_ts and pharm_ts != _DNA:
                out.append(f"        Pharm first: {pharm_ts}")
            if mech_ts and mech_ts != _DNA:
                out.append(f"        Mech first:  {mech_ts}")
    else:
        out.append(f"  DVT:  {_DNA}")

    # GI
    gi = feats.get("gi_prophylaxis_v1", {})
    if gi:
        excluded = gi.get("excluded_reason")
        if excluded:
            out.append(f"  GI:   Excluded ({excluded})")
        else:
            pharm_ts = gi.get("pharm_first_ts", _DNA)
            delay = gi.get("delay_hours")
            delay_flag = gi.get("delay_flag_48h")
            out.append(f"  GI:   First pharm at {pharm_ts}")
            if delay is not None:
                out.append(f"        Delay: {_fv(delay, 1)} hrs post-arrival")
            out.append(f"        Delay flag (>48h): {_fb(delay_flag)}")
    else:
        out.append(f"  GI:   {_DNA}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §7  TRIGGER / HEMODYNAMIC STATUS
# ════════════════════════════════════════════════════════════════════

def _render_trigger_hemodynamic(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    out.append("TRIGGER / HEMODYNAMIC STATUS")
    out.append("-" * 60)

    # Shock trigger
    shock = feats.get("shock_trigger_v1", {})
    shock_triggered = shock.get("shock_triggered")
    if shock_triggered is not None:
        out.append(f"  Shock Triggered:  {_fb(shock_triggered)}")
        if shock_triggered:
            out.append(f"    Type:           {shock.get('shock_type', _DNA)}")
            out.append(f"    Rule:           {shock.get('trigger_rule_id', _DNA)}")
            tv = shock.get("trigger_vitals") or {}
            if tv:
                out.append(f"    Vitals:         SBP={tv.get('sbp', '?')}, BD={tv.get('bd', '?')}")
    else:
        out.append(f"  Shock Triggered:  {_DNA}")

    # Neuro trigger
    neuro = feats.get("neuro_trigger_v1", {})
    neuro_triggered = neuro.get("neuro_triggered")
    if neuro_triggered is not None:
        out.append(f"  Neuro Triggered:  {_fb(neuro_triggered)}")
        if neuro_triggered:
            out.append(f"    Rule:           {neuro.get('trigger_rule_id', _DNA)}")
            ti = neuro.get("trigger_inputs") or {}
            gcs_val = ti.get("arrival_gcs_value", _DNA)
            out.append(f"    GCS:            {gcs_val}")
    else:
        out.append(f"  Neuro Triggered:  {_DNA}")

    # Hemodynamic instability pattern
    hemo = feats.get("hemodynamic_instability_pattern_v1", {})
    pattern_present = hemo.get("pattern_present")
    if pattern_present is not None:
        out.append(f"  Hemodynamic Instability: {_fb(pattern_present)}")
        if pattern_present:
            for pname in ("hypotension_pattern", "map_low_pattern", "tachycardia_pattern"):
                p = hemo.get(pname) or {}
                if p.get("detected"):
                    cnt = p.get("reading_count", 0)
                    days_aff = p.get("days_affected", 0)
                    thresh = p.get("threshold", "?")
                    label = pname.replace("_pattern", "").replace("_", " ").title()
                    out.append(f"    {label}: {cnt} readings across {days_aff} day(s) (threshold: {thresh})")
    else:
        out.append(f"  Hemodynamic Instability: {_DNA}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §8  BASE DEFICIT / INR TREND
# ════════════════════════════════════════════════════════════════════

def _render_bd_inr_trend(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    out.append("BASE DEFICIT / INR MONITORING")
    out.append("-" * 60)

    # Base deficit
    bd = feats.get("base_deficit_monitoring_v1", {})
    if bd:
        initial_val = bd.get("initial_bd_value")
        initial_ts = bd.get("initial_bd_ts", _DNA)
        initial_src = bd.get("initial_bd_source", _DNA)
        compliant = bd.get("overall_compliant")
        series = bd.get("bd_series", [])

        if initial_val is not None:
            out.append(f"  Initial BD:       {_fv(initial_val)} ({initial_src}) at {initial_ts}")
        else:
            out.append(f"  Initial BD:       {_DNA}")

        if series and len(series) > 1:
            last = series[-1]
            last_val = last.get("value") if isinstance(last, dict) else last
            out.append(f"  Latest BD:        {_fv(last_val)}")
        out.append(f"  BD Compliant:     {_fb(compliant)}")

        trigger = bd.get("trigger_bd_gt4")
        if trigger is not None:
            out.append(f"  BD > 4 trigger:   {_fb(trigger)}")
    else:
        out.append(f"  Base Deficit:     {_DNA}")

    # INR
    inr = feats.get("inr_normalization_v1", {})
    if inr:
        initial_val = inr.get("initial_inr_value")
        initial_ts = inr.get("initial_inr_ts", _DNA)
        inr_count = inr.get("inr_count", 0)
        series = inr.get("inr_series", [])

        if initial_val is not None:
            out.append(f"  Initial INR:      {_fv(initial_val)} at {initial_ts}")
        else:
            out.append(f"  Initial INR:      {_DNA}")
        if series and len(series) > 1:
            last = series[-1]
            last_val = last.get("value") if isinstance(last, dict) else last
            out.append(f"  Latest INR:       {_fv(last_val)}")
        out.append(f"  INR readings:     {inr_count}")
    else:
        out.append(f"  INR:              {_DNA}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §9  IMPRESSION / PLAN DRIFT
# ════════════════════════════════════════════════════════════════════

def _render_impression_drift(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    ipd = feats.get("impression_plan_drift_v1", {})
    if not ipd:
        out.append("IMPRESSION / PLAN DRIFT")
        out.append("-" * 60)
        out.append(f"  {_DNA}")
        out.append("")
        return out

    drift_detected = ipd.get("drift_detected")
    days_compared = ipd.get("days_compared_count", 0)
    days_with = ipd.get("days_with_impression_count", 0)
    events = ipd.get("drift_events", [])

    out.append("IMPRESSION / PLAN DRIFT")
    out.append("-" * 60)
    out.append(f"  Drift detected:       {_fb(drift_detected)}")
    out.append(f"  Days with impression: {days_with}")
    out.append(f"  Days compared:        {days_compared}")
    out.append(f"  Drift events:         {len(events)}")
    if events:
        highest = max((e.get("drift_ratio", 0) for e in events), default=0)
        out.append(f"  Highest drift ratio:  {_fv(highest, 2)}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §10  SPINE CLEARANCE
# ════════════════════════════════════════════════════════════════════

def _render_spine_clearance(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    sc = feats.get("spine_clearance_v1", {})
    if not sc:
        return out  # Omit section entirely if not present

    status = sc.get("clearance_status", _DNA)
    collar = sc.get("collar_status", _DNA)
    method = sc.get("method", _DNA)
    ts = sc.get("clearance_ts")

    out.append("SPINE CLEARANCE")
    out.append("-" * 60)
    out.append(f"  Clearance Status: {status}")
    out.append(f"  Collar Status:    {collar}")
    if method and method != _DNA:
        out.append(f"  Method:           {method}")
    if ts:
        out.append(f"  Clearance Time:   {ts}")
    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §11  INCENTIVE SPIROMETRY SUMMARY
# ════════════════════════════════════════════════════════════════════

def _render_incentive_spirometry(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    isp = feats.get("incentive_spirometry_v1", {})
    if not isp or not isp.get("is_mentioned"):
        return out  # Omit if not mentioned

    out.append("INCENTIVE SPIROMETRY")
    out.append("-" * 60)
    out.append(f"  Mentioned:        {isp.get('is_mentioned', _DNA)}")
    out.append(f"  Values Present:   {isp.get('is_value_present', _DNA)}")
    out.append(f"  Mention Count:    {isp.get('mention_count', 0)}")
    out.append(f"  Measurement Count:{isp.get('measurement_count', 0)}")

    # Show measurements if present (suppress rows with no extracted values)
    measurements = isp.get("measurements", [])
    if measurements:
        rendered_count = 0
        measure_lines: List[str] = []
        suppressed = 0
        for m in measurements:
            ts = m.get("ts", "?")
            avg = m.get("avg_volume_cc")
            largest = m.get("largest_volume_cc")
            goal = m.get("goal_cc")
            effort = m.get("patient_effort")
            # Suppress literal "None" effort string from upstream
            if effort and str(effort) == "None":
                effort = None
            vol_str = f"avg={avg}cc" if avg else ""
            if largest:
                vol_str += f" max={largest}cc"
            if goal:
                vol_str += f" goal={goal}cc"
            if effort:
                vol_str += f" effort={effort}"
            if not vol_str.strip():
                suppressed += 1
                continue  # Skip rows with no extracted values
            if rendered_count < 10:
                measure_lines.append(f"    {ts}: {vol_str}")
            rendered_count += 1
        if measure_lines:
            out.append("  Measurements:")
            out.extend(measure_lines)
            if rendered_count > 10:
                out.append(f"    ... +{rendered_count - 10} more")
        if suppressed:
            out.append(f"  ({suppressed} mention-only entries with no measured values suppressed)")

    # Goals
    goals = isp.get("goals", [])
    if goals:
        for g in goals[:3]:
            out.append(f"  Goal:             {g.get('value', '?')}{g.get('unit', 'cc')}")

    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# §12  NOTE SECTIONS SUMMARY  (Impression / Plan excerpts)
# ════════════════════════════════════════════════════════════════════

# Display labels for note sections — ordered for rendering
_NOTE_SECTION_RENDER_ORDER: tuple = (
    ("hpi", "HPI"),
    ("primary_survey", "PRIMARY SURVEY"),
    ("secondary_survey", "SECONDARY SURVEY"),
    ("impression", "IMPRESSION"),
    ("plan", "PLAN"),
)


def _render_note_sections(feats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    ns = feats.get("note_sections_v1", {})
    if not ns or not ns.get("sections_present"):
        return out

    out.append("NOTE SECTIONS (Trauma H&P)")
    out.append("-" * 60)

    # Alert History — not yet extracted into note_sections_v1.
    # Deferred to a future extractor PR.  When added, render here.
    # (The raw Trauma H&P text contains "Alert History: ..." lines
    #  but they are not broken out as a separate extracted field.)

    for section_key, label in _NOTE_SECTION_RENDER_ORDER:
        sec = ns.get(section_key, {})
        if sec.get("present"):
            txt = sec.get("text", "")
            lines = txt.strip().split("\n") if txt else []
            out.append(f"  {label} ({len(lines)} lines):")
            # Show first 50 lines — clinical sections need higher cap
            _MAX_NOTE_SECTION_LINES = 50
            for ln in lines[:_MAX_NOTE_SECTION_LINES]:
                out.append(f"    {ln.rstrip()}")
            if len(lines) > _MAX_NOTE_SECTION_LINES:
                out.append(f"    ... (+{len(lines) - _MAX_NOTE_SECTION_LINES} more lines)")
            out.append("")

    return out


# ════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════
# PER-DAY: Trauma Daily Plan (from trauma progress notes)
# ════════════════════════════════════════════════════════════════════

def _render_trauma_daily_plan(feats: Dict[str, Any], day_iso: str) -> List[str]:
    """Render trauma daily plan notes for a specific day."""
    out: List[str] = []
    tdp = feats.get("trauma_daily_plan_by_day_v1", {})
    if not tdp:
        return out
    days = tdp.get("days", {})
    day_data = days.get(day_iso, {})
    notes = day_data.get("notes", [])
    if not notes:
        return out

    out.append("Trauma Daily Plan:")
    for note in notes:
        note_type = note.get("note_type", "Unknown")
        dt = note.get("dt", "?")
        author = note.get("author", "Unknown")
        # Format time portion
        time_str = dt.split("T")[1][:5] if "T" in str(dt) else str(dt)
        out.append(f"  [{note_type}] {time_str} — {author}")

        imp_lines = note.get("impression_lines", [])
        if imp_lines:
            out.append("    Impression:")
            for ln in imp_lines[:15]:
                out.append(f"      {ln.rstrip()}")
            if len(imp_lines) > 15:
                out.append(f"      ... (+{len(imp_lines) - 15} more lines)")

        plan_lines = note.get("plan_lines", [])
        if plan_lines:
            out.append("    Plan:")
            for ln in plan_lines[:40]:
                out.append(f"      {ln.rstrip()}")
            if len(plan_lines) > 40:
                out.append(f"      ... (+{len(plan_lines) - 40} more lines)")

        out.append("")

    return out


# ════════════════════════════════════════════════════════════════════
# PER-DAY: Consultant Day Plans (from consultant notes)
# ════════════════════════════════════════════════════════════════════

# Deterministic cap for consultant plan items per service in per-day view
_MAX_CONSULTANT_DAY_ITEMS_PER_SERVICE = 25


def _render_consultant_day_plans(feats: Dict[str, Any], day_iso: str) -> List[str]:
    """Render consultant plan items for a specific day, grouped by service."""
    out: List[str] = []
    cdp = feats.get("consultant_day_plans_by_day_v1", {})
    if not cdp:
        return out
    days = cdp.get("days", {})
    day_data = days.get(day_iso, {})
    services = day_data.get("services", {})
    if not services:
        return out

    out.append("Consultant Day Plans:")
    for svc_name in sorted(services.keys()):
        svc = services[svc_name]
        items = svc.get("items", [])
        if not items:
            continue
        authors = svc.get("authors", [])
        author_str = ", ".join(authors) if authors else "Unknown"
        # Use first item ts for time display
        first_ts = items[0].get("ts", "")
        time_str = first_ts.split("T")[1][:5] if "T" in str(first_ts) else str(first_ts)
        out.append(f"  [{svc_name}] {time_str} — {author_str} ({len(items)} items)")
        cap = _MAX_CONSULTANT_DAY_ITEMS_PER_SERVICE
        for it in items[:cap]:
            item_type = it.get("item_type", "")
            item_text = it.get("item_text", "")
            out.append(f"    - ({item_type}) {item_text}")
        if len(items) > cap:
            out.append(f"    ... (+{len(items) - cap} more items)")
    out.append("")
    return out


# ════════════════════════════════════════════════════════════════════
# PER-DAY: Non-Trauma Team Day Plans
# ════════════════════════════════════════════════════════════════════

# Deterministic cap for brief lines per note in the per-day view
_MAX_NON_TRAUMA_BRIEF_LINES = 8

# Deterministic cap for notes per service in the per-day view
_MAX_NON_TRAUMA_NOTES_PER_SERVICE = 6


def _render_non_trauma_day_plans(feats: Dict[str, Any], day_iso: str) -> List[str]:
    """Render non-trauma team day plan/update entries for a specific day."""
    out: List[str] = []
    ntp = feats.get("non_trauma_team_day_plans_v1", {})
    if not ntp:
        return out
    days = ntp.get("days", {})
    day_data = days.get(day_iso, {})
    services = day_data.get("services", {})
    if not services:
        return out

    out.append("Non-Trauma Day Plans:")
    for svc_name in sorted(services.keys()):
        svc = services[svc_name]
        notes = svc.get("notes", [])
        if not notes:
            continue
        cap = _MAX_NON_TRAUMA_NOTES_PER_SERVICE
        for note in notes[:cap]:
            dt = note.get("dt", "?")
            author = note.get("author", "Unknown")
            time_str = dt.split("T")[1][:5] if "T" in str(dt) else str(dt)
            out.append(f"  [{svc_name}] {time_str} — {author}")
            brief_lines = note.get("brief_lines", [])
            line_cap = _MAX_NON_TRAUMA_BRIEF_LINES
            for ln in brief_lines[:line_cap]:
                out.append(f"    {ln.rstrip()}")
            if len(brief_lines) > line_cap:
                out.append(f"    ... (+{len(brief_lines) - line_cap} more lines)")
            out.append("")
        if len(notes) > cap:
            out.append(f"  ... (+{len(notes) - cap} more {svc_name} notes)")

    return out


# ════════════════════════════════════════════════════════════════════
# PER-DAY: Vitals Trending  (reused from v4 logic)
# ════════════════════════════════════════════════════════════════════

def _render_vitals_trending(vitals: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not vitals or not isinstance(vitals, dict):
        lines.append(f"  {_DNA}")
        return lines

    def _metric_line(label: str, metric_key: str) -> str:
        m = vitals.get(metric_key, {})
        if not m or not isinstance(m, dict):
            return f"  {label}: {_DNA}"
        mn = m.get("min")
        mx = m.get("max")
        if mn is None and mx is None:
            return f"  {label}: {_DNA}"
        return f"  {label}: {_fv(mn)} – {_fv(mx)}"

    lines.append(_metric_line("Temp (°F)", "temp_f"))
    lines.append(_metric_line("HR", "hr"))
    lines.append(_metric_line("SBP", "sbp"))

    map_data = vitals.get("map", {})
    if map_data and isinstance(map_data, dict) and map_data.get("min") is not None:
        lines.append(f"  Lowest MAP: {_fv(map_data['min'])}")
    else:
        lines.append(f"  Lowest MAP: {_DNA}")

    spo2_data = vitals.get("spo2", {})
    if spo2_data and isinstance(spo2_data, dict) and spo2_data.get("min") is not None:
        lines.append(f"  Lowest SpO2: {_fv(spo2_data['min'])}")
    else:
        lines.append(f"  Lowest SpO2: {_DNA}")

    lines.append(_metric_line("RR", "rr"))
    return lines


def _render_gcs(gcs: Dict[str, Any], is_arrival_day: bool = True) -> List[str]:
    lines: List[str] = []
    if not gcs or not isinstance(gcs, dict):
        lines.append(f"  {_DNA}")
        return lines

    arrival = gcs.get("arrival_gcs", _DNA)
    # Only show Arrival GCS on arrival day or when a value is actually present
    has_arrival_value = (arrival is not None and arrival != _DNA
                         and not (isinstance(arrival, dict) and arrival.get("value") in (None, _DNA)))
    if has_arrival_value:
        if isinstance(arrival, dict):
            val = arrival.get("value", _DNA)
            src = arrival.get("source", "")
            dt = arrival.get("dt", "")
            intub = " (T)" if arrival.get("intubated") else ""
            lines.append(f"  Arrival GCS: {val}{intub}  [{src}] {dt}")
        else:
            lines.append(f"  Arrival GCS: {arrival}")
    elif is_arrival_day:
        lines.append(f"  Arrival GCS: {_DNA}")
    # else: non-arrival day with no value → suppress field entirely

    best = gcs.get("best_gcs", _DNA)
    if best == _DNA or best is None:
        lines.append(f"  Best GCS: {_DNA}")
    elif isinstance(best, dict):
        val = best.get("value", _DNA)
        intub = " (T)" if best.get("intubated") else ""
        lines.append(f"  Best GCS: {val}{intub}")
    else:
        lines.append(f"  Best GCS: {best}")

    worst = gcs.get("worst_gcs", _DNA)
    if worst == _DNA or worst is None:
        lines.append(f"  Worst GCS: {_DNA}")
    elif isinstance(worst, dict):
        val = worst.get("value", _DNA)
        intub = " (T)" if worst.get("intubated") else ""
        lines.append(f"  Worst GCS: {val}{intub}")
    else:
        lines.append(f"  Worst GCS: {worst}")

    return lines


def _render_labs_panel(panel: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not panel or not isinstance(panel, dict):
        lines.append(f"  {_DNA}")
        return lines

    cbc = panel.get("cbc", {})
    if isinstance(cbc, dict):
        parts = [f"{k}: {_fmt_lab_entry(cbc.get(k, _DNA))}" for k in ("WBC", "Hgb", "Hct", "Plt")]
        lines.append(f"  CBC: {' | '.join(parts)}")
    else:
        lines.append(f"  CBC: {_DNA}")

    bmp = panel.get("bmp", {})
    if isinstance(bmp, dict):
        parts = [f"{k}: {_fmt_lab_entry(bmp.get(k, _DNA))}" for k in ("Na", "K", "Cl", "CO2", "BUN", "Cr", "Glucose")]
        lines.append(f"  BMP: {' | '.join(parts)}")
    else:
        lines.append(f"  BMP: {_DNA}")

    coags = panel.get("coags", {})
    if isinstance(coags, dict):
        parts = [f"{k}: {_fmt_lab_entry(coags.get(k, _DNA))}" for k in ("INR", "PT", "PTT")]
        lines.append(f"  Coags: {' | '.join(parts)}")
    else:
        lines.append(f"  Coags: {_DNA}")

    lines.append(f"  Lactate: {_fmt_lab_entry(panel.get('lactate', _DNA))}")
    lines.append(f"  Base Deficit: {_fmt_lab_entry(panel.get('base_deficit', _DNA))}")
    return lines


def _render_device_day_counts(counts: Dict[str, Any]) -> List[str]:
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


# ════════════════════════════════════════════════════════════════════
# B7 NARRATIVE: Noise Filtering + Per-Day Narrative Extraction
# ════════════════════════════════════════════════════════════════════

# Compiled noise-filter patterns (deterministic, order-independent).
# Each is a (compiled_regex, description) tuple.  A line matching ANY
# pattern is suppressed from the rendered narrative.
_NOISE_PATTERNS: List[tuple] = [
    # ── ROS / review-of-systems negative bullet blocks ──
    (re.compile(
        r"^\s*[-•]?\s*denies\b",
        re.IGNORECASE,
    ), "ROS denies line"),
    (re.compile(
        r"^\s*[-•]\s*(no |negative for |without |not present|normal |unremarkable)",
        re.IGNORECASE,
    ), "ROS negative bullet"),
    (re.compile(
        r"^\s*(review of systems|ros)\s*[:.]?\s*$",
        re.IGNORECASE,
    ), "ROS header"),

    # ── MAR / medication administration boilerplate ──
    (re.compile(
        r"hold.{0,20}(sbp|systolic|bp|hr|pulse|rate)\s*[<>≤≥]",
        re.IGNORECASE,
    ), "MAR hold threshold"),
    (re.compile(
        r"^\s*(medication|med)\s+(administration|admin)\s+(record|report)",
        re.IGNORECASE,
    ), "MAR header"),

    # ── Nursing device/line maintenance boilerplate ──
    (re.compile(
        r"^\s*[-•]\s*(site clean|dressing (clean|dry|intact)|patent|flushed|no redness|no swelling|no drainage)\b",
        re.IGNORECASE,
    ), "nursing line maintenance"),
    (re.compile(
        r"^\s*[-•]\s*(IV site|PIV|central line|catheter)\s+(clean|patent|intact|flushed|without)",
        re.IGNORECASE,
    ), "device status boilerplate"),

    # ── Checklist / template / instructional boilerplate ──
    (re.compile(
        r"mychart.{0,30}(progress notes|visible to patients|will allow)",
        re.IGNORECASE,
    ), "MyChart disclaimer"),
    (re.compile(
        r"disclaimer.{0,60}(dictated|voice recognition|technology software)",
        re.IGNORECASE,
    ), "dictation disclaimer"),
    (re.compile(
        r"^\s*revision\s*history\s*toggle|^\s*routing\s*history\s*toggle",
        re.IGNORECASE,
    ), "Epic UI artifact"),
    (re.compile(
        r"^\s*(cosigned by|authenticated by)\s*:.{0,60}$",
        re.IGNORECASE,
    ), "signature line"),
    (re.compile(
        r"^\s*(signed|cosign needed|untitled image)\s*$",
        re.IGNORECASE,
    ), "signed/template marker"),

    # ── Vitals block lines (already rendered in structured vitals) ──
    (re.compile(
        r"^\s*(visit vitals|vitals?:?)\s*$",
        re.IGNORECASE,
    ), "vitals header"),
    (re.compile(
        r"^\s*(BP|Pulse|Temp|Resp|SpO2|Ht|Wt|BMI|BSA|Smoking Status)\s*$",
        re.IGNORECASE,
    ), "vitals label-only line"),
    (re.compile(
        r"^\s*\d+(\.\d+)?\s*(bpm|°[FC]|%|kg|lb|m²|kg/m²)\s*$",
        re.IGNORECASE,
    ), "vitals value-only line"),
    (re.compile(
        r"^\s*\d{1,3}/\d{1,3}\s*$",
    ), "BP value-only line"),
    (re.compile(
        r"^\s*\d+' \d+\"\s*$",
    ), "height value-only line"),
    (re.compile(
        r"^\s*comment:.*$",
        re.IGNORECASE,
    ), "vitals comment"),

    # ── Empty / whitespace-only lines ──
    (re.compile(
        r"^\s*$",
    ), "blank line"),

    # ── Header bracket lines already captured by type tag ──
    (re.compile(
        r"^\s*\[(PHYSICIAN_NOTE|CONSULT_NOTE|NURSING_NOTE|ED_NOTE|OP_NOTE|TRAUMA_HP|PROCEDURE|CASE_MGMT|DISCHARGE|DISCHARGE_SUMMARY|SIGNIFICANT_EVENT|ANESTHESIA_CONSULT|ANESTHESIA_PROCEDURE)\]\s",
        re.IGNORECASE,
    ), "source type header"),

    # ── Radiology result headers (fully covered in injury catalog) ──
    (re.compile(
        r"^\s*(no results found\.?|radiology:?)\s*$",
        re.IGNORECASE,
    ), "radiology stub"),

    # ── Solo vitals values (structured vitals already in Vitals Trending) ──
    (re.compile(
        r"^\s*\d{1,4}(\.\d+)?\s*$",
    ), "solo numeric value"),
    (re.compile(
        r"^\s*\d+\.?\d*\s*°[FC]",
        re.IGNORECASE,
    ), "temperature reading"),
    (re.compile(
        r"^\s*\(!\)\s*\d+",
    ), "EHR abnormal flag value"),
    (re.compile(
        r"^\s*(Never|Former|Current|Not Asked|Every Day|Some Days)\s*$",
        re.IGNORECASE,
    ), "smoking status value"),

    # ── Attribution / boilerplate lines ──
    (re.compile(
        r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$",
    ), "standalone date"),
    (re.compile(
        r"^\s*[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+,?\s*(?:MD|DO|NP|PA-C|PA|RN|BSN|APRN|DPM|DPT|OT|PT|SLP|RD|PharmD|RPh|BCC)\s*$",
    ), "author name line"),

    # ── Epic UI chrome ──
    (re.compile(
        r"^\s*expand\s+all\s+collapse\s+all\s*$",
        re.IGNORECASE,
    ), "Epic expand/collapse toggle"),

    # ── Allergy block noise (already in patient summary) ──
    (re.compile(
        r"^\s*allerg(ies|en|y)\s*:?\s*$",
        re.IGNORECASE,
    ), "allergy header"),
    (re.compile(
        r"^\s*allergen\s+reactions?\s*$",
        re.IGNORECASE,
    ), "allergen table header"),

    # ── PMH / medication list boilerplate (duplicated from patient summary) ──
    (re.compile(
        r"^\s*past\s+medical\s+history\s*:?\s*$",
        re.IGNORECASE,
    ), "PMH header"),
    (re.compile(
        r"^\s*diagnosis\s+date\s*$",
        re.IGNORECASE,
    ), "PMH table header"),
    (re.compile(
        r"^\s*(medications?\s+ordered\s+prior|current\s+outpatient\s+medications?|no\s+current\s+facility.administered\s+medications?)",
        re.IGNORECASE,
    ), "medication list boilerplate"),

    # ── Social history template lines ──
    (re.compile(
        r"^\s*(marital\s+status|education|number\s+of\s+children|years\s+of\s+education|living\s+situation|sexual\s+orientation|gender\s+identity)\s*[:.]?\s*(\S.*)?$",
        re.IGNORECASE,
    ), "social history template field"),
    (re.compile(
        r"^\s*social\s+history\s*:?\s*$",
        re.IGNORECASE,
    ), "social history header"),
    (re.compile(
        r"^\s*(tobacco|alcohol|drug)\s+use\s*:?\s*$",
        re.IGNORECASE,
    ), "substance use label"),

    # ── Demographics in consult notes ──
    (re.compile(
        r"^\s*(patient\s+name|mrn|dob)\s*:?\s*\S",
        re.IGNORECASE,
    ), "consult demographics line"),
    (re.compile(
        r"^\s*source\s+of\s+history\s*:",
        re.IGNORECASE,
    ), "source of history line"),

    # ── Phone numbers / contact info ──
    (re.compile(
        r"^\s*\d{3}[-.\s]\d{3}[-.\s]\d{4}\s*$",
    ), "phone number"),
    (re.compile(
        r"^\s*(or\s+)?secure\s+chat\s*$",
        re.IGNORECASE,
    ), "secure chat line"),

    # ── Consult order boilerplate ──
    (re.compile(
        r"^\s*(inpatient\s+consult\s+to|consult\s+orders?)\s*",
        re.IGNORECASE,
    ), "consult order boilerplate"),
]


def _is_noise_line(line: str) -> bool:
    """Return True if *line* matches any known noise pattern."""
    for pat, _desc in _NOISE_PATTERNS:
        if pat.search(line):
            return True
    return False


def _filter_narrative_text(raw_text: str) -> List[str]:
    """Filter a raw note's text, returning only clinically meaningful lines.

    Deterministic, order-preserving.  Noise patterns are suppressed;
    remaining lines are stripped of trailing whitespace and returned.
    Consecutive blank results after filtering are collapsed.
    """
    lines = raw_text.split("\n")
    kept: List[str] = []
    prev_blank = True  # Start True to suppress leading blanks
    for ln in lines:
        if _is_noise_line(ln):
            continue
        stripped = ln.rstrip()
        if not stripped:
            if prev_blank:
                continue  # collapse consecutive blanks
            prev_blank = True
            # Don't add blank — we'll let the next non-blank reset
            continue
        prev_blank = False
        kept.append(stripped)
    return kept


def _extract_day_narratives(
    day_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract narrative-worthy items from a day's timeline items.

    Returns a list of dicts with keys: type, dt, filtered_lines.
    Ordered by dt (timestamp), deterministic.
    """
    candidates: List[Dict[str, Any]] = []
    for item in day_items:
        itype = item.get("type", "")
        if itype in _NARRATIVE_SKIP_TYPES:
            continue
        if itype not in _NARRATIVE_SOURCE_TYPES:
            continue
        raw_text = (item.get("payload") or {}).get("text", "")
        if not raw_text.strip():
            continue
        filtered = _filter_narrative_text(raw_text)
        if not filtered:
            continue
        dt = item.get("dt", "")
        candidates.append({
            "type": itype,
            "dt": dt,
            "filtered_lines": filtered,
        })

    # Sort by timestamp deterministically; ties broken by type priority
    type_order = {t: i for i, t in enumerate(_NARRATIVE_SOURCE_TYPES)}
    candidates.sort(key=lambda c: (c["dt"] or "", type_order.get(c["type"], 99)))
    return candidates


def _render_day_narrative(
    day_items: List[Dict[str, Any]],
) -> List[str]:
    """Render per-day clinical narrative from timeline items.

    Returns lines ready to append to the per-day block.
    Deterministic, capped, noise-filtered.
    """
    narratives = _extract_day_narratives(day_items)
    if not narratives:
        return []

    out: List[str] = []
    out.append("Clinical Narrative:")

    total_lines = 0
    notes_rendered = 0

    for narr in narratives:
        if notes_rendered >= _MAX_NARRATIVE_NOTES_PER_DAY:
            remaining = len(narratives) - notes_rendered
            out.append(f"  ... +{remaining} additional note(s) suppressed (cap)")
            break
        if total_lines >= _MAX_NARRATIVE_LINES_PER_DAY:
            out.append(f"  ... (narrative cap reached: {_MAX_NARRATIVE_LINES_PER_DAY} lines)")
            break

        ntype = narr["type"]
        dt = narr["dt"] or "?"
        lines = narr["filtered_lines"]

        # Per-note cap
        truncated = False
        if len(lines) > _MAX_NARRATIVE_LINES_PER_NOTE:
            lines = lines[:_MAX_NARRATIVE_LINES_PER_NOTE]
            truncated = True

        # Day-level cap
        remaining_budget = _MAX_NARRATIVE_LINES_PER_DAY - total_lines
        if len(lines) > remaining_budget:
            lines = lines[:remaining_budget]
            truncated = True

        out.append(f"  [{ntype}] {dt}:")
        for ln in lines:
            out.append(f"    {ln}")
            total_lines += 1
        if truncated:
            out.append(f"    ... (truncated)")
        notes_rendered += 1

    return out


# ════════════════════════════════════════════════════════════════════
# MAIN RENDER FUNCTION
# ════════════════════════════════════════════════════════════════════

def render_v5(
    features_data: Dict[str, Any],
    days_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Render Daily Notes v5 text.

    Parameters
    ----------
    features_data : loaded patient_features_v1.json
    days_data     : loaded patient_days_v1.json (optional, for metadata)
    """
    patient_id = features_data.get("patient_id", _DNA)
    feats = features_data.get("features", {})
    feature_days = features_data.get("days", {})
    meta = {}
    timeline_days: Dict[str, Any] = {}
    if days_data:
        meta = days_data.get("meta", {})
        timeline_days = days_data.get("days", {})

    # Prefer patient_name from timeline meta over features patient_id
    display_id = meta.get("patient_name") or meta.get("patient_id") or patient_id

    day_keys = sorted(k for k in feature_days.keys() if k != "__UNDATED__")

    out: List[str] = []

    # ── Report Header ──
    out.append("PI DAILY NOTES (v5)")
    out.append("=" * 60)
    out.append(f"Patient ID: {display_id}")
    out.append(f"Arrival:    {meta.get('arrival_datetime', _DNA)}")
    out.append(f"Timezone:   {meta.get('timezone', _DNA)}")
    out.append(f"Days:       {len(day_keys)}")
    out.append(f"Build:      deterministic extraction — no inference")
    out.append("=" * 60)
    out.append("")

    # ── Patient-level Sections ──
    out.extend(_render_patient_summary(feats, feature_days=feature_days))
    out.extend(_render_injury_catalog(feats))
    out.extend(_render_movement_summary(feats))
    out.extend(_render_procedure_summary(feats))
    out.extend(_render_lda_summary(feats))
    out.extend(_render_urine_output(feats))
    out.extend(_render_consultant_summary(feats))
    out.extend(_render_prophylaxis(feats))
    out.extend(_render_trigger_hemodynamic(feats))
    out.extend(_render_bd_inr_trend(feats))
    out.extend(_render_impression_drift(feats))
    out.extend(_render_spine_clearance(feats))
    out.extend(_render_incentive_spirometry(feats))
    out.extend(_render_note_sections(feats))

    # ── Per-Day Clinical Status ──
    out.append("=" * 60)
    out.append("PER-DAY CLINICAL STATUS")
    out.append("=" * 60)
    out.append("")

    prev_date: Optional[date] = None
    for dk in day_keys:
        # Evidence gap detection
        try:
            cur_date = date.fromisoformat(dk)
        except ValueError:
            cur_date = None
        if prev_date is not None and cur_date is not None:
            gap_days = (cur_date - prev_date).days
            if gap_days > 1:
                out.append(f"--- EVIDENCE GAP: {gap_days - 1} day(s) with no dated documentation ---")
                out.append("")
        if cur_date is not None:
            prev_date = cur_date

        day = feature_days.get(dk, {})
        out.append(f"===== {dk} =====")
        out.append("")

        # Vitals Trending
        out.append("Vitals Trending:")
        out.extend(_render_vitals_trending(day.get("vitals", {})))
        out.append("")

        # GCS — suppress Arrival GCS field on non-arrival days
        out.append("GCS:")
        is_arrival_day = (dk == day_keys[0]) if day_keys else True
        out.extend(_render_gcs(day.get("gcs_daily", {}), is_arrival_day=is_arrival_day))
        out.append("")

        # Labs Panel Lite
        out.append("Labs Panel Lite:")
        out.extend(_render_labs_panel(day.get("labs_panel_daily", {})))
        out.append("")

        # Device Day Counts
        out.append("Device Day Counts:")
        out.extend(_render_device_day_counts(day.get("device_day_counts", {})))
        out.append("")

        # Trauma Daily Plan (from trauma progress notes)
        tdp_lines = _render_trauma_daily_plan(feats, dk)
        if tdp_lines:
            out.extend(tdp_lines)
            out.append("")

        # Consultant Day Plans (from consultant notes)
        cdp_lines = _render_consultant_day_plans(feats, dk)
        if cdp_lines:
            out.extend(cdp_lines)
            out.append("")

        # Non-Trauma Team Day Plans (hospitalist, critical care, etc.)
        ntp_lines = _render_non_trauma_day_plans(feats, dk)
        if ntp_lines:
            out.extend(ntp_lines)
            out.append("")

        # B7 Clinical Narrative (from timeline items, noise-filtered)
        tl_day = timeline_days.get(dk, {})
        tl_items = tl_day.get("items", [])
        narrative_lines = _render_day_narrative(tl_items)
        if narrative_lines:
            out.extend(narrative_lines)
            out.append("")

    # ── Undated ──
    if "__UNDATED__" in feature_days:
        out.append("===== __UNDATED__ =====")
        out.append("(undated items — see v3 for detail)")
        out.append("")

    # ── Footer ──
    out.append("=" * 60)
    out.append("END OF PI DAILY NOTES (v5)")
    out.append("Generated by CerebralOS — deterministic, fail-closed")
    out.append("=" * 60)

    return "\n".join(out).rstrip() + "\n"


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render PI Daily Notes v5 from patient_features_v1.json",
    )
    ap.add_argument("--features", dest="features_path", required=True,
                    help="Path to patient_features_v1.json")
    ap.add_argument("--days", dest="days_path", required=False, default=None,
                    help="Path to patient_days_v1.json (optional, for metadata)")
    ap.add_argument("--out", dest="out_path", required=True,
                    help="Path for output TRAUMA_DAILY_NOTES_v5.txt")
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

    text = render_v5(features_data, days_data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"OK \u2705 Wrote daily notes v5: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
