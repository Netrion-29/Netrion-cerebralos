#!/usr/bin/env python3
"""
Assemble patient_bundle_v1.json from existing pipeline artifacts.

Reads per-patient outputs (evidence, features, timeline, NTDS, protocols)
and produces a single curated JSON bundle for the future casefile renderer.

Usage:
    python3 cerebralos/reporting/build_patient_bundle_v1.py \
        --slug Betty_Roll \
        --out outputs/casefile/Betty_Roll/patient_bundle_v1.json

Exit codes:
    0 — bundle written successfully
    1 — required artifact missing or assembly error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Constants ──────────────────────────────────────────────────────

BUNDLE_VERSION = "1.0"
ASSEMBLER_NAME = "build_patient_bundle_v1"

# Feature keys used in the summary section.
_SUMMARY_FEATURE_MAP: Dict[str, str] = {
    "mechanism": "mechanism_region_v1",
    "pmh": "pmh_social_allergies_v1",
    "anticoagulants": "anticoag_context_v1",
    "demographics": "demographics_v1",
    "activation": "category_activation_v1",
    "shock_trigger": "shock_trigger_v1",
    "age": "age_extraction_v1",
    "injuries": "radiology_findings_v1",
    "imaging": "radiology_findings_v1",
    "procedures": "procedure_operatives_v1",
    "devices": "lda_events_v1",
    "dvt_prophylaxis": "dvt_prophylaxis_v1",
    "gi_prophylaxis": "gi_prophylaxis_v1",
    "seizure_prophylaxis": "seizure_prophylaxis_v1",
    "base_deficit": "base_deficit_monitoring_v1",
    "transfusions": "transfusion_blood_products_v1",
    "hemodynamic_instability": "hemodynamic_instability_pattern_v1",
    "patient_movement": "patient_movement_v1",
    "sbirt_screening": "sbirt_screening_v1",
}

# Per-day feature keys extracted from the features dict (keyed by day).
_DAILY_FROM_FEATURES: Dict[str, str] = {
    "vitals": "vitals_canonical_v1",
    "ventilator": "ventilator_settings_v1",
    "plans": "trauma_daily_plan_by_day_v1",
    "consultant_plans": "consultant_day_plans_by_day_v1",
    "non_trauma_team_plans": "non_trauma_team_day_plans_v1",
}

# Per-day keys extracted from the days dict directly.
_DAILY_FROM_DAYS: tuple[str, ...] = ("labs", "gcs_daily")


# ── Helpers ────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    """Load and parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path) -> Optional[Any]:
    """Load a JSON file, returning None if the file doesn't exist."""
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _resolve_outputs_root() -> Path:
    """Return the project outputs/ directory."""
    return Path(__file__).resolve().parent.parent.parent / "outputs"


# ── Trauma Summary assembly ────────────────────────────────────────

# Regex for GCS value in disability text.  Captures the numeric score
# and an optional trailing "T" indicating intubated patient.
_RE_GCS = re.compile(r"GCS\s*(\d+)(T)?", re.IGNORECASE)

# Regex for explicit intubation markers in note text.
_RE_INTUBATED = re.compile(
    r"\b(?:ETT|endotracheal\s+tube|intubated|controlled\s+with\s+ETT)\b",
    re.IGNORECASE,
)

# Regex matching known Trauma H&P title line variants (case-insensitive).
# Covers: "Trauma H & P", "Trauma H&P", "TRAUMA H & P", "Trauma H/P", etc.
_RE_TRAUMA_HP_TITLE = re.compile(
    r"^trauma\s+h\s*[&/]\s*p$",
    re.IGNORECASE,
)

# Known consult service patterns extracted from Plan text.
# Conservative: explicit service name after consult-related keywords.
_RE_CONSULT_SERVICE = re.compile(
    r"(?:^|\n)\s*[-•]?\s*"  # line start, optional bullet
    r"(?:consult(?:ed|ation)?)\s+(?:to\s+|for\s+|with\s+)?"  # "consult to/for"
    r"([A-Z][A-Za-z /&-]+?)(?:\s*[-:,]|\s*$)",  # capture service name
    re.MULTILINE,
)

