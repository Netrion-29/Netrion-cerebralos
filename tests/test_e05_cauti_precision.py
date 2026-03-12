#!/usr/bin/env python3
"""
Precision regression tests for Event 05 (Catheter-Associated Urinary Tract
Infection — CAUTI) gate coverage.

Verifies that mapper patterns correctly detect:
  1. cauti_dx — UTI / CAUTI diagnosis
  2. cauti_catheter_in_place — indwelling urinary catheter documentation
  3. cauti_catheter_duration — device-qualified urinary catheter duration ≥3d/>48h
  4. cauti_symptoms — CDC SUTI 1a signs/symptoms
  5. cauti_culture_positive — urine culture >= 10^5 CFU/ml
  6. cauti_negation_noise — negated / ruled-out UTI/CAUTI
  7. cauti_chronic_catheter — chronic/pre-admission catheter terms
  8. cauti_onset — timing/onset language

Also verifies E05 rule JSON wiring against the NTDS spec:
  - 5 required gates (dx, catheter >2d, symptoms, culture, timing)
  - 2 exclusions (POA, chronic catheter)
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPER_PATH = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "05_cauti.json"


def _load_patterns() -> dict:
    with open(MAPPER_PATH) as f:
        data = json.load(f)
    return data.get("query_patterns", {})


def _any_pattern_matches(patterns: list, text: str) -> bool:
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ─── Rule wiring checks ─────────────────────────────────────────────────


class TestE05RuleWiring:
    """E05 rule JSON must have correct gate topology per NTDS spec."""

    @pytest.fixture(autouse=True)
    def _load_rule(self):
        with open(RULE_PATH) as f:
            self.rule = json.load(f)

    def test_meta_event_id(self):
        assert self.rule["meta"]["event_id"] == 5

    def test_has_five_required_gates(self):
        gates = self.rule["gates"]
        required = [g for g in gates if g.get("required", True)]
        assert len(required) == 5

    def test_gate_ids(self):
        ids = {g["gate_id"] for g in self.rule["gates"]}
        assert ids == {
            "cauti_dx",
            "cauti_catheter_gt2d",
            "cauti_catheter_duration_lda",
            "cauti_symptoms",
            "cauti_culture",
            "cauti_after_arrival",
        }

    def test_has_poa_exclusion(self):
        excl_ids = {e["gate_id"] for e in self.rule["exclusions"]}
        assert "cauti_excl_poa" in excl_ids

    def test_has_chronic_catheter_exclusion(self):
        excl_ids = {e["gate_id"] for e in self.rule["exclusions"]}
        assert "cauti_excl_chronic_catheter" in excl_ids

    def test_dx_gate_has_noise_filter(self):
        dx_gate = next(g for g in self.rule["gates"] if g["gate_id"] == "cauti_dx")
        assert "cauti_negation_noise" in dx_gate.get("exclude_noise_keys", [])

    def test_timing_gate_type(self):
        tg = next(g for g in self.rule["gates"] if g["gate_id"] == "cauti_after_arrival")
        assert tg["gate_type"] == "timing_after_arrival"

    def test_catheter_gt2d_uses_duration_key(self):
        gate = next(g for g in self.rule["gates"] if g["gate_id"] == "cauti_catheter_gt2d")
        assert gate["query_keys"] == ["cauti_catheter_duration"]


# ─── cauti_dx: must match UTI/CAUTI diagnosis text ──────────────────────


class TestCautiDxMatches:

    def test_cauti_abbreviation(self):
        pats = _load_patterns()["cauti_dx"]
        assert _any_pattern_matches(pats, "CAUTI")

    def test_catheter_associated_uti(self):
        pats = _load_patterns()["cauti_dx"]
        assert _any_pattern_matches(pats, "catheter-associated urinary tract infection")

    def test_uti_with_catheter(self):
        pats = _load_patterns()["cauti_dx"]
        assert _any_pattern_matches(pats, "urinary tract infection related to catheter")

    def test_plain_uti_diagnosis(self):
        pats = _load_patterns()["cauti_dx"]
        assert _any_pattern_matches(pats, "Diagnosed with UTI")

    def test_urinary_tract_infection_standalone(self):
        pats = _load_patterns()["cauti_dx"]
        assert _any_pattern_matches(pats, "urinary tract infection suspected")


# ─── cauti_dx: must NOT match noise text ─────────────────────────────────


class TestCautiDxRejectsNoise:

    def test_no_uti_plain_text(self):
        """Noise filter catches 'no UTI' — but at cauti_dx pattern level,
        the pattern itself will match 'UTI'; the noise gate removes it."""
        # This is intentional: dx patterns cast wide, noise patterns exclude.
        pass


# ─── cauti_negation_noise: must match negated UTI text ──────────────────


class TestCautiNegationNoiseMatches:

    def test_no_uti(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert _any_pattern_matches(pats, "No UTI identified.")

    def test_no_evidence_of_uti(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert _any_pattern_matches(pats, "No evidence of urinary tract infection.")

    def test_no_cauti(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert _any_pattern_matches(pats, "No CAUTI.")

    def test_negative_for_uti(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert _any_pattern_matches(pats, "Culture negative for UTI.")

    def test_uti_ruled_out(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert _any_pattern_matches(pats, "UTI ruled out based on cultures.")

    def test_rule_out_uti(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert _any_pattern_matches(pats, "Rule out UTI — pending cultures.")


class TestCautiNegationNoiseRejects:
    """Negation patterns must NOT fire on true positive CAUTI text."""

    def test_cauti_diagnosed(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert not _any_pattern_matches(pats, "CAUTI diagnosed on hospital day 5.")

    def test_uti_confirmed(self):
        pats = _load_patterns()["cauti_negation_noise"]
        assert not _any_pattern_matches(pats, "UTI confirmed by urine culture.")


# ─── cauti_catheter_in_place: must match catheter text ──────────────────


class TestCautiCatheterInPlace:

    def test_foley_in_place(self):
        pats = _load_patterns()["cauti_catheter_in_place"]
        assert _any_pattern_matches(pats, "Foley catheter in place.")

    def test_indwelling_urinary_catheter(self):
        pats = _load_patterns()["cauti_catheter_in_place"]
        assert _any_pattern_matches(pats, "Indwelling urinary catheter inserted in ED.")

    def test_foley_inserted(self):
        pats = _load_patterns()["cauti_catheter_in_place"]
        assert _any_pattern_matches(pats, "Foley inserted on admission.")

    def test_foley_since_day_1(self):
        pats = _load_patterns()["cauti_catheter_in_place"]
        assert _any_pattern_matches(pats, "Foley catheter in place since day 1.")

    def test_catheter_in_place_since(self):
        pats = _load_patterns()["cauti_catheter_in_place"]
        assert _any_pattern_matches(pats, "catheter in place since admission.")


# ─── cauti_symptoms: must match CDC SUTI 1a symptoms ────────────────────


class TestCautiSymptoms:

    def test_fever_38c(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Temperature 38.6 C.")

    def test_febrile(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Patient febrile.")

    def test_suprapubic_tenderness(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Suprapubic tenderness on exam.")

    def test_cva_tenderness(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Costovertebral angle tenderness noted.")

    def test_cva_pain(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "CVA pain on left side.")

    def test_dysuria(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Reports dysuria.")

    def test_urinary_urgency(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Urinary urgency reported.")

    def test_urinary_frequency(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Urinary frequency noted.")

    def test_flank_pain(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Flank pain noted on exam.")


class TestCautiSymptomsRejects:

    def test_no_fever_match_below_38(self):
        """Temperature below 38 should not match fever patterns."""
        pats = _load_patterns()["cauti_symptoms"]
        assert not _any_pattern_matches(pats, "Temperature 37.2 C.")


# ─── cauti_culture_positive: must match culture >=10^5 ──────────────────


class TestCautiCulturePositive:

    def test_100000_cfu_per_ml(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "100,000 CFU per mL")

    def test_urine_culture_positive(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "Urine culture positive for E. coli.")

    def test_positive_urine_culture(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "positive urine culture with Klebsiella")

    def test_greater_than_10_5(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture greater than 10^5 CFU/ml")

    def test_100000_cfu_ml_numeric(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture 100000 CFU/mL")


# ─── cauti_chronic_catheter: chronic/pre-admission detection ────────────


class TestCautiChronicCatheter:

    def test_chronic_foley(self):
        pats = _load_patterns()["cauti_chronic_catheter"]
        assert _any_pattern_matches(pats, "Chronic foley catheter in place.")

    def test_long_term_catheter(self):
        pats = _load_patterns()["cauti_chronic_catheter"]
        assert _any_pattern_matches(pats, "Long-term urinary catheter.")

    def test_chronic_suprapubic(self):
        pats = _load_patterns()["cauti_chronic_catheter"]
        assert _any_pattern_matches(pats, "Chronic suprapubic catheter.")

    def test_foley_prior_to_admission(self):
        pats = _load_patterns()["cauti_chronic_catheter"]
        assert _any_pattern_matches(pats, "Foley prior to admission.")


class TestCautiChronicCatheterRejects:

    def test_new_foley(self):
        pats = _load_patterns()["cauti_chronic_catheter"]
        assert not _any_pattern_matches(pats, "New foley catheter inserted today.")

    def test_foley_in_ed(self):
        pats = _load_patterns()["cauti_chronic_catheter"]
        assert not _any_pattern_matches(pats, "Foley catheter inserted in ED.")


# ─── cauti_onset: timing language detection ──────────────────────────────


class TestCautiOnset:

    def test_onset_after_arrival(self):
        pats = _load_patterns()["cauti_onset"]
        assert _any_pattern_matches(pats, "onset after arrival")

    def test_developed_fever(self):
        pats = _load_patterns()["cauti_onset"]
        assert _any_pattern_matches(pats, "Patient developed fever on HD3.")

    def test_new_onset_uti(self):
        pats = _load_patterns()["cauti_onset"]
        assert _any_pattern_matches(pats, "New onset UTI on hospital day 4.")

    def test_hospital_acquired(self):
        pats = _load_patterns()["cauti_onset"]
        assert _any_pattern_matches(pats, "Hospital-acquired UTI.")

    def test_nosocomial_uti(self):
        pats = _load_patterns()["cauti_onset"]
        assert _any_pattern_matches(pats, "Nosocomial UTI suspected.")


# ─── cauti_culture_positive: format variant coverage ────────────────────


class TestCautiCultureFormatVariants:
    """Additional culture format variants per NTDS spec."""

    def test_1e5_cfu(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture grew E. coli 1e5 CFU")

    def test_greater_than_100000_no_cfu(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture >100,000")

    def test_gte_100000_no_cfu(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture >=100000")

    def test_10_caret_5_spaced(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "10 ^ 5 CFU/mL")

    def test_culture_with_organism_and_count(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture: E. coli 100,000 CFU/mL")

    def test_greater_than_100000_cfu_ml(self):
        pats = _load_patterns()["cauti_culture_positive"]
        assert _any_pattern_matches(pats, "urine culture greater than 100,000 CFU")


class TestCautiCultureRejectsSubthreshold:
    """Culture patterns should NOT match counts below 10^5 in general text."""

    def test_10000_cfu_no_match_positive_pattern(self):
        """10,000 CFU is below threshold — should not match 'positive' or '>10^5'."""
        pats = _load_patterns()["cauti_culture_positive"]
        # 'urine culture positive' pattern would match any 'positive' text,
        # but '10,000 CFU/mL' alone should not match the numeric patterns
        assert not _any_pattern_matches(pats, "10,000 CFU/mL from urinary sample")


# ─── cauti_symptoms: extended coverage ──────────────────────────────────


class TestCautiSymptomsExtended:
    """Additional symptom patterns per NTDS spec."""

    def test_altered_mental_status(self):
        """NTDS E05 spec: altered mental status in elderly."""
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Patient with altered mental status.")

    def test_fever_40c(self):
        """Fever above 39.9 should match (>38C threshold)."""
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "Temperature 40.2 C.")

    def test_fever_41c(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "fever 41.0")

    def test_temp_42c(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert _any_pattern_matches(pats, "temp 42.0")

    def test_no_match_37c(self):
        """Temperature below 38 should not match."""
        pats = _load_patterns()["cauti_symptoms"]
        assert not _any_pattern_matches(pats, "Temperature 37.2 C.")

    def test_no_match_36c(self):
        pats = _load_patterns()["cauti_symptoms"]
        assert not _any_pattern_matches(pats, "temp 36.5")


# ─── cauti_catheter_duration: device-qualified duration ≥3d / >48h ──────


class TestCautiCatheterDuration:
    """cauti_catheter_duration: positives require urinary device + duration."""

    def test_foley_day_3(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "foley day 3")

    def test_foley_catheter_day_4(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "foley catheter day 4")

    def test_foley_colon_day_5(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "foley: day 5")

    def test_foley_em_dash_day_3(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "foley \u2014 day 3")

    def test_indwelling_catheter_day_colon_3(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "indwelling catheter day: 3")

    def test_urinary_catheter_in_place_5_days(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "urinary catheter in place for 5 days")

    def test_foley_gt48h(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "foley >48h")

    def test_urinary_catheter_gt48_hours(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "urinary catheter >48 hours")

    def test_indwelling_foley_day_hash_4(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "indwelling foley day #4")

    def test_foley_catheter_placed_4_days_ago(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "foley catheter placed 4 days ago")

    def test_urethral_catheter_present_3_days(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(pats, "urethral catheter present for 3 days")

    def test_real_ehr_urethral_assessment_day_3(self):
        """Real EHR phrasing from Jamie Hunter.txt."""
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(
            pats,
            "Urethral Catheter 16 fr Assessment      Catheter day: 3",
        )

    def test_foley_in_place_since_day1_catheter_day_3(self):
        """Fixture phrasing: device + bridge + catheter day."""
        pats = _load_patterns()["cauti_catheter_duration"]
        assert _any_pattern_matches(
            pats,
            "Foley catheter in place since admission day 1. Catheter day 3.",
        )


class TestCautiCatheterDurationRejects:
    """cauti_catheter_duration negatives — no device, wrong device, or <3 days."""

    def test_hospital_day_22_no_device(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "hospital day 22")

    def test_hospital_day_field_no_device(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "Hospital Day: 8")

    def test_los_day_no_device(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "LOS Day 11")

    def test_cvc_day_5_wrong_device(self):
        """CVC = central venous catheter, not urinary."""
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "CVC day 5")

    def test_central_line_day_4_wrong_device(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "central line day 4")

    def test_foley_day_1_too_short(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "foley day 1")

    def test_bare_catheter_day_2_no_device_too_short(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "catheter day: 2")

    def test_bare_catheter_day_3_no_device(self):
        """Duration ≥3 but no urinary device qualifier."""
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "catheter day: 3")

    def test_arterial_line_day_5_wrong_device(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "arterial line day 5")

    def test_in_place_5_days_no_device(self):
        pats = _load_patterns()["cauti_catheter_duration"]
        assert not _any_pattern_matches(pats, "in place for 5 days")
