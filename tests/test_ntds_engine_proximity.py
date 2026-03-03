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


if __name__ == "__main__":
    unittest.main()
