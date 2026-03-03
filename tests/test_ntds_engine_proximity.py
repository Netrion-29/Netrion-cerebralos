#!/usr/bin/env python3
"""
Unit tests for proximity_mode: sentence_window in engine.eval_exclude_if_any.

Covers:
  U1 – default (no proximity_mode): whole-line co-occurrence preserved
  U2 – sentence_window: same-sentence co-occurrence → HardStop
  U3 – sentence_window: far-apart co-occurrence → no HardStop
  U4 – sentence_window: empty text → fail-closed (no HardStop)
  U5 – unknown proximity_mode → fallback to whole-line matching
  U6 – sentence_window: ±1 neighbor co-occurrence → HardStop
  U7 – _split_sentences deterministic splitting
  D1–D4 – DVT-specific POA exclusion proximity
  P1–P4 – PE-specific POA exclusion proximity
"""

from __future__ import annotations

import unittest
from typing import List

from cerebralos.ntds_logic.engine import (
    _split_sentences,
    _sentence_window_matches,
    eval_exclude_if_any,
)
from cerebralos.ntds_logic.model import (
    Evidence,
    EvidencePointer,
    PatientFacts,
    SourceType,
)


# ---- helpers ---------------------------------------------------------------

def _make_patient(evidence_texts: List[str], query_patterns: dict) -> PatientFacts:
    """Build a minimal PatientFacts with the given evidence texts and patterns."""
    evs = [
        Evidence(
            source_type=SourceType.PHYSICIAN_NOTE,
            text=t,
            pointer=EvidencePointer(),
        )
        for t in evidence_texts
    ]
    return PatientFacts(
        patient_id="TEST",
        facts={"query_patterns": query_patterns},
        evidence=evs,
    )


CONTRACT = {"evidence": {"max_items_per_gate": 8}}

# Pattern maps reused across tests
PATTERNS = {
    "or_planned_staged": [r"\bplanned\s+return\b"],
    "or_procedure_context": [r"\boperating\s+room\b", r"\bOR\b", r"\bsurgery\b"],
}


# ---- _split_sentences tests (U7) ------------------------------------------

