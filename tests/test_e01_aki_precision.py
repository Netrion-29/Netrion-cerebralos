#!/usr/bin/env python3
"""
Precision regression tests for Event 01 (AKI) noise filtering.

Verifies that aki_negation_noise patterns in the mapper correctly filter
ESRD/CKD/chronic hemodialysis context and historical/PMH AKI mentions —
while preserving true positive detection for genuine acute kidney injury.

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


# ─── aki_negation_noise: MUST match false-positive / noise text ─────────


class TestAkiNegationNoiseMatches:
    """Noise patterns must catch all ESRD/CKD/chronic HD and historical AKI phrasings."""

    # --- ESRD / CKD / chronic renal disease ---

    def test_end_stage_renal_disease(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "ESRD (end stage renal disease) (HCC)",
        )

    def test_esrd_abbreviation(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Patient has ESRD on dialysis.",
        )

    def test_end_stage_renal_disease_on_hemodialysis(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "End-stage renal disease on hemodialysis Monday Wednesday Friday.",
        )

    def test_chronic_kidney_disease(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Chronic kidney disease stage 4.",
        )

    def test_chronic_renal_failure(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Chronic renal failure requiring dialysis.",
        )

    def test_ckd_abbreviation(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "CKD stage 3b.",
        )

    def test_crf_abbreviation(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "CRF on hemodialysis.",
        )

    # --- Chronic hemodialysis context ---

    def test_hemodialysis_access_site(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Hemodialysis access site with arteriovenous graft",
        )

    def test_on_hemodialysis(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Patient on hemodialysis MWF schedule.",
        )

    def test_maintenance_hemodialysis(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Maintenance hemodialysis three times weekly.",
        )

    def test_renal_disease_on_hemodialysis(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "6. End-stage renal disease on hemodialysis",
        )

    # --- Historical / PMH AKI ---

    def test_history_colon_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "History:  AKI, anemia, anorexia, arthritis, afib",
        )

    def test_history_colon_aki_no_space(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "History: AKI, anemia",
        )

    def test_pmh_of_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "PMH of AKI, COPD, GERD, HLD, HTN",
        )

    def test_pmh_includes_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "PMH includes AKI and hypertension.",
        )

    def test_pmh_significant_for_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "PMH significant for AKI, diabetes.",
        )

    def test_with_pmh_of_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "82 y.o. male with PMH of AKI, COPD, GERD",
        )

    def test_past_medical_history_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Past medical history includes AKI.",
        )

    def test_past_history_acute_kidney_injury(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Past history of acute kidney injury.",
        )

    def test_history_of_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "History of AKI requiring dialysis last year.",
        )

    def test_history_of_acute_kidney_injury(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "history of acute kidney injury post surgery in 2020.",
        )

    # --- Full evidence text from false-positive patients ---

    def test_lolita_calcia_hemodialysis_access(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "Hemodialysis access site with arteriovenous graft",
        )

    def test_lolita_calcia_esrd_on_hd(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "6. End-stage renal disease on hemodialysis",
        )

    def test_william_simmons_history_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "History:  AKI, anemia, anorexia, arthritis, afib, av block, bacterial endocarditis, BPH, CAD, CVA, mitral valve replacement, HLD, HTN, TIA, thyroid disease, pacemaker replacement",
        )


# ─── aki_negation_noise: MUST NOT match true positive text ──────────────


class TestAkiNegationNoiseRejects:
    """Noise patterns must NOT catch genuine AKI diagnosis evidence."""

    def test_acute_kidney_injury_diagnosis(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Acute kidney injury secondary to sepsis.",
        )

    def test_aki_abbreviation_standalone(self):
        """Bare abbreviation with parenthetical expansion = PMH list entry."""
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "AKI (acute kidney injury)",
        )

    def test_acute_renal_failure(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Developed acute renal failure post-operatively.",
        )

    def test_creatinine_rising(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Creatinine rising from 1.2 to 3.4.",
        )

    def test_renal_replacement_therapy(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Started renal replacement therapy today.",
        )

    def test_new_onset_hemodialysis(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "New onset hemodialysis initiated for AKI.",
        )

    def test_oliguria(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Patient with oliguria and rising creatinine.",
        )

    def test_aki_after_chemotherapy(self):
        """PMH note referencing prior AKI after chemotherapy."""
        pats = _load_patterns()["aki_negation_noise"]
        assert _any_pattern_matches(
            pats,
            "hospital stay due to dehydration, acute kidney injury after chemotherapy",
        )

    def test_developed_aki_during_stay(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Developed AKI during hospitalization.",
        )

    def test_aki_problem_list_entry(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "- AKI.",
        )

    def test_ongoing_aki(self):
        pats = _load_patterns()["aki_negation_noise"]
        assert not _any_pattern_matches(
            pats,
            "Ongoing AKI with creatinine elevated.",
        )


# ─── aki_dx: MUST still match positive evidence ────────────────────────


class TestAkiDxPositive:
    """The aki_dx query patterns must still fire on true positives."""

    def test_acute_kidney_injury(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Acute kidney injury noted.")

    def test_aki_abbreviation(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "AKI (acute kidney injury)")

    def test_acute_renal_failure(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Acute renal failure requiring dialysis.")

    def test_creatinine_rose(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Creatinine rose from 1.0 to 2.5.")

    def test_creatinine_elevated(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Creatinine elevated at 4.2.")

    def test_renal_replacement_therapy(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Renal replacement therapy initiated.")

    def test_hemodialysis(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Hemodialysis started emergently.")

    def test_oliguria(self):
        pats = _load_patterns()["aki_dx"]
        assert _any_pattern_matches(pats, "Oliguria with output < 500ml/day.")


# ─── Rule structure / wiring ────────────────────────────────────────────


class TestAkiRuleStructure:
    """Rule file wiring: aki_negation_noise must be active."""

    RULE_PATH = REPO_ROOT / "rules" / "ntds" / "logic" / "2026" / "01_aki.json"

    def test_exclude_noise_keys_wired(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "aki_negation_noise" in gate["exclude_noise_keys"]

    def test_aki_negation_noise_bucket_exists_in_mapper(self):
        pats = _load_patterns()
        assert "aki_negation_noise" in pats
        assert len(pats["aki_negation_noise"]) >= 10

    def test_gate_still_requires_aki_dx_key(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        gate = rule["gates"][0]
        assert "aki_dx" in gate["query_keys"]

    def test_timing_gate_unchanged(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        timing_gate = rule["gates"][2]
        assert timing_gate["gate_id"] == "aki_after_arrival"
        assert timing_gate["query_key"] == "aki_onset"
        assert timing_gate["fail_outcome"] == "UNABLE_TO_DETERMINE"

    def test_exclusion_unchanged(self):
        with open(self.RULE_PATH) as f:
            rule = json.load(f)
        excl = rule["exclusions"][0]
        assert excl["gate_id"] == "aki_excl_poa"
        assert "history_noise" in excl["query_keys"]
