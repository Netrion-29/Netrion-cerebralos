#!/usr/bin/env python3
"""
CerebralOS — Calendar Daily Notes Renderer (v1)

Comprehensive day-by-day calendar notes designed for thorough admission
review of long-stay patients.  Primary audience: PI RN / trauma reviewers
needing the full clinical picture for each calendar day.

Key differences from v3 / v5
─────────────────────────────
* No caps on physician-note length — every TRAUMA_HP, PHYSICIAN_NOTE,
  and CONSULT_NOTE is rendered in full (noise-filtered but un-truncated).
* Each note block is labelled [NEW] (content not seen on any prior day)
  or [CARRIED] (full block hash identical to a prior day's block), so
  reviewers can instantly see what actually changed.
* All note types relevant to clinical care are surfaced: physician notes,
  consultant notes, procedure / anesthesia notes, ED notes, case
  management, discharge notes, and nursing-signal lines.
* Labs, imaging impressions, and nursing-protocol signals are each
  rendered in dedicated per-day sections with no line cap.
* Optional integration with patient_features_v1.json supplies structured
  vitals, GCS, and labs panels when available.

Inputs
──────
  --days     outputs/timeline/<PAT>/patient_days_v1.json        (required)
  --features outputs/features/<PAT>/patient_features_v1.json   (optional)
  --out      outputs/reporting/<PAT>/CALENDAR_DAILY_NOTES_v1.txt (required)

Output
──────
  CALENDAR_DAILY_NOTES_v1.txt

Design guarantees
─────────────────
* Deterministic — identical input → identical output.
* Fail-closed — missing data rendered as "DATA NOT AVAILABLE", never
  silently omitted.
* No clinical inference — raw source text only, noise-filtered.
* Does NOT replace or alter v3 / v4 / v5 outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ── Constants ────────────────────────────────────────────────────────

_DNA = "DATA NOT AVAILABLE"
_DIVIDER_MAJOR = "=" * 70
_DIVIDER_MINOR = "-" * 70
_DIVIDER_DAY   = "━" * 70

# Item types shown in the PHYSICIAN NOTES section (full text, no caps)
_PHYSICIAN_TYPES: frozenset[str] = frozenset({
    "TRAUMA_HP",
    "PHYSICIAN_NOTE",
    "ED_NOTE",
})

# Item types shown in the CONSULTANT NOTES section (full text, no caps)
_CONSULTANT_TYPES: frozenset[str] = frozenset({
    "CONSULT_NOTE",
})

# Item types shown in the PROCEDURE / ANESTHESIA section
_PROCEDURE_TYPES: frozenset[str] = frozenset({
    "OP_NOTE",
    "PROCEDURE",
    "ANESTHESIA_CONSULT",
    "ANESTHESIA_PROCEDURE",
    "PRE_PROCEDURE",
})

# Item types shown in the OTHER NOTES section
_OTHER_NOTE_TYPES: frozenset[str] = frozenset({
    "CASE_MGMT",
    "DISCHARGE",
    "DISCHARGE_SUMMARY",
    "SIGNIFICANT_EVENT",
})

# Item types shown in the LAB section
_LAB_TYPES: frozenset[str] = frozenset({
    "LAB",
    "LAB_RESULT",
})

# Item types shown in the IMAGING section
_IMAGING_TYPES: frozenset[str] = frozenset({
    "RADIOLOGY",
    "IMAGING",
})

# Item types shown in the NURSING SIGNALS section (filtered by keyword)
_NURSING_TYPES: frozenset[str] = frozenset({
    "NURSING_NOTE",
    "ED_NURSING",
})

# All note types that carry narrative clinical value (for full-text rendering)
_ALL_NARRATIVE_TYPES: frozenset[str] = (
    _PHYSICIAN_TYPES | _CONSULTANT_TYPES | _PROCEDURE_TYPES | _OTHER_NOTE_TYPES
)

# Noise patterns — lines matching these are stripped from note text
_NOISE_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in (
    r"\bADS Dispense\b",
    r"\bOMNICELL\b",
    r"\bRoutine,\s*EVERY\b",
    r"\bProcedure Documentation Timeline\b",
    r"\bLink to Procedure Log\b",
    r"^\s*Procedure Log\s*$",
    r"^\s*Date and Time\b",
    r"^\s*Ordering Quantity\b",
    r"^\s*Panel Detail\b",
    r"^\s*Or Linked Group Details\b",
    r"^\s*Notes to Pharmacy\b",
    r"^\s*Note to Pharmacy\b",
    r"\bWorkstation:\b",
    r"^\s*Procedure Orders\s*$",
    r"\bExpected length of stay\b",
    r"^\s*All Administrations of\b",
    r"^\s*MAR Admin\b",
    r"^\[(?:LAB|RADIOLOGY|IMAGING|MAR|NURSING_NOTE|TRIAGE)\]",
    # Strip leading source-type header line from note text (e.g. "[PHYSICIAN_NOTE] 2026-01-15 ...")
    r"^\s*\[(?:PHYSICIAN_NOTE|TRAUMA_HP|CONSULT_NOTE|OP_NOTE|PROCEDURE|ANESTHESIA_CONSULT"
    r"|ANESTHESIA_PROCEDURE|PRE_PROCEDURE|ED_NOTE|CASE_MGMT|DISCHARGE|DISCHARGE_SUMMARY"
    r"|SIGNIFICANT_EVENT|NURSING_NOTE|ED_NURSING)\]\s+\d{4}-\d{2}-\d{2}",
)]

# Nursing-signal keywords that trigger inclusion in the Nursing Signals section
_NURSING_SIGNAL_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in (
    r"\brestraint\b",
    r"\bsitter\b",
    r"\bfall risk\b|\bfall\b|\bfell\b",
    r"\bbed alarm\b",
    r"\bconfus\b|\bdisori\b|\bagitat\b",
    r"\bpain\b",
    r"\bfever\b|\bhypertherm\b",
    r"\bhypotension\b|\bsbp\b",
    r"\btachycard\b|\bhr\b",
    r"\bdesatur\b|\bspo2\b|\bO2 sat\b",
    r"\bseizure\b|\bconvuls\b",
    r"\bbleed\b|\bhemorrhage\b|\bhematoma\b",
    r"\bwound\b|\bdrainage\b|\bsuction\b",
    r"\burinary\b|\bfoley\b|\bcatheter\b",
    r"\bpressure\b|\bulcer\b|\bskin\b",
    r"\btube feed\b|\benteral\b|\bnpo\b",
    r"\bvent\b|\bintubat\b|\bextubat\b",
    r"\bdischarg\b|\btransfer\b",
    r"\bcode\b|\brapid response\b|\brrT\b",
    r"\bGCS\b|\bglasgow\b",
    r"\bpupil\b|\bneurolog\b",
    r"\bischemia\b|\bstroke\b|\bCVA\b",
)]


# ── Helpers ──────────────────────────────────────────────────────────

def _block_hash(text: str) -> str:
    """SHA-256 of normalised block text for cross-day duplicate detection."""
    norm = re.sub(r"\s+", " ", text.strip()).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _filter_note_text(raw: str) -> list[str]:
    """Return cleaned lines from a raw note, suppressing noise patterns.

    Consecutive blank results are collapsed; leading/trailing blanks are
    removed.  The result preserves the original clinical narrative.
    """
    lines = raw.split("\n")
    kept: list[str] = []
    prev_blank = True
    for ln in lines:
        stripped = ln.rstrip()
        # Check noise
        if any(rx.search(stripped) for rx in _NOISE_PATTERNS):
            continue
        if not stripped:
            if prev_blank:
                continue
            prev_blank = True
            kept.append("")
        else:
            prev_blank = False
            kept.append(stripped)
    # Remove trailing blanks
    while kept and not kept[-1]:
        kept.pop()
    return kept


def _dt_label(item: Dict[str, Any]) -> str:
    """Return a human-readable timestamp label for a timeline item."""
    return item.get("header_dt") or item.get("dt") or "?"


def _admission_day_number(day_iso: str, day0_iso: str) -> Optional[int]:
    """Return admission day number (1-based) relative to day0_iso."""
    try:
        d = date.fromisoformat(day_iso)
        d0 = date.fromisoformat(day0_iso)
        return (d - d0).days + 1
    except Exception:
        return None


def _fv(val: Any, decimals: int = 1) -> str:
    """Format a numeric value or return DNA."""
    if val is None:
        return _DNA
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def _fb(val: Any) -> str:
    """Format a boolean feature value."""
    if val is None:
        return _DNA
    return "Yes" if val else "No"


# ── Structured vitals / GCS / labs from features ─────────────────────

def _render_vitals_from_features(day_feats: Dict[str, Any]) -> list[str]:
    """Render structured vitals from per-day features dict.

    Per-day vitals structure: {temp_f: {min, max}, hr: {min, max},
    sbp: {min, max}, map: {min, max}, spo2: {min, max}, rr: {min, max}}.
    """
    vitals = day_feats.get("vitals", {})
    if not vitals or not isinstance(vitals, dict):
        return [f"  {_DNA}"]
    out: list[str] = []

    def _metric_line(label: str, key: str, unit: str = "") -> None:
        m = vitals.get(key)
        if not m or not isinstance(m, dict):
            return
        mn = m.get("min")
        mx = m.get("max")
        if mn is None and mx is None:
            return
        u = f" {unit}" if unit else ""
        if mn == mx or mx is None:
            out.append(f"  {label}: {_fv(mn)}{u}")
        elif mn is None:
            out.append(f"  {label}: {_fv(mx)}{u}")
        else:
            out.append(f"  {label}: {_fv(mn)}–{_fv(mx)}{u}")

    _metric_line("Temp",  "temp_f", "°F")
    _metric_line("HR",    "hr",     "bpm")
    _metric_line("SBP",   "sbp",    "mmHg")
    _metric_line("MAP",   "map",    "mmHg")
    _metric_line("RR",    "rr",     "/min")
    _metric_line("SpO2",  "spo2",   "%")

    return out if out else [f"  {_DNA}"]


def _render_gcs_from_features(day_feats: Dict[str, Any]) -> list[str]:
    """Render GCS from per-day features dict.

    Structure mirrors v5: gcs_daily.{arrival_gcs, best_gcs, worst_gcs}
    each with {value, intubated, source, dt}.
    """
    gcs = day_feats.get("gcs_daily", {})
    if not gcs or not isinstance(gcs, dict):
        return [f"  {_DNA}"]
    out: list[str] = []

    def _gcs_val(entry: Any) -> str:
        if entry is None or entry == _DNA:
            return _DNA
        if isinstance(entry, dict):
            val = entry.get("value")
            intub = " (T)" if entry.get("intubated") else ""
            if val is None or val == _DNA:
                return _DNA
            return f"{val}{intub}"
        return str(entry)

    arrival_str = _gcs_val(gcs.get("arrival_gcs"))
    best_str    = _gcs_val(gcs.get("best_gcs"))
    worst_str   = _gcs_val(gcs.get("worst_gcs"))

    if arrival_str != _DNA:
        out.append(f"  Arrival GCS: {arrival_str}")
    if best_str != _DNA:
        out.append(f"  Best GCS: {best_str}")
    if worst_str != _DNA:
        out.append(f"  Worst GCS: {worst_str}")

    return out if out else [f"  {_DNA}"]


def _render_labs_panel_from_features(day_feats: Dict[str, Any]) -> list[str]:
    """Render labs panel lite from per-day features dict.

    The labs_panel_daily structure has nested panel dicts (cbc, bmp, coags)
    plus top-level scalars (lactate, base_deficit).
    Values are either numeric or the string "DATA NOT AVAILABLE".
    """
    panel = day_feats.get("labs_panel_daily", {})
    if not panel:
        return [f"  {_DNA}"]

    _PANEL_LABELS = {
        "cbc":   "CBC",
        "bmp":   "BMP",
        "coags": "Coags",
    }

    out: list[str] = []
    all_dna = True

    for panel_key in ("cbc", "bmp", "coags"):
        sub = panel.get(panel_key)
        if not isinstance(sub, dict):
            continue
        sub_items = [(k, v) for k, v in sub.items() if v is not None and v != _DNA]
        if not sub_items:
            continue
        all_dna = False
        label = _PANEL_LABELS.get(panel_key, panel_key.upper())
        parts = []
        for k, v in sub.items():
            if v is None or v == _DNA:
                parts.append(f"{k}=—")
            else:
                try:
                    parts.append(f"{k}={_fv(float(v), 1)}")
                except (TypeError, ValueError):
                    parts.append(f"{k}={v}")
        out.append(f"  {label}: {',  '.join(parts)}")

    # Top-level scalar values (lactate, base_deficit, etc.)
    nested_keys = {"cbc", "bmp", "coags"}
    for k in sorted(panel.keys()):
        if k in nested_keys:
            continue
        v = panel.get(k)
        if v is None or v == _DNA:
            continue
        all_dna = False
        try:
            out.append(f"  {k}: {_fv(float(v), 1)}")
        except (TypeError, ValueError):
            out.append(f"  {k}: {v}")

    return out if (out and not all_dna) else [f"  {_DNA}"]


# ── Per-day note rendering ────────────────────────────────────────────

def _render_full_note(
    item: Dict[str, Any],
    label: str,
    is_new: bool,
) -> list[str]:
    """Render a single note item in full (no truncation).

    Parameters
    ----------
    item    : timeline item dict
    label   : human-readable type label (e.g. "PHYSICIAN NOTE")
    is_new  : True if this block has not appeared on any prior day
    """
    dt = _dt_label(item)
    tag = "[NEW]" if is_new else "[CARRIED]"
    raw = (item.get("payload") or {}).get("text", "")
    filtered = _filter_note_text(raw)

    out: list[str] = []
    out.append(f"  ┌─ {label}  {tag}  {dt}")
    if filtered:
        for ln in filtered:
            out.append(f"  │  {ln}" if ln else "  │")
    else:
        out.append(f"  │  {_DNA}")
    out.append("  └─" + _DIVIDER_MINOR[3:])
    return out


def _render_imaging_item(item: Dict[str, Any], is_new: bool) -> list[str]:
    """Render an imaging/radiology item, impression-first."""
    dt = _dt_label(item)
    tag = "[NEW]" if is_new else "[CARRIED]"
    raw = (item.get("payload") or {}).get("text", "")
    lines = raw.split("\n")

    impression_lines: list[str] = []
    findings_lines: list[str] = []
    header_lines: list[str] = []
    in_impression = False
    in_findings = False
    for ln in lines:
        stripped = ln.strip()
        if re.match(r"^\s*IMPRESSION\s*:?", stripped, re.IGNORECASE):
            in_impression = True
            in_findings = False
            imp_text = re.sub(r"^\s*IMPRESSION\s*:?\s*", "", stripped, flags=re.IGNORECASE).strip()
            if imp_text:
                impression_lines.append(imp_text)
        elif re.match(r"^\s*FINDINGS\s*:?", stripped, re.IGNORECASE):
            in_findings = True
            in_impression = False
            fnd_text = re.sub(r"^\s*FINDINGS\s*:?\s*", "", stripped, flags=re.IGNORECASE).strip()
            if fnd_text:
                findings_lines.append(fnd_text)
        elif in_impression:
            if stripped:
                impression_lines.append(stripped)
            else:
                in_impression = False
        elif in_findings:
            if stripped:
                findings_lines.append(stripped)
            else:
                in_findings = False
        else:
            if not any(rx.search(stripped) for rx in _NOISE_PATTERNS):
                if stripped:
                    header_lines.append(stripped)

    out: list[str] = []
    # First non-empty header line as study title
    title = next((h for h in header_lines if h), "IMAGING STUDY")
    out.append(f"  ┌─ IMAGING {tag}  {dt}  — {title}")
    if impression_lines:
        out.append("  │  IMPRESSION:")
        for ln in impression_lines:
            out.append(f"  │    {ln}")
    if findings_lines:
        out.append("  │  FINDINGS:")
        for ln in findings_lines:
            out.append(f"  │    {ln}")
    if not impression_lines and not findings_lines:
        # Fall back to filtered full text
        filtered = _filter_note_text(raw)
        for ln in filtered:
            out.append(f"  │  {ln}" if ln else "  │")
    out.append("  └─" + _DIVIDER_MINOR[3:])
    return out


def _render_lab_item(item: Dict[str, Any]) -> list[str]:
    """Render a lab item — all result lines."""
    dt = _dt_label(item)
    raw = (item.get("payload") or {}).get("text", "")
    filtered = _filter_note_text(raw)
    out: list[str] = []
    for ln in filtered:
        if ln:
            out.append(f"  {dt}  {ln}")
    return out


def _render_nursing_signals(item: Dict[str, Any]) -> list[str]:
    """Return lines matching nursing-signal patterns from a nursing note."""
    raw = (item.get("payload") or {}).get("text", "")
    dt = _dt_label(item)
    matched: list[str] = []
    for ln in raw.split("\n"):
        stripped = ln.strip()
        if not stripped:
            continue
        if any(rx.search(stripped) for rx in _NURSING_SIGNAL_PATTERNS):
            matched.append(f"  {dt}  {stripped}")
    return matched


# ── Day renderer ─────────────────────────────────────────────────────

def _render_one_day(
    day_iso: str,
    items: list[Dict[str, Any]],
    day_feats: Dict[str, Any],
    prior_block_hashes: Set[str],
    day0_iso: str,
    has_features: bool,
) -> list[str]:
    """Render all sections for a single calendar day."""
    adm_day = _admission_day_number(day_iso, day0_iso)
    day_label = f"ADMISSION DAY {adm_day}" if adm_day is not None else day_iso

    out: list[str] = []
    out.append("")
    out.append(_DIVIDER_DAY)
    out.append(f"  {day_label}  ·  {day_iso}")
    out.append(_DIVIDER_DAY)
    out.append("")

    # Bucket items by type
    physician_items: list[Dict[str, Any]] = []
    consultant_items: list[Dict[str, Any]] = []
    procedure_items: list[Dict[str, Any]] = []
    other_items: list[Dict[str, Any]] = []
    lab_items: list[Dict[str, Any]] = []
    imaging_items: list[Dict[str, Any]] = []
    nursing_items: list[Dict[str, Any]] = []

    for it in items:
        itype = (it.get("type") or "").upper()
        if itype in _PHYSICIAN_TYPES:
            physician_items.append(it)
        elif itype in _CONSULTANT_TYPES:
            consultant_items.append(it)
        elif itype in _PROCEDURE_TYPES:
            procedure_items.append(it)
        elif itype in _OTHER_NOTE_TYPES:
            other_items.append(it)
        elif itype in _LAB_TYPES:
            lab_items.append(it)
        elif itype in _IMAGING_TYPES:
            imaging_items.append(it)
        elif itype in _NURSING_TYPES:
            nursing_items.append(it)
        # MAR and other administrative types are intentionally omitted

    # ── Structured Vitals / GCS / Labs (from features, when available) ──
    if has_features:
        out.append("STRUCTURED VITALS  (from features layer)")
        out.append(_DIVIDER_MINOR)
        out.extend(_render_vitals_from_features(day_feats))
        out.append("")

        out.append("GCS  (from features layer)")
        out.append(_DIVIDER_MINOR)
        out.extend(_render_gcs_from_features(day_feats))
        out.append("")

        out.append("LABS PANEL  (from features layer)")
        out.append(_DIVIDER_MINOR)
        out.extend(_render_labs_panel_from_features(day_feats))
        out.append("")

    # ── Physician Notes (FULL TEXT, no truncation) ───────────────────
    out.append("PHYSICIAN NOTES  (full text)")
    out.append(_DIVIDER_MINOR)
    if physician_items:
        for it in physician_items:
            itype = (it.get("type") or "").upper()
            raw = (it.get("payload") or {}).get("text", "")
            bh = _block_hash(raw)
            is_new = bh not in prior_block_hashes
            label = {
                "TRAUMA_HP": "TRAUMA H&P",
                "PHYSICIAN_NOTE": "PHYSICIAN NOTE",
                "ED_NOTE": "ED NOTE",
            }.get(itype, itype)
            out.extend(_render_full_note(it, label, is_new))
            out.append("")
    else:
        out.append(f"  {_DNA}")
        out.append("")

    # ── Consultant Notes (FULL TEXT, no truncation) ──────────────────
    out.append("CONSULTANT NOTES  (full text)")
    out.append(_DIVIDER_MINOR)
    if consultant_items:
        for it in consultant_items:
            raw = (it.get("payload") or {}).get("text", "")
            bh = _block_hash(raw)
            is_new = bh not in prior_block_hashes
            out.extend(_render_full_note(it, "CONSULT NOTE", is_new))
            out.append("")
    else:
        out.append(f"  {_DNA}")
        out.append("")

    # ── Procedure / Anesthesia Notes ─────────────────────────────────
    if procedure_items:
        out.append("PROCEDURE / ANESTHESIA NOTES  (full text)")
        out.append(_DIVIDER_MINOR)
        for it in procedure_items:
            itype = (it.get("type") or "").upper()
            raw = (it.get("payload") or {}).get("text", "")
            bh = _block_hash(raw)
            is_new = bh not in prior_block_hashes
            label = {
                "OP_NOTE":              "OPERATIVE NOTE",
                "PROCEDURE":            "PROCEDURE NOTE",
                "ANESTHESIA_CONSULT":   "ANESTHESIA CONSULT",
                "ANESTHESIA_PROCEDURE": "ANESTHESIA PROCEDURE",
                "PRE_PROCEDURE":        "PRE-PROCEDURE NOTE",
            }.get(itype, itype)
            out.extend(_render_full_note(it, label, is_new))
            out.append("")

    # ── Other Notes (FULL TEXT) ───────────────────────────────────────
    if other_items:
        out.append("OTHER CLINICAL NOTES  (full text)")
        out.append(_DIVIDER_MINOR)
        for it in other_items:
            itype = (it.get("type") or "").upper()
            raw = (it.get("payload") or {}).get("text", "")
            bh = _block_hash(raw)
            is_new = bh not in prior_block_hashes
            label = {
                "CASE_MGMT":         "CASE MANAGEMENT NOTE",
                "DISCHARGE":         "DISCHARGE NOTE",
                "DISCHARGE_SUMMARY": "DISCHARGE SUMMARY",
                "SIGNIFICANT_EVENT": "SIGNIFICANT EVENT",
            }.get(itype, itype)
            out.extend(_render_full_note(it, label, is_new))
            out.append("")

    # ── Imaging ──────────────────────────────────────────────────────
    if imaging_items:
        out.append("IMAGING / RADIOLOGY")
        out.append(_DIVIDER_MINOR)
        for it in imaging_items:
            raw = (it.get("payload") or {}).get("text", "")
            bh = _block_hash(raw)
            is_new = bh not in prior_block_hashes
            out.extend(_render_imaging_item(it, is_new))
            out.append("")

    # ── Labs (raw text) ───────────────────────────────────────────────
    if lab_items:
        out.append("LABORATORY RESULTS  (raw)")
        out.append(_DIVIDER_MINOR)
        for it in lab_items:
            lab_lines = _render_lab_item(it)
            out.extend(lab_lines)
        out.append("")

    # ── Nursing Signals ───────────────────────────────────────────────
    nursing_signal_lines: list[str] = []
    for it in nursing_items:
        nursing_signal_lines.extend(_render_nursing_signals(it))
    if nursing_signal_lines:
        out.append("NURSING SIGNALS  (protocol-relevant lines)")
        out.append(_DIVIDER_MINOR)
        out.extend(nursing_signal_lines)
        out.append("")

    return out


# ── Top-level patient header from features ───────────────────────────

def _render_patient_header(
    meta: Dict[str, Any],
    features_data: Optional[Dict[str, Any]],
) -> list[str]:
    """Render a compact patient header at the top of the report."""
    out: list[str] = []
    out.append(_DIVIDER_MAJOR)
    out.append("CALENDAR DAILY NOTES (v1)")
    out.append("CerebralOS — Comprehensive Admission Review")
    out.append(_DIVIDER_MAJOR)
    out.append("")

    pat_id = meta.get("patient_id", _DNA)
    arrival = meta.get("arrival_datetime", _DNA)
    discharge = meta.get("discharge_datetime") or "ongoing / not recorded"
    tz = meta.get("timezone", _DNA)

    out.append(f"Patient ID   : {pat_id}")
    out.append(f"Arrival      : {arrival}")
    out.append(f"Discharge    : {discharge}")
    out.append(f"Timezone     : {tz}")

    if features_data:
        feats = features_data.get("features", {})

        # Age / sex
        age_feat = feats.get("age_extraction_v1", {})
        age = age_feat.get("age_years") or age_feat.get("age")
        sex_feat = feats.get("sex_extraction_v1", {})
        sex = sex_feat.get("sex")
        if age or sex:
            out.append(f"Demographics : age={age or _DNA}  sex={sex or _DNA}")

        # Mechanism / injury
        mech_feat = feats.get("mechanism_of_injury_v1", {})
        mech = mech_feat.get("mechanism")
        if mech:
            out.append(f"Mechanism    : {mech}")

        # ISS / injury list
        inj_feat = feats.get("injury_extraction_v1", {})
        inj_list = inj_feat.get("injuries", [])
        if inj_list:
            out.append(f"Injuries ({len(inj_list)}) :")
            for inj in inj_list[:20]:
                body = inj.get("body_part") or ""
                desc = inj.get("description") or inj.get("text") or ""
                line = "  · " + "  ".join(filter(None, [body, desc]))
                out.append(line[:120])
            if len(inj_list) > 20:
                out.append(f"  ... +{len(inj_list) - 20} additional injuries")

        # PMH
        pmh_feat = feats.get("pmh_extraction_v1", {})
        pmh = pmh_feat.get("conditions", [])
        if pmh:
            out.append(f"PMH ({len(pmh)})     : {', '.join(str(c) for c in pmh[:15])}")

        # Allergies
        allergy_feat = feats.get("allergy_extraction_v1", {})
        allergies = allergy_feat.get("allergies", [])
        if allergies:
            out.append(f"Allergies    : {', '.join(str(a) for a in allergies[:10])}")

        # Admission movement
        mov_feat = feats.get("patient_movement_v1", {})
        adm_ts = mov_feat.get("admission_ts") or mov_feat.get("summary", {}).get("admission_ts")
        dis_ts = mov_feat.get("discharge_ts") or mov_feat.get("summary", {}).get("discharge_ts")
        if adm_ts:
            out.append(f"ADT Admit    : {adm_ts}")
        if dis_ts:
            out.append(f"ADT Discharge: {dis_ts}")

    out.append("")
    out.append("LEGEND")
    out.append("  [NEW]     — note block not seen on any prior calendar day")
    out.append("  [CARRIED] — identical block hash found on a prior day (repeated/carried-over content)")
    out.append("")
    return out


# ── Main render function ──────────────────────────────────────────────

def render_calendar_v1(
    days_data: Dict[str, Any],
    features_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Render comprehensive calendar daily notes.

    Parameters
    ----------
    days_data     : parsed patient_days_v1.json
    features_data : parsed patient_features_v1.json (optional)

    Returns
    -------
    str : complete text report, UTF-8 safe, ends with newline
    """
    meta = days_data.get("meta") or {}
    days = days_data.get("days") or {}

    # Extract per-day feature dicts (from features_data if present)
    feature_days: Dict[str, Any] = {}
    has_features = False
    if features_data:
        has_features = True
        feature_days = features_data.get("days") or {}

    # Day ordering: chronological, UNDATED appended
    day_keys = sorted(k for k in days.keys() if k != "UNDATED")
    if "UNDATED" in days:
        day_keys.append("UNDATED")

    day0_iso = meta.get("day0_date") or (day_keys[0] if day_keys else "?")

    out: list[str] = []
    out.extend(_render_patient_header(meta, features_data))

    # Summary of admission span
    if day_keys:
        first_day = next((k for k in day_keys if k != "UNDATED"), None)
        last_day  = next((k for k in reversed(day_keys) if k != "UNDATED"), None)
        if first_day and last_day:
            try:
                span = (date.fromisoformat(last_day) - date.fromisoformat(first_day)).days + 1
                out.append(f"Admission span : {first_day} → {last_day}  ({span} calendar day(s) documented)")
            except Exception:
                pass
        out.append(f"Days with data : {len([k for k in day_keys if k != 'UNDATED'])}")
        out.append("")

    # Cross-day block hash set — tracks which full note blocks have been seen
    prior_block_hashes: Set[str] = set()

    prev_date: Optional[date] = None

    for dk in day_keys:
        if dk == "UNDATED":
            continue

        # Evidence gap detection
        try:
            cur_date = date.fromisoformat(dk)
        except ValueError:
            cur_date = None
        if prev_date is not None and cur_date is not None:
            gap = (cur_date - prev_date).days
            if gap > 1:
                out.append("")
                out.append(f"  ⚠  EVIDENCE GAP: {gap - 1} calendar day(s) with no documentation between "
                           f"{prev_date.isoformat()} and {dk}")
        if cur_date is not None:
            prev_date = cur_date

        day_obj = days.get(dk) or {}
        items: list[Dict[str, Any]] = day_obj.get("items") or []

        # Per-day features (from features layer if present)
        day_feats: Dict[str, Any] = feature_days.get(dk) or {}

        # Render this day's content
        day_lines = _render_one_day(
            day_iso=dk,
            items=items,
            day_feats=day_feats,
            prior_block_hashes=prior_block_hashes,
            day0_iso=day0_iso,
            has_features=has_features,
        )
        out.extend(day_lines)

        # Update prior block hashes with ALL note blocks seen today
        for it in items:
            itype = (it.get("type") or "").upper()
            if itype in (_PHYSICIAN_TYPES | _CONSULTANT_TYPES | _PROCEDURE_TYPES
                         | _OTHER_NOTE_TYPES | _IMAGING_TYPES):
                raw = (it.get("payload") or {}).get("text", "")
                prior_block_hashes.add(_block_hash(raw))

    # Undated items appendix
    if "UNDATED" in days:
        undated_obj = days.get("UNDATED") or {}
        undated_items: list[Dict[str, Any]] = undated_obj.get("items") or []
        if undated_items:
            out.append("")
            out.append(_DIVIDER_DAY)
            out.append("  UNDATED ITEMS  (no calendar date assigned)")
            out.append(_DIVIDER_DAY)
            out.append("")
            for it in undated_items:
                itype = (it.get("type") or "").upper()
                raw = (it.get("payload") or {}).get("text", "")
                if itype in _ALL_NARRATIVE_TYPES:
                    out.extend(_render_full_note(it, itype, is_new=True))
                    out.append("")

    # Footer
    out.append("")
    out.append(_DIVIDER_MAJOR)
    out.append("END OF CALENDAR DAILY NOTES (v1)")
    out.append("Generated by CerebralOS — deterministic, fail-closed, no clinical inference")
    out.append(_DIVIDER_MAJOR)
    out.append("")

    return "\n".join(out)


