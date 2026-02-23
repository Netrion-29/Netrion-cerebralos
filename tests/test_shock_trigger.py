#!/usr/bin/env python3
"""
Tests for shock_trigger_v1 — deterministic shock trigger detection.

Covers:
  - SBP < 90 triggers shock (primary rule)
  - BD > 6 triggers shock (supporting rule)
  - Combined SBP + BD → hemorrhagic_likely
  - SBP < 90 alone → indeterminate
  - BD > 6 alone → indeterminate
  - No trigger when SBP >= 90 and BD <= 6
  - DATA NOT AVAILABLE when arrival vitals missing
  - DATA NOT AVAILABLE when SBP is null
  - Evidence traceability (raw_line_id on every evidence entry)
  - Warnings for non-arterial BD specimen
  - Notes when BD unavailable
  - Output schema completeness
"""

from __future__ import annotations

import pytest

from cerebralos.features.shock_trigger_v1 import (
    BD_SHOCK_THRESHOLD,
    SBP_SHOCK_THRESHOLD,
    extract_shock_trigger,
)

# ── Helpers ─────────────────────────────────────────────────────────

def _make_arrival_vitals(
    *,
    status: str = "selected",
    sbp: float | None = 120.0,
    map_val: float | None = 80.0,
    ts: str | None = "2025-12-18T14:30:00",
    raw_line_id: str | None = "abc123deadbeef00",
    selector_rule: str = "tier_0_TRAUMA_HP",
) -> dict:
    """Build a minimal arrival_vitals dict."""
    return {
        "status": status,
        "selector_rule": selector_rule,
        "selector_source": "TRAUMA_HP" if status == "selected" else None,
        "ts": ts,
        "day": ts[:10] if ts else None,
        "raw_line_id": raw_line_id,
        "confidence": 70,
        "sbp": sbp,
        "dbp": 60.0,
        "map": map_val,
        "hr": 88.0,
        "rr": 18.0,
        "spo2": 98.0,
        "temp_c": 36.8,
        "temp_f": 98.2,
        "abnormal_flags": [],
        "abnormal_count": 0,
    }


def _make_bdm(
    *,
    initial_bd_value: float | None = 3.0,
    initial_bd_ts: str | None = "2025-12-18T14:45:00",
    initial_bd_source: str | None = "arterial",
    bd_raw_line_id: str = "bd0000deadbeef01",
) -> dict:
    """Build a minimal base_deficit_monitoring_v1 dict."""
    bd_series = []
    if initial_bd_value is not None:
        bd_series.append({
            "ts": initial_bd_ts,
            "value": initial_bd_value,
            "specimen": initial_bd_source or "unknown",
            "raw_line_id": bd_raw_line_id,
            "snippet": f"Base Deficit {initial_bd_value}",
        })
    return {
        "initial_bd_value": initial_bd_value,
        "initial_bd_ts": initial_bd_ts,
        "initial_bd_source": initial_bd_source,
        "bd_series": bd_series,
        "trigger_bd_gt4": initial_bd_value is not None and initial_bd_value > 4,
    }


def _make_features(
    arrival_vitals: dict | None = None,
    bdm: dict | None = None,
) -> dict:
    """Build a minimal features dict for testing."""
    feats: dict = {}
    feats["vitals_canonical_v1"] = {
        "days": {},
        "arrival_vitals": arrival_vitals or _make_arrival_vitals(),
    }
    feats["base_deficit_monitoring_v1"] = bdm or _make_bdm()
    return feats


# ── Schema validation helper ────────────────────────────────────────

REQUIRED_TOP_KEYS = {
    "shock_triggered", "trigger_rule_id", "trigger_ts",
    "trigger_vitals", "shock_type", "evidence", "notes", "warnings",
}

REQUIRED_EVIDENCE_KEYS = {"raw_line_id", "source", "ts", "snippet", "role"}


def _assert_schema(result: dict) -> None:
    """Verify all required keys exist in result."""
    missing = REQUIRED_TOP_KEYS - set(result.keys())
    assert not missing, f"Missing top-level keys: {missing}"
    assert isinstance(result["evidence"], list)
    assert isinstance(result["notes"], list)
    assert isinstance(result["warnings"], list)
    for ev in result["evidence"]:
        ev_missing = REQUIRED_EVIDENCE_KEYS - set(ev.keys())
        assert not ev_missing, f"Evidence entry missing keys: {ev_missing}"
        assert ev["raw_line_id"], "Evidence raw_line_id must be non-empty"


