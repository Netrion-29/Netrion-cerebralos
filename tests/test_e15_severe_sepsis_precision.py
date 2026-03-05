#!/usr/bin/env python3
"""
Precision regression tests for Event 15 (Severe Sepsis) noise filtering.

Verifies that sepsis_negation_noise patterns in the mapper correctly filter
HCC billing code descriptors, ICD-10 code language, sepsis screening criteria
templates, and explicit negation — while preserving true positive detection
for actual severe sepsis diagnoses.

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


def _load_patterns() -> dict:
    with open(MAPPER_PATH) as f:
        data = json.load(f)
    return data.get("query_patterns", {})


def _any_pattern_matches(patterns: list, text: str) -> bool:
    """Return True if any pattern in the list matches text (case-insensitive)."""
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ─── sepsis_negation_noise: MUST match false-positive / noise text ──────


class TestSepsisNegationNoiseMatches:
    """Noise patterns must catch all common false-positive phrasings."""

    # --- HCC billing code ---

    def test_hcc_billing_marker(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis, due to unspecified organism, unspecified whether acute organ dysfunction present (HCC)",
        )

    def test_hcc_in_admission_dx_list(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "T12 burst fracture (HCC), Sepsis, due to unspecified organism (HCC)",
        )

    # --- ICD-10 code descriptor language ---

    def test_due_to_unspecified_organism(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis, due to unspecified organism",
        )

    def test_unspecified_whether_organ_dysfunction(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "unspecified whether acute organ dysfunction present",
        )

    # --- Sepsis screening criteria templates ---

    def test_sepsis_criteria_header(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis Criteria",
        )

    def test_sirs_criteria(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "SIRS criteria and a known or suspected infection",
        )

    def test_sepsis_screening(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis screening performed on admission.",
        )

    def test_sepsis_screen(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis screen negative.",
        )

    # --- Sepsis panel / bundle / protocol ---

    def test_sepsis_panel(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ensure that the Sepsis Panel has been ordered",
        )

    def test_sepsis_bundle(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis bundle compliance documented.",
        )

    # --- Explicit negative assessments ---

    def test_organ_dysfunction_none(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Sepsis related organ dysfunction: None",
        )

    def test_organ_dysfunction_colon_none(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "organ dysfunction:None",
        )

    # --- Rule out / negation ---

    def test_rule_out_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Rule out sepsis. Blood cultures pending.",
        )

    def test_rule_out_septic_shock(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Rule out septic shock in this patient.",
        )

    def test_ro_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "r/o sepsis, started empiric antibiotics.",
        )

    def test_no_evidence_of_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "No evidence of sepsis at this time.",
        )

    def test_no_signs_of_septic_shock(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "No signs of septic shock.",
        )

    def test_no_sign_of_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "No sign of sepsis currently.",
        )

    # --- Reminder / template text ---

    def test_as_a_reminder_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "As a reminder, please ensure that the Sepsis Panel has been ordered and the patient's problem list has been updated to include appropriate diagnosis at this time (severe sepsis, septic shock, etc.)",
        )

    # --- Full evidence text from Wilma_Yates (the false positive) ---

    def test_wilma_yates_nutrition_note(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Patient was admitted with T12 burst fracture (HCC), Closed fracture of multiple ribs of right side, initial encounter, Diabetic ketoacidosis without coma associated with other specified diabetes mellitus (HCC), Motor vehicle collision, initial encounter, Sepsis, due to unspecified organism, unspecified whether acute organ dysfunction present (HCC).",
        )


# ─── sepsis_negation_noise: MUST NOT match true positive text ───────────


class TestSepsisNegationNoiseRejects:
    """Noise patterns must NOT catch genuine severe sepsis evidence."""

    def test_patient_with_severe_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient with severe sepsis.  Gurgly.  Rule out aspiration pneumonia.",
        )

    def test_severe_sepsis_diagnosis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Diagnosis: severe sepsis secondary to pneumonia.",
        )

    def test_septic_shock_requiring_vasopressors(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Septic shock requiring vasopressor support.",
        )

    def test_sepsis_with_organ_dysfunction(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Sepsis with organ dysfunction documented.",
        )

    def test_organ_dysfunction_from_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Organ dysfunction secondary to sepsis.",
        )

    def test_lactate_elevated(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Lactate elevated at 4.2 mmol/L consistent with severe sepsis.",
        )

    def test_vasopressor_infusion_required(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Vasopressor infusion required for hemodynamic support.",
        )

    def test_sepsis_ongoing_issue(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Sepsis, an ongoing issue.",
        )

    def test_id_consult_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "ID consult called regarding antimicrobial management of her sepsis.",
        )

    def test_admitted_with_severe_sepsis(self):
        pats = _load_patterns()["sepsis_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient admitted with severe sepsis and multiple organ failure.",
        )


# ─── sepsis_dx: MUST still match positive evidence ─────────────────────


class TestSepsisDxPositive:
    """The sepsis_dx query patterns must still fire on true positives."""

    def test_severe_sepsis(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(pats, "Patient with severe sepsis.")

    def test_septic_shock(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(pats, "Septic shock requiring pressors.")

    def test_sepsis_organ_dysfunction(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(
            pats,
            "Sepsis with organ dysfunction documented.",
        )

    def test_organ_dysfunction_sepsis(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(
            pats,
            "Organ dysfunction secondary to sepsis.",
        )

    def test_lactate_elevated(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(
            pats,
            "Lactate elevated at 4.2 mmol/L.",
        )

    def test_lactate_elevation(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(
            pats,
            "Significant lactate elevation noted.",
        )

    def test_vasopressor_support(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(
            pats,
            "Vasopressor support initiated for septic shock.",
        )

    def test_vasopressor_infusion(self):
        pats = _load_patterns()["sepsis_dx"]
        assert _any_pattern_matches(
            pats,
            "Vasopressor infusion required.",
        )


# ─── Rule structure / wiring ────────────────────────────────────────────


class TestSepsisRuleStructure:
    """Rule file wiring: sepsis_negation_noise must be active."""

    RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "15_severe_sepsis.json"

    def test_exclude_noise_keys_wired(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "sepsis_negation_noise" in gate["exclude_noise_keys"]

    def test_sepsis_negation_noise_bucket_exists_in_mapper(self):
        pats = _load_patterns()
        assert "sepsis_negation_noise" in pats
        assert len(pats["sepsis_negation_noise"]) >= 10

    def test_gate_still_requires_sepsis_dx_key(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "sepsis_dx" in gate["query_keys"]