# ── CLI ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Render Calendar Daily Notes v1 — comprehensive per-day admission "
            "review with full physician notes and no narrative caps."
        ),
    )
    ap.add_argument(
        "--days", dest="days_path", required=True,
        help="Path to patient_days_v1.json",
    )
    ap.add_argument(
        "--features", dest="features_path", required=False, default=None,
        help="Path to patient_features_v1.json (optional — adds structured vitals/GCS/labs)",
    )
    ap.add_argument(
        "--out", dest="out_path", required=True,
        help="Output path for CALENDAR_DAILY_NOTES_v1.txt",
    )
    args = ap.parse_args()

    days_path = Path(args.days_path).expanduser().resolve()
    out_path  = Path(args.out_path).expanduser().resolve()

    if not days_path.is_file():
        print(f"FAIL: days file not found: {days_path}")
        return 1

    with open(days_path, encoding="utf-8", errors="replace") as f:
        days_data = json.load(f)

    features_data: Optional[Dict[str, Any]] = None
    if args.features_path:
        features_path = Path(args.features_path).expanduser().resolve()
        if features_path.is_file():
            with open(features_path, encoding="utf-8", errors="replace") as f:
                features_data = json.load(f)
        else:
            print(f"WARNING: features file not found: {features_path} — continuing without")

    text = render_calendar_v1(days_data, features_data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"OK ✅ Wrote calendar daily notes v1: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