# Alternate pattern: "ServiceName consult" at start of plan line
_RE_SERVICE_CONSULT = re.compile(
    r"(?:^|\n)\s*[-•]?\s*"
    r"([A-Z][A-Za-z /&-]+?)\s+consult(?:ed|ation)?\b",
    re.MULTILINE,
)

# Admission disposition line in plan text
_RE_ADMIT_DISPOSITION = re.compile(
    r"(?:^|\n)\s*[-•]?\s*(Admit\s+to\s+[^\n]{3,80})",
    re.IGNORECASE | re.MULTILINE,
)

# Known service name whitelist for conservative filtering.
# Only services whose lowercase form appears here will be emitted.
_CONSULT_SERVICE_WHITELIST = frozenset({
    "Neurosurgery", "NSGY", "Ortho", "Orthopedics", "Hospitalist",
    "Urology", "ENT", "Cardiology", "Pulmonology", "PCCM",
    "Vascular", "Ophthalmology", "Plastic Surgery", "Plastics",
    "General Surgery", "Oral Surgery", "Interventional Radiology",
    "Physical Therapy", "Occupational Therapy", "Speech Therapy",
    "Pain Management", "Palliative Care", "Social Work",
    "Case Management", "Wound Care", "Infectious Disease",
    "Nephrology", "GI", "Gastroenterology", "Hematology",
    "Oncology", "Psychiatry", "Dermatology",
})
# Case-folded set for O(1) membership tests.
_CONSULT_SERVICE_WHITELIST_FOLDED = frozenset(
    s.lower() for s in _CONSULT_SERVICE_WHITELIST
)


def _extract_gcs_from_disability(disability_text: Optional[str]) -> Optional[str]:
    """Extract GCS string from primary survey disability field.

    Returns the GCS value as a string (e.g. "15", "3T").
    Returns None if no GCS found.
    """
    if not disability_text:
        return None
    m = _RE_GCS.search(disability_text)
    if not m:
        return None
    score = m.group(1)
    suffix = m.group(2) or ""
    return f"{score}{suffix}"


def _extract_intubated(
    disability_text: Optional[str],
    airway_text: Optional[str],
    gcs_str: Optional[str],
) -> Optional[bool]:
    """Determine intubated status.  Strict fail-closed.

    Returns True only for:
    - explicit "ETT", "endotracheal tube", "intubated", or
      "controlled with ETT" in disability or airway text
    - GCS string ending in "T"

    Returns False if texts are present but no intubation marker found.
    Returns None if all input texts are absent.
    """
    texts = [t for t in (disability_text, airway_text) if t]
    has_text = bool(texts)

    for text in texts:
        if _RE_INTUBATED.search(text):
            return True

    if gcs_str and gcs_str.upper().endswith("T"):
        return True

    if has_text:
        return False
    return None


def _extract_consult_services(plan_text: Optional[str]) -> Optional[List[str]]:
    """Extract consult service names from Plan text.

    Conservative: only explicit service name strings.
    No surgeon names, no contact times, no consult prose.
    Returns None if plan_text is absent.
    """
    if not plan_text:
        return None

    services: List[str] = []
    seen: set = set()

    # Pattern 1: "ServiceName consult"
    for m in _RE_SERVICE_CONSULT.finditer(plan_text):
        svc = m.group(1).strip().rstrip(".-")
        if not svc or len(svc) > 60:
            continue
        if svc.lower() not in _CONSULT_SERVICE_WHITELIST_FOLDED:
            continue
        svc_key = svc.lower()
        if svc_key not in seen:
            seen.add(svc_key)
            services.append(svc)

    # Pattern 2: "consult to/for ServiceName"
    for m in _RE_CONSULT_SERVICE.finditer(plan_text):
        svc = m.group(1).strip().rstrip(".-")
        if not svc or len(svc) > 60:
            continue
        if svc.lower() not in _CONSULT_SERVICE_WHITELIST_FOLDED:
            continue
        svc_key = svc.lower()
        if svc_key not in seen:
            seen.add(svc_key)
            services.append(svc)

    return services if services else []


