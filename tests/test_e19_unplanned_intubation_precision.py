#!/usr/bin/env python3
"""
Precision regression tests for Event 19 (Unplanned Intubation) noise filtering.

Verifies that intubation_negation_noise patterns in the mapper correctly filter
radiology tube-positioning descriptions, planned/elective/OR intubation language,
and multi-tube radiology enumeration — while preserving true positive detection
for actual unplanned/emergent intubation events.

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


# ─── intubation_negation_noise: MUST match false-positive / noise text ──


class TestIntubationNegationNoiseMatches:
    """Noise patterns must catch all common false-positive phrasings."""

    # --- Radiology tube positioning ---

    def test_ett_tip_at_carina(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube tip is at the carina",
        )

    def test_ett_tip_projects(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube tip projects over the midthoracic trachea approximately 7.7 cm superior to the carina.",
        )

    def test_ett_terminates_right_mainstem(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "2. The endotracheal tube terminates within the right mainstem bronchus.",
        )

    def test_ett_terminates_midthoracic(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Visualized neck: Endotracheal tube terminates in the midthoracic trachea.",
        )

    def test_ett_is_cm_measurement(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube is 6 cm.  Enteric tube is in stomach.  Right-sided central",
        )

    def test_ett_is_above_carina(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "combination of all these.  Endotracheal tube is 3.5 cm above the carina.",
        )

    def test_ett_projects_over(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube projects over the midthoracic trachea.",
        )

    def test_ett_in_place(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube in place with its tip at the carina; recommend retraction by",
        )

    def test_ett_in_situ(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube in situ.  Airways are patent.",
        )

    def test_follow_up_ett_location(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Follow-up endotracheal tube location",
        )

    def test_tubes_and_lines_section(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "TUBES and LINES:  Unchanged. Specifically, the endotracheal tube tip projects",
        )

    def test_ett_placement_radiology_header(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Endotracheal tube placement",
        )

    # --- Multi-tube radiology enumeration ---

    def test_enteric_before_endotracheal(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Subdiaphragmatic enteric tube tip projects over the stomach. Endotracheal tube",
        )

    def test_nasogastric_before_endotracheal(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Nasogastric tube is in stomach. Endotracheal tube tip at the carina.",
        )

    def test_orogastric_before_endotracheal(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Orogastric tube in place. Endotracheal tube position unchanged.",
        )

    # --- Planned / elective / OR intubation ---

    def test_coming_up_intubated(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Coming up intubated",
        )

    def test_elective_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Patient underwent elective intubation for the procedure.",
        )

    def test_planned_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Planned intubation for ventilatory support postoperatively.",
        )

    def test_scheduled_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Scheduled intubation prior to surgery.",
        )

    def test_intubated_for_surgery(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Patient was intubated for surgery without complication.",
        )

    def test_intubation_for_the_procedure(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Intubation for the procedure performed by anesthesia.",
        )

    def test_intubation_for_operation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Intubation for operation was uneventful.",
        )

    def test_anesthesia_endotracheal(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "General anesthesia with endotracheal tube placement.",
        )


# ─── intubation_negation_noise: MUST NOT match true positive text ───────


class TestIntubationNegationNoiseRejects:
    """Noise patterns must NOT catch genuine unplanned intubation evidence."""

    def test_emergent_endotracheal_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "EMERGENT ENDOTRACHEAL INTUBATION",
        )

    def test_procedure_endotracheal_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Procedure: Endotracheal intubation",
        )

    def test_intubated_after_nippv_failure(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient was intubated after failure of noninvasive positive-pressure ventilation in setting of acute hypoxic and hypercapnic respiratory failure.",
        )

    def test_intubation_performed_by_direct_laryngoscopy(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Intubation was performed by direct laryngoscopy using a laryngoscope and a 7.5 cuffed endotracheal tube.",
        )

    def test_emergent_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Emergent intubation for airway protection",
        )

    def test_ett_placed(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "ETT placed at bedside for respiratory distress.",
        )

    def test_required_intubation(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient required intubation due to respiratory failure.",
        )

    def test_intubated_during_hospitalization(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Intubated during hospitalization due to decompensation.",
        )

    def test_intubation_respiratory_failure(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Intubation for respiratory failure and hypoxia.",
        )

    def test_intubated_for_hypoxic_respiratory_failure(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Intubated for hypoxic respiratory failure.",
        )

    def test_bronchoscope_through_ett(self):
        pats = _load_patterns()["intubation_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "The bronchoscope was then passed through the adapter down the endotracheal tube.",
        )


# ─── unplanned_intubation dx: MUST still match positive evidence ────────


class TestUnplannedIntubationDxPositive:
    """The unplanned_intubation query patterns must still fire on true positives."""

    def test_emergent_intubation(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(pats, "Emergent intubation at bedside")

    def test_intubation_respiratory_failure(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(
            pats,
            "Patient was intubated for respiratory failure.",
        )

    def test_endotracheal_tube(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(pats, "Endotracheal tube placed emergently.")

    def test_endotracheal_intubation(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(
            pats,
            "Procedure: Endotracheal intubation",
        )

    def test_ett_placed(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(
            pats,
            "ETT placed by Dr. Smith at 0230.",
        )

    def test_intubated_during_hospitalization(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(
            pats,
            "Intubation during hospitalization for acute decompensation.",
        )

    def test_required_intubation(self):
        pats = _load_patterns()["unplanned_intubation"]
        assert _any_pattern_matches(
            pats,
            "Patient required intubation for airway protection.",
        )


# ─── Rule structure / wiring ────────────────────────────────────────────


class TestIntubationRuleStructure:
    """Rule file wiring: intubation_negation_noise must be active."""

    RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "19_unplanned_intubation.json"

    def test_exclude_noise_keys_wired(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "intubation_negation_noise" in gate["exclude_noise_keys"]

    def test_intubation_negation_noise_bucket_exists_in_mapper(self):
        pats = _load_patterns()
        assert "intubation_negation_noise" in pats
        assert len(pats["intubation_negation_noise"]) >= 10

    def test_gate_still_requires_unplanned_intubation_key(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "unplanned_intubation" in gate["query_keys"]
