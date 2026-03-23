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