def _extract_admission_disposition(plan_text: Optional[str]) -> Optional[str]:
    """Extract first admission disposition line from Plan text.

    Returns the raw "Admit to ..." text.
    Returns None if not found.
    """
    if not plan_text:
        return None
    m = _RE_ADMIT_DISPOSITION.search(plan_text)
    if m:
        return m.group(1).strip()
    return None


def _extract_doc_title_and_author(
    evidence_items: List[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract source_doc_title and app_author from the TRAUMA_HP evidence item text.

    Returns (source_doc_title, app_author, attending).
    """
    for item in evidence_items:
        if item.get("kind") != "TRAUMA_HP":
            continue
        text = item.get("text", "")
        lines = text.split("\n")

        doc_title: Optional[str] = None
        app_author: Optional[str] = None
        attending: Optional[str] = None

        # Find Trauma H&P title line (case-insensitive) → next non-blank = author.
        # Covers: "Trauma H & P", "Trauma H&P", "TRAUMA H & P", "Trauma H/P", etc.
        _SKIP_BOILERPLATE = frozenset({"Signed", "Expand All Collapse All", ""})
        for i, line in enumerate(lines):
            stripped = line.strip()
            if _RE_TRAUMA_HP_TITLE.match(stripped):
                doc_title = stripped
                # Look for author on subsequent non-blank line
                for j in range(i + 1, min(i + 4, len(lines))):
                    candidate = lines[j].strip()
                    if candidate and candidate not in _SKIP_BOILERPLATE:
                        app_author = candidate
                        break
                break

        # Find attending: look for MD signature in a local window around
        # the attestation phrase.  Consistently appears 1-3 lines BELOW.
        # Also check a small window above as a fallback.
        for i in range(len(lines) - 1, max(len(lines) - 50, -1), -1):
            stripped = lines[i].strip()
            if "I have seen and examined patient" in stripped:
                # Primary: search below attestation line
                for j in range(i + 1, min(i + 8, len(lines))):
                    candidate = lines[j].strip()
                    if candidate and ", MD" in candidate:
                        attending = candidate
                        break
                # Fallback: search above attestation line
                if not attending:
                    for j in range(i - 1, max(i - 6, -1), -1):
                        candidate = lines[j].strip()
                        if candidate and ", MD" in candidate:
                            attending = candidate
                            break
                break

        if doc_title is None:
            doc_title = "Trauma H & P"

        return doc_title, app_author, attending

    return None, None, None


def _split_into_items(text: Optional[str]) -> Optional[List[str]]:
    """Split section text into individual line items.

    Splits on lines starting with -, •, or newlines with content.
    Returns list of non-empty stripped lines.
    Returns None if text is absent.
    """
    if not text:
        return None
    items: List[str] = []
    for line in text.split("\n"):
        stripped = line.strip().lstrip("-•").strip()
        if stripped:
            items.append(stripped)
    return items if items else None


def _truncate_hpi(hpi_text: Optional[str], max_lines: int = 15) -> Optional[str]:
    """Truncate HPI to first N non-empty lines for summary display."""
    if not hpi_text:
        return None
    lines = [ln for ln in hpi_text.split("\n") if ln.strip()]
    truncated = lines[:max_lines]
    return "\n".join(truncated) if truncated else None


def build_trauma_summary(
    feat: Dict[str, Any],
    evidence_items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build summary.trauma_summary from note_sections_v1 and evidence.

    Returns a dict if a TRAUMA_HP anchor exists, with partial/null
    subfields for any missing data.  Returns None only if no
    TRAUMA_HP evidence item exists at all.
    """
    # ── Check for TRAUMA_HP anchor ──────────────────────────────
    has_trauma_hp = any(
        item.get("kind") == "TRAUMA_HP" for item in evidence_items
    )
    if not has_trauma_hp:
        return None

    # ── Source metadata from note_sections_v1 ───────────────────
    ns = feat.get("note_sections_v1") or {}
    source_type = ns.get("source_type")
    source_ts = ns.get("source_ts")

    # If note_sections_v1 didn't select TRAUMA_HP, we still build
    # the summary using whatever we can extract from the evidence item.
    # The anchor is the evidence item itself.

    # Find the TRAUMA_HP evidence item for timestamp fallback
    trauma_hp_item: Optional[Dict[str, Any]] = None
    for item in evidence_items:
        if item.get("kind") == "TRAUMA_HP":
            trauma_hp_item = item
            break

    # Use note_sections_v1 source_ts when its source is TRAUMA_HP and non-null;
    # always fall back to the evidence item datetime otherwise.
    if source_type == "TRAUMA_HP" and source_ts:
        source_note_datetime = source_ts
    else:
        source_note_datetime = (
            trauma_hp_item.get("datetime") or trauma_hp_item.get("header_dt")
            if trauma_hp_item else None
        )

    # ── Extract doc title and authors from raw evidence text ────
    doc_title, app_author, attending = _extract_doc_title_and_author(
        evidence_items
    )

    # ── Activation category from features ───────────────────────
    activation = feat.get("category_activation_v1") or {}
    activation_category = None
    if isinstance(activation, dict) and activation.get("detected"):
        raw_cat = activation.get("category")
        if raw_cat:
            activation_category = str(raw_cat).strip()

    # ── Mechanism from features ─────────────────────────────────
    mechanism = feat.get("mechanism_region_v1") or {}
    mechanism_summary = None
    if isinstance(mechanism, dict):
        mech_primary = mechanism.get("mechanism_primary")
        if mech_primary:
            mechanism_summary = str(mech_primary).strip()

    # ── Sections from note_sections_v1 (may be partial/absent) ──
    hpi_section = ns.get("hpi") or {}
    ps_section = ns.get("primary_survey") or {}
    imp_section = ns.get("impression") or {}
    plan_section = ns.get("plan") or {}

    hpi_text = hpi_section.get("text") if hpi_section.get("present") else None
    ps_fields = ps_section.get("fields") or {}
    imp_text = imp_section.get("text") if imp_section.get("present") else None
    plan_text = plan_section.get("text") if plan_section.get("present") else None

    # ── Primary survey fields (raw passthrough) ─────────────────
    primary_survey = {
        "airway": ps_fields.get("airway"),
        "breathing": ps_fields.get("breathing"),
        "circulation": ps_fields.get("circulation"),
        "disability": ps_fields.get("disability"),
        "exposure": ps_fields.get("exposure"),
        "fast": ps_fields.get("fast"),  # raw text only, no normalization
    }

    # ── GCS from disability text ────────────────────────────────
    gcs = _extract_gcs_from_disability(ps_fields.get("disability"))

    # ── Intubated (strict fail-closed) ──────────────────────────
    intubated = _extract_intubated(
        ps_fields.get("disability"),
        ps_fields.get("airway"),
        gcs,
    )

    # ── Impression items ────────────────────────────────────────
    impression_items = _split_into_items(imp_text)

    # ── Plan items ──────────────────────────────────────────────
    plan_items = _split_into_items(plan_text)

    # ── Consult services (conservative) ─────────────────────────
    consult_services = _extract_consult_services(plan_text)

    # ── Admission disposition text ──────────────────────────────
    admission_disposition_text = _extract_admission_disposition(plan_text)

    # ── HPI summary (truncated) ─────────────────────────────────
    hpi_summary = _truncate_hpi(hpi_text)

    return {
        "present": True,
        "source_note_type": "TRAUMA_HP",
        "source_note_datetime": source_note_datetime,
        "source_doc_title": doc_title,
        "activation_category": activation_category,
        "mechanism_summary": mechanism_summary,
        "hpi_summary": hpi_summary,
        "primary_survey": primary_survey,
        "gcs": gcs,
        "impression_text": imp_text,
        "impression_items": impression_items,
        "plan_text": plan_text,
        "plan_items": plan_items,
        "consult_services": consult_services,
        "intubated": intubated,
        "admission_disposition_text": admission_disposition_text,
        "attending": attending,
        "app_author": app_author,
    }


# ── Assembly ───────────────────────────────────────────────────────

def assemble_bundle(
    slug: str,
    outputs_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Assemble a patient_bundle_v1 dict from existing pipeline outputs.

    Raises FileNotFoundError for missing required artifacts.
    """
    root = outputs_root or _resolve_outputs_root()
    warnings: List[str] = []

    # ── Required artifacts ──────────────────────────────────────
    evidence_path = root / "evidence" / slug / "patient_evidence_v1.json"
    features_path = root / "features" / slug / "patient_features_v1.json"
    timeline_path = root / "timeline" / slug / "patient_days_v1.json"

    for req_path, label in [
        (evidence_path, "patient_evidence_v1.json"),
        (features_path, "patient_features_v1.json"),
        (timeline_path, "patient_days_v1.json"),
    ]:
        if not req_path.is_file():
            raise FileNotFoundError(
                f"Required artifact missing: {label} "
                f"(expected at {req_path})"
            )

    evidence = _load_json(evidence_path)
    features = _load_json(features_path)
    timeline = _load_json(timeline_path)

    meta = evidence.get("meta", {})
    feat = features.get("features", {})
    feat_days = features.get("days", {})
    timeline_days = timeline.get("days", {})

    # Merge day keys from both sources for completeness.
    all_day_keys = sorted(set(feat_days.keys()) | set(timeline_days.keys()))

    # ── Optional artifacts ──────────────────────────────────────
    ntds_summary_path = root / "ntds" / slug / "ntds_summary_2026_v1.json"
    ntds_summary_data = _load_optional_json(ntds_summary_path)
    if ntds_summary_data is None:
        warnings.append("NTDS summary not found; compliance.ntds_summary set to null")

    # Compact NTDS event outcomes from per-event files.
    ntds_event_outcomes: Optional[Dict[str, Any]] = None
    ntds_dir = root / "ntds" / slug
    if ntds_dir.is_dir():
        outcomes = {}
        for event_file in sorted(ntds_dir.glob("ntds_event_*_2026_v1.json")):
            event_data = _load_json(event_file)
            event_id = event_data.get("event_id")
            if event_id is not None:
                outcomes[str(event_id)] = {
                    "event_id": event_id,
                    "canonical_name": event_data.get("canonical_name", ""),
                    "outcome": event_data.get("outcome", ""),
                }
        if outcomes:
            ntds_event_outcomes = outcomes
    if ntds_event_outcomes is None and ntds_summary_data is not None:
        warnings.append("NTDS per-event files not found; compliance.ntds_event_outcomes set to null")

    protocol_results_path = root / "protocols" / slug / "protocol_results_v1.json"
    protocol_results_data = _load_optional_json(protocol_results_path)
    if protocol_results_data is None:
        warnings.append("Protocol results not found; compliance.protocol_results set to null")

    v5_path = root / "reporting" / slug / "TRAUMA_DAILY_NOTES_v5.txt"
    if not v5_path.is_file():
        warnings.append("V5 report not found; artifacts.v5_report_path set to null")

    # ── Build sections ──────────────────────────────────────────

    # patient
    patient_section = {
        "patient_id": meta.get("patient_id", ""),
        "patient_name": meta.get("patient_name", ""),
        "dob": meta.get("dob", ""),
        "slug": slug,
        "arrival_datetime": meta.get("arrival_datetime"),
        "discharge_datetime": meta.get("discharge_datetime"),
        "trauma_category": meta.get("trauma_category", ""),
    }

    # summary
    summary_section: Dict[str, Any] = {}
    for bundle_key, feat_key in _SUMMARY_FEATURE_MAP.items():
        summary_section[bundle_key] = feat.get(feat_key)

    evidence_items = evidence.get("items", [])
    summary_section["trauma_summary"] = build_trauma_summary(feat, evidence_items)

    # compliance
    compliance_section = {
        "ntds_summary": ntds_summary_data,
        "ntds_event_outcomes": ntds_event_outcomes,
        "protocol_results": protocol_results_data,
    }

    # daily
    daily_section: Dict[str, Dict[str, Any]] = {}
    for day_key in all_day_keys:
        day_data: Dict[str, Any] = {}

        # From features dict (date-keyed feature modules)
        for bundle_key, feat_key in _DAILY_FROM_FEATURES.items():
            feat_module = feat.get(feat_key)
            if isinstance(feat_module, dict):
                # Try nested days[date] first (canonical shape), then
                # fall back to top-level date key for flat modules.
                days_sub = feat_module.get("days")
                if isinstance(days_sub, dict):
                    day_data[bundle_key] = days_sub.get(day_key)
                else:
                    day_data[bundle_key] = feat_module.get(day_key)
            else:
                day_data[bundle_key] = None

        # From days dict directly
        day_obj = feat_days.get(day_key, {})
        for dk in _DAILY_FROM_DAYS:
            bundle_name = dk.replace("gcs_daily", "gcs")
            day_data[bundle_name] = day_obj.get(dk) if isinstance(day_obj, dict) else None

        daily_section[day_key] = day_data

    # consultants
    consultants_section = feat.get("consultant_events_v1")

    # artifacts
    artifacts_section = {
        "evidence_path": str(evidence_path.relative_to(root.parent)),
        "timeline_path": str(timeline_path.relative_to(root.parent)),
        "features_path": str(features_path.relative_to(root.parent)),
        "ntds_summary_path": (
            str(ntds_summary_path.relative_to(root.parent))
            if ntds_summary_data is not None
            else None
        ),
        "protocol_results_path": (
            str(protocol_results_path.relative_to(root.parent))
            if protocol_results_data is not None
            else None
        ),
        "v5_report_path": (
            str(v5_path.relative_to(root.parent))
            if v5_path.is_file()
            else None
        ),
    }

    # warnings — inherit from features + add assembly warnings
    inherited_warnings = features.get("warnings", [])
    all_warnings = list(inherited_warnings) + warnings

    # ── Assemble top-level ──────────────────────────────────────

    bundle = {
        "build": {
            "bundle_version": BUNDLE_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "assembler": ASSEMBLER_NAME,
        },
        "patient": patient_section,
        "summary": summary_section,
        "compliance": compliance_section,
        "daily": daily_section,
        "consultants": consultants_section,
        "artifacts": artifacts_section,
        "warnings": all_warnings,
    }

    return bundle


def write_bundle(bundle: Dict[str, Any], out_path: Path) -> None:
    """Write bundle dict to JSON file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(bundle, indent=2, default=str, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ── CLI ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble patient_bundle_v1.json from pipeline outputs."
    )
    parser.add_argument("--slug", required=True, help="Patient slug (e.g. Betty_Roll)")
    parser.add_argument(
        "--out",
        required=True,
        help="Output path for patient_bundle_v1.json",
    )
    args = parser.parse_args()

    try:
        bundle = assemble_bundle(args.slug)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    write_bundle(bundle, Path(args.out))
    print(f"OK  Bundle written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