class TestSplitSentences(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   \n  "), [])

    def test_single_sentence(self):
        self.assertEqual(_split_sentences("Patient arrived."), ["Patient arrived."])

    def test_two_sentences(self):
        result = _split_sentences("Patient arrived. Vitals stable.")
        self.assertEqual(result, ["Patient arrived.", "Vitals stable."])

    def test_newline_split(self):
        result = _split_sentences("Line one.\nLine two.")
        self.assertEqual(result, ["Line one.", "Line two."])

    def test_period_without_uppercase_does_not_split(self):
        # e.g. "Dr. jones" — lowercase after period → no split
        result = _split_sentences("Dr. jones was consulted.")
        self.assertEqual(result, ["Dr. jones was consulted."])

    def test_question_and_exclamation(self):
        result = _split_sentences("Is there bleeding? Yes! Proceed with surgery.")
        self.assertEqual(result, [
            "Is there bleeding?",
            "Yes!",
            "Proceed with surgery.",
        ])


# ---- _sentence_window_matches tests ---------------------------------------

class TestSentenceWindowMatches(unittest.TestCase):
    def test_same_sentence_match(self):
        """query + context in same sentence → True"""
        patient = _make_patient([], PATTERNS)
        text = "The planned return to the operating room was uneventful."
        self.assertTrue(
            _sentence_window_matches(patient, text, "or_planned_staged", ["or_procedure_context"])
        )

    def test_far_apart_no_match(self):
        """query and context separated by >1 sentence → False"""
        patient = _make_patient([], PATTERNS)
        text = (
            "Patient had a planned return for wound care. "
            "Labs were drawn. Vitals checked. "
            "Taken to the operating room for debridement."
        )
        self.assertFalse(
            _sentence_window_matches(patient, text, "or_planned_staged", ["or_procedure_context"])
        )

    def test_adjacent_sentence_match(self):
        """query in sentence i, context in sentence i+1 → True (within ±1)"""
        patient = _make_patient([], PATTERNS)
        text = "The planned return was discussed. Patient taken to the OR for revision."
        self.assertTrue(
            _sentence_window_matches(patient, text, "or_planned_staged", ["or_procedure_context"])
        )

    def test_empty_text(self):
        """Empty text → fail-closed (False)"""
        patient = _make_patient([], PATTERNS)
        self.assertFalse(
            _sentence_window_matches(patient, "", "or_planned_staged", ["or_procedure_context"])
        )

    def test_no_query_match(self):
        """Text doesn't match query_key → False"""
        patient = _make_patient([], PATTERNS)
        text = "Patient taken to operating room for debridement."
        self.assertFalse(
            _sentence_window_matches(patient, text, "or_planned_staged", ["or_procedure_context"])
        )


# ---- eval_exclude_if_any tests ---------------------------------------------

class TestEvalExcludeProximity(unittest.TestCase):
    """Integration-level tests exercising eval_exclude_if_any with and without proximity_mode."""

    def _gate(self, proximity_mode=None):
        gate = {
            "gate_type": "exclude_if_any",
            "gate_id": "test_excl",
            "rule_id": "TEST_EXCL",
            "reason": "Test exclusion",
            "query_keys": ["or_planned_staged"],
            "require_context_keys": ["or_procedure_context"],
        }
        if proximity_mode is not None:
            gate["proximity_mode"] = proximity_mode
        return gate

    # U1 – default: whole-line matching (no proximity_mode)
    def test_default_whole_line_cooccurrence_fires(self):
        """No proximity_mode → same-line co-occurrence → HardStop."""
        text = "Transfer note mentions planned return. Also operating room was prepped."
        patient = _make_patient([text], PATTERNS)
        result = eval_exclude_if_any(self._gate(), patient, CONTRACT)
        self.assertIsNotNone(result, "default mode should fire on whole-line co-occurrence")

    # U2 – sentence_window: same-sentence → HardStop
    def test_sentence_window_same_sentence_fires(self):
        text = "The planned return to the operating room was uneventful."
        patient = _make_patient([text], PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "sentence_window: same sentence should fire")
        self.assertEqual(result.rule_id, "TEST_EXCL")

    # U3 – sentence_window: far-apart → no HardStop
    def test_sentence_window_far_apart_does_not_fire(self):
        text = (
            "Patient had a planned return for wound care. "
            "Labs were drawn. Vitals checked. "
            "Taken to the operating room for debridement."
        )
        patient = _make_patient([text], PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNone(result, "sentence_window: far-apart should not fire")

    # U4 – sentence_window: empty text → fail-closed
    def test_sentence_window_empty_text_no_fire(self):
        patient = _make_patient([""], PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNone(result, "sentence_window: empty text should not fire")

    # U5 – unknown proximity_mode → fallback to default whole-line
    def test_unknown_proximity_mode_falls_back(self):
        text = "Transfer note mentions planned return. Also operating room was prepped."
        patient = _make_patient([text], PATTERNS)
        result = eval_exclude_if_any(self._gate("some_future_mode"), patient, CONTRACT)
        self.assertIsNotNone(result, "unknown proximity_mode should fallback to whole-line")

    # U6 – sentence_window: ±1 neighbor → HardStop
    def test_sentence_window_adjacent_fires(self):
        text = "The planned return was discussed. Patient taken to the OR for revision."
        patient = _make_patient([text], PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "sentence_window: adjacent sentence should fire")

    # Additional: no require_context_keys → proximity_mode irrelevant, HardStop fires normally
    def test_no_context_keys_ignores_proximity(self):
        gate = {
            "gate_type": "exclude_if_any",
            "gate_id": "test_simple",
            "rule_id": "TEST_SIMPLE",
            "reason": "Simple exclusion",
            "query_keys": ["or_planned_staged"],
            "proximity_mode": "sentence_window",
        }
        text = "Patient had a planned return for wound care."
        patient = _make_patient([text], PATTERNS)
        result = eval_exclude_if_any(gate, patient, CONTRACT)
        self.assertIsNotNone(result, "no context keys → proximity not evaluated, should fire")

    # Multiple evidence lines: one passes proximity, another doesn't
    def test_mixed_evidence_picks_proximate(self):
        texts = [
            # This line has far-apart co-occurrence
            "Patient had a planned return for wound care. Labs drawn. Vitals checked. Operating room prepped.",
            # This line has same-sentence co-occurrence
            "The planned return to the operating room went well.",
        ]
        patient = _make_patient(texts, PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "should fire on the proximate evidence line")
        self.assertIn("planned return to the operating room", result.evidence[0].text)


# ---- DVT POA exclusion proximity tests (D1–D4) ----------------------------

# Mapper-aligned patterns for DVT
DVT_PATTERNS = {
    "dvt_poa_phrase": [
        r"\bpresent\s+on\s+arrival\b",
        r"\bprior\s+to\s+arrival\b",
        r"\bbefore\s+arrival\b",
        r"\bon\s+arrival\b",
    ],
    "dvt_dx": [
        r"\bdeep\s+vein\s+thrombosis\b",
        r"\bvenous\s+duplex\b.*\bpositive\b",
        r"\bocclusive\s+thrombus\b",
        r"\bthrombus\b.*\b(popli(teal)?|femoral|iliac|tibial|peroneal)\b",
    ],
}


class TestDvtPoaProximity(unittest.TestCase):
    """DVT Event 8: dvt_excl_poa with proximity_mode=sentence_window."""

    def _gate(self, proximity_mode=None):
        gate = {
            "gate_type": "exclude_if_any",
            "gate_id": "dvt_excl_poa",
            "rule_id": "DVT_EXCL_POA",
            "reason": "DVT documented as present on arrival.",
            "query_keys": ["dvt_poa_phrase"],
            "require_context_keys": ["dvt_dx"],
        }
        if proximity_mode is not None:
            gate["proximity_mode"] = proximity_mode
        return gate

    # D1 – same sentence: POA + DVT dx together → EXCLUDED
    def test_dvt_poa_same_sentence_fires(self):
        text = "Deep vein thrombosis was present on arrival per outside records."
        patient = _make_patient([text], DVT_PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "DVT POA same sentence should fire")
        self.assertEqual(result.rule_id, "DVT_EXCL_POA")

    # D2 – far apart: POA phrase in history, DVT dx many sentences later → no exclusion
    def test_dvt_poa_far_apart_does_not_fire(self):
        text = (
            "Patient was present on arrival with multiple injuries. "
            "Vitals stable. Labs drawn. CT ordered. "
            "Imaging reviewed. Consult placed. "
            "Venous duplex revealed deep vein thrombosis in the left femoral vein."
        )
        patient = _make_patient([text], DVT_PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNone(result, "DVT POA far-apart should not fire")

    # D3 – default (no proximity_mode): whole-line co-occurrence still fires
    def test_dvt_default_whole_line_fires(self):
        text = (
            "Patient was present on arrival with multiple injuries. "
            "Vitals stable. Labs drawn. CT ordered. "
            "Venous duplex revealed deep vein thrombosis in the left femoral vein."
        )
        patient = _make_patient([text], DVT_PATTERNS)
        result = eval_exclude_if_any(self._gate(), patient, CONTRACT)
        self.assertIsNotNone(result, "DVT default whole-line should fire")

    # D4 – adjacent sentence: POA in sentence i, DVT dx in i+1 → fires (within ±1)
    def test_dvt_poa_adjacent_fires(self):
        text = "History of prior to arrival conditions. Deep vein thrombosis confirmed on duplex."
        patient = _make_patient([text], DVT_PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "DVT POA adjacent sentence should fire")


# ---- PE POA exclusion proximity tests (P1–P4) -----------------------------

# Mapper-aligned patterns for PE
PE_PATTERNS = {
    "pe_poa_strict": [
        r"\b(pulmonary\s+embol(?:ism)?|PE)\b.*\bpresent\s+on\s+arrival\b",
        r"\bpresent\s+on\s+arrival\b.*\b(pulmonary\s+embol(?:ism)?|PE)\b",
        r"\b(pulmonary\s+embol(?:ism)?|PE)\b.*\bPOA\b",
        r"\bPOA\b.*\b(pulmonary\s+embol(?:ism)?|PE)\b",
    ],
    "pe_dx_positive": [
        r"\bacute\s+(pulmonary\s+embol(?:ism)?|PE)\b",
        r"\b(pulmonary\s+embol(?:ism)?|PE)\b.*\b(positive|confirmed|diagnos)\b",
        r"\bfilling\s+defect\b.*\bpulmonary\s+arter",
        r"\bembolus\b.*\bpulmonary\b",
    ],
}


class TestPePoaProximity(unittest.TestCase):
    """PE Event 14: pe_excl_poa with proximity_mode=sentence_window."""

    def _gate(self, proximity_mode=None):
        gate = {
            "gate_type": "exclude_if_any",
            "gate_id": "pe_excl_poa",
            "rule_id": "PE_EXCL_POA",
            "reason": "PE documented as present on arrival.",
            "query_keys": ["pe_poa_strict"],
            "require_context_keys": ["pe_dx_positive"],
        }
        if proximity_mode is not None:
            gate["proximity_mode"] = proximity_mode
        return gate

    # P1 – same sentence: PE POA + PE dx together → EXCLUDED
    def test_pe_poa_same_sentence_fires(self):
        text = "Acute pulmonary embolism was present on arrival and confirmed on CTA."
        patient = _make_patient([text], PE_PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "PE POA same sentence should fire")
        self.assertEqual(result.rule_id, "PE_EXCL_POA")

    # P2 – far apart: PE POA phrase early, PE dx many sentences later → no exclusion
    def test_pe_poa_far_apart_does_not_fire(self):
        text = (
            "PE was present on arrival per EMS report. "
            "Patient stabilized. Vitals monitored. Labs drawn. "
            "CT angiography performed. Radiology consulted. "
            "Filling defect noted in right pulmonary artery on repeat imaging."
        )
        patient = _make_patient([text], PE_PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNone(result, "PE POA far-apart should not fire")

    # P3 – default (no proximity_mode): whole-line co-occurrence still fires
    def test_pe_default_whole_line_fires(self):
        text = (
            "PE was present on arrival per EMS report. "
            "Vitals monitored. Labs drawn. "
            "Acute pulmonary embolism confirmed on CTA."
        )
        patient = _make_patient([text], PE_PATTERNS)
        result = eval_exclude_if_any(self._gate(), patient, CONTRACT)
        self.assertIsNotNone(result, "PE default whole-line should fire")

    # P4 – adjacent sentence: PE POA in sentence i, PE dx confirmation in i+1 → fires
    def test_pe_poa_adjacent_fires(self):
        text = "Pulmonary embolism present on arrival. Acute PE confirmed on CTA chest."
        patient = _make_patient([text], PE_PATTERNS)
        result = eval_exclude_if_any(self._gate("sentence_window"), patient, CONTRACT)
        self.assertIsNotNone(result, "PE POA adjacent sentence should fire")


if __name__ == "__main__":
    unittest.main()
