#!/usr/bin/env python3
"""
Precision regression tests for Event 21 (Ventilator-Associated Pneumonia)
noise filtering.

Verifies that vap_negation_noise patterns in the mapper correctly filter
negative imaging language, aspiration pneumonia contexts, and other
non-VAP mentions — while preserving true positive detection for actual
VAP evidence.

These tests operate at two levels:
  1. Regex-level: verify vap_negation_noise patterns match expected text
  2. Rule structure: verify E21 rule wiring is correct
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


# ─── vap_negation_noise: MUST match negative/non-VAP text ─────────────


class TestVapNegationNoiseMatches:
    """Noise patterns must catch common false-positive phrasings."""

    def test_no_consolidation(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "No dense consolidation seen on CXR."
        )

    def test_no_infiltrate(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "CXR: No infiltrate or effusion identified."
        )

    def test_no_opacity(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "No new opacity on chest film."
        )

    def test_no_acute_airspace_disease(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "No acute airspace disease."
        )

    def test_negative_for_consolidation(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "CXR negative for consolidation or pleural effusion."
        )

    def test_negative_for_pneumonia(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "Imaging negative for pneumonia."
        )

    def test_aspiration_pneumonia(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "Treated for aspiration pneumonia, not ventilator-associated."
        )

    def test_aspiration_pneumonitis(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "Aspiration pneumonitis suspected after intubation."
        )

    def test_ronald_marshall_fp_text(self):
        """FP case: Ronald_Marshall CXR with negated consolidation."""
        pats = _load_patterns()["vap_negation_noise"]
        assert _any_pattern_matches(
            pats, "CXR done 12/25: No dense consolidation seen"
        )


# ─── vap_negation_noise: must NOT match true positive VAP text ────────


class TestVapNegationNoiseRejects:
    """Noise patterns must NOT fire on true-positive VAP evidence."""

    def test_ventilator_associated_pneumonia(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "possible ventilator associated pneumonia"
        )

    def test_worsening_consolidation(self):
        """Worsening consolidation is positive evidence, not noise."""
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Worsening consolidation on CXR consistent with VAP"
        )

    def test_new_consolidation(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "New consolidation in RLL on chest X-ray"
        )

    def test_sputum_culture_positive(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "sputum culture positive for Pseudomonas"
        )

    def test_purulent_sputum(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "purulent sputum noted on ventilator day 5"
        )

    def test_new_infiltrate(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "New infiltrate on CXR, consistent with pneumonia"
        )

    def test_vap_diagnosed(self):
        pats = _load_patterns()["vap_negation_noise"]
        assert not _any_pattern_matches(
            pats, "VAP diagnosed on hospital day 7."
        )


# ─── vap_dx / vap_cxr: must still match positive text ─────────────────


class TestVapDxPositive:
    """Ensure vap_dx patterns still match true positive evidence."""

    def test_ventilator_associated_pneumonia(self):
        pats = _load_patterns()["vap_dx"]
        assert _any_pattern_matches(pats, "ventilator-associated pneumonia")

    def test_vap_abbreviation(self):
        pats = _load_patterns()["vap_dx"]
        assert _any_pattern_matches(pats, "VAP")

    def test_pneumonia_on_ventilator(self):
        pats = _load_patterns()["vap_dx"]
        assert _any_pattern_matches(
            pats, "pneumonia while on mechanical ventilation"
        )

    def test_sputum_culture_positive(self):
        pats = _load_patterns()["vap_dx"]
        assert _any_pattern_matches(pats, "sputum culture positive")

    def test_purulent_sputum(self):
        pats = _load_patterns()["vap_dx"]
        assert _any_pattern_matches(pats, "purulent sputum noted")


class TestVapCxrPositive:
    """Ensure vap_cxr patterns still match positive imaging evidence."""

    def test_new_infiltrate(self):
        pats = _load_patterns()["vap_cxr"]
        assert _any_pattern_matches(pats, "new infiltrate on imaging")

    def test_new_consolidation(self):
        pats = _load_patterns()["vap_cxr"]
        assert _any_pattern_matches(pats, "new consolidation in RLL")

    def test_cxr_consolidation(self):
        pats = _load_patterns()["vap_cxr"]
        assert _any_pattern_matches(
            pats, "CXR shows right lower lobe consolidation"
        )

    def test_chest_xray_infiltrate(self):
        pats = _load_patterns()["vap_cxr"]
        assert _any_pattern_matches(
            pats, "chest x-ray with bilateral infiltrate"
        )


# ─── Rule file structure validation ───────────────────────────────────


class TestVapRuleStructure:
    """Verify Event 21 rule wiring is correct."""

    def test_exclude_noise_keys_wiring(self):
        rule_path = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "21_vap.json"
        with open(rule_path) as f:
            rule = json.load(f)
        gates = {g["gate_id"]: g for g in rule["gates"]}
        assert set(gates.keys()) == {"vent_evidence", "vent_duration_lda", "vap_evidence"}
        assert "vap_negation_noise" in gates["vap_evidence"]["exclude_noise_keys"], \
            "vap_negation_noise must be wired into exclude_noise_keys"
        assert "history_noise" in gates["vap_evidence"]["exclude_noise_keys"], \
            "history_noise must still be present"

    def test_vap_negation_noise_exists_in_mapper(self):
        pats = _load_patterns()
        assert "vap_negation_noise" in pats, \
            "vap_negation_noise bucket must exist in mapper"
        assert len(pats["vap_negation_noise"]) >= 5, \
            "vap_negation_noise should have at least 5 patterns"

    def test_min_count_two(self):
        """VAP requires min_count 2 — two independent pieces of evidence."""
        rule_path = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "21_vap.json"
        with open(rule_path) as f:
            rule = json.load(f)
        gates = {g["gate_id"]: g for g in rule["gates"]}
        assert gates["vent_evidence"]["min_count"] == 1
        assert gates["vap_evidence"]["min_count"] == 2
