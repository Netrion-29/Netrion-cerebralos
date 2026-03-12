#!/usr/bin/env python3
"""
Precision regression tests for Event 01 (AKI) — KDIGO Stage 3 spec fidelity.

Tests cover:
  - aki_stage3_lab: KDIGO Stage 3 lab/urine criteria patterns
  - aki_new_dialysis: new RRT/dialysis initiation patterns
  - aki_chronic_rrt: chronic RRT exclusion patterns
  - aki_onset (enhanced): hospital-acquired onset patterns
  - aki_dx (tightened): ATN/acute tubular necrosis additions
  - Rule structure: new gates and exclusions wired correctly

Tests operate at the regex level against mapper patterns.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPER_PATH = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "01_aki.json"


def _load_patterns() -> dict:
    with open(MAPPER_PATH) as f:
        data = json.load(f)
    return data.get("query_patterns", {})


def _any_pattern_matches(patterns: list, text: str) -> bool:
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ─── aki_stage3_lab: MUST match Stage 3 lab evidence ───────────────────


class TestAkiStage3LabMatches:
    """Patterns must detect KDIGO Stage 3 lab/urine criteria."""

    def test_creatinine_4_point_8(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Creatinine: 4.8 mg/dL")

    def test_creatinine_rose_to_5_1(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Creatinine rose to 5.1 from baseline 1.3.")

    def test_scr_at_4_0(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "SCr at 4.0 mg/dL, consistent with AKI stage 3.")

    def test_cr_peaked_at_6_2(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Cr peaked at 6.2 yesterday.")

    def test_creatinine_increased_to_12_4(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Creatinine increased to 12.4 mg/dL.")

    def test_3x_baseline(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Creatinine greater than 3x baseline.")

    def test_3_times_baseline(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "SCr rose to 3 times baseline value.")

    def test_greater_than_3x_baseline(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Creatinine 4.8, greater than 3x baseline.")

    def test_kdigo_stage_3(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "KDIGO stage 3 AKI.")

    def test_kdigo_3(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "KDIGO 3 criteria met.")

    def test_stage_3_aki(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Stage 3 AKI diagnosed on day 2.")

    def test_stage_3_acute_kidney_injury(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Stage 3 acute kidney injury confirmed.")

    def test_anuria(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Patient anuric for past 14 hours.")

    def test_anuric(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Patient is anuric, no urine output recorded.")

    def test_no_urine_output(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "No urine output documented for last 12 hours.")

    def test_urine_output_less_than_50(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Urine output < 50 mL in 12 hours.")

    def test_creatinine_gte_4(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert _any_pattern_matches(pats, "Creatinine >= 4.0 mg/dL")


class TestAkiStage3LabRejects:
    """Stage 3 patterns must NOT fire on sub-threshold values."""

    def test_creatinine_1_8(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert not _any_pattern_matches(pats, "Creatinine: 1.8 mg/dL")

    def test_creatinine_2_5(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert not _any_pattern_matches(pats, "Creatinine: 2.5 mg/dL, stage 1 AKI.")

    def test_creatinine_3_6_no_baseline(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert not _any_pattern_matches(pats, "Creatinine: 3.6 mg/dL")

    def test_normal_urine_output(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert not _any_pattern_matches(pats, "Urine output adequate at 0.8 mL/kg/hr.")

    def test_gfr_value(self):
        pats = _load_patterns()["aki_stage3_lab"]
        assert not _any_pattern_matches(pats, "GFR: 42 mL/min")


# ─── aki_new_dialysis: MUST match new RRT initiation ──────────────────


class TestAkiNewDialysisMatches:
    """Patterns must detect new dialysis/RRT initiation."""

    def test_initiated_hemodialysis(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Initiated hemodialysis emergently.")

    def test_started_dialysis(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Started dialysis today for acute renal failure.")

    def test_hemodialysis_initiated(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Hemodialysis initiated for fluid overload.")

    def test_rrt_started(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Renal replacement therapy started emergently.")

    def test_initiation_of_rrt(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Initiation of renal replacement therapy planned.")

    def test_crrt_initiated(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "CRRT initiated in ICU for volume management.")

    def test_cvvh_ordered(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "CVVH ordered for AKI.")

    def test_emergent_dialysis(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Emergent dialysis required for hyperkalemia.")

    def test_continuous_venovenous_hemofiltration(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Continuous veno-venous hemofiltration initiated.")

    def test_new_hemodialysis(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "New hemodialysis for AKI management.")

    def test_began_crrt(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Began CRRT overnight for worsening AKI.")

    def test_dialysis_planned(self):
        pats = _load_patterns()["aki_new_dialysis"]
        assert _any_pattern_matches(pats, "Dialysis planned for tomorrow morning.")


# ─── aki_chronic_rrt: MUST match chronic RRT ───────────────────────────


class TestAkiChronicRrtMatches:
    """Patterns must detect chronic/maintenance RRT."""

    def test_chronic_hemodialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "Chronic hemodialysis patient.")

    def test_maintenance_hemodialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "Maintenance hemodialysis three times weekly.")

    def test_maintenance_dialysis_mwf(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "On hemodialysis MWF schedule.")

    def test_long_term_dialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "Long-term dialysis via AV fistula.")

    def test_esrd_on_hemodialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "ESRD on hemodialysis Monday Wednesday Friday.")

    def test_esrd_requiring_dialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "ESRD requiring dialysis.")

    def test_chronic_rrt(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "Chronic renal replacement therapy for 3 years.")

    def test_maintenance_dialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert _any_pattern_matches(pats, "Maintenance dialysis patient, MWF.")


class TestAkiChronicRrtRejects:
    """Chronic RRT patterns must NOT fire on new/acute dialysis starts."""

    def test_initiated_hemodialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert not _any_pattern_matches(pats, "Initiated hemodialysis emergently for AKI.")

    def test_started_dialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert not _any_pattern_matches(pats, "Started dialysis today for volume overload.")

    def test_emergent_hemodialysis(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert not _any_pattern_matches(pats, "Emergent hemodialysis required.")

    def test_new_rrt(self):
        pats = _load_patterns()["aki_chronic_rrt"]
        assert not _any_pattern_matches(pats, "New renal replacement therapy initiated.")


# ─── aki_onset (enhanced): MUST match expanded onset patterns ──────────


class TestAkiOnsetEnhanced:
    """Enhanced onset patterns for hospital-acquired AKI."""

    def test_hospital_acquired_aki(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "Hospital-acquired AKI noted on day 3.")

    def test_new_onset_aki(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "New-onset AKI during admission.")

    def test_aki_developed_during(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "AKI developed during hospitalization.")

    def test_aki_diagnosed_after(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "AKI diagnosed after admission to ward.")

    def test_postoperative_aki(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "Post-operative acute kidney injury documented.")

    def test_post_admission_renal_failure(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "Post-admission renal failure requiring nephrology consult.")

    def test_creatinine_began_rising(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "Creatinine began rising on hospital day 2.")

    def test_creatinine_started_trending_up(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "Creatinine started trending up after surgery.")

    def test_aki_during_admission(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "AKI during admission, creatinine 4.2.")

    def test_developed_aki_during_stay(self):
        pats = _load_patterns()["aki_onset"]
        assert _any_pattern_matches(pats, "Developed AKI during stay.")


# ─── aki_dx (tightened): ATN / acute tubular necrosis ──────────────────


class TestAkiDxTightened:
    """Tightened aki_dx patterns now include ATN."""

    def test_acute_tubular_necrosis(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Acute tubular necrosis diagnosed.")

    def test_atn_abbreviation(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "ATN likely secondary to hypotension.")

    def test_creatinine_increasing(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Creatinine increasing despite fluids.")


# ─── Rule structure: new gates and exclusions wired correctly ──────────


class TestAkiRuleStructureV2:
    """Updated AKI rule wiring with KDIGO Stage 3 gates."""

    def test_version_is_2(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        assert rule["meta"]["version"] == "2.0.0"

    def test_has_three_gates(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        assert len(rule["gates"]) == 3

    def test_aki_dx_gate_exists(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        gate_ids = [g["gate_id"] for g in rule["gates"]]
        assert "aki_dx" in gate_ids

    def test_aki_stage3_gate_exists(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        gate_ids = [g["gate_id"] for g in rule["gates"]]
        assert "aki_stage3" in gate_ids

    def test_aki_stage3_uses_two_query_keys(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        stage3 = [g for g in rule["gates"] if g["gate_id"] == "aki_stage3"][0]
        assert "aki_stage3_lab" in stage3["query_keys"]
        assert "aki_new_dialysis" in stage3["query_keys"]

    def test_aki_stage3_excludes_chronic_rrt(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        stage3 = [g for g in rule["gates"] if g["gate_id"] == "aki_stage3"][0]
        assert "aki_chronic_rrt" in stage3["exclude_noise_keys"]

    def test_aki_dx_has_nursing_note(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        dx = [g for g in rule["gates"] if g["gate_id"] == "aki_dx"][0]
        assert "NURSING_NOTE" in dx["allowed_sources"]

    def test_aki_dx_has_progress_note(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        dx = [g for g in rule["gates"] if g["gate_id"] == "aki_dx"][0]
        assert "PROGRESS_NOTE" in dx["allowed_sources"]

    def test_timing_gate_has_nursing_note(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        timing = [g for g in rule["gates"] if g["gate_id"] == "aki_after_arrival"][0]
        assert "NURSING_NOTE" in timing["allowed_sources"]

    def test_timing_gate_has_progress_note(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        timing = [g for g in rule["gates"] if g["gate_id"] == "aki_after_arrival"][0]
        assert "PROGRESS_NOTE" in timing["allowed_sources"]

    def test_two_exclusions(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        assert len(rule["exclusions"]) == 2

    def test_excl_poa_exists(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        excl_ids = [e["gate_id"] for e in rule["exclusions"]]
        assert "aki_excl_poa" in excl_ids

    def test_excl_chronic_rrt_exists(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        excl_ids = [e["gate_id"] for e in rule["exclusions"]]
        assert "aki_excl_chronic_rrt" in excl_ids

    def test_excl_chronic_rrt_uses_aki_chronic_rrt_key(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        excl = [e for e in rule["exclusions"] if e["gate_id"] == "aki_excl_chronic_rrt"][0]
        assert "aki_chronic_rrt" in excl["query_keys"]

    def test_reporting_section_exists(self):
        with open(RULE_PATH) as f:
            rule = json.load(f)
        assert "reporting" in rule
        assert rule["reporting"]["if_excluded"] == "EXCLUDED"
        assert rule["reporting"]["if_all_required_gates_pass"] == "YES"

    def test_mapper_stage3_lab_key_exists(self):
        pats = _load_patterns()
        assert "aki_stage3_lab" in pats
        assert len(pats["aki_stage3_lab"]) >= 10

    def test_mapper_new_dialysis_key_exists(self):
        pats = _load_patterns()
        assert "aki_new_dialysis" in pats
        assert len(pats["aki_new_dialysis"]) >= 4

    def test_mapper_chronic_rrt_key_exists(self):
        pats = _load_patterns()
        assert "aki_chronic_rrt" in pats
        assert len(pats["aki_chronic_rrt"]) >= 4

    def test_mapper_onset_has_enhanced_patterns(self):
        pats = _load_patterns()
        assert len(pats["aki_onset"]) >= 10
