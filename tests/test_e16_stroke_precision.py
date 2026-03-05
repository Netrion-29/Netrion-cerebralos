#!/usr/bin/env python3
"""
Precision regression tests for Event 16 (Stroke/CVA) noise filtering.

Verifies that stroke_negation_noise patterns in the mapper correctly
filter negative CT imaging language, prevention contexts, and other
non-diagnostic mentions of stroke/CVA — while preserving true positive
detection for actual stroke/CVA diagnoses.

These tests operate at two levels:
  1. Regex-level: verify stroke_negation_noise patterns match expected text
  2. Engine-level: verify full evaluation with synthetic evidence
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


# ─── stroke_negation_noise: MUST match negative/non-diagnostic text ────


class TestStrokeNegationNoiseMatches:
    """Noise patterns must catch all common false-positive phrasings."""

    def test_no_acute_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "No acute intracranial hemorrhage. No mass effect or midline shift."
        )

    def test_no_evidence_of_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "No evidence of intracranial hemorrhage.  There are no focal abnormal densities."
        )

    def test_no_evidence_of_acute_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "IMPRESSION: No evidence of acute intracranial hemorrhage or skull fracture."
        )

    def test_no_overt_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "I have reviewed the imaging and CT head in my opinion showing no overt intracranial hemorrhage"
        )

    def test_no_new_acute_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "No new acute intracranial hemorrhage/abnormality or mass effect."
        )

    def test_without_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "Repeat CT head without intracranial hemorrhage."
        )

    def test_no_acute_stroke(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "The midline structures are nondisplaced. No acute stroke, hemorrhage, edema or mass effect."
        )

    def test_no_acute_ischemic_stroke(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "No acute ischemic stroke identified."
        )

    def test_no_evidence_of_list_negation(self):
        """Catch list-style negation: 'No evidence of X, Y, or intracranial hemorrhage'."""
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "No evidence of acute infarct, mass lesion, abnormal extra-axial fluid, or intracranial hemorrhage.",
        )

    def test_negative_for_stroke(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "MRI brain negative for stroke or acute infarct."
        )

    def test_negative_for_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "CT head negative for intracranial hemorrhage."
        )

    def test_no_cerebral_infarction(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "No cerebral infarction identified on imaging."
        )

    def test_no_acute_cerebral_infarction(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "No acute cerebral infarction."
        )

    def test_cva_prevention(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "-Chronic OAC for CVA prevention: None (s/p LAA ligation)"
        )

    def test_stroke_prevention(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert _any_pattern_matches(
            pats, "Continue aspirin for stroke prevention."
        )


# ─── stroke_negation_noise: must NOT match true positive text ──────────


class TestStrokeNegationNoiseRejects:
    """Noise patterns must NOT fire on true-positive stroke evidence."""

    def test_actual_intracranial_hemorrhage_positive(self):
        """Positive mention of ICH without negation must not be filtered."""
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Neurology and Neurosurgery consult in view of dysphasia and intracranial hemorrhage.",
        )

    def test_acute_intracranial_hemorrhage_positive(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats, "acute intracranial hemorrhage/abnormality or mass effect."
        )

    def test_chads_vasc_intracranial_hemorrhage(self):
        """Clinical discussion of actual ICH should not be caught by noise."""
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "discussed risks versus benefits of anticoagulation in the context of intracranial hemorrhage and recurrent falls",
        )

    def test_acute_stroke_diagnosed(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Patient diagnosed with acute ischemic stroke, NIHSS 14."
        )

    def test_cerebrovascular_accident(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Acute cerebrovascular accident confirmed on MRI."
        )

    def test_hemorrhagic_stroke(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Hemorrhagic stroke identified in right MCA territory."
        )

    def test_nihss_score(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats, "NIHSS score 8 on arrival, consistent with moderate stroke."
        )

    def test_cerebral_infarction_positive(self):
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats, "MRI confirms acute cerebral infarction in left parietal lobe."
        )

    def test_subarachnoid_hemorrhage(self):
        """Positive subarachnoid hemorrhage phrasing should not match negation noise."""
        pats = _load_patterns()["stroke_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Mildly increased moderate subarachnoid hemorrhage within the bilateral inferior occipital lobes.",
        )


# ─── stroke_dx: must still match positive diagnostic text ─────────────


class TestStrokeDxPositive:
    """Ensure stroke_dx patterns still match true positive evidence."""

    def test_acute_stroke(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "acute stroke confirmed")

    def test_acute_ischemic_stroke(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "acute ischemic stroke identified")

    def test_cva(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "CVA")

    def test_cerebrovascular_accident(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "cerebrovascular accident")

    def test_cerebral_infarction(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "cerebral infarction on MRI")

    def test_intracranial_hemorrhage(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "intracranial hemorrhage identified")

    def test_hemorrhagic_stroke(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "hemorrhagic stroke in right hemisphere")

    def test_nihss(self):
        pats = _load_patterns()["stroke_dx"]
        assert _any_pattern_matches(pats, "NIHSS score 12")


# ─── Rule file structure validation ───────────────────────────────────


class TestStrokeRuleStructure:
    """Verify Event 16 rule wiring is correct."""

    def test_exclude_noise_keys_wiring(self):
        rule_path = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "16_stroke_cva.json"
        with open(rule_path) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert gate["gate_id"] == "stroke_dx"
        assert "stroke_negation_noise" in gate["exclude_noise_keys"], \
            "stroke_negation_noise must be wired into exclude_noise_keys"

    def test_stroke_negation_noise_exists_in_mapper(self):
        pats = _load_patterns()
        assert "stroke_negation_noise" in pats, \
            "stroke_negation_noise bucket must exist in mapper"
        assert len(pats["stroke_negation_noise"]) >= 8, \
            "stroke_negation_noise should have at least 8 patterns"

    def test_stroke_dx_patterns_unchanged(self):
        """Guard: stroke_dx patterns must not be modified by this PR."""
        pats = _load_patterns()["stroke_dx"]
        expected = [
            "\\bacute\\s+(ischemic\\s+)?stroke\\b",
            "\\bcerebrovascular\\s+accident\\b",
            "\\bCVA\\b",
            "\\bcerebral\\s+infarction\\b",
            "\\bintracranial\\s+hemorrhage\\b",
            "\\bhemorrhagic\\s+stroke\\b",
            "\\bNIHSS\\b",
        ]
        assert pats == expected, "stroke_dx patterns must remain unchanged"
