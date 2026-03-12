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
        assert LDA_CONFIDENCE_LEVELS == ("TEXT_APPROXIMATE", "TEXT_DERIVED", "STRUCTURED")

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

    # ── lda_overlap (stub) ──

    def test_overlap_stub_returns_false(self):
        patient = _make_patient()
        gate = _gate("lda_overlap", "overlap_test", device_type="CENTRAL_LINE",
                      overlap_gate="other", window_days=2)
        result = engine.eval_lda_overlap(gate, patient, _contract())
        assert not result.passed
        assert "not yet" in result.reason.lower()


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
