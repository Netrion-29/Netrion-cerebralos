#!/usr/bin/env python3
"""
Precision regression tests for Event 10 (Myocardial Infarction) noise filtering.

Verifies that mi_negation_noise patterns in the mapper correctly filter
negative EKG findings, HCC billing codes, negative troponin results,
workup/rule-out contexts, and "without evidence" negation — while
preserving true positive detection for actual MI diagnoses.

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


# ─── mi_negation_noise: MUST match false-positive / noise text ─────────


class TestMiNegationNoiseMatches:
    """Noise patterns must catch all common false-positive phrasings."""

    def test_no_stemi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Normal sinus rhythm. Heart rate 105.  No STEMI.   Normal PR, QRS, and QT intervals.",
        )

    def test_no_nstemi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(pats, "No NSTEMI identified on workup.")

    def test_no_myocardial_infarction(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "No myocardial infarction identified."
        )

    def test_no_acute_myocardial_infarction(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "No acute myocardial infarction on imaging."
        )

    def test_no_evidence_of_myocardial_infarction(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Coronary artery disease, involving left main and proximal LAD, no evidence of acute myocardial infarction",
        )

    def test_without_evidence_of_myocardial_infarction(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Coronary artery disease, involving left main and proximal LAD, without evidence of acute plaque rupture or myocardial infarction",
        )

    def test_troponin_negative(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Repeat labs:  CBC shows mild anemia.  Initial troponin T negative.",
        )

    def test_negative_troponin(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "negative troponin on admission"
        )

    def test_no_culprit_lesion_for_nstemi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "2 vessel CAD with probably significant disease in the LAD with no obvious culprit lesion for NSTEMI",
        )

    def test_no_culprit_for_stemi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "No culprit for STEMI identified."
        )

    def test_hcc_billing_code(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "MI (myocardial infarction) (HCC)"
        )

    def test_hcc_with_date(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "MI (myocardial infarction) (HCC)\t2007"
        )

    def test_hcc_no_date(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "No date: MI (myocardial infarction) (HCC)"
        )

    def test_no_acute_coronary_syndrome(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "No acute coronary syndrome identified."
        )

    def test_rule_out_mi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "Admit to telemetry to rule out MI."
        )

    def test_rule_out_nstemi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "Serial troponins to rule out NSTEMI."
        )

    def test_ro_stemi(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "EKG ordered to r/o STEMI."
        )

    def test_rule_out_myocardial_infarction(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert _any_pattern_matches(
            pats, "Troponin obtained to rule out myocardial infarction."
        )


# ─── mi_negation_noise: must NOT match true positive text ─────────────


class TestMiNegationNoiseRejects:
    """Noise patterns must NOT fire on true-positive MI evidence."""

    def test_nstemi_discharge_positive(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(pats, "NSTEMI")

    def test_nstemi_with_troponin(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Elevated troponin - NSTEMI vs cardiac injury due to CPR/defibrillation",
        )

    def test_elevated_troponin_plain(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Elevated troponin, consistent with acute MI."
        )

    def test_stemi_positive(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "STEMI confirmed on 12-lead EKG."
        )

    def test_acute_myocardial_infarction(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Acute myocardial infarction diagnosed."
        )

    def test_st_elevation_myocardial(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "ST segment elevation consistent with myocardial injury."
        )

    def test_acute_coronary_syndrome_positive(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Patient presents with acute coronary syndrome."
        )

    def test_troponin_significantly_elevated(self):
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Troponin significantly elevated at 2.4 ng/mL."
        )

    def test_nstemi_versus_cardiac_injury(self):
        """This is clinically ambiguous but contains genuine NSTEMI mention."""
        pats = _load_patterns()["mi_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Elevated troponin, NSTEMI versus acute myocardial injury post CPR/defibrillation",
        )


# ─── mi_dx: must still match positive diagnostic text ─────────────────


class TestMiDxPositive:
    """Ensure mi_dx patterns still match true positive evidence."""

    def test_myocardial_infarction(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(pats, "acute myocardial infarction")

    def test_stemi(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(pats, "STEMI on EKG")

    def test_nstemi(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(pats, "NSTEMI")

    def test_st_elevation(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(
            pats, "ST segment elevation with myocardial injury"
        )

    def test_acute_coronary_syndrome(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(pats, "acute coronary syndrome")

    def test_troponin_elevated(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(pats, "troponin significantly elevated")

    def test_troponin_elevation(self):
        pats = _load_patterns()["mi_dx"]
        assert _any_pattern_matches(pats, "troponin elevation noted")


# ─── Rule file structure validation ───────────────────────────────────


class TestMiRuleStructure:
    """Verify Event 10 rule wiring is correct."""

    def test_exclude_noise_keys_wiring(self):
        rule_path = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "10_mi.json"
        with open(rule_path) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert gate["gate_id"] == "mi_dx"
        assert "mi_negation_noise" in gate["exclude_noise_keys"], \
            "mi_negation_noise must be wired into exclude_noise_keys"

    def test_mi_negation_noise_exists_in_mapper(self):
        pats = _load_patterns()
        assert "mi_negation_noise" in pats, \
            "mi_negation_noise bucket must exist in mapper"
        assert len(pats["mi_negation_noise"]) >= 10, \
            "mi_negation_noise should have at least 10 patterns"

    def test_mi_dx_patterns_unchanged(self):
        """Guard: mi_dx patterns must not be modified by this PR."""
        pats = _load_patterns()["mi_dx"]
        expected = [
            "\\bmyocardial\\s+infarction\\b",
            "\\bSTEMI\\b",
            "\\bNSTEMI\\b",
            "\\bST\\s+(segment\\s+)?elevation\\b.*\\bmyocardial\\b",
            "\\bacute\\s+coronary\\s+syndrome\\b",
            "\\btroponin\\b.*\\b(significantly\\s+)?elevat(ed|ion)\\b",
        ]
        assert pats == expected, "mi_dx patterns must remain unchanged"
