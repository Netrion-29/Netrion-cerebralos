#!/usr/bin/env python3
"""
Tests for protocol engine: trigger criteria evaluation + rules loading.

Covers:
- rules_loader loads deaconess shared_action_buckets_v1.json
- eval_trigger_criteria correctly returns NOT_TRIGGERED for non-matching patients
- eval_trigger_criteria correctly returns passed=True for matching patients
- keyword fallback does not false-trigger when text doesn't match
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from cerebralos.protocol_engine.model import (
    EvidencePointer,
    ProtocolEvidence,
    ProtocolFacts,
    ProtocolOutcome,
    RequirementType,
    SourceType,
)
from cerebralos.protocol_engine.engine import eval_trigger_criteria, evaluate_protocol
from cerebralos.protocol_engine.rules_loader import (
    load_protocol_shared,
    load_protocol_ruleset,
)


# ── Helper: build minimal ProtocolFacts ──────────────────────────
def _make_facts(
    texts: list[str],
    action_patterns: dict | None = None,
    source_type: SourceType = SourceType.TRAUMA_HP,
) -> ProtocolFacts:
    """Build ProtocolFacts with given evidence texts and action patterns."""
    evidence = []
    for i, t in enumerate(texts):
        evidence.append(
            ProtocolEvidence(
                source_type=source_type,
                timestamp="2026-01-15 08:00:00",
                text=t,
                pointer=EvidencePointer(ref={"block_id": i, "line_start": i, "line_end": i}),
            )
        )
    return ProtocolFacts(
        evidence=evidence,
        facts={
            "action_patterns": action_patterns or {},
            "arrival_time": "2026-01-15 07:30:00",
            "patient_id": "TEST_PATIENT",
        },
    )


# ── 1. Rules loader merges deaconess action buckets ────────────
class TestRulesLoaderDeaconessMerge:
    def test_shared_contains_deaconess_gate_keys(self):
        """load_protocol_shared() must include deaconess-specific gate patterns."""
        shared = load_protocol_shared()
        buckets = shared["action_buckets"]
        assert "protocol_tbi_gate" in buckets, "Missing protocol_tbi_gate from deaconess buckets"
        assert "protocol_rib_fx_gate" in buckets, "Missing protocol_rib_fx_gate"
        assert "protocol_dvt_gate" in buckets, "Missing protocol_dvt_gate"
        assert "protocol_burn_gate" in buckets, "Missing protocol_burn_gate"

    def test_shared_still_has_generic_keys(self):
        """Generic shared keys (vital_signs_patterns, etc.) must still be present."""
        shared = load_protocol_shared()
        buckets = shared["action_buckets"]
        assert "vital_signs_patterns" in buckets
        assert "imaging_order_patterns" in buckets

    def test_deaconess_gate_keys_are_lists(self):
        """Deaconess gate keys must be non-empty lists of pattern strings."""
        shared = load_protocol_shared()
        buckets = shared["action_buckets"]
        for key in ["protocol_tbi_gate", "protocol_rib_fx_gate", "protocol_dvt_gate"]:
            val = buckets[key]
            assert isinstance(val, list), f"{key} should be a list"
            assert len(val) > 0, f"{key} should have at least one pattern"
            assert all(isinstance(p, str) for p in val), f"{key} should contain strings"

    def test_ruleset_patterns_expand_deaconess_keys(self):
        """load_protocol_ruleset() must make deaconess gate keys available for matching."""
        rs = load_protocol_ruleset("TRAUMATIC_BRAIN_INJURY_MANAGEMENT")
        buckets = rs.shared.get("action_buckets", {})
        assert "protocol_tbi_gate" in buckets


# ── 2. eval_trigger_criteria: NOT_TRIGGERED for non-matching ───
class TestTriggerCriteriaNotTriggered:
    def _get_shared_patterns(self):
        shared = load_protocol_shared()
        return shared.get("action_buckets", {})

    def test_tbi_trigger_on_non_tbi_patient(self):
        """Patient with ankle fracture should NOT trigger TBI protocol."""
        patterns = self._get_shared_patterns()
        patient = _make_facts(
            texts=[
                "54-year-old male with left ankle fracture after fall from ladder. "
                "No loss of consciousness. GCS 15. Alert and oriented x4.",
            ],
            action_patterns=patterns,
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["protocol_tbi_gate"],
            "acceptable_evidence": ["TRAUMA_HP"],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert not result.passed, "TBI trigger should not fire for ankle fracture"
        assert "NOT_TRIGGERED" in result.reason

    def test_rib_fx_trigger_on_non_rib_patient(self):
        """Patient with isolated femur fracture should NOT trigger rib fracture protocol."""
        patterns = self._get_shared_patterns()
        patient = _make_facts(
            texts=[
                "28-year-old female with right femur fracture from MVC. "
                "Chest X-ray unremarkable. No thoracic injuries.",
            ],
            action_patterns=patterns,
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["protocol_rib_fx_gate"],
            "acceptable_evidence": ["TRAUMA_HP", "RADIOLOGY"],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert not result.passed
        assert "NOT_TRIGGERED" in result.reason

    def test_burn_trigger_on_non_burn_patient(self):
        """Patient with blunt trauma should NOT trigger burn protocol."""
        patterns = self._get_shared_patterns()
        patient = _make_facts(
            texts=[
                "72-year-old male pedestrian struck by vehicle at low speed. "
                "Complains of right hip pain. No thermal injury.",
            ],
            action_patterns=patterns,
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["protocol_burn_gate"],
            "acceptable_evidence": ["TRAUMA_HP"],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert not result.passed
        assert "NOT_TRIGGERED" in result.reason


# ── 3. eval_trigger_criteria: passed=True for matching ──────────
class TestTriggerCriteriaTriggered:
    def _get_shared_patterns(self):
        shared = load_protocol_shared()
        return shared.get("action_buckets", {})

    def test_tbi_trigger_fires_for_tbi_patient(self):
        """Patient with documented TBI should trigger TBI protocol."""
        patterns = self._get_shared_patterns()
        patient = _make_facts(
            texts=[
                "42-year-old male with traumatic brain injury after motorcycle "
                "accident. CT head shows subdural hematoma. GCS 10.",
            ],
            action_patterns=patterns,
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["protocol_tbi_gate"],
            "acceptable_evidence": ["TRAUMA_HP", "PHYSICIAN_NOTE", "RADIOLOGY"],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert result.passed, f"TBI trigger should fire. Reason: {result.reason}"

    def test_rib_fx_trigger_fires_for_rib_patient(self):
        """Patient with rib fractures should trigger rib fracture protocol."""
        patterns = self._get_shared_patterns()
        patient = _make_facts(
            texts=[
                "65-year-old female with multiple left-sided rib fractures "
                "(ribs 4-8) after fall from standing. Pain with deep inspiration.",
            ],
            action_patterns=patterns,
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["protocol_rib_fx_gate"],
            "acceptable_evidence": ["TRAUMA_HP", "RADIOLOGY"],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert result.passed, f"Rib fx trigger should fire. Reason: {result.reason}"

    def test_dvt_trigger_fires_for_trauma_patient(self):
        """Any trauma patient should trigger DVT prophylaxis protocol."""
        patterns = self._get_shared_patterns()
        patient = _make_facts(
            texts=[
                "55-year-old male fall from 10 feet. Multiple injuries.",
            ],
            action_patterns=patterns,
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["protocol_dvt_gate"],
            "acceptable_evidence": ["TRAUMA_HP"],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert result.passed, f"DVT trigger should fire for trauma patient. Reason: {result.reason}"


# ── 4. Keyword fallback does NOT false-trigger ──────────────────
class TestKeywordFallbackNoFalseTrigger:
    def test_keyword_no_match_gives_not_triggered(self):
        """Keyword fallback must NOT set found=True when text doesn't contain the keyword."""
        patient = _make_facts(
            texts=["Patient has ankle fracture. No other injuries noted."],
            action_patterns={},  # No pattern keys — forces keyword fallback
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["traumatic brain injury"],
            "acceptable_evidence": [],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert not result.passed, "Keyword fallback should not false-trigger"
        assert "NOT_TRIGGERED" in result.reason

    def test_keyword_match_does_trigger(self):
        """Keyword fallback should trigger when text actually contains the keyword."""
        patient = _make_facts(
            texts=["Patient sustained traumatic brain injury from fall."],
            action_patterns={},  # No pattern keys — forces keyword fallback
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": ["traumatic brain injury"],
            "acceptable_evidence": [],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        assert result.passed, f"Keyword fallback should trigger when text matches. Reason: {result.reason}"

    def test_keyword_secondary_condition_no_false_trigger(self):
        """Secondary keyword condition must not false-trigger either."""
        patient = _make_facts(
            texts=["Patient sustained traumatic brain injury from fall."],
            action_patterns={},
        )
        req = {
            "id": "REQ_TRIGGER_CRITERIA",
            "trigger_conditions": [
                "traumatic brain injury",  # matches
                "compartment syndrome",    # does NOT match
            ],
            "acceptable_evidence": [],
        }
        contract = {"evidence": {"max_items_per_requirement": 8}}
        result = eval_trigger_criteria(req, patient, contract)
        # Primary matches, secondary doesn't → INDETERMINATE (missing data)
        assert not result.passed
        assert "INDETERMINATE" in result.reason


# ── 5. Full protocol evaluation: NOT_TRIGGERED outcomes ────────
class TestFullProtocolEvaluation:
    def test_tbi_protocol_not_triggered_for_non_tbi(self):
        """Full TBI protocol evaluation should return NOT_TRIGGERED for non-TBI patient."""
        rs = load_protocol_ruleset("TRAUMATIC_BRAIN_INJURY_MANAGEMENT")
        action_patterns = {}
        action_patterns.update(rs.shared.get("action_buckets", {}))

        patient = _make_facts(
            texts=[
                "44-year-old with isolated right wrist fracture after mechanical fall. "
                "No head strike. No loss of consciousness. GCS 15.",
            ],
            action_patterns=action_patterns,
        )
        result = evaluate_protocol(rs.protocol, rs.contract, patient)
        assert result.outcome == ProtocolOutcome.NOT_TRIGGERED, (
            f"TBI protocol should be NOT_TRIGGERED for wrist fracture patient. "
            f"Got: {result.outcome.value}"
        )

    def test_tbi_protocol_triggered_for_tbi(self):
        """Full TBI protocol evaluation should not be NOT_TRIGGERED for TBI patient."""
        rs = load_protocol_ruleset("TRAUMATIC_BRAIN_INJURY_MANAGEMENT")
        action_patterns = {}
        action_patterns.update(rs.shared.get("action_buckets", {}))

        patient = _make_facts(
            texts=[
                "38-year-old male with traumatic brain injury after assault. "
                "CT head: subarachnoid hemorrhage. GCS 12 after resuscitation.",
            ],
            action_patterns=action_patterns,
        )
        result = evaluate_protocol(rs.protocol, rs.contract, patient)
        assert result.outcome != ProtocolOutcome.NOT_TRIGGERED, (
            f"TBI protocol should trigger for TBI patient. Got: {result.outcome.value}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