# ── Tests ───────────────────────────────────────────────────────────

class TestShockTriggerSBPOnly:
    """SBP-based shock trigger (primary rule)."""

    def test_sbp_below_threshold_triggers(self) -> None:
        """SBP < 90 → shock_triggered=yes, rule=shock_sbp_lt90."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=85.0),
            bdm=_make_bdm(initial_bd_value=2.0),  # BD normal
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_sbp_lt90"
        assert result["shock_type"] == "indeterminate"
        assert result["trigger_ts"] is not None

    def test_sbp_exactly_90_no_trigger(self) -> None:
        """SBP == 90 → not < 90, no trigger."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=90.0),
            bdm=_make_bdm(initial_bd_value=2.0),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "no"
        assert result["trigger_rule_id"] is None
        assert result["shock_type"] is None

    def test_sbp_well_above_threshold(self) -> None:
        """SBP 140 → no trigger."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=140.0),
            bdm=_make_bdm(initial_bd_value=2.0),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "no"

    def test_sbp_89_triggers(self) -> None:
        """SBP just below threshold."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=89.0),
            bdm=_make_bdm(initial_bd_value=None),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_sbp_lt90"


class TestShockTriggerBDOnly:
    """BD-based shock trigger (supporting rule, fires alone)."""

    def test_bd_above_threshold_no_sbp_trigger(self) -> None:
        """BD > 6 with normal SBP → shock_triggered=yes, indeterminate."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=120.0),
            bdm=_make_bdm(initial_bd_value=8.0, initial_bd_source="arterial"),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_bd_gt6"
        assert result["shock_type"] == "indeterminate"

    def test_bd_exactly_6_no_trigger(self) -> None:
        """BD == 6 → not > 6, no trigger."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=120.0),
            bdm=_make_bdm(initial_bd_value=6.0),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "no"

    def test_bd_6_point_1_triggers(self) -> None:
        """BD just above threshold."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=120.0),
            bdm=_make_bdm(initial_bd_value=6.1),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_bd_gt6"


class TestShockTriggerCombined:
    """Combined SBP + BD trigger → hemorrhagic_likely."""

    def test_both_trigger_hemorrhagic(self) -> None:
        """SBP < 90 + BD > 6 → hemorrhagic_likely."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=78.0),
            bdm=_make_bdm(initial_bd_value=9.0, initial_bd_source="arterial"),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_sbp_lt90+bd_gt6"
        assert result["shock_type"] == "hemorrhagic_likely"
        # Should have 2 evidence entries (SBP + BD)
        assert len(result["evidence"]) == 2
        roles = {e["role"] for e in result["evidence"]}
        assert "primary" in roles
        assert "supporting" in roles

    def test_combined_venous_specimen_warns(self) -> None:
        """SBP + BD triggered but BD specimen is venous → warning."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=80.0),
            bdm=_make_bdm(initial_bd_value=10.0, initial_bd_source="venous"),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["shock_type"] == "hemorrhagic_likely"
        assert any("bd_specimen_not_arterial" in w for w in result["warnings"])

    def test_combined_unknown_specimen_warns(self) -> None:
        """SBP + BD triggered but BD specimen is unknown → warning."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=80.0),
            bdm=_make_bdm(initial_bd_value=10.0, initial_bd_source="unknown"),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert any("bd_specimen_not_arterial" in w for w in result["warnings"])


class TestShockTriggerDNA:
    """DATA NOT AVAILABLE scenarios."""

    def test_arrival_not_selected(self) -> None:
        """Arrival vitals status != selected → DNA."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(status="DATA NOT AVAILABLE", sbp=None),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "DATA NOT AVAILABLE"
        assert result["trigger_rule_id"] is None

    def test_sbp_null(self) -> None:
        """Arrival selected but SBP null → DNA."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=None),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "DATA NOT AVAILABLE"

    def test_no_vitals_canonical(self) -> None:
        """Missing vitals_canonical_v1 entirely → DNA."""
        feats = {"base_deficit_monitoring_v1": _make_bdm()}
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "DATA NOT AVAILABLE"

    def test_no_arrival_vitals_key(self) -> None:
        """vitals_canonical_v1 present but no arrival_vitals → DNA."""
        feats = _make_features()
        feats["vitals_canonical_v1"]["arrival_vitals"] = {}
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "DATA NOT AVAILABLE"


