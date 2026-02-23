#!/usr/bin/env python3
"""
Tests for hemodynamic_instability_pattern_v1 feature extractor.

Covers:
  - DNA when vitals_canonical_v1 is missing/empty
  - DNA when days present but zero records
  - No patterns detected (all vitals normal)
  - Hypotension pattern only (SBP < 90)
  - MAP low pattern only (MAP < 65)
  - Tachycardia pattern only (HR > 120)
  - Combined patterns
  - Evidence traceability (raw_line_id present)
  - Boundary values (exact threshold values)
  - Multi-day scanning
  - Records without raw_line_id generate warnings
"""

from __future__ import annotations

import pytest

from cerebralos.features.hemodynamic_instability_pattern_v1 import (
    extract_hemodynamic_instability_pattern,
    SBP_HYPOTENSION_THRESHOLD,
    MAP_LOW_THRESHOLD,
    HR_TACHYCARDIA_THRESHOLD,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_features(
    days: dict | None = None,
    arrival_vitals: dict | None = None,
) -> dict:
    """Build a minimal features dict with vitals_canonical_v1."""
    vc = {}
    if days is not None:
        vc["days"] = days
    if arrival_vitals is not None:
        vc["arrival_vitals"] = arrival_vitals
    return {"vitals_canonical_v1": vc}


def _make_record(
    sbp=None, dbp=None, map_val=None, hr=None, rr=None, spo2=None,
    ts="2024-01-15T10:00:00", day="2024-01-15",
    raw_line_id="test_rlid_001",
    abnormal_flags=None,
):
    """Build a canonical vitals record."""
    return {
        "ts": ts,
        "day": day,
        "source": "FLOWSHEET",
        "confidence": 60,
        "raw_line_id": raw_line_id,
        "sbp": sbp,
        "dbp": dbp,
        "map": map_val,
        "hr": hr,
        "rr": rr,
        "spo2": spo2,
        "temp_c": None,
        "temp_f": None,
        "abnormal_flags": abnormal_flags or [],
        "abnormal_count": len(abnormal_flags) if abnormal_flags else 0,
    }


# ── DNA tests ──────────────────────────────────────────────────────

class TestDNA:
    """DATA NOT AVAILABLE scenarios."""

    def test_dna_missing_vitals_canonical(self):
        result = extract_hemodynamic_instability_pattern({})
        assert result["pattern_present"] == "DATA NOT AVAILABLE"
        assert result["patterns_detected"] == []
        assert len(result["notes"]) > 0

    def test_dna_empty_days(self):
        features = _make_features(days={})
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "DATA NOT AVAILABLE"

    def test_dna_days_with_zero_records(self):
        features = _make_features(days={
            "2024-01-15": {"records": [], "count": 0, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "DATA NOT AVAILABLE"

    def test_dna_structure_complete(self):
        """DNA result still has full schema shape."""
        result = extract_hemodynamic_instability_pattern({})
        assert "hypotension_pattern" in result
        assert "map_low_pattern" in result
        assert "tachycardia_pattern" in result
        assert result["hypotension_pattern"]["detected"] is False
        assert result["map_low_pattern"]["detected"] is False
        assert result["tachycardia_pattern"]["detected"] is False
        assert result["total_abnormal_readings"] == 0
        assert result["total_vitals_readings"] == 0


# ── No pattern detected ───────────────────────────────────────────

class TestNoPattern:
    """Normal vitals — no patterns."""

    def test_normal_vitals(self):
        records = [
            _make_record(sbp=120, map_val=80, hr=75, raw_line_id="r1"),
            _make_record(sbp=110, map_val=70, hr=90, raw_line_id="r2"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 2, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "no"
        assert result["patterns_detected"] == []
        assert result["total_vitals_readings"] == 2
        assert result["total_abnormal_readings"] == 0
        assert result["evidence"] == []

    def test_normal_vitals_no_map(self):
        """SBP and HR normal, MAP absent → no patterns."""
        records = [
            _make_record(sbp=120, hr=80, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "no"


# ── Hypotension pattern ───────────────────────────────────────────

class TestHypotension:
    """SBP < 90 triggers hypotension pattern."""

    def test_single_hypotension_reading(self):
        records = [
            _make_record(sbp=85, map_val=55, hr=80, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "yes"
        assert result["hypotension_pattern"]["detected"] is True
        assert result["hypotension_pattern"]["reading_count"] == 1
        assert result["hypotension_pattern"]["days_affected"] == 1
        assert "hypotension" in result["patterns_detected"]

    def test_multiple_hypotension_readings(self):
        records = [
            _make_record(sbp=75, raw_line_id="r1", ts="2024-01-15T06:00:00"),
            _make_record(sbp=82, raw_line_id="r2", ts="2024-01-15T12:00:00"),
            _make_record(sbp=110, raw_line_id="r3", ts="2024-01-15T18:00:00"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 3, "abnormal_total": 2},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["hypotension_pattern"]["reading_count"] == 2
        assert result["hypotension_pattern"]["days_affected"] == 1

    def test_boundary_sbp_exactly_90(self):
        """SBP == 90 should NOT trigger (threshold is SBP < 90)."""
        records = [
            _make_record(sbp=90, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["hypotension_pattern"]["detected"] is False

    def test_boundary_sbp_89(self):
        """SBP == 89 should trigger."""
        records = [
            _make_record(sbp=89, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["hypotension_pattern"]["detected"] is True


# ── MAP low pattern ────────────────────────────────────────────────

class TestMAPLow:
    """MAP < 65 triggers map_low pattern."""

    def test_single_low_map(self):
        records = [
            _make_record(map_val=60, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "yes"
        assert result["map_low_pattern"]["detected"] is True
        assert "map_low" in result["patterns_detected"]

    def test_boundary_map_exactly_65(self):
        """MAP == 65 should NOT trigger (threshold is MAP < 65)."""
        records = [
            _make_record(map_val=65, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["map_low_pattern"]["detected"] is False

    def test_boundary_map_64(self):
        """MAP == 64 should trigger."""
        records = [
            _make_record(map_val=64, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["map_low_pattern"]["detected"] is True


# ── Tachycardia pattern ───────────────────────────────────────────

class TestTachycardia:
    """HR > 120 triggers tachycardia pattern."""

    def test_single_tachycardia(self):
        records = [
            _make_record(hr=130, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "yes"
        assert result["tachycardia_pattern"]["detected"] is True
        assert "tachycardia" in result["patterns_detected"]

    def test_boundary_hr_exactly_120(self):
        """HR == 120 should NOT trigger (threshold is HR > 120)."""
        records = [
            _make_record(hr=120, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["tachycardia_pattern"]["detected"] is False

    def test_boundary_hr_121(self):
        """HR == 121 should trigger."""
        records = [
            _make_record(hr=121, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["tachycardia_pattern"]["detected"] is True


# ── Combined patterns ──────────────────────────────────────────────

class TestCombined:
    """Multiple patterns in same or different records."""

    def test_hypotension_and_tachycardia_same_record(self):
        records = [
            _make_record(sbp=80, hr=135, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 2},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "yes"
        assert "hypotension" in result["patterns_detected"]
        assert "tachycardia" in result["patterns_detected"]
        assert result["total_abnormal_readings"] == 2

    def test_all_three_patterns(self):
        records = [
            _make_record(sbp=80, map_val=50, hr=130, raw_line_id="r1"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 3},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert len(result["patterns_detected"]) == 3
        assert result["total_abnormal_readings"] == 3

    def test_patterns_across_days(self):
        day1_records = [
            _make_record(sbp=75, raw_line_id="r1", day="2024-01-15"),
        ]
        day2_records = [
            _make_record(hr=140, raw_line_id="r2", day="2024-01-16"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": day1_records, "count": 1, "abnormal_total": 1},
            "2024-01-16": {"records": day2_records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["pattern_present"] == "yes"
        assert "hypotension" in result["patterns_detected"]
        assert "tachycardia" in result["patterns_detected"]
        assert result["hypotension_pattern"]["days_affected"] == 1
        assert result["tachycardia_pattern"]["days_affected"] == 1


# ── Multi-day tracking ─────────────────────────────────────────────

class TestMultiDay:
    """days_affected counts distinct days."""

    def test_hypotension_across_two_days(self):
        day1 = [
            _make_record(sbp=80, raw_line_id="r1", day="2024-01-15",
                         ts="2024-01-15T06:00:00"),
            _make_record(sbp=85, raw_line_id="r2", day="2024-01-15",
                         ts="2024-01-15T12:00:00"),
        ]
        day2 = [
            _make_record(sbp=70, raw_line_id="r3", day="2024-01-16",
                         ts="2024-01-16T08:00:00"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": day1, "count": 2, "abnormal_total": 2},
            "2024-01-16": {"records": day2, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["hypotension_pattern"]["reading_count"] == 3
        assert result["hypotension_pattern"]["days_affected"] == 2


# ── Evidence traceability ──────────────────────────────────────────

class TestEvidence:
    """Evidence entries have required fields."""

    def test_evidence_has_raw_line_id(self):
        records = [
            _make_record(sbp=80, raw_line_id="rlid_abc123"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert len(result["evidence"]) >= 1
        for ev in result["evidence"]:
            assert "raw_line_id" in ev
            assert ev["raw_line_id"] == "rlid_abc123"

    def test_evidence_fields(self):
        records = [
            _make_record(sbp=80, raw_line_id="r1", ts="2024-01-15T10:00:00",
                         day="2024-01-15"),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        ev = result["evidence"][0]
        assert ev["raw_line_id"] == "r1"
        assert ev["ts"] == "2024-01-15T10:00:00"
        assert ev["day"] == "2024-01-15"
        assert ev["pattern"] == "hypotension"
        assert ev["value"] == 80
        assert "SBP < 90" in ev["threshold"]
        assert "snippet" in ev

    def test_missing_raw_line_id_generates_warning(self):
        """Records without raw_line_id are skipped with warning."""
        records = [
            _make_record(sbp=80, raw_line_id=None),
        ]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert any("missing_raw_line_id" in w for w in result["warnings"])
        # Abnormal reading is counted but no evidence entry
        assert len(result["evidence"]) == 0

    def test_evidence_sorted_by_day(self):
        """Evidence from day1 appears before day2."""
        day1 = [_make_record(sbp=80, raw_line_id="r1", day="2024-01-15",
                             ts="2024-01-15T10:00:00")]
        day2 = [_make_record(sbp=75, raw_line_id="r2", day="2024-01-16",
                             ts="2024-01-16T10:00:00")]
        features = _make_features(days={
            "2024-01-16": {"records": day2, "count": 1, "abnormal_total": 1},
            "2024-01-15": {"records": day1, "count": 1, "abnormal_total": 1},
        })
        result = extract_hemodynamic_instability_pattern(features)
        days_in_evidence = [ev["day"] for ev in result["evidence"]]
        assert days_in_evidence == sorted(days_in_evidence)


# ── Threshold constants ───────────────────────────────────────────

class TestThresholdConstants:
    """Verify locked threshold values."""

    def test_sbp_threshold(self):
        assert SBP_HYPOTENSION_THRESHOLD == 90

    def test_map_threshold(self):
        assert MAP_LOW_THRESHOLD == 65

    def test_hr_threshold(self):
        assert HR_TACHYCARDIA_THRESHOLD == 120


# ── Source rule ID ─────────────────────────────────────────────────

class TestSourceRuleID:
    """Verify source_rule_id is always present."""

    def test_source_rule_id_present(self):
        records = [_make_record(sbp=120, hr=80, raw_line_id="r1")]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 0},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["source_rule_id"] == "hemodynamic_instability_pattern_canonical_vitals"

    def test_sub_pattern_rule_ids(self):
        records = [_make_record(sbp=80, map_val=50, hr=130, raw_line_id="r1")]
        features = _make_features(days={
            "2024-01-15": {"records": records, "count": 1, "abnormal_total": 3},
        })
        result = extract_hemodynamic_instability_pattern(features)
        assert result["hypotension_pattern"]["source_rule_id"] == "hemo_sbp_lt90"
        assert result["map_low_pattern"]["source_rule_id"] == "hemo_map_lt65"
        assert result["tachycardia_pattern"]["source_rule_id"] == "hemo_hr_gt120"
