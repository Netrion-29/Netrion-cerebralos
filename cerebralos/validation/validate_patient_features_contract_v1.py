#!/usr/bin/env python3
"""
Validate patient_features_v1.json against the locked output contract.

Checks:
  1. Top-level keys are EXACTLY the allowed set (no extras, no missing).
  2. "features" is a non-null dict.
  3. No known feature module keys leaked to the top level.
  4. Evidence entries in feature modules have raw_line_id (blocking).
  5. bd_series entries in base_deficit_monitoring_v1 have raw_line_id.
  6. vitals_canonical_v1 record entries have raw_line_id.

Exit codes:
  0 — contract valid
  1 — contract violation(s) detected

Usage:
    python3 cerebralos/validation/validate_patient_features_contract_v1.py \\
        --in outputs/features/Timothy_Cowan/patient_features_v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── Contract constants ──────────────────────────────────────────────

ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "build",
    "patient_id",
    "days",
    "evidence_gaps",
    "features",
    "warnings",
    "warnings_summary",
})

# Feature module keys that MUST live under "features", never at top level.
KNOWN_FEATURE_KEYS = frozenset({
    "vitals_canonical_v1",
    "dvt_prophylaxis_v1",
    "gi_prophylaxis_v1",
    "base_deficit_monitoring_v1",
    "inr_normalization_v1",
    "fast_exam_v1",
    "etoh_uds_v1",
    "impression_plan_drift_v1",
    "category_activation_v1",
    "shock_trigger_v1",
    "neuro_trigger_v1",
    "age_extraction_v1",
    "mechanism_region_v1",
    "vitals_qa",
})


# ── Validation logic ───────────────────────────────────────────────

def validate_contract(data: Dict[str, Any]) -> List[str]:
    """
    Validate patient_features_v1.json against the locked contract.

    Returns a list of error strings (empty = valid).
    """
    errors: List[str] = []

    top_keys = set(data.keys())

    # 1. No unexpected top-level keys
    extra_keys = sorted(top_keys - ALLOWED_TOP_LEVEL_KEYS)
    if extra_keys:
        errors.append(
            f"TOP_LEVEL_EXTRA_KEYS: unexpected keys at top level: {extra_keys}"
        )

    # 2. No missing required top-level keys
    missing_keys = sorted(ALLOWED_TOP_LEVEL_KEYS - top_keys)
    if missing_keys:
        errors.append(
            f"TOP_LEVEL_MISSING_KEYS: required keys missing: {missing_keys}"
        )

    # 3. "features" must be a non-null dict
    features_val = data.get("features")
    if features_val is None:
        errors.append("FEATURES_NULL: top-level 'features' is null/missing")
    elif not isinstance(features_val, dict):
        errors.append(
            f"FEATURES_TYPE_ERROR: 'features' must be dict, "
            f"got {type(features_val).__name__}"
        )

    # 4. No known feature keys leaked to top level
    leaked = sorted(KNOWN_FEATURE_KEYS & top_keys)
    if leaked:
        errors.append(
            f"LEAKED_FEATURE_KEYS: feature modules found at top level "
            f"(must be under 'features'): {leaked}"
        )

    # 5. Evidence raw_line_id spot-check (blocking — fail-fast on drift)
    if isinstance(features_val, dict):
        _check_evidence_line_ids(features_val, errors)

    return errors


def _check_evidence_line_ids(
    features: Dict[str, Any], errors: List[str],
) -> None:
    """
    Walk feature modules looking for evidence/series/records lists.
    Verify entries have raw_line_id.  This check is BLOCKING.
    """
    for feat_key, feat_val in features.items():
        if not isinstance(feat_val, dict):
            continue

        # ── "evidence" dict/list (dvt, gi, category_activation) ──
        evidence_container = feat_val.get("evidence")
        if evidence_container is not None:
            entries: list = []
            if isinstance(evidence_container, list):
                entries = evidence_container
            elif isinstance(evidence_container, dict):
                # e.g. {"pharm": [...], "exclusion": [...]}
                for sub_key, sub_val in evidence_container.items():
                    if isinstance(sub_val, list):
                        entries.extend(sub_val)

            missing_count = 0
            for entry in entries:
                if isinstance(entry, dict) and "raw_line_id" not in entry:
                    missing_count += 1

            if missing_count > 0:
                errors.append(
                    f"EVIDENCE_MISSING_RAW_LINE_ID: {feat_key} has "
                    f"{missing_count} evidence entry(ies) without raw_line_id"
                )

        # ── base_deficit_monitoring_v1.bd_series[] ──
        if feat_key == "base_deficit_monitoring_v1":
            bd_series = feat_val.get("bd_series", [])
            if isinstance(bd_series, list):
                bd_missing = sum(
                    1 for e in bd_series
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if bd_missing > 0:
                    errors.append(
                        f"BD_SERIES_MISSING_RAW_LINE_ID: "
                        f"{bd_missing} bd_series entry(ies) without raw_line_id"
                    )

        # ── inr_normalization_v1.inr_series[] ──
        if feat_key == "inr_normalization_v1":
            inr_series = feat_val.get("inr_series", [])
            if isinstance(inr_series, list):
                inr_missing = sum(
                    1 for e in inr_series
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if inr_missing > 0:
                    errors.append(
                        f"INR_SERIES_MISSING_RAW_LINE_ID: "
                        f"{inr_missing} inr_series entry(ies) without raw_line_id"
                    )

        # ── fast_exam_v1: top-level raw_line_id ──
        if feat_key == "fast_exam_v1":
            # fast_exam_v1 has a top-level raw_line_id when FAST is found
            # and evidence[] entries must also have raw_line_id.
            fast_evidence = feat_val.get("evidence", [])
            if isinstance(fast_evidence, list):
                fast_missing = sum(
                    1 for e in fast_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if fast_missing > 0:
                    errors.append(
                        f"FAST_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{fast_missing} evidence entry(ies) without raw_line_id"
                    )

        # ── etoh_uds_v1: evidence[] raw_line_id ──
        if feat_key == "etoh_uds_v1":
            eu_evidence = feat_val.get("evidence", [])
            if isinstance(eu_evidence, list):
                eu_missing = sum(
                    1 for e in eu_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if eu_missing > 0:
                    errors.append(
                        f"ETOH_UDS_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{eu_missing} evidence entry(ies) without raw_line_id"
                    )

        # ── impression_plan_drift_v1: evidence[] + drift_events[].evidence[] ──
        if feat_key == "impression_plan_drift_v1":
            ipd_evidence = feat_val.get("evidence", [])
            if isinstance(ipd_evidence, list):
                ipd_missing = sum(
                    1 for e in ipd_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if ipd_missing > 0:
                    errors.append(
                        f"IMPRESSION_PLAN_DRIFT_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{ipd_missing} evidence entry(ies) without raw_line_id"
                    )
            # Also check evidence within drift_events
            for de in feat_val.get("drift_events", []):
                if not isinstance(de, dict):
                    continue
                de_ev = de.get("evidence", [])
                if isinstance(de_ev, list):
                    de_missing = sum(
                        1 for e in de_ev
                        if isinstance(e, dict) and "raw_line_id" not in e
                    )
                    if de_missing > 0:
                        errors.append(
                            f"IMPRESSION_PLAN_DRIFT_EVENT_EVIDENCE_MISSING_RAW_LINE_ID: "
                            f"drift_event {de.get('date', '?')} has "
                            f"{de_missing} evidence entry(ies) without raw_line_id"
                        )

        # ── shock_trigger_v1: evidence[] raw_line_id ──
        if feat_key == "shock_trigger_v1":
            st_evidence = feat_val.get("evidence", [])
            if isinstance(st_evidence, list):
                st_missing = sum(
                    1 for e in st_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if st_missing > 0:
                    errors.append(
                        f"SHOCK_TRIGGER_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{st_missing} evidence entry(ies) without raw_line_id"
                    )

        # ── neuro_trigger_v1: evidence[] raw_line_id ──
        if feat_key == "neuro_trigger_v1":
            nt_evidence = feat_val.get("evidence", [])
            if isinstance(nt_evidence, list):
                nt_missing = sum(
                    1 for e in nt_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if nt_missing > 0:
                    errors.append(
                        f"NEURO_TRIGGER_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{nt_missing} evidence entry(ies) without raw_line_id"
                    )

        # ── age_extraction_v1: evidence[] raw_line_id ──
        if feat_key == "age_extraction_v1":
            ae_evidence = feat_val.get("evidence", [])
            if isinstance(ae_evidence, list):
                ae_missing = sum(
                    1 for e in ae_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if ae_missing > 0:
                    errors.append(
                        f"AGE_EXTRACTION_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{ae_missing} evidence entry(ies) without raw_line_id"
                    )

        # ── mechanism_region_v1: evidence[] raw_line_id ──
        if feat_key == "mechanism_region_v1":
            mr_evidence = feat_val.get("evidence", [])
            if isinstance(mr_evidence, list):
                mr_missing = sum(
                    1 for e in mr_evidence
                    if isinstance(e, dict) and "raw_line_id" not in e
                )
                if mr_missing > 0:
                    errors.append(
                        f"MECHANISM_REGION_EVIDENCE_MISSING_RAW_LINE_ID: "
                        f"{mr_missing} evidence entry(ies) without raw_line_id"
                    )

        # ── vitals_canonical_v1.days.<date>.records[] ──
        if feat_key == "vitals_canonical_v1":
            vc_days = feat_val.get("days", {})
            if isinstance(vc_days, dict):
                vc_missing = 0
                for day_key, day_val in vc_days.items():
                    if not isinstance(day_val, dict):
                        continue
                    for rec in day_val.get("records", []):
                        if isinstance(rec, dict) and "raw_line_id" not in rec:
                            vc_missing += 1
                if vc_missing > 0:
                    errors.append(
                        f"VITALS_CANONICAL_MISSING_RAW_LINE_ID: "
                        f"{vc_missing} record(s) without raw_line_id"
                    )


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate patient_features_v1.json contract",
    )
    ap.add_argument(
        "--in", dest="in_path", required=True,
        help="Path to patient_features_v1.json",
    )
    args = ap.parse_args()

    in_path = Path(args.in_path).expanduser().resolve()
    if not in_path.is_file():
        print(f"FAIL: input not found: {in_path}", file=sys.stderr)
        return 1

    with open(in_path, encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    errors = validate_contract(data)

    if errors:
        print(f"FAIL ❌  patient_features_v1 contract: "
              f"{len(errors)} violation(s):")
        for err in errors:
            print(f"  • {err}")
        return 1

    # Success summary
    features = data.get("features", {})
    top_keys = sorted(data.keys())
    feat_keys = sorted(features.keys()) if isinstance(features, dict) else []
    print(f"OK ✅  patient_features_v1 contract valid")
    print(f"  top_level_keys: {top_keys}")
    print(f"  features_keys: {feat_keys}")
    print(f"  leaked_feature_keys_at_top: []")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
