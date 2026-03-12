#!/usr/bin/env python3
"""
Precision regression tests for Event 06 (Central Line-Associated
Bloodstream Infection — CLABSI) gate coverage.

Verifies that mapper patterns correctly detect:
  1. clabsi_dx — CLABSI / catheter-related BSI diagnosis
  2. clabsi_central_line_in_place — central line device documentation
  3. clabsi_blood_culture_positive — positive blood culture with organism
  4. clabsi_symptoms — fever, chills, rigors, hypotension
  5. clabsi_negation_noise — negated / ruled-out CLABSI
  6. clabsi_chronic_line — chronic/pre-admission central line terms
  7. clabsi_onset — timing/onset language

Also verifies E06 rule JSON wiring against the NTDS spec:
  - 5 required gates (dx, central line >2d, blood culture, symptoms, timing)
  - 2 exclusions (POA, chronic line)
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPER_PATH = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "06_clabsi.json"


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


class TestE06RuleWiring:
    """E06 rule JSON must have correct gate topology per NTDS spec."""

    @pytest.fixture(autouse=True)
    def _load_rule(self):
        with open(RULE_PATH) as f:
            self.rule = json.load(f)

    def test_meta_event_id(self):
        assert self.rule["meta"]["event_id"] == 6

    def test_version_2(self):
        assert self.rule["meta"]["version"] == "2.0.0"

    def test_has_five_required_gates(self):
        gates = self.rule["gates"]
        required = [g for g in gates if g.get("required", True)]
        assert len(required) == 5

    def test_gate_ids(self):
        ids = {g["gate_id"] for g in self.rule["gates"]}
        assert ids == {
            "clabsi_dx",
            "clabsi_central_line_gt2d",
            "clabsi_lab_positive",
            "clabsi_symptoms",
            "clabsi_after_arrival",
        }

    def test_has_poa_exclusion(self):
        excl_ids = {e["gate_id"] for e in self.rule["exclusions"]}
        assert "clabsi_excl_poa" in excl_ids

    def test_has_chronic_line_exclusion(self):
        excl_ids = {e["gate_id"] for e in self.rule["exclusions"]}
        assert "clabsi_excl_chronic_line" in excl_ids

    def test_dx_gate_has_noise_filter(self):
        dx_gate = next(g for g in self.rule["gates"] if g["gate_id"] == "clabsi_dx")
        assert "clabsi_negation_noise" in dx_gate.get("exclude_noise_keys", [])

    def test_timing_gate_type(self):
        tg = next(
            g for g in self.rule["gates"] if g["gate_id"] == "clabsi_after_arrival"
        )
        assert tg["gate_type"] == "timing_after_arrival"

    def test_lab_positive_gate_query_key(self):
        lg = next(
            g for g in self.rule["gates"] if g["gate_id"] == "clabsi_lab_positive"
        )
        assert "clabsi_blood_culture_positive" in lg["query_keys"]

    def test_central_line_gate_query_key(self):
        cg = next(
            g
            for g in self.rule["gates"]
            if g["gate_id"] == "clabsi_central_line_gt2d"
        )
        assert "clabsi_central_line_in_place" in cg["query_keys"]


# ─── clabsi_dx: must match CLABSI / catheter-related BSI ────────────────


class TestClabsiDxMatches:

    def test_clabsi_abbreviation(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(pats, "CLABSI")

    def test_central_line_associated_bsi(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(
            pats, "central line-associated bloodstream infection"
        )

    def test_central_line_associated_bsi_hyphen(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(
            pats, "central line associated bloodstream infection"
        )

    def test_bacteremia_central_line(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(pats, "bacteremia related to central line")

    def test_central_venous_bacteremia(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(pats, "central venous catheter bacteremia")

    def test_line_sepsis(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(pats, "line sepsis suspected")

    def test_catheter_related_bloodstream(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(pats, "catheter-related bloodstream infection")

    def test_catheter_related_infection(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(pats, "catheter related infection")

    def test_bloodstream_infection_central_line(self):
        pats = _load_patterns()["clabsi_dx"]
        assert _any_pattern_matches(
            pats, "bloodstream infection from central line"
        )


class TestClabsiDxRejectsNoise:

    def test_plain_blood_culture_not_dx(self):
        """'blood culture positive' alone should NOT match dx — it's in
        the separate clabsi_blood_culture_positive key."""
        pats = _load_patterns()["clabsi_dx"]
        assert not _any_pattern_matches(pats, "blood culture positive for staph")

    def test_peripheral_bacteremia_not_dx(self):
        pats = _load_patterns()["clabsi_dx"]
        assert not _any_pattern_matches(pats, "bacteremia from peripheral source")


# ─── clabsi_negation_noise: must match negated CLABSI text ──────────────


class TestClabsiNegationNoiseMatches:

    def test_no_clabsi(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(pats, "No CLABSI identified.")

    def test_no_evidence_of_clabsi(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(
            pats, "No evidence of central line-associated infection."
        )

    def test_negative_for_bacteremia(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(pats, "Negative for bacteremia.")

    def test_clabsi_ruled_out(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(pats, "CLABSI ruled out based on cultures.")

    def test_no_bacteremia(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(pats, "No evidence of bacteremia.")

    def test_rule_out_line_sepsis(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(pats, "Rule out line sepsis — pending cultures.")

    def test_without_bacteremia(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert _any_pattern_matches(pats, "Patient without bacteremia.")


class TestClabsiNegationNoiseRejects:
    """Negation patterns must NOT fire on true positive CLABSI text."""

    def test_clabsi_diagnosed(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "CLABSI diagnosed on hospital day 5."
        )

    def test_bacteremia_confirmed(self):
        pats = _load_patterns()["clabsi_negation_noise"]
        assert not _any_pattern_matches(
            pats, "Bacteremia confirmed from central line cultures."
        )


# ─── clabsi_central_line_in_place: must match central line device ────────


class TestClabsiCentralLineMatches:

    def test_central_line_in_place(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Central line in place, right subclavian.")

    def test_central_venous_catheter_inserted(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Central venous catheter inserted.")

    def test_picc_line_in_place(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "PICC line in place, left arm.")

    def test_cvl_site(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "CVL site clean and dry.")

    def test_triple_lumen(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Triple-lumen catheter placed.")

    def test_central_line_subclavian(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Central line right subclavian.")

    def test_central_venous_catheter_standalone(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Central venous catheter maintained.")

    def test_hickman_in_place(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Hickman catheter in place.")

    def test_picc_inserted(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "PICC inserted on day 2.")

    def test_central_line_day(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert _any_pattern_matches(pats, "Central line day 4.")


class TestClabsiCentralLineRejects:

    def test_peripheral_iv(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert not _any_pattern_matches(pats, "Peripheral IV access adequate.")

    def test_foley_catheter_not_central(self):
        pats = _load_patterns()["clabsi_central_line_in_place"]
        assert not _any_pattern_matches(pats, "Foley catheter in place.")


# ─── clabsi_blood_culture_positive: must match positive blood culture ────


class TestClabsiBloodCultureMatches:

    def test_blood_culture_positive(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(pats, "Blood culture positive for S. aureus.")

    def test_positive_blood_culture(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(pats, "Positive blood culture with E. coli.")

    def test_blood_culture_grew(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(pats, "Blood culture grew Staph aureus.")

    def test_blood_culture_positive_for(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(
            pats, "Blood culture positive for enterococcus."
        )

    def test_bacteremia_confirmed(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(pats, "Bacteremia confirmed from peripheral draw.")

    def test_blood_culture_candida(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(pats, "Blood culture grew candida.")

    def test_organism_isolated(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(
            pats, "Klebsiella isolated from blood culture."
        )

    def test_blood_culture_organism(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert _any_pattern_matches(pats, "Blood culture shows organism growth.")


class TestClabsiBloodCultureRejects:

    def test_no_growth(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert not _any_pattern_matches(
            pats, "Blood cultures drawn — no growth at 5 days."
        )

    def test_urine_culture(self):
        pats = _load_patterns()["clabsi_blood_culture_positive"]
        assert not _any_pattern_matches(pats, "Urine culture positive for E. coli.")


# ─── clabsi_symptoms: must match fever/chills/rigors/hypotension ────────


class TestClabsiSymptoms:

    def test_fever_39c(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Temperature 39.1 C.")

    def test_fever_38c(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Fever 38.5 C documented.")

    def test_febrile(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Patient febrile.")

    def test_chills(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Patient reports chills.")

    def test_rigors(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Rigors noted during line flush.")

    def test_hypotension(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Hypotension noted, BP 85/52.")

    def test_hemodynamic_instability(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Hemodynamic instability requiring pressors.")

    def test_septic_shock(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert _any_pattern_matches(pats, "Septic shock secondary to line infection.")


class TestClabsiSymptomsRejects:

    def test_no_fever_match_below_38(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert not _any_pattern_matches(pats, "Temperature 37.2 C.")

    def test_normal_vitals(self):
        pats = _load_patterns()["clabsi_symptoms"]
        assert not _any_pattern_matches(
            pats, "Vitals stable, no fever, normotensive."
        )


# ─── clabsi_onset: must match timing/onset after arrival ────────────────


class TestClabsiOnset:

    def test_onset_after_arrival(self):
        pats = _load_patterns()["clabsi_onset"]
        assert _any_pattern_matches(pats, "Onset after arrival to hospital.")

    def test_developed_bacteremia(self):
        pats = _load_patterns()["clabsi_onset"]
        assert _any_pattern_matches(pats, "Developed bacteremia on hospital day 4.")

    def test_new_onset_fever(self):
        pats = _load_patterns()["clabsi_onset"]
        assert _any_pattern_matches(pats, "New onset fever on day 3.")

    def test_hospital_acquired(self):
        pats = _load_patterns()["clabsi_onset"]
        assert _any_pattern_matches(pats, "Hospital-acquired bloodstream infection.")

    def test_nosocomial_bacteremia(self):
        pats = _load_patterns()["clabsi_onset"]
        assert _any_pattern_matches(pats, "Nosocomial bacteremia suspected.")

    def test_new_clabsi(self):
        pats = _load_patterns()["clabsi_onset"]
        assert _any_pattern_matches(pats, "New CLABSI identified.")


# ─── clabsi_chronic_line: chronic/pre-admission line detection ───────────


class TestClabsiChronicLine:

    def test_chronic_central_line(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert _any_pattern_matches(pats, "Chronic central line in place.")

    def test_long_term_catheter(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert _any_pattern_matches(pats, "Long-term central venous catheter.")

    def test_chronic_dialysis_catheter(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert _any_pattern_matches(pats, "Chronic dialysis catheter.")

    def test_chronic_tunneled_catheter(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert _any_pattern_matches(pats, "Chronic tunneled catheter in place.")

    def test_hd_catheter_prior_to_admission(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert _any_pattern_matches(pats, "HD catheter prior to admission.")

    def test_pre_admission_central_line(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert _any_pattern_matches(pats, "Pre-admission central line.")


class TestClabsiChronicLineRejects:

    def test_new_central_line(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert not _any_pattern_matches(pats, "New central line placed today.")

    def test_central_line_inserted_in_icu(self):
        pats = _load_patterns()["clabsi_chronic_line"]
        assert not _any_pattern_matches(
            pats, "Central line inserted in ICU on day 1."
        )
