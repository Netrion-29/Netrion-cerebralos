#!/usr/bin/env python3
"""
Unit and integration tests for LDA (Lines/Drains/Airways) engine gates.

Covers:
  1. LDA gate functions (lda_duration, lda_present_at, lda_device_day_count)
  2. PatientFacts builder (build_lda_episodes round-trip)
  3. Feature flag behavior (ENABLE_LDA_GATES on/off)
  4. Rule precision: LDA gates in E05/E06/E21 with synthetic episodes
  5. Contract validation for lda_episodes_v1
  6. Text-derived LDA episodes from flowsheet day-counter patterns
  7. Engine gate integration with text-derived episodes
  8. Precision tests per event (E05/E06/E21) with flag toggle

Raw evidence derivation note:
  - David_Gross.txt: central line (Left IJ), mechanical ventilator, Foley catheter
    Phrases: "Left IJ approach central line", "mechanical ventilation",
    "Foley catheter", "intubated", "extubated"
    Flowsheet: "Catheter day" (max 3), "Line Day" (max 6)
  - Linda_Hufford.txt: "LDAs" section present, "Non-Invasive Mechanical Ventilation"
    (baseline — no invasive devices with duration data, no day-counter lines)
  - Ronald_Bittner: "Catheter day" (max 8), "Line Day" (max 12) — richest device data
  - Timothy_Nachtwey: "Vent day" (max 6), "Catheter day" (max 6) — only vent patient
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cerebralos.ntds_logic.model import (
    Evidence,
    EvidencePointer,
    EventResult,
    GateResult,
    LDAEpisode,
    LDA_CONFIDENCE_LEVELS,
    LDA_DEVICE_TYPES,
    Outcome,
    PatientFacts,
    SourceType,
)
from cerebralos.ntds_logic import engine
from cerebralos.ntds_logic.build_patientfacts_from_txt import (
    build_lda_episodes,
    _extract_lda_episodes_from_lines,
    _extract_lda_startstop_episodes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Helpers ──────────────────────────────────────────────────────────

def _make_patient(lda_episodes=None, device_day_counts=None, query_patterns=None):
    """Build a PatientFacts with optional LDA episode data."""
    facts = {"query_patterns": query_patterns or {}}
    if lda_episodes is not None:
        facts["lda_episodes_v1"] = {
            "episodes": lda_episodes,
            "device_day_counts": device_day_counts or {},
        }
    return PatientFacts(patient_id="test", facts=facts, evidence=[])


def _gate(gate_type, gate_id, **kwargs):
    """Build a gate dict."""
    d = {"gate_type": gate_type, "gate_id": gate_id}
    d.update(kwargs)
    return d


def _contract():
    return {"evidence": {"max_items_per_gate": 8}, "outcomes": {"allowed": ["YES", "NO", "EXCLUDED", "UNABLE_TO_DETERMINE"]}}


# ═══════════════════════════════════════════════════════════════════
# 1. Model / SourceType
# ═══════════════════════════════════════════════════════════════════

class TestSourceTypeLDA:
    def test_lda_in_source_type(self):
        assert SourceType.LDA.value == "LDA"

    def test_lda_device_types_frozenset(self):
        assert "URINARY_CATHETER" in LDA_DEVICE_TYPES
        assert "CENTRAL_LINE" in LDA_DEVICE_TYPES
        assert "MECHANICAL_VENTILATOR" in LDA_DEVICE_TYPES

    def test_lda_confidence_order(self):
        assert LDA_CONFIDENCE_LEVELS == ("TEXT_APPROXIMATE", "TEXT_DERIVED", "TEXT_DERIVED_STARTSTOP", "STRUCTURED")

    def test_lda_episode_dataclass(self):
        ep = LDAEpisode(
            device_type="URINARY_CATHETER",
            start_ts="2026-01-03T14:30:00",
            stop_ts="2026-01-07T09:00:00",
            episode_days=3,
            source_confidence="STRUCTURED",
        )
        assert ep.device_type == "URINARY_CATHETER"
        assert ep.episode_days == 3
        assert ep.raw_line_ids == []


# ═══════════════════════════════════════════════════════════════════
# 2. LDA Gate Functions — Flag OFF (default)
# ═══════════════════════════════════════════════════════════════════

class TestLDAGatesFlagOff:
    """When ENABLE_LDA_GATES is False, all LDA gates should no-op to False."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES
        engine.ENABLE_LDA_GATES = False

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def test_lda_duration_noop(self):
        patient = _make_patient(lda_episodes=[{
            "device_type": "URINARY_CATHETER", "episode_days": 5,
            "source_confidence": "STRUCTURED",
        }])
        gate = _gate("lda_duration", "test_dur", device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed
        assert "disabled" in result.reason.lower()

    def test_lda_present_at_noop(self):
        patient = _make_patient(lda_episodes=[{
            "device_type": "CENTRAL_LINE", "start_ts": "2026-01-01T00:00:00",
            "source_confidence": "STRUCTURED",
        }])
        gate = _gate("lda_present_at", "test_pres", device_type="CENTRAL_LINE")
        result = engine.eval_lda_present_at(gate, patient, _contract())
        assert not result.passed

    def test_lda_device_day_count_noop(self):
        patient = _make_patient(device_day_counts={"URINARY_CATHETER": 5})
        gate = _gate("lda_device_day_count", "test_ddc", device_type="URINARY_CATHETER", count_gte=1)
        result = engine.eval_lda_device_day_count(gate, patient, _contract())
        assert not result.passed


# ═══════════════════════════════════════════════════════════════════
# 3. LDA Gate Functions — Flag ON
# ═══════════════════════════════════════════════════════════════════

class TestLDAGatesFlagOn:
    """When ENABLE_LDA_GATES is True, gates should evaluate LDA data."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES
        engine.ENABLE_LDA_GATES = True

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    # ── lda_duration ──

    def test_duration_pass_3day_foley(self):
        patient = _make_patient(lda_episodes=[{
            "device_type": "URINARY_CATHETER", "episode_days": 3,
            "source_confidence": "STRUCTURED",
            "start_ts": "2026-01-03T14:30:00", "stop_ts": "2026-01-06T09:00:00",
        }])
        gate = _gate("lda_duration", "cauti_lda", device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed
        assert "3d" in result.reason

    def test_duration_fail_1day_foley(self):
        patient = _make_patient(lda_episodes=[{
            "device_type": "URINARY_CATHETER", "episode_days": 1,
            "source_confidence": "STRUCTURED",
        }])
        gate = _gate("lda_duration", "cauti_lda", device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_duration_fail_wrong_device(self):
        patient = _make_patient(lda_episodes=[{
            "device_type": "CENTRAL_LINE", "episode_days": 5,
            "source_confidence": "STRUCTURED",
        }])
        gate = _gate("lda_duration", "cauti_lda", device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_duration_missing_lda_data(self):
        patient = _make_patient()  # No lda_episodes_v1
        gate = _gate("lda_duration", "cauti_lda", device_type="URINARY_CATHETER",
                      days_gte=2, outcome_if_missing="NO")
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed
        assert "missing" in result.reason.lower()

    def test_duration_confidence_filter(self):
        """TEXT_APPROXIMATE episode should fail min_confidence=TEXT_DERIVED."""
        patient = _make_patient(lda_episodes=[{
            "device_type": "URINARY_CATHETER", "episode_days": 5,
            "source_confidence": "TEXT_APPROXIMATE",
        }])
        gate = _gate("lda_duration", "cauti_lda", device_type="URINARY_CATHETER",
                      days_gte=2, min_confidence="TEXT_DERIVED")
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_duration_confidence_structured_passes(self):
        """STRUCTURED episode should pass min_confidence=TEXT_DERIVED."""
        patient = _make_patient(lda_episodes=[{
            "device_type": "URINARY_CATHETER", "episode_days": 5,
            "source_confidence": "STRUCTURED",
        }])
        gate = _gate("lda_duration", "cauti_lda", device_type="URINARY_CATHETER",
                      days_gte=2, min_confidence="TEXT_DERIVED")
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    # ── lda_present_at ──

    def test_present_at_active(self):
        patient = _make_patient(lda_episodes=[{
            "device_type": "CENTRAL_LINE",
            "start_ts": "2026-01-01T08:00:00",
            "stop_ts": "2026-01-10T12:00:00",
            "source_confidence": "STRUCTURED",
        }])
        gate = _gate("lda_present_at", "cl_present", device_type="CENTRAL_LINE")
        result = engine.eval_lda_present_at(gate, patient, _contract())
        assert result.passed

    def test_present_at_no_episodes(self):
        patient = _make_patient(lda_episodes=[])
        gate = _gate("lda_present_at", "cl_present", device_type="CENTRAL_LINE")
        result = engine.eval_lda_present_at(gate, patient, _contract())
        assert not result.passed

    # ── lda_device_day_count ──

    def test_device_day_count_pass(self):
        patient = _make_patient(
            lda_episodes=[],
            device_day_counts={"URINARY_CATHETER": 5, "CENTRAL_LINE": 3},
        )
        gate = _gate("lda_device_day_count", "uc_days", device_type="URINARY_CATHETER", count_gte=3)
        result = engine.eval_lda_device_day_count(gate, patient, _contract())
        assert result.passed

    def test_device_day_count_fail(self):
        patient = _make_patient(
            lda_episodes=[],
            device_day_counts={"URINARY_CATHETER": 1},
        )
        gate = _gate("lda_device_day_count", "uc_days", device_type="URINARY_CATHETER", count_gte=3)
        result = engine.eval_lda_device_day_count(gate, patient, _contract())
        assert not result.passed

    # ── lda_overlap ──

    def test_overlap_no_reference_ts(self):
        """Without a reference timestamp, overlap should fail."""
        patient = _make_patient()
        gate = _gate("lda_overlap", "overlap_test", device_type="CENTRAL_LINE",
                      reference="event_date", window_days=2)
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed
        assert "no reference" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════════
# 4. PatientFacts builder — build_lda_episodes()
# ═══════════════════════════════════════════════════════════════════

class TestBuildLDAEpisodes:
    def test_no_file_returns_empty(self):
        result = build_lda_episodes(patient_id="test", lda_json_path=None)
        assert result == []

    def test_missing_file_returns_empty(self):
        result = build_lda_episodes(
            patient_id="test",
            lda_json_path=Path("/nonexistent/file.json"),
        )
        assert result == []

    def test_structured_feed_round_trip(self):
        feed = {
            "patient_id": "test_patient",
            "lda_records": [
                {
                    "device_type": "URINARY_CATHETER",
                    "start_ts": "2026-01-03T14:30:00",
                    "stop_ts": "2026-01-07T09:00:00",
                    "episode_days": 3,
                    "source_confidence": "STRUCTURED",
                    "location": "urethral",
                    "inserted_by": "RN",
                    "notes": "Foley 16Fr placed for strict I&O",
                    "raw_line_ids": ["L4521-L4521"],
                },
                {
                    "device_type": "CENTRAL_LINE",
                    "start_ts": "2026-01-01T08:00:00",
                    "stop_ts": "2026-01-06T16:00:00",
                    "source_confidence": "STRUCTURED",
                    "location": "left IJ",
                },
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(feed, f)
            tmp_path = Path(f.name)

        try:
            episodes = build_lda_episodes(patient_id="test", lda_json_path=tmp_path)
            assert len(episodes) == 2
            assert episodes[0]["device_type"] == "URINARY_CATHETER"
            assert episodes[0]["episode_days"] == 3
            assert episodes[0]["source_confidence"] == "STRUCTURED"
            assert episodes[1]["device_type"] == "CENTRAL_LINE"
            # episode_days computed from timestamps: 5 days
            assert episodes[1]["episode_days"] == 5
        finally:
            tmp_path.unlink()

    def test_invalid_device_type_filtered(self):
        feed = {
            "lda_records": [
                {"device_type": "INVALID_TYPE", "episode_days": 3},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(feed, f)
            tmp_path = Path(f.name)

        try:
            episodes = build_lda_episodes(lda_json_path=tmp_path)
            assert episodes == []
        finally:
            tmp_path.unlink()


# ═══════════════════════════════════════════════════════════════════
# 5. Rule precision — LDA gates in E05/E06/E21
# ═══════════════════════════════════════════════════════════════════

RULE_DIR = REPO_ROOT / "rules" / "ntds" / "logic" / "2026"


class TestE05CautiLDAGateWiring:
    @pytest.fixture(autouse=True)
    def _load_rule(self):
        with open(RULE_DIR / "05_cauti.json") as f:
            self.rule = json.load(f)

    def test_lda_gate_present(self):
        gate_ids = {g["gate_id"] for g in self.rule["gates"]}
        assert "cauti_catheter_duration_lda" in gate_ids

    def test_lda_gate_not_required(self):
        for g in self.rule["gates"]:
            if g["gate_id"] == "cauti_catheter_duration_lda":
                assert g.get("required") is False

    def test_lda_gate_type(self):
        for g in self.rule["gates"]:
            if g["gate_id"] == "cauti_catheter_duration_lda":
                assert g["gate_type"] == "lda_duration"
                assert g["device_type"] == "URINARY_CATHETER"
                assert g["days_gte"] == 2


class TestE06ClabsiLDAGateWiring:
    @pytest.fixture(autouse=True)
    def _load_rule(self):
        with open(RULE_DIR / "06_clabsi.json") as f:
            self.rule = json.load(f)

    def test_lda_gate_present(self):
        gate_ids = {g["gate_id"] for g in self.rule["gates"]}
        assert "clabsi_central_line_duration_lda" in gate_ids

    def test_lda_gate_not_required(self):
        for g in self.rule["gates"]:
            if g["gate_id"] == "clabsi_central_line_duration_lda":
                assert g.get("required") is False


class TestE21VapLDAGateWiring:
    @pytest.fixture(autouse=True)
    def _load_rule(self):
        with open(RULE_DIR / "21_vap.json") as f:
            self.rule = json.load(f)

    def test_lda_gate_present(self):
        gate_ids = {g["gate_id"] for g in self.rule["gates"]}
        assert "vent_duration_lda" in gate_ids

    def test_lda_gate_not_required(self):
        for g in self.rule["gates"]:
            if g["gate_id"] == "vent_duration_lda":
                assert g.get("required") is False
                assert g["device_type"] == "MECHANICAL_VENTILATOR"
                assert g["days_gte"] == 2


# ═══════════════════════════════════════════════════════════════════
# 6. Engine dispatch — LDA gate types recognized
# ═══════════════════════════════════════════════════════════════════

class TestEngineDispatchLDA:
    """Verify that the engine gate dispatch recognizes LDA gate types
    without returning 'Unknown gate_type'."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES
        engine.ENABLE_LDA_GATES = False

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _eval_gate(self, gate_type, **kwargs):
        """Simulate evaluate_event's gate dispatch for a single gate."""
        gate = {"gate_type": gate_type, "gate_id": f"test_{gate_type}"}
        gate.update(kwargs)
        patient = _make_patient()
        contract = _contract()

        gt = str(gate.get("gate_type", ""))
        if gt == "lda_duration":
            return engine.eval_lda_duration(gate, patient, contract)
        elif gt == "lda_present_at":
            return engine.eval_lda_present_at(gate, patient, contract)
        elif gt == "lda_overlap":
            return engine.eval_lda_overlap(gate, patient, contract)
        elif gt == "lda_device_day_count":
            return engine.eval_lda_device_day_count(gate, patient, contract)
        return GateResult(gate="unknown", passed=False, reason=f"Unknown: {gt}", evidence=[])

    def test_lda_duration_dispatched(self):
        r = self._eval_gate("lda_duration", device_type="URINARY_CATHETER", days_gte=2)
        assert "Unknown" not in r.reason

    def test_lda_present_at_dispatched(self):
        r = self._eval_gate("lda_present_at", device_type="CENTRAL_LINE")
        assert "Unknown" not in r.reason

    def test_lda_overlap_dispatched(self):
        r = self._eval_gate("lda_overlap", device_type="CENTRAL_LINE")
        assert "Unknown" not in r.reason

    def test_lda_device_day_count_dispatched(self):
        r = self._eval_gate("lda_device_day_count", device_type="URINARY_CATHETER", count_gte=1)
        assert "Unknown" not in r.reason


# ═══════════════════════════════════════════════════════════════════
# 7. Flag-off backward compatibility — existing outcomes unchanged
# ═══════════════════════════════════════════════════════════════════

class TestFlagOffBackwardCompat:
    """With ENABLE_LDA_GATES=False (default), LDA gates in rules should
    not block or change outcomes since they are required=false."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES
        engine.ENABLE_LDA_GATES = False

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def test_e05_lda_gate_does_not_block(self):
        """Evaluate E05 with LDA gate — should not cause unknown gate_type error."""
        with open(RULE_DIR / "05_cauti.json") as f:
            rule = json.load(f)

        lda_gate = None
        for g in rule["gates"]:
            if g["gate_id"] == "cauti_catheter_duration_lda":
                lda_gate = g
                break
        assert lda_gate is not None
        assert lda_gate.get("required") is False

        # Evaluate the gate directly
        patient = _make_patient()
        result = engine.eval_lda_duration(lda_gate, patient, _contract())
        assert not result.passed  # Expected: flag off → False
        assert "disabled" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════════
# 8. Contract validation — lda_episodes_v1
# ═══════════════════════════════════════════════════════════════════

class TestContractLDAEpisodes:
    def test_lda_episodes_v1_in_known_features(self):
        from cerebralos.validation.validate_patient_features_contract_v1 import KNOWN_FEATURE_KEYS
        assert "lda_episodes_v1" in KNOWN_FEATURE_KEYS

    def test_valid_lda_episodes_passes(self):
        from cerebralos.validation.validate_patient_features_contract_v1 import validate_contract
        data = {
            "build": {},
            "patient_id": "test",
            "days": 1,
            "evidence_gaps": [],
            "features": {
                "lda_episodes_v1": {
                    "episodes": [
                        {"device_type": "URINARY_CATHETER", "episode_days": 3},
                    ],
                    "device_day_counts": {"URINARY_CATHETER": 3},
                },
            },
            "warnings": [],
            "warnings_summary": {},
        }
        errors = validate_contract(data)
        assert not errors, f"Unexpected errors: {errors}"

    def test_missing_device_type_caught(self):
        from cerebralos.validation.validate_patient_features_contract_v1 import validate_contract
        data = {
            "build": {},
            "patient_id": "test",
            "days": 1,
            "evidence_gaps": [],
            "features": {
                "lda_episodes_v1": {
                    "episodes": [
                        {"episode_days": 3},  # missing device_type
                    ],
                },
            },
            "warnings": [],
            "warnings_summary": {},
        }
        errors = validate_contract(data)
        lda_errors = [e for e in errors if "LDA_EPISODES" in e]
        assert lda_errors


# ═══════════════════════════════════════════════════════════════════
# 9. Text-derived LDA episode extraction
# ═══════════════════════════════════════════════════════════════════

class TestTextDerivedExtraction:
    """Unit tests for _extract_lda_episodes_from_lines helper."""

    def test_catheter_day_simple(self):
        eps = _extract_lda_episodes_from_lines(["Catheter day 3"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"
        assert eps[0]["episode_days"] == 3
        assert eps[0]["source_confidence"] == "TEXT_DERIVED"

    def test_catheter_day_colon(self):
        eps = _extract_lda_episodes_from_lines(["Catheter day: 5"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"
        assert eps[0]["episode_days"] == 5

    def test_catheter_day_tabbed_multicolumn(self):
        """Format observed in Ronald_Bittner: 'Catheter day     8   -KW ...'"""
        eps = _extract_lda_episodes_from_lines([
            "Catheter day     8   -KW —       —       —       8   -BW",
        ])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"
        assert eps[0]["episode_days"] == 8

    def test_line_day_simple(self):
        eps = _extract_lda_episodes_from_lines(["Line Day: 5"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"
        assert eps[0]["episode_days"] == 5

    def test_line_day_multicolumn(self):
        """Format observed in Ronald_Bittner: 'Line Day 12   -DP   12   -ET'"""
        eps = _extract_lda_episodes_from_lines([
            "Line Day 12   -DP        12   -ET        11   -ET",
        ])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"
        assert eps[0]["episode_days"] == 12

    def test_central_line_day(self):
        eps = _extract_lda_episodes_from_lines(["Central line day 4"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"
        assert eps[0]["episode_days"] == 4

    def test_cvc_day(self):
        eps = _extract_lda_episodes_from_lines(["CVC day: 3"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"
        assert eps[0]["episode_days"] == 3

    def test_vent_day(self):
        eps = _extract_lda_episodes_from_lines(["Vent day: 4"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "MECHANICAL_VENTILATOR"
        assert eps[0]["episode_days"] == 4

    def test_ventilator_day(self):
        eps = _extract_lda_episodes_from_lines(["Ventilator day 6"])
        assert len(eps) == 1
        assert eps[0]["device_type"] == "MECHANICAL_VENTILATOR"
        assert eps[0]["episode_days"] == 6

    def test_max_day_across_lines(self):
        """Multiple mentions of same device → keep highest day."""
        eps = _extract_lda_episodes_from_lines([
            "Catheter day     1   -CG",
            "Catheter day     3   -MW",
            "Catheter day     2   -AW",
        ])
        assert len(eps) == 1
        assert eps[0]["episode_days"] == 3

    def test_multiple_device_types(self):
        eps = _extract_lda_episodes_from_lines([
            "Catheter day 3",
            "Line Day 5",
        ])
        assert len(eps) == 2
        types = {ep["device_type"] for ep in eps}
        assert types == {"URINARY_CATHETER", "CENTRAL_LINE"}

    def test_no_matches(self):
        eps = _extract_lda_episodes_from_lines([
            "Patient resting comfortably.",
            "Vitals stable.",
            "No issues today.",
        ])
        assert eps == []

    def test_empty_input(self):
        eps = _extract_lda_episodes_from_lines([])
        assert eps == []

    def test_raw_line_ids_populated(self):
        eps = _extract_lda_episodes_from_lines([
            "Some intro text",
            "Catheter day 2",
            "More text",
            "Catheter day 4",
        ])
        assert len(eps) == 1
        assert "L2" in eps[0]["raw_line_ids"]
        assert "L4" in eps[0]["raw_line_ids"]

    def test_all_schema_fields_present(self):
        """Every text-derived episode must have all LDAEpisode fields."""
        eps = _extract_lda_episodes_from_lines(["Catheter day 3"])
        expected_fields = {
            "device_type", "episode_days", "source_confidence",
            "start_ts", "stop_ts", "location", "inserted_by",
            "notes", "raw_line_ids",
        }
        assert set(eps[0].keys()) == expected_fields

    def test_start_stop_ts_none(self):
        """Text-derived episodes have no start/stop timestamps."""
        eps = _extract_lda_episodes_from_lines(["Line Day 3"])
        assert eps[0]["start_ts"] is None
        assert eps[0]["stop_ts"] is None


# ═══════════════════════════════════════════════════════════════════
# 10. build_lda_episodes with text-derived path
# ═══════════════════════════════════════════════════════════════════

class TestBuildLDAEpisodesTextDerived:
    """Tests for build_lda_episodes when raw_lines are provided."""

    def test_text_only_episodes(self):
        eps = build_lda_episodes(
            patient_id="test",
            raw_lines=["Catheter day 3", "Line Day 5"],
        )
        assert len(eps) == 2
        types = {ep["device_type"] for ep in eps}
        assert types == {"URINARY_CATHETER", "CENTRAL_LINE"}

    def test_text_and_no_json(self):
        eps = build_lda_episodes(
            patient_id="test",
            lda_json_path=None,
            raw_lines=["Catheter day 4"],
        )
        assert len(eps) == 1
        assert eps[0]["episode_days"] == 4

    def test_structured_overrides_text_for_same_device(self):
        """Structured JSON episode takes precedence over text for same device."""
        feed = {
            "lda_records": [
                {
                    "device_type": "URINARY_CATHETER",
                    "episode_days": 5,
                    "source_confidence": "STRUCTURED",
                },
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(feed, f)
            tmp_path = Path(f.name)

        try:
            eps = build_lda_episodes(
                patient_id="test",
                lda_json_path=tmp_path,
                raw_lines=["Catheter day 3"],  # also URINARY_CATHETER
            )
            # Only structured should remain for URINARY_CATHETER
            cath = [e for e in eps if e["device_type"] == "URINARY_CATHETER"]
            assert len(cath) == 1
            assert cath[0]["source_confidence"] == "STRUCTURED"
            assert cath[0]["episode_days"] == 5
        finally:
            tmp_path.unlink()

    def test_text_adds_device_not_in_structured(self):
        """Text-derived episodes for devices absent from structured are added."""
        feed = {
            "lda_records": [
                {
                    "device_type": "URINARY_CATHETER",
                    "episode_days": 5,
                    "source_confidence": "STRUCTURED",
                },
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(feed, f)
            tmp_path = Path(f.name)

        try:
            eps = build_lda_episodes(
                patient_id="test",
                lda_json_path=tmp_path,
                raw_lines=["Line Day 7"],  # CENTRAL_LINE not in structured
            )
            assert len(eps) == 2
            types = {ep["device_type"] for ep in eps}
            assert types == {"URINARY_CATHETER", "CENTRAL_LINE"}
        finally:
            tmp_path.unlink()

    def test_no_lines_no_json_returns_empty(self):
        eps = build_lda_episodes(patient_id="test")
        assert eps == []

    def test_empty_lines_returns_empty(self):
        eps = build_lda_episodes(patient_id="test", raw_lines=[])
        assert eps == []


# ═══════════════════════════════════════════════════════════════════
# 11. Engine gate integration with text-derived episodes
# ═══════════════════════════════════════════════════════════════════

class TestLDAGatesWithTextDerived:
    """Engine LDA gates should work with text-derived episodes when flag on."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES
        engine.ENABLE_LDA_GATES = True

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def test_duration_passes_with_text_catheter(self):
        """Text-derived catheter day 3 >= 2 → passes lda_duration gate."""
        episodes = _extract_lda_episodes_from_lines(["Catheter day 3"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_cath_dur",
                      device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_duration_fails_with_text_catheter_below_threshold(self):
        """Text-derived catheter day 1 < 2 → fails."""
        episodes = _extract_lda_episodes_from_lines(["Catheter day 1"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_cath_dur",
                      device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_duration_passes_with_text_line_day(self):
        """Text-derived Line Day 5 >= 2 → passes for CENTRAL_LINE."""
        episodes = _extract_lda_episodes_from_lines(["Line Day 5"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_line_dur",
                      device_type="CENTRAL_LINE", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_duration_passes_with_text_vent_day(self):
        """Text-derived Vent day 4 >= 2 → passes for MECHANICAL_VENTILATOR."""
        episodes = _extract_lda_episodes_from_lines(["Vent day 4"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_vent_dur",
                      device_type="MECHANICAL_VENTILATOR", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_text_confidence_meets_text_derived_min(self):
        """TEXT_DERIVED confidence meets min_confidence=TEXT_DERIVED."""
        episodes = _extract_lda_episodes_from_lines(["Catheter day 3"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_conf",
                      device_type="URINARY_CATHETER", days_gte=2,
                      min_confidence="TEXT_DERIVED")
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_text_confidence_fails_structured_min(self):
        """TEXT_DERIVED confidence < STRUCTURED minimum → fails."""
        episodes = _extract_lda_episodes_from_lines(["Catheter day 5"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_conf_fail",
                      device_type="URINARY_CATHETER", days_gte=2,
                      min_confidence="STRUCTURED")
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_flag_off_text_episodes_still_noop(self):
        """With flag off, text-derived episodes are present but gate returns False."""
        engine.ENABLE_LDA_GATES = False
        episodes = _extract_lda_episodes_from_lines(["Catheter day 10"])
        patient = _make_patient(lda_episodes=episodes)
        gate = _gate("lda_duration", "test_noop",
                      device_type="URINARY_CATHETER", days_gte=2)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed
        assert "disabled" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════════
# 12. Per-event precision with text-derived LDA + flag toggle
# ═══════════════════════════════════════════════════════════════════

class TestE05CautiTextDerivedPrecision:
    """E05 CAUTI: lda_duration gate with text-derived catheter episode."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _load_e05_lda_gate(self):
        with open(RULE_DIR / "05_cauti.json") as f:
            rule = json.load(f)
        for g in rule["gates"]:
            if g["gate_id"] == "cauti_catheter_duration_lda":
                return g
        pytest.fail("cauti_catheter_duration_lda gate not found in E05 rule")

    def test_flag_true_text_catheter_3d_passes(self):
        """Flag on + catheter day 3 (>=2) → gate passes."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e05_lda_gate()
        episodes = _extract_lda_episodes_from_lines(["Catheter day 3"])
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_flag_false_text_catheter_3d_fails(self):
        """Flag off + catheter day 3 → gate does not pass (disabled)."""
        engine.ENABLE_LDA_GATES = False
        gate = self._load_e05_lda_gate()
        episodes = _extract_lda_episodes_from_lines(["Catheter day 3"])
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_flag_true_no_catheter_fails(self):
        """Flag on but no catheter data → gate fails."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e05_lda_gate()
        patient = _make_patient(lda_episodes=[])
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed


class TestE06ClabsiTextDerivedPrecision:
    """E06 CLABSI: lda_duration gate with text-derived central line episode."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _load_e06_lda_gate(self):
        with open(RULE_DIR / "06_clabsi.json") as f:
            rule = json.load(f)
        for g in rule["gates"]:
            if g["gate_id"] == "clabsi_central_line_duration_lda":
                return g
        pytest.fail("clabsi_central_line_duration_lda gate not found in E06 rule")

    def test_flag_true_text_line_day_5_passes(self):
        """Flag on + Line Day 5 (>=2) → gate passes."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e06_lda_gate()
        episodes = _extract_lda_episodes_from_lines(["Line Day 5"])
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_flag_false_text_line_day_5_fails(self):
        """Flag off + Line Day 5 → gate does not pass (disabled)."""
        engine.ENABLE_LDA_GATES = False
        gate = self._load_e06_lda_gate()
        episodes = _extract_lda_episodes_from_lines(["Line Day 5"])
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_flag_true_no_line_data_fails(self):
        """Flag on but no central line data → gate fails."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e06_lda_gate()
        patient = _make_patient(lda_episodes=[])
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed


class TestE21VapTextDerivedPrecision:
    """E21 VAP: lda_duration gate with text-derived vent episode."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _load_e21_lda_gate(self):
        with open(RULE_DIR / "21_vap.json") as f:
            rule = json.load(f)
        for g in rule["gates"]:
            if g["gate_id"] == "vent_duration_lda":
                return g
        pytest.fail("vent_duration_lda gate not found in E21 rule")

    def test_flag_true_text_vent_day_4_passes(self):
        """Flag on + Vent day 4 (>=2) → gate passes."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e21_lda_gate()
        episodes = _extract_lda_episodes_from_lines(["Vent day 4"])
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_flag_false_text_vent_day_fails(self):
        """Flag off + Vent day 4 → gate does not pass (disabled)."""
        engine.ENABLE_LDA_GATES = False
        gate = self._load_e21_lda_gate()
        episodes = _extract_lda_episodes_from_lines(["Vent day 4"])
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed

    def test_flag_true_no_vent_data_fails(self):
        """Flag on but no vent data → gate fails."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e21_lda_gate()
        patient = _make_patient(lda_episodes=[])
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed


# ═══════════════════════════════════════════════════════════════════
# 13. Start/stop text extraction — insertion/removal patterns
# ═══════════════════════════════════════════════════════════════════

class TestStartStopExtraction:
    """Unit tests for _extract_lda_startstop_episodes helper."""

    # ── URINARY_CATHETER ──

    def test_foley_placed(self):
        eps = _extract_lda_startstop_episodes(
            ["Foley catheter placed in ED."],
            timestamps=["2026-01-15T09:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"
        assert eps[0]["start_ts"] == "2026-01-15T09:00:00"
        assert eps[0]["stop_ts"] is None
        assert eps[0]["source_confidence"] == "TEXT_DERIVED_STARTSTOP"

    def test_foley_inserted(self):
        eps = _extract_lda_startstop_episodes(
            ["Foley inserted for strict I&O."],
            timestamps=["2026-01-15T10:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"
        assert eps[0]["start_ts"] == "2026-01-15T10:00:00"

    def test_urinary_catheter_inserted(self):
        eps = _extract_lda_startstop_episodes(
            ["Urinary catheter inserted by RN."],
            timestamps=["2026-01-15T11:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"

    def test_foley_removed(self):
        eps = _extract_lda_startstop_episodes(
            ["Foley catheter placed.", "Foley removed at bedside."],
            timestamps=["2026-01-15T09:00:00", "2026-01-18T08:00:00"],
        )
        assert len(eps) == 1
        ep = eps[0]
        assert ep["device_type"] == "URINARY_CATHETER"
        assert ep["start_ts"] == "2026-01-15T09:00:00"
        assert ep["stop_ts"] == "2026-01-18T08:00:00"
        assert ep["episode_days"] == 3

    def test_indwelling_catheter_in_place(self):
        eps = _extract_lda_startstop_episodes(
            ["Indwelling urinary catheter in place."],
            timestamps=["2026-01-15T10:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "URINARY_CATHETER"

    # ── CENTRAL_LINE ──

    def test_central_line_placed(self):
        eps = _extract_lda_startstop_episodes(
            ["Central venous catheter placed, right IJ."],
            timestamps=["2026-01-15T14:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"
        assert eps[0]["start_ts"] == "2026-01-15T14:00:00"

    def test_picc_placed(self):
        eps = _extract_lda_startstop_episodes(
            ["PICC line placed in right arm."],
            timestamps=["2026-01-16T10:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"

    def test_cvl_inserted_removed(self):
        eps = _extract_lda_startstop_episodes(
            ["CVL inserted left subclavian.", "CVL removed without complication."],
            timestamps=["2026-01-15T08:00:00", "2026-01-20T10:00:00"],
        )
        assert len(eps) == 1
        ep = eps[0]
        assert ep["start_ts"] == "2026-01-15T08:00:00"
        assert ep["stop_ts"] == "2026-01-20T10:00:00"
        assert ep["episode_days"] == 5

    def test_central_line_removed(self):
        eps = _extract_lda_startstop_episodes(
            ["Central line removed per MD order."],
            timestamps=["2026-01-20T10:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"
        assert eps[0]["stop_ts"] == "2026-01-20T10:00:00"

    def test_triple_lumen_placed(self):
        eps = _extract_lda_startstop_episodes(
            ["Triple-lumen catheter placed."],
            timestamps=["2026-01-15T12:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "CENTRAL_LINE"

    # ── MECHANICAL_VENTILATOR / ENDOTRACHEAL_TUBE ──

    def test_intubated(self):
        eps = _extract_lda_startstop_episodes(
            ["Patient intubated in the ED."],
            timestamps=["2026-01-15T08:30:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "ENDOTRACHEAL_TUBE"
        assert eps[0]["start_ts"] == "2026-01-15T08:30:00"

    def test_extubated(self):
        eps = _extract_lda_startstop_episodes(
            ["Patient intubated.", "Patient extubated successfully."],
            timestamps=["2026-01-15T08:00:00", "2026-01-20T10:00:00"],
        )
        assert len(eps) == 1
        ep = eps[0]
        assert ep["device_type"] == "ENDOTRACHEAL_TUBE"
        assert ep["start_ts"] == "2026-01-15T08:00:00"
        assert ep["stop_ts"] == "2026-01-20T10:00:00"
        assert ep["episode_days"] == 5

    def test_mechanical_ventilation_initiated(self):
        eps = _extract_lda_startstop_episodes(
            ["Mechanical ventilation initiated for respiratory failure."],
            timestamps=["2026-01-15T09:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "MECHANICAL_VENTILATOR"

    def test_vent_discontinued(self):
        eps = _extract_lda_startstop_episodes(
            ["Patient placed on ventilator.", "Ventilator discontinued after wean trial."],
            timestamps=["2026-01-15T08:00:00", "2026-01-22T14:00:00"],
        )
        assert len(eps) == 1
        assert eps[0]["device_type"] == "MECHANICAL_VENTILATOR"
        assert eps[0]["episode_days"] == 7

    def test_trach_placed_ends_ett(self):
        """Tracheostomy placement ends the ETT episode."""
        eps = _extract_lda_startstop_episodes(
            ["Patient intubated.", "Tracheostomy placed."],
            timestamps=["2026-01-15T08:00:00", "2026-01-22T10:00:00"],
        )
        ett = [e for e in eps if e["device_type"] == "ENDOTRACHEAL_TUBE"]
        assert len(ett) == 1
        assert ett[0]["start_ts"] == "2026-01-15T08:00:00"
        assert ett[0]["stop_ts"] == "2026-01-22T10:00:00"

    # ── Edge cases ──

    def test_no_matches_empty(self):
        eps = _extract_lda_startstop_episodes(
            ["Patient resting comfortably.", "Vitals stable."],
            timestamps=["2026-01-15T08:00:00", "2026-01-15T09:00:00"],
        )
        assert eps == []

    def test_no_timestamps_still_returns_episode(self):
        """Episode still created without timestamps (nullable start/stop)."""
        eps = _extract_lda_startstop_episodes(
            ["Foley catheter placed."],
            timestamps=[None],
        )
        assert len(eps) == 1
        assert eps[0]["start_ts"] is None
        assert eps[0]["episode_days"] is None

    def test_no_timestamps_list_at_all(self):
        """timestamps arg omitted entirely."""
        eps = _extract_lda_startstop_episodes(["Foley catheter placed."])
        assert len(eps) == 1
        assert eps[0]["start_ts"] is None

    def test_multiple_device_types(self):
        """Multiple devices in same text."""
        eps = _extract_lda_startstop_episodes(
            ["Foley catheter placed.", "Central line placed left IJ."],
            timestamps=["2026-01-15T08:00:00", "2026-01-15T09:00:00"],
        )
        types = {e["device_type"] for e in eps}
        assert "URINARY_CATHETER" in types
        assert "CENTRAL_LINE" in types

    def test_all_schema_fields_present(self):
        """Every start/stop episode must have all LDAEpisode fields."""
        eps = _extract_lda_startstop_episodes(
            ["Foley catheter placed."],
            timestamps=["2026-01-15T08:00:00"],
        )
        expected = {
            "device_type", "episode_days", "source_confidence",
            "start_ts", "stop_ts", "location", "inserted_by",
            "notes", "raw_line_ids",
        }
        assert set(eps[0].keys()) == expected

    def test_raw_line_ids_populated(self):
        eps = _extract_lda_startstop_episodes(
            ["Some intro", "Foley catheter placed.", "More text", "Foley removed."],
            timestamps=[None, "2026-01-15T08:00:00", None, "2026-01-18T10:00:00"],
        )
        assert len(eps) == 1
        assert "L2" in eps[0]["raw_line_ids"]
        assert "L4" in eps[0]["raw_line_ids"]


# ═══════════════════════════════════════════════════════════════════
# 14. eval_lda_overlap tests
# ═══════════════════════════════════════════════════════════════════

class TestEvalLDAOverlap:
    """Tests for the eval_lda_overlap gate function."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES
        engine.ENABLE_LDA_GATES = True

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _make_overlap_patient(self, episodes, event_date=None, arrival_time=None):
        facts = {"query_patterns": {}}
        if event_date:
            facts["event_date"] = event_date
        if arrival_time:
            facts["arrival_time"] = arrival_time
        if episodes is not None:
            facts["lda_episodes_v1"] = {"episodes": episodes, "device_day_counts": {}}
        return PatientFacts(patient_id="test", facts=facts, evidence=[])

    def test_overlap_device_active_during_event(self):
        """Device episode spans the event date → passes."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-15T08:00:00",
                "stop_ts": "2026-01-20T10:00:00",
                "source_confidence": "TEXT_DERIVED_STARTSTOP",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert result.passed

    def test_overlap_device_before_event(self):
        """Device removed before event date → fails."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-10T08:00:00",
                "stop_ts": "2026-01-12T10:00:00",
                "source_confidence": "TEXT_DERIVED_STARTSTOP",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed

    def test_overlap_device_after_event(self):
        """Device placed after event date → fails."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-22T08:00:00",
                "stop_ts": "2026-01-25T10:00:00",
                "source_confidence": "TEXT_DERIVED_STARTSTOP",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed

    def test_overlap_with_window_days(self):
        """Device within ±2 days of event → passes."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "CENTRAL_LINE",
                "start_ts": "2026-01-10T08:00:00",
                "stop_ts": "2026-01-17T10:00:00",
                "source_confidence": "STRUCTURED",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="CENTRAL_LINE", reference="event_date", window_days=2)
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert result.passed

    def test_overlap_open_ended_start_only(self):
        """Device with only start_ts (no removal) → treat as still active."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-15T08:00:00",
                "stop_ts": None,
                "source_confidence": "TEXT_DERIVED_STARTSTOP",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert result.passed

    def test_overlap_no_timestamps_fails(self):
        """Episode with no timestamps at all → no overlap possible."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": None,
                "stop_ts": None,
                "source_confidence": "TEXT_DERIVED",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed

    def test_overlap_wrong_device_type(self):
        """Overlapping episode but wrong device → fails."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "CENTRAL_LINE",
                "start_ts": "2026-01-15T08:00:00",
                "stop_ts": "2026-01-20T10:00:00",
                "source_confidence": "STRUCTURED",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed

    def test_overlap_flag_off_noop(self):
        """With flag off, overlap should no-op to False."""
        engine.ENABLE_LDA_GATES = False
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-15T08:00:00",
                "stop_ts": "2026-01-20T10:00:00",
                "source_confidence": "STRUCTURED",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed
        assert "disabled" in result.reason.lower()

    def test_overlap_confidence_filter(self):
        """Episode below min_confidence → skipped."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-15T08:00:00",
                "stop_ts": "2026-01-20T10:00:00",
                "source_confidence": "TEXT_APPROXIMATE",
            }],
            event_date="2026-01-18T10:00:00",
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date",
                      min_confidence="STRUCTURED")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed

    def test_overlap_no_reference_timestamp(self):
        """No event_date or arrival_time in facts → fails."""
        patient = self._make_overlap_patient(
            episodes=[{
                "device_type": "URINARY_CATHETER",
                "start_ts": "2026-01-15T08:00:00",
                "stop_ts": "2026-01-20T10:00:00",
                "source_confidence": "STRUCTURED",
            }],
        )
        gate = _gate("lda_overlap", "test_overlap",
                      device_type="URINARY_CATHETER", reference="event_date")
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed


# ═══════════════════════════════════════════════════════════════════
# 15. Merge precedence: structured > startstop > day-counter
# ═══════════════════════════════════════════════════════════════════

class TestMergePrecedenceStartStop:
    """Tests for build_lda_episodes merge precedence with start/stop tier."""

    def test_startstop_overrides_day_counter(self):
        """TEXT_DERIVED_STARTSTOP takes precedence over TEXT_DERIVED day-counter."""
        eps = build_lda_episodes(
            patient_id="test",
            raw_lines=[
                "Foley catheter placed.",
                "Catheter day 3",
                "Foley removed at bedside.",
            ],
            raw_timestamps=[
                "2026-01-15T09:00:00",
                None,
                "2026-01-18T08:00:00",
            ],
        )
        cath = [e for e in eps if e["device_type"] == "URINARY_CATHETER"]
        assert len(cath) == 1
        assert cath[0]["source_confidence"] == "TEXT_DERIVED_STARTSTOP"
        assert cath[0]["start_ts"] == "2026-01-15T09:00:00"
        assert cath[0]["stop_ts"] == "2026-01-18T08:00:00"
        assert cath[0]["episode_days"] == 3

    def test_structured_overrides_startstop(self):
        """STRUCTURED JSON episode takes precedence over TEXT_DERIVED_STARTSTOP."""
        import tempfile
        feed = {
            "lda_records": [{
                "device_type": "URINARY_CATHETER",
                "episode_days": 5,
                "source_confidence": "STRUCTURED",
                "start_ts": "2026-01-12T08:00:00",
                "stop_ts": "2026-01-17T08:00:00",
            }],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(feed, f)
            tmp_path = Path(f.name)

        try:
            eps = build_lda_episodes(
                patient_id="test",
                lda_json_path=tmp_path,
                raw_lines=["Foley catheter placed.", "Foley removed."],
                raw_timestamps=["2026-01-15T09:00:00", "2026-01-18T08:00:00"],
            )
            cath = [e for e in eps if e["device_type"] == "URINARY_CATHETER"]
            assert len(cath) == 1
            assert cath[0]["source_confidence"] == "STRUCTURED"
            assert cath[0]["episode_days"] == 5
        finally:
            tmp_path.unlink()

    def test_different_devices_all_tiers(self):
        """Different device types from different tiers coexist."""
        eps = build_lda_episodes(
            patient_id="test",
            raw_lines=[
                "Foley catheter placed.",
                "Foley removed.",
                "Line Day 5",
                "Patient intubated.",
            ],
            raw_timestamps=[
                "2026-01-15T09:00:00",
                "2026-01-18T08:00:00",
                None,
                "2026-01-15T10:00:00",
            ],
        )
        types = {e["device_type"] for e in eps}
        assert "URINARY_CATHETER" in types   # TEXT_DERIVED_STARTSTOP
        assert "CENTRAL_LINE" in types       # TEXT_DERIVED
        assert "ENDOTRACHEAL_TUBE" in types  # TEXT_DERIVED_STARTSTOP

    def test_day_counter_kept_when_no_startstop(self):
        """Day-counter episode retained when no start/stop patterns match."""
        eps = build_lda_episodes(
            patient_id="test",
            raw_lines=["Catheter day 5"],
        )
        assert len(eps) == 1
        assert eps[0]["source_confidence"] == "TEXT_DERIVED"
        assert eps[0]["episode_days"] == 5

    def test_new_raw_timestamps_param_backward_compat(self):
        """Existing callers without raw_timestamps still work."""
        eps = build_lda_episodes(
            patient_id="test",
            raw_lines=["Catheter day 3", "Line Day 5"],
        )
        assert len(eps) == 2

    def test_startstop_confidence_in_tier(self):
        """TEXT_DERIVED_STARTSTOP is between TEXT_DERIVED and STRUCTURED."""
        assert LDA_CONFIDENCE_LEVELS.index("TEXT_DERIVED_STARTSTOP") > LDA_CONFIDENCE_LEVELS.index("TEXT_DERIVED")
        assert LDA_CONFIDENCE_LEVELS.index("TEXT_DERIVED_STARTSTOP") < LDA_CONFIDENCE_LEVELS.index("STRUCTURED")


# ═══════════════════════════════════════════════════════════════════
# 16. Precision tests: E05/E06/E21 with start/stop + flag toggle
# ═══════════════════════════════════════════════════════════════════

class TestE05StartStopPrecision:
    """E05 CAUTI: lda_duration gate with start/stop-derived episodes."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _load_e05_lda_gate(self):
        with open(RULE_DIR / "05_cauti.json") as f:
            rule = json.load(f)
        for g in rule["gates"]:
            if g["gate_id"] == "cauti_catheter_duration_lda":
                return g
        pytest.fail("cauti_catheter_duration_lda gate not found")

    def test_flag_on_startstop_3d_passes(self):
        """Flag on + foley placed/removed (3d) → gate passes."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e05_lda_gate()
        episodes = _extract_lda_startstop_episodes(
            ["Foley catheter placed.", "Foley removed."],
            timestamps=["2026-01-15T09:00:00", "2026-01-18T09:00:00"],
        )
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_flag_off_startstop_noop(self):
        """Flag off + foley start/stop → gate disabled."""
        engine.ENABLE_LDA_GATES = False
        gate = self._load_e05_lda_gate()
        episodes = _extract_lda_startstop_episodes(
            ["Foley catheter placed.", "Foley removed."],
            timestamps=["2026-01-15T09:00:00", "2026-01-18T09:00:00"],
        )
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed
        assert "disabled" in result.reason.lower()


class TestE06StartStopPrecision:
    """E06 CLABSI: lda_duration gate with start/stop-derived episodes."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _load_e06_lda_gate(self):
        with open(RULE_DIR / "06_clabsi.json") as f:
            rule = json.load(f)
        for g in rule["gates"]:
            if g["gate_id"] == "clabsi_central_line_duration_lda":
                return g
        pytest.fail("clabsi_central_line_duration_lda gate not found")

    def test_flag_on_cvl_5d_passes(self):
        """Flag on + CVL placed/removed (5d) → gate passes."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e06_lda_gate()
        episodes = _extract_lda_startstop_episodes(
            ["Central venous catheter placed right IJ.", "Central line removed."],
            timestamps=["2026-01-15T08:00:00", "2026-01-20T08:00:00"],
        )
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_flag_off_cvl_noop(self):
        """Flag off → gate disabled."""
        engine.ENABLE_LDA_GATES = False
        gate = self._load_e06_lda_gate()
        episodes = _extract_lda_startstop_episodes(
            ["Central venous catheter placed.", "Central line removed."],
            timestamps=["2026-01-15T08:00:00", "2026-01-20T08:00:00"],
        )
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed


class TestE21StartStopPrecision:
    """E21 VAP: lda_duration gate with start/stop-derived episodes."""

    def setup_method(self):
        self._orig = engine.ENABLE_LDA_GATES

    def teardown_method(self):
        engine.ENABLE_LDA_GATES = self._orig

    def _load_e21_lda_gate(self):
        with open(RULE_DIR / "21_vap.json") as f:
            rule = json.load(f)
        for g in rule["gates"]:
            if g["gate_id"] == "vent_duration_lda":
                return g
        pytest.fail("vent_duration_lda not found")

    def test_flag_on_intubation_7d_passes(self):
        """Flag on + intubated/extubated (7d) → gate passes."""
        engine.ENABLE_LDA_GATES = True
        gate = self._load_e21_lda_gate()
        # Intubation creates ETT episode, but vent gate expects MECHANICAL_VENTILATOR.
        # Use placed on ventilator / vent discontinued.
        episodes = _extract_lda_startstop_episodes(
            ["Patient placed on mechanical ventilator.", "Ventilator discontinued."],
            timestamps=["2026-01-15T08:00:00", "2026-01-22T08:00:00"],
        )
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert result.passed

    def test_flag_off_vent_noop(self):
        """Flag off → gate disabled."""
        engine.ENABLE_LDA_GATES = False
        gate = self._load_e21_lda_gate()
        episodes = _extract_lda_startstop_episodes(
            ["Patient placed on ventilator.", "Ventilator discontinued."],
            timestamps=["2026-01-15T08:00:00", "2026-01-22T08:00:00"],
        )
        patient = _make_patient(lda_episodes=episodes)
        result = engine.eval_lda_duration(gate, patient, _contract())
        assert not result.passed
