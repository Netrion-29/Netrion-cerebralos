#!/usr/bin/env python3
"""
Tests for neuro_trigger_v1 — deterministic neuro emergency trigger detection.

Covers:
  - GCS < 9 triggers neuro emergency (primary rule)
  - GCS == 9 does NOT trigger
  - GCS > 9 does NOT trigger
  - DATA NOT AVAILABLE when arrival GCS is null
  - DATA NOT AVAILABLE when no feature days
  - DATA NOT AVAILABLE when arrival_gcs is string "DATA NOT AVAILABLE"
  - DATA NOT AVAILABLE when arrival day not in feature days
  - DATA NOT AVAILABLE when no dated days
  - Evidence traceability (raw_line_id on every entry)
  - Intubated note appended when arrival GCS intubated
  - ED fallback warning when arrival_gcs_missing_in_trauma_hp
  - Fallback note when arrival_gcs_source_rule_id contains "fallback"
  - Output schema completeness
  - Threshold constant matches contract
"""

from __future__ import annotations

import pytest

from cerebralos.features.neuro_trigger_v1 import (
    GCS_NEURO_THRESHOLD,
    extract_neuro_trigger,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_gcs_block(
    *,
    arrival_gcs_value: int | None = 15,
    arrival_gcs_ts: str | None = "2025-12-18T14:30:00",
    arrival_gcs_source: str | None = "TRAUMA_HP",
    arrival_gcs_source_rule_id: str | None = "trauma_hp_primary_survey",
    arrival_gcs_missing_in_trauma_hp: bool = False,
    intubated: bool = False,
    line_preview: str = "GCS 15",
) -> dict:
    """Build a minimal gcs_daily block for one day."""
    arrival_gcs: dict | str
    if arrival_gcs_value is None and arrival_gcs_source is None:
        arrival_gcs = "DATA NOT AVAILABLE"
    else:
        arrival_gcs = {
            "value": arrival_gcs_value,
            "intubated": intubated,
            "source": arrival_gcs_source,
            "dt": arrival_gcs_ts,
            "timestamp_quality": "explicit",
        }

    readings = []
    if arrival_gcs_value is not None:
        readings.append({
            "value": arrival_gcs_value,
            "intubated": intubated,
            "source": arrival_gcs_source or "TRAUMA_HP",
            "dt": arrival_gcs_ts,
            "timestamp_quality": "explicit",
            "line_preview": line_preview,
            "is_arrival": True,
        })

    return {
        "arrival_gcs": arrival_gcs,
        "arrival_gcs_value": arrival_gcs_value,
        "arrival_gcs_ts": arrival_gcs_ts,
        "arrival_gcs_source": arrival_gcs_source,
        "arrival_gcs_source_rule_id": arrival_gcs_source_rule_id,
        "arrival_gcs_missing_in_trauma_hp": arrival_gcs_missing_in_trauma_hp,
        "all_readings": readings,
    }


def _make_feature_days(
    gcs_block: dict | None = None,
    day: str = "2025-12-18",
) -> dict:
    """Wrap a gcs_daily block into a feature_days structure."""
    if gcs_block is None:
        gcs_block = _make_gcs_block()
    return {day: {"gcs_daily": gcs_block}}


ARRIVAL_TS = "2025-12-18T14:30:00"


# ── Schema validation helper ────────────────────────────────────────

REQUIRED_TOP_KEYS = {
    "neuro_triggered", "trigger_rule_id", "trigger_ts",
    "trigger_inputs", "evidence", "notes", "warnings",
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


# ── Tests: GCS < 9 triggers ────────────────────────────────────────

class TestNeuroTriggerFires:
    """GCS below threshold fires neuro trigger."""

    def test_gcs_3_triggers(self) -> None:
        """GCS 3 (lowest possible) → neuro_triggered=yes."""
        gcs = _make_gcs_block(arrival_gcs_value=3, line_preview="GCS 3")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert result["trigger_rule_id"] == "neuro_gcs_lt9"
        assert result["trigger_ts"] is not None

    def test_gcs_8_triggers(self) -> None:
        """GCS 8 (just below threshold) → neuro_triggered=yes."""
        gcs = _make_gcs_block(arrival_gcs_value=8, line_preview="GCS 8")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert result["trigger_rule_id"] == "neuro_gcs_lt9"

    def test_gcs_6_triggers(self) -> None:
        """GCS 6 (mid-range severe) → neuro_triggered=yes."""
        gcs = _make_gcs_block(arrival_gcs_value=6, line_preview="GCS 6")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"

    def test_trigger_ts_matches_arrival_gcs_ts(self) -> None:
        """trigger_ts must match the arrival GCS timestamp."""
        ts = "2025-12-18T15:00:00"
        gcs = _make_gcs_block(
            arrival_gcs_value=5, arrival_gcs_ts=ts, line_preview="GCS 5",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert result["trigger_ts"] == ts


# ── Tests: GCS >= 9 no trigger ─────────────────────────────────────

class TestNeuroTriggerNoFire:
    """GCS at or above threshold does not fire."""

    def test_gcs_9_no_trigger(self) -> None:
        """GCS == 9 → not < 9, no trigger."""
        gcs = _make_gcs_block(arrival_gcs_value=9, line_preview="GCS 9")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"
        assert result["trigger_rule_id"] is None
        assert result["trigger_ts"] is None

    def test_gcs_15_no_trigger(self) -> None:
        """GCS 15 (normal) → no trigger."""
        gcs = _make_gcs_block(arrival_gcs_value=15, line_preview="GCS 15")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"

    def test_gcs_10_no_trigger(self) -> None:
        """GCS 10 → no trigger."""
        gcs = _make_gcs_block(arrival_gcs_value=10, line_preview="GCS 10")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"

    def test_no_trigger_still_has_evidence(self) -> None:
        """When no trigger fires, evidence still includes evaluated GCS."""
        gcs = _make_gcs_block(arrival_gcs_value=12, line_preview="GCS 12")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["source"] == "gcs_daily"
        assert result["evidence"][0]["role"] == "primary"


# ── Tests: DATA NOT AVAILABLE ──────────────────────────────────────

class TestNeuroTriggerDNA:
    """Fail-closed DATA NOT AVAILABLE scenarios."""

    def test_null_arrival_gcs_value(self) -> None:
        """arrival_gcs_value is None → DNA."""
        gcs = _make_gcs_block(arrival_gcs_value=None, arrival_gcs_source=None)
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "DATA NOT AVAILABLE"
        assert result["trigger_rule_id"] is None
        assert result["trigger_inputs"] is None

    def test_no_feature_days(self) -> None:
        """Empty feature_days → DNA."""
        result = extract_neuro_trigger({}, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "DATA NOT AVAILABLE"

    def test_only_undated_days(self) -> None:
        """Only __UNDATED__ day → DNA (no dated days)."""
        days = {"__UNDATED__": {"gcs_daily": _make_gcs_block()}}
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "DATA NOT AVAILABLE"
        assert "no dated days" in result["notes"][0]

    def test_arrival_day_not_in_days(self) -> None:
        """arrival_ts maps to day not in feature_days → falls back to earliest day."""
        gcs = _make_gcs_block(arrival_gcs_value=7)
        days = {"2025-12-19": {"gcs_daily": gcs}}  # different day
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        # Now falls back to earliest day (2025-12-19) instead of DNA
        assert result["neuro_triggered"] == "yes"
        assert any("falling back" in n for n in result["notes"])

    def test_gcs_daily_string_dna(self) -> None:
        """gcs_daily is literal string "DATA NOT AVAILABLE" → DNA."""
        days = {"2025-12-18": {"gcs_daily": "DATA NOT AVAILABLE"}}
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "DATA NOT AVAILABLE"

    def test_no_arrival_ts_fallback(self) -> None:
        """No arrival_ts → uses earliest dated day (note added)."""
        gcs = _make_gcs_block(arrival_gcs_value=7, line_preview="GCS 7")
        days = {"2025-12-18": {"gcs_daily": gcs}}
        result = extract_neuro_trigger(days, arrival_ts=None)
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert any("earliest day" in n for n in result["notes"])

    def test_missing_gcs_daily_key(self) -> None:
        """Day block exists but no gcs_daily key → DNA (empty dict)."""
        days = {"2025-12-18": {}}
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "DATA NOT AVAILABLE"


# ── Tests: Evidence traceability ────────────────────────────────────

class TestNeuroTriggerEvidence:
    """Evidence integrity checks."""

    def test_evidence_has_raw_line_id(self) -> None:
        """Every evidence entry must have a non-empty raw_line_id."""
        gcs = _make_gcs_block(arrival_gcs_value=7, line_preview="GCS 7")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert len(result["evidence"]) == 1
        for ev in result["evidence"]:
            assert "raw_line_id" in ev
            assert ev["raw_line_id"], "raw_line_id must be non-empty"
            assert len(ev["raw_line_id"]) == 16

    def test_evidence_source_is_gcs_daily(self) -> None:
        """Evidence source should always be 'gcs_daily'."""
        gcs = _make_gcs_block(arrival_gcs_value=5, line_preview="GCS 5")
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        for ev in result["evidence"]:
            assert ev["source"] == "gcs_daily"

    def test_evidence_deterministic(self) -> None:
        """Same inputs → same raw_line_id (deterministic hash)."""
        gcs = _make_gcs_block(arrival_gcs_value=7, line_preview="GCS 7")
        days = _make_feature_days(gcs)
        r1 = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        r2 = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert r1["evidence"][0]["raw_line_id"] == r2["evidence"][0]["raw_line_id"]

    def test_dna_result_has_empty_evidence(self) -> None:
        """DNA results have no evidence entries."""
        result = extract_neuro_trigger({}, arrival_ts=ARRIVAL_TS)
        assert result["evidence"] == []


# ── Tests: Intubated note ──────────────────────────────────────────

class TestNeuroTriggerIntubated:
    """Intubated GCS handling."""

    def test_intubated_note_when_triggered(self) -> None:
        """GCS < 9 + intubated → note about intubated V-score."""
        gcs = _make_gcs_block(
            arrival_gcs_value=3, intubated=True, line_preview="GCS 3T",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert any("intubated" in n.lower() for n in result["notes"])

    def test_intubated_no_trigger_no_note(self) -> None:
        """GCS >= 9 + intubated → no intubated note (trigger didn't fire)."""
        gcs = _make_gcs_block(
            arrival_gcs_value=10, intubated=True, line_preview="GCS 10T",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert result["neuro_triggered"] == "no"
        assert not any("intubated" in n.lower() for n in result["notes"])


# ── Tests: ED fallback warning ─────────────────────────────────────

class TestNeuroTriggerEdFallback:
    """ED fallback source handling — GCS came from ED, not Trauma H&P."""

    def test_fallback_rule_note(self) -> None:
        """arrival_gcs_source_rule_id with 'fallback' → note."""
        gcs = _make_gcs_block(
            arrival_gcs_value=7,
            arrival_gcs_source="ED_NOTE",
            arrival_gcs_source_rule_id="trauma_hp_primary_survey_missing_fallback_ed",
            line_preview="GCS 7",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert any("fallback" in n for n in result["notes"])

    def test_missing_in_trauma_hp_warning(self) -> None:
        """arrival_gcs_missing_in_trauma_hp → warning."""
        gcs = _make_gcs_block(
            arrival_gcs_value=7,
            arrival_gcs_source="ED_NOTE",
            arrival_gcs_source_rule_id="trauma_hp_primary_survey_missing_fallback_ed",
            arrival_gcs_missing_in_trauma_hp=True,
            line_preview="GCS 7",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert any("arrival_gcs_missing_in_trauma_hp" in w for w in result["warnings"])

    def test_trauma_hp_source_no_fallback_note(self) -> None:
        """GCS from Trauma H&P (primary survey) → no fallback note."""
        gcs = _make_gcs_block(
            arrival_gcs_value=7,
            arrival_gcs_source="TRAUMA_HP",
            arrival_gcs_source_rule_id="trauma_hp_primary_survey",
            line_preview="GCS 7",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert not any("fallback" in n for n in result["notes"])
        assert not any("arrival_gcs_missing_in_trauma_hp" in w for w in result["warnings"])


# ── Tests: trigger_inputs ──────────────────────────────────────────

class TestNeuroTriggerInputs:
    """trigger_inputs field checks."""

    def test_trigger_inputs_populated(self) -> None:
        """trigger_inputs includes GCS value, source, rule, intubated."""
        gcs = _make_gcs_block(
            arrival_gcs_value=7,
            arrival_gcs_source="TRAUMA_HP",
            arrival_gcs_source_rule_id="trauma_hp_primary_survey",
            intubated=False,
            line_preview="GCS 7",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        ti = result["trigger_inputs"]
        assert ti is not None
        assert ti["arrival_gcs_value"] == 7
        assert ti["arrival_gcs_source"] == "TRAUMA_HP"
        assert ti["arrival_gcs_source_rule_id"] == "trauma_hp_primary_survey"
        assert ti["arrival_gcs_intubated"] is False

    def test_trigger_inputs_null_when_dna(self) -> None:
        """trigger_inputs is None when neuro_triggered is DNA."""
        result = extract_neuro_trigger({}, arrival_ts=ARRIVAL_TS)
        assert result["trigger_inputs"] is None

    def test_trigger_inputs_intubated_true(self) -> None:
        """Intubated flag propagated to trigger_inputs."""
        gcs = _make_gcs_block(
            arrival_gcs_value=5, intubated=True, line_preview="GCS 5T",
        )
        days = _make_feature_days(gcs)
        result = extract_neuro_trigger(days, arrival_ts=ARRIVAL_TS)
        assert result["trigger_inputs"]["arrival_gcs_intubated"] is True


# ── Tests: threshold constant ──────────────────────────────────────

class TestNeuroThresholdConstant:
    """Verify threshold constant matches contract."""

    def test_gcs_threshold(self) -> None:
        assert GCS_NEURO_THRESHOLD == 9


# ── Tests: arrival-gcs-summary-selector-alignment-v1 ───────────────

class TestArrivalTsValidation:
    """Invalid arrival_ts values should fall back to earliest dated day."""

    def test_data_not_available_arrival_ts(self) -> None:
        """arrival_ts = 'DATA_NOT_AVAILABLE' → falls back to earliest day."""
        gcs = _make_gcs_block(arrival_gcs_value=15)
        days = {"2025-12-09": {"gcs_daily": gcs}}
        result = extract_neuro_trigger(days, arrival_ts="DATA_NOT_AVAILABLE")
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"
        assert result["trigger_inputs"]["arrival_gcs_value"] == 15
        assert any("not a valid ISO date" in n for n in result["notes"])

    def test_garbage_arrival_ts(self) -> None:
        """arrival_ts = 'garbage' → falls back to earliest day."""
        gcs = _make_gcs_block(arrival_gcs_value=8, line_preview="GCS 8")
        days = {"2025-12-18": {"gcs_daily": gcs}}
        result = extract_neuro_trigger(days, arrival_ts="garbage_ts_str")
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert result["trigger_inputs"]["arrival_gcs_value"] == 8

    def test_empty_string_arrival_ts(self) -> None:
        """arrival_ts = '' → same as None, falls back to earliest day."""
        gcs = _make_gcs_block(arrival_gcs_value=15)
        days = {"2025-12-18": {"gcs_daily": gcs}}
        result = extract_neuro_trigger(days, arrival_ts="")
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"


class TestCrossMidnightFallback:
    """Cross-midnight TRAUMA_HP: arrival day has no GCS but next day does."""

    def test_cross_midnight_finds_gcs_on_next_day(self) -> None:
        """TRAUMA_HP at 00:23 next day → cross-midnight fallback resolves."""
        arrival_gcs_block = _make_gcs_block(
            arrival_gcs_value=None,
            arrival_gcs_source=None,
            arrival_gcs_source_rule_id=None,
        )
        next_gcs_block = _make_gcs_block(
            arrival_gcs_value=15,
            arrival_gcs_source="TRAUMA_HP:Primary_Survey:Disability",
            arrival_gcs_ts="2025-12-17T00:23:00",
            line_preview="GCS 15",
        )
        days = {
            "2025-12-16": {"gcs_daily": arrival_gcs_block},
            "2025-12-17": {"gcs_daily": next_gcs_block},
        }
        result = extract_neuro_trigger(days, arrival_ts="2025-12-16T22:30:00")
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"
        assert result["trigger_inputs"]["arrival_gcs_value"] == 15
        assert any("cross-midnight" in n for n in result["notes"])

    def test_cross_midnight_does_not_skip_arrival_day_gcs(self) -> None:
        """When arrival day HAS GCS, cross-midnight should NOT override."""
        arrival_gcs_block = _make_gcs_block(
            arrival_gcs_value=14,
            arrival_gcs_source="TRAUMA_HP:Primary_Survey:Disability",
            line_preview="GCS 14",
        )
        next_gcs_block = _make_gcs_block(
            arrival_gcs_value=15,
            line_preview="GCS 15",
        )
        days = {
            "2025-12-16": {"gcs_daily": arrival_gcs_block},
            "2025-12-17": {"gcs_daily": next_gcs_block},
        }
        result = extract_neuro_trigger(days, arrival_ts="2025-12-16T22:30:00")
        assert result["trigger_inputs"]["arrival_gcs_value"] == 14
        assert not any("cross-midnight" in n for n in result["notes"])

    def test_cross_midnight_severe_gcs_triggers(self) -> None:
        """Cross-midnight GCS < 9 → neuro trigger fires."""
        arrival_gcs_block = _make_gcs_block(
            arrival_gcs_value=None,
            arrival_gcs_source=None,
            arrival_gcs_source_rule_id=None,
        )
        next_gcs_block = _make_gcs_block(
            arrival_gcs_value=6,
            arrival_gcs_source="TRAUMA_HP:Primary_Survey:Disability",
            arrival_gcs_ts="2025-12-13T00:59:00",
            line_preview="GCS 6",
        )
        days = {
            "2025-12-12": {"gcs_daily": arrival_gcs_block},
            "2025-12-13": {"gcs_daily": next_gcs_block},
        }
        result = extract_neuro_trigger(days, arrival_ts="2025-12-12T23:00:00")
        _assert_schema(result)
        assert result["neuro_triggered"] == "yes"
        assert result["trigger_inputs"]["arrival_gcs_value"] == 6

    def test_cross_midnight_no_gcs_on_next_day_either(self) -> None:
        """Both arrival and next day have no GCS → still DNA."""
        empty_gcs = _make_gcs_block(
            arrival_gcs_value=None,
            arrival_gcs_source=None,
            arrival_gcs_source_rule_id=None,
        )
        days = {
            "2025-12-16": {"gcs_daily": empty_gcs},
            "2025-12-17": {"gcs_daily": empty_gcs},
        }
        result = extract_neuro_trigger(days, arrival_ts="2025-12-16T22:30:00")
        _assert_schema(result)
        assert result["neuro_triggered"] == _DNA
        assert result["trigger_inputs"] is None

    def test_arrival_day_not_found_falls_back_to_earliest(self) -> None:
        """arrival_ts maps to non-existent day → falls back to earliest."""
        gcs = _make_gcs_block(arrival_gcs_value=15)
        days = {"2025-12-20": {"gcs_daily": gcs}}
        result = extract_neuro_trigger(days, arrival_ts="2025-12-18T14:00:00")
        _assert_schema(result)
        assert result["neuro_triggered"] == "no"
        assert result["trigger_inputs"]["arrival_gcs_value"] == 15
        assert any("falling back" in n for n in result["notes"])


_DNA = "DATA NOT AVAILABLE"