class TestShockTriggerBDUnavailable:
    """BD unavailable — evaluate on SBP only."""

    def test_sbp_trigger_no_bd(self) -> None:
        """SBP < 90 with no BD → shock with note about missing BD."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=75.0),
            bdm=_make_bdm(initial_bd_value=None),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_sbp_lt90"
        assert result["shock_type"] == "indeterminate"
        assert any("BD not available" in n or "BD" in n for n in result["notes"])

    def test_no_trigger_no_bd(self) -> None:
        """SBP >= 90 with no BD → no trigger."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=100.0),
            bdm=_make_bdm(initial_bd_value=None),
        )
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "no"

    def test_no_bdm_module_at_all(self) -> None:
        """base_deficit_monitoring_v1 missing entirely."""
        feats = _make_features(arrival_vitals=_make_arrival_vitals(sbp=75.0))
        del feats["base_deficit_monitoring_v1"]
        result = extract_shock_trigger(feats)
        _assert_schema(result)
        assert result["shock_triggered"] == "yes"
        assert result["trigger_rule_id"] == "shock_sbp_lt90"


class TestShockTriggerEvidence:
    """Evidence traceability checks."""

    def test_evidence_has_raw_line_id(self) -> None:
        """Every evidence entry must have a non-empty raw_line_id."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=80.0),
            bdm=_make_bdm(initial_bd_value=9.0),
        )
        result = extract_shock_trigger(feats)
        for ev in result["evidence"]:
            assert "raw_line_id" in ev
            assert ev["raw_line_id"], "raw_line_id must be non-empty"

    def test_sbp_trigger_has_one_evidence(self) -> None:
        """SBP-only trigger has exactly 1 evidence entry (primary)."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=80.0),
            bdm=_make_bdm(initial_bd_value=3.0),
        )
        result = extract_shock_trigger(feats)
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["role"] == "primary"
        assert result["evidence"][0]["source"] == "arrival_vitals"

    def test_no_trigger_still_has_evidence_for_evaluated_vitals(self) -> None:
        """When no trigger fires, evidence still includes vitals that were evaluated."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=120.0),
            bdm=_make_bdm(initial_bd_value=2.0),
        )
        result = extract_shock_trigger(feats)
        # Evidence includes the arrival vitals entry even when not triggered
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["source"] == "arrival_vitals"


class TestShockTriggerTriggerVitals:
    """trigger_vitals field checks."""

    def test_trigger_vitals_populated(self) -> None:
        """trigger_vitals includes SBP, MAP, BD when all available."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=85.0, map_val=55.0),
            bdm=_make_bdm(initial_bd_value=8.0, initial_bd_source="arterial"),
        )
        result = extract_shock_trigger(feats)
        tv = result["trigger_vitals"]
        assert tv is not None
        assert tv["sbp"] == 85.0
        assert tv["map"] == 55.0
        assert tv["bd_value"] == 8.0
        assert tv["bd_specimen"] == "arterial"

    def test_trigger_vitals_bd_null_when_missing(self) -> None:
        """trigger_vitals.bd_value is None when BD unavailable."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(sbp=120.0),
            bdm=_make_bdm(initial_bd_value=None),
        )
        result = extract_shock_trigger(feats)
        tv = result["trigger_vitals"]
        assert tv is not None
        assert tv["bd_value"] is None

    def test_trigger_vitals_null_when_dna(self) -> None:
        """trigger_vitals is null when shock_triggered is DNA."""
        feats = _make_features(
            arrival_vitals=_make_arrival_vitals(status="DATA NOT AVAILABLE", sbp=None),
        )
        result = extract_shock_trigger(feats)
        assert result["trigger_vitals"] is None


class TestShockTriggerThresholdConstants:
    """Verify threshold constants match contract."""

    def test_sbp_threshold(self) -> None:
        assert SBP_SHOCK_THRESHOLD == 90

    def test_bd_threshold(self) -> None:
        assert BD_SHOCK_THRESHOLD == 6.0
