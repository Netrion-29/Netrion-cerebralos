#!/usr/bin/env python3
"""
Precision regression tests for Event 09 (Delirium) noise filtering.

Verifies that delirium_negation_noise patterns in the mapper correctly filter
screening-context, risk-assessment, and historical delirium mentions —
while preserving true positive detection for:
  - Explicit clinician delirium affirmation on delirium-screen lines
  - Metabolic encephalopathy documentation
  - Standard delirium diagnosis phrases

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


def _survives_noise(text: str) -> bool:
    """True if text matches delirium_dx and is NOT filtered by noise."""
    pats = _load_patterns()
    dx_hit = _any_pattern_matches(pats["delirium_dx"], text)
    noise_hit = _any_pattern_matches(pats["delirium_negation_noise"], text)
    return dx_hit and not noise_hit


# ─── delirium_dx: MUST match true-positive delirium text ─────────────


class TestDeliriumDxMatches:
    """Positive patterns must catch genuine delirium documentation."""

    def test_bare_delirium(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "Patient developed delirium on hospital day 3.")

    def test_acute_confusional_state(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "Acute confusional state with waxing and waning consciousness.")

    def test_cam_positive(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "CAM positive for delirium.")

    def test_cam_icu_positive(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "Overall CAM-ICU: positive")

    def test_bcam_positive(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "bCAM screening: positive")

    def test_patient_does_have_delirium(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "At present patient does have delirium.")

    def test_patient_have_delirium(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "At present patient have delirium.")

    def test_acute_metabolic_encephalopathy(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "Acute metabolic encephalopathy")

    def test_metabolic_encephalopathy(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "EEG shows mild-to-moderate generalized slowing suggestive of systemic/metabolic encephalopathy.")

    def test_acute_altered_mental_status(self):
        pats = _load_patterns()["delirium_dx"]
        assert _any_pattern_matches(pats, "Acute altered mental status, disoriented.")


# ─── delirium_negation_noise: MUST match false-positive / noise text ──


class TestDeliriumNegationNoiseMatches:
    """Noise patterns must catch screening context, risk assessment, and historical mentions."""

    def test_at_risk_for_delirium(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "At risk for delirium given ICU stay.")

    def test_risk_for_delirium(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Risk for delirium remains elevated.")

    def test_delirium_screen_alone(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Delirium screen: negative.")

    def test_delirium_precautions_alone(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Delirium precautions as outlined by policy will be followed.")

    def test_delirium_precaution_singular(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Delirium precaution in effect.")

    def test_history_of_delirium(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "History of delirium during prior admission.")

    def test_pmh_delirium(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "PMH delirium, dementia, HTN.")

    def test_prevent_delirium(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Preventing delirium with sleep hygiene protocol.")

    def test_cam_icu_negative(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Overall CAM-ICU: negative")

    def test_bcam_negative(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "bCAM: negative")

    def test_no_encephalopathy(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "No encephalopathy noted here yet (for coders)")

    def test_hepatic_encephalopathy(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Hepatic encephalopathy requiring lactulose.")

    def test_history_of_encephalopathy(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "History of encephalopathy in 2024.")

    def test_delirium_protocol(self):
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Following delirium protocol.")

    def test_standalone_delirium_header(self):
        """Geriatric Trauma Screen 'Delirium:' header is noise, not a diagnosis."""
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(pats, "Delirium:")

    def test_delirium_scale_used(self):
        """bCAM table header 'Delirium Scale Used' is noise."""
        pats = _load_patterns()["delirium_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Date/Time\tDelirium Scale Used\tSAS Score\tFeature 1: Acute Onset",
        )


# ─── delirium_negation_noise: MUST NOT match on affirmed-delirium lines ─


class TestDeliriumNoiseDoesNotSuppressAffirmation:
    """Noise patterns must NOT fire when the same line contains affirmative delirium."""

    def test_linda_hufford_delirium_screen_affirmed(self):
        """Linda Hufford L1517: delirium screen template with 'patient does have delirium'."""
        pats = _load_patterns()["delirium_negation_noise"]
        text = (
            "Delirium screen:  Patient is at risk for delirium given acute trauma, "
            "unfamiliar surroundings, pain, metabolic derangements, possible infection.  "
            "At present patient does have delirium.  "
            "Delirium precautions as outlined by policy will be followed."
        )
        assert not _any_pattern_matches(pats, text)

    def test_screen_affirmed_no_precautions(self):
        """Variation: screen + affirmation without precautions mention."""
        pats = _load_patterns()["delirium_negation_noise"]
        text = "Delirium screen: At present patient does have delirium."
        assert not _any_pattern_matches(pats, text)


# ─── delirium_negation_noise: MUST still match negative-delirium lines ──


class TestDeliriumNoiseCatchesNegation:
    """Noise patterns must fire on lines with negative delirium assessment."""

    def test_bittner_delirium_screen_negative(self):
        """Ronald Bittner L2094: delirium screen template with 'does not have delirium'."""
        pats = _load_patterns()["delirium_negation_noise"]
        text = (
            "Delirium screen:  Patient is at risk for delirium given acute trauma, "
            "unfamiliar surroundings, pain, metabolic derangements, possible infection.  "
            "At present patient does not have delirium.  "
            "Delirium precautions as outlined by policy will be followed."
        )
        assert _any_pattern_matches(pats, text)


# ─── Survival tests: dx matches that survive noise filtering ────────


class TestDeliriumSurvivesNoise:
    """End-to-end: dx match + noise check → evidence survives or is filtered."""

    def test_linda_hufford_affirmed_survives(self):
        """Linda Hufford L1517: must survive noise filtering."""
        text = (
            "Delirium screen:  Patient is at risk for delirium given acute trauma, "
            "unfamiliar surroundings, pain, metabolic derangements, possible infection.  "
            "At present patient does have delirium.  "
            "Delirium precautions as outlined by policy will be followed."
        )
        assert _survives_noise(text)

    def test_bittner_negative_filtered(self):
        """Ronald Bittner L2094: must be filtered by noise."""
        text = (
            "Delirium screen:  Patient is at risk for delirium given acute trauma, "
            "unfamiliar surroundings, pain, metabolic derangements, possible infection.  "
            "At present patient does not have delirium.  "
            "Delirium precautions as outlined by policy will be followed."
        )
        assert not _survives_noise(text)

    def test_acute_metabolic_encephalopathy_survives(self):
        assert _survives_noise("Acute metabolic encephalopathy")

    def test_systemic_metabolic_encephalopathy_survives(self):
        assert _survives_noise(
            "This was suggestive of systemic/metabolic encephalopathy."
        )

    def test_bare_delirium_survives(self):
        assert _survives_noise("Patient developed delirium on hospital day 3.")

    def test_risk_only_filtered(self):
        assert not _survives_noise("At risk for delirium given ICU stay.")

    def test_screen_only_filtered(self):
        assert not _survives_noise("Delirium screen: negative.")

    def test_hepatic_enc_does_not_survive(self):
        assert not _survives_noise("Hepatic encephalopathy requiring lactulose.")

    def test_no_enc_does_not_survive(self):
        assert not _survives_noise("No encephalopathy noted here yet (for coders)")

    def test_anna_dennis_baseline_confusion_no_match(self):
        """Control: baseline dementia confusion must NOT match delirium_dx."""
        assert not _survives_noise("Pt arrives pleasantly confused, denies any pain anywhere.")

    def test_nachtwey_acute_encephalopathy_ich_no_match(self):
        """Control: TBI-related encephalopathy (no 'metabolic') must NOT match."""
        assert not _survives_noise("Acute encephalopathy - likely 2/2 ICH")

    def test_eeg_moderate_enc_no_metabolic_no_match(self):
        """Control: generic EEG encephalopathy without 'metabolic' must NOT match."""
        assert not _survives_noise(
            "This is indicative of a moderate encephalopathy but is non-specific as to its etiology."
        )

    def test_standalone_delirium_header_filtered(self):
        """Geriatric Trauma Screen 'Delirium:' header must be filtered."""
        assert not _survives_noise("Delirium:")

    def test_delirium_scale_table_header_filtered(self):
        """bCAM flowsheet table header must be filtered."""
        assert not _survives_noise(
            "Date/Time\tDelirium Scale Used\tSAS Score\tFeature 1"
        )
