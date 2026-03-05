#!/usr/bin/env python3
"""
Precision regression tests for Event 18 (Unplanned ICU Admission) noise filtering.

Verifies that icu_negation_noise patterns in the mapper correctly filter
EHR order-set metadata, planned/elective/scheduled ICU admission language,
and protocol template text — while preserving true positive detection
for actual unplanned ICU admissions.

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


# ─── icu_negation_noise: MUST match false-positive / noise text ─────────


class TestIcuNegationNoiseMatches:
    """Noise patterns must catch all common false-positive phrasings."""

    # --- EHR order-set metadata ---

    def test_order_part_of_order_set_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Order part of Order Set: DHS IP ICU ADMISSION",
        )

    def test_order_set_colon_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Order Set: DHS IP ICU ADMISSION",
        )

    def test_dhs_ip_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "DHS IP ICU medication orders",
        )

    def test_order_part_of_icu_panel(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Order part of ICU admission panel",
        )

    def test_order_set_of_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Order set of ICU admission orders",
        )

    # --- ICU admission order/protocol/bundle ---

    def test_icu_admission_order(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ICU admission order set completed.",
        )

    def test_icu_admission_panel(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ICU admission panel activated.",
        )

    def test_icu_admission_protocol(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ICU admission protocol followed.",
        )

    def test_icu_admission_bundle(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ICU admission bundle initiated.",
        )

    # --- Planned/elective/scheduled ICU ---

    def test_planned_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Planned ICU admission post-operatively.",
        )

    def test_elective_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Elective ICU admission for monitoring after surgery.",
        )

    def test_scheduled_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Scheduled ICU admission for post-cardiac surgery.",
        )

    def test_routine_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Routine ICU admission per protocol.",
        )

    # --- ICU admission criteria (template) ---

    def test_icu_admission_criteria(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ICU admission criteria not met.",
        )

    # --- Post-op planned ICU ---

    def test_postop_planned_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Post-op planned ICU stay for monitoring.",
        )

    def test_postoperative_routine_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Postoperative routine ICU observation.",
        )

    def test_postop_scheduled_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Post-op scheduled ICU admission.",
        )

    # --- Explicit negation ---

    def test_no_evidence_of_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "No evidence of need for ICU level care.",
        )

    def test_no_signs_of_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "No signs of ICU-level deterioration.",
        )

    # --- Full evidence text from Timothy_Nachtwey (the false positive) ---

    def test_timothy_nachtwey_order_set_line(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Order part of Order Set: DHS IP ICU ADMISSION",
        )


# ─── icu_negation_noise: MUST NOT match true positive text ──────────────


class TestIcuNegationNoiseRejects:
    """Noise patterns must NOT catch genuine unplanned ICU admission evidence."""

    def test_icu_admission_for_vent_management(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "hypoxemic and unable to be extubated post op prompting icu admission with critical care consult for vent management",
        )

    def test_transferred_to_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient transferred to ICU for respiratory failure.",
        )

    def test_upgraded_to_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Upgraded to ICU due to hemodynamic instability.",
        )

    def test_admitted_to_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Admitted to ICU for septic shock management.",
        )

    def test_icu_admission_clinical(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "ICU admission warranted for acute decompensation.",
        )

    def test_transfer_to_intensive_care(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Transfer to the intensive care unit for closer monitoring.",
        )

    def test_requiring_icu_admission(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Requiring ICU admission due to respiratory distress.",
        )

    def test_patient_currently_in_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient currently in the ICU. Doing well.",
        )

    def test_continue_care_in_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Continue care in ICU.",
        )

    def test_okay_to_transfer_out_of_icu(self):
        pats = _load_patterns()["icu_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Okay to transfer out of ICU.",
        )


# ─── unplanned_icu: MUST still match positive evidence ──────────────────


class TestUnplannedIcuDxPositive:
    """The unplanned_icu query patterns must still fire on true positives."""

    def test_transferred_to_icu(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(pats, "Patient transferred to ICU.")

    def test_upgraded_to_icu(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(pats, "Upgraded to ICU for monitoring.")

    def test_icu_admission(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(pats, "ICU admission required.")

    def test_admitted_to_icu(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(pats, "Admitted to ICU per critical care.")

    def test_transfer_to_intensive_care(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(
            pats,
            "Transfer to the intensive care unit.",
        )

    def test_transferred_to_intensive_care(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(
            pats,
            "Transferred to intensive care for respiratory failure.",
        )

    def test_icu_admission_with_consult(self):
        pats = _load_patterns()["unplanned_icu"]
        assert _any_pattern_matches(
            pats,
            "prompting icu admission with critical care consult",
        )


# ─── Rule structure / wiring ────────────────────────────────────────────


class TestIcuRuleStructure:
    """Rule file wiring: icu_negation_noise must be active."""

    RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "18_unplanned_icu_admission.json"

    def test_exclude_noise_keys_wired(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "icu_negation_noise" in gate["exclude_noise_keys"]

    def test_icu_negation_noise_bucket_exists_in_mapper(self):
        pats = _load_patterns()
        assert "icu_negation_noise" in pats
        assert len(pats["icu_negation_noise"]) >= 8

    def test_gate_still_requires_unplanned_icu_key(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "unplanned_icu" in gate["query_keys"]
