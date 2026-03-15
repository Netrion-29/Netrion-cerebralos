"""
Tests for deterministic arrival vitals selector hierarchy.

Contract §4 hierarchy (v2):
  Tier 0  TRAUMA_HP    within 120 min of arrival
  Tier 1  ED_NOTE      within 60 min of arrival
  Tier 2  FLOWSHEET    within 15 min of arrival
  Tier 3  NURSING_NOTE within 120 min of arrival
  Tier 4  TABULAR      within 120 min of arrival
  Else    DATA NOT AVAILABLE
"""

import pytest
from cerebralos.features.vitals_canonical_v1 import select_arrival_vitals


# ── helpers ──────────────────────────────────────────────────────────

def _rec(source: str, ts: str, sbp: int = 120, raw_line_id: str = "R001",
         **overrides) -> dict:
    """Build a minimal canonical record for testing."""
    base = {
        "source": source,
        "ts": ts,
        "day": ts[:10] if ts else None,
        "raw_line_id": raw_line_id,
        "confidence": "extracted",
        "sbp": sbp, "dbp": 80, "map": 93, "hr": 80,
        "rr": 16, "spo2": 98, "temp_f": 98.6, "temp_c": 37.0,
        "abnormal_flags": [], "abnormal_count": 0,
    }
    base.update(overrides)
    return base


ARRIVAL_TS = "2025-12-31 14:59:00"


# ── tier 0: TRAUMA_HP within 30 min ─────────────────────────────────

class TestTier0TraumaHP:

    def test_selected_within_window(self):
        """TRAUMA_HP record 10 min after arrival → selected."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T15:09:00", sbp=145)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"
        assert result["sbp"] == 145

    def test_rejected_outside_window(self):
        """TRAUMA_HP record 125 min after arrival → outside 120-min window."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T17:04:00", sbp=145)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        # Should NOT be tier 0 — 125 min > 120 min
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_selected_within_widened_window(self):
        """TRAUMA_HP record 45 min after arrival → within 120-min window (v2)."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T15:44:00", sbp=145)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"

    def test_before_arrival_rejected(self):
        """TRAUMA_HP record before arrival_ts → outside window (negative delta)."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T14:50:00")]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_exactly_at_window_edge(self):
        """TRAUMA_HP at exactly 120 min → included (boundary is <=)."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T16:59:00")]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"


# ── tier 1: ED_NOTE within 60 min ───────────────────────────────────

class TestTier1EDNote:

    def test_ed_note_selected(self):
        """ED_NOTE on arrival day within 60 min → tier 1."""
        recs = [_rec("ED_NOTE", "2025-12-31T15:30:00", sbp=160)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_1_ED_NOTE"
        assert result["sbp"] == 160

    def test_ed_note_outside_window(self):
        """ED_NOTE 90 min after arrival → beyond 60-min window."""
        recs = [_rec("ED_NOTE", "2025-12-31T16:29:00", sbp=160)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_ed_note_fallback_when_trauma_hp_misses(self):
        """TRAUMA_HP outside 120 min; ED_NOTE in 60 min → ED_NOTE wins."""
        recs = [
            _rec("TRAUMA_HP", "2025-12-31T17:04:00", sbp=145),  # 125 min → too late
            _rec("ED_NOTE",   "2025-12-31T15:30:00", sbp=160),  # 31 min → ok for tier 1
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_1_ED_NOTE"


# ── tier 2: FLOWSHEET within 15 min ─────────────────────────────────

class TestTier2Flowsheet:

    def test_flowsheet_within_window(self):
        """FLOWSHEET 10 min after arrival → tier 2."""
        recs = [_rec("FLOWSHEET", "2025-12-31T15:09:00", sbp=130)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_2_FLOWSHEET"

    def test_flowsheet_outside_window(self):
        """FLOWSHEET 20 min after arrival → outside 15 min window."""
        recs = [_rec("FLOWSHEET", "2025-12-31T15:19:00", sbp=130)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"


# ── DATA NOT AVAILABLE ──────────────────────────────────────────────

class TestDataNotAvailable:

    def test_empty_records(self):
        result = select_arrival_vitals([], ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"
        assert result["selector_rule"] == "no_viable_records"

    def test_no_matching_source(self):
        """Only UNKNOWN source → no tier match → stub."""
        recs = [_rec("UNKNOWN_SRC", "2025-12-31T15:05:00", sbp=120)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"
        assert result["selector_rule"] == "no_qualifying_record"

    def test_no_arrival_ts(self):
        """When arrival_ts is None, time-window filtering uses no filter
        but source hierarchy still applies."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T15:09:00", sbp=145)]
        result = select_arrival_vitals(recs, arrival_ts=None)
        # With no arrival_ts, time-window cannot be applied;
        # the function should still select by source hierarchy
        assert result["status"] == "selected"
        assert result["selector_source"] == "TRAUMA_HP"

    def test_all_null_metrics_skipped(self):
        """Records with no viable metric values should be excluded."""
        null_rec = _rec("TRAUMA_HP", "2025-12-31T15:09:00",
                        sbp=None, dbp=None, map=None, hr=None,
                        rr=None, spo2=None, temp_f=None, temp_c=None)
        result = select_arrival_vitals([null_rec], ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"
        assert result["selector_rule"] == "no_viable_records"


# ── tie-breaking ─────────────────────────────────────────────────────

class TestTieBreaking:

    def test_earliest_ts_wins(self):
        """Two TRAUMA_HP records in window → earlier ts wins."""
        recs = [
            _rec("TRAUMA_HP", "2025-12-31T15:20:00", sbp=150, raw_line_id="R002"),
            _rec("TRAUMA_HP", "2025-12-31T15:05:00", sbp=145, raw_line_id="R003"),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["sbp"] == 145
        assert result["ts"] == "2025-12-31T15:05:00"

    def test_same_ts_lower_raw_line_id_wins(self):
        """Same timestamp → lower raw_line_id wins."""
        recs = [
            _rec("TRAUMA_HP", "2025-12-31T15:10:00", sbp=150, raw_line_id="R005"),
            _rec("TRAUMA_HP", "2025-12-31T15:10:00", sbp=145, raw_line_id="R002"),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["raw_line_id"] == "R002"
        assert result["sbp"] == 145


# ── priority ordering ───────────────────────────────────────────────

class TestPriorityOrdering:

    def test_trauma_hp_over_ed_note(self):
        """TRAUMA_HP and ED_NOTE both in window → TRAUMA_HP wins (tier 0 > tier 1)."""
        recs = [
            _rec("ED_NOTE",   "2025-12-31T15:05:00", sbp=160),
            _rec("TRAUMA_HP", "2025-12-31T15:10:00", sbp=145),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"

    def test_ed_note_over_flowsheet(self):
        """ED_NOTE and FLOWSHEET both qualify → ED_NOTE wins (tier 1 > tier 2)."""
        recs = [
            _rec("FLOWSHEET", "2025-12-31T15:05:00", sbp=130),
            _rec("ED_NOTE",   "2025-12-31T15:10:00", sbp=160),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_1_ED_NOTE"


# ── tier 3: NURSING_NOTE within 120 min ──────────────────────────────

class TestTier3NursingNote:

    def test_nursing_note_selected(self):
        """NURSING_NOTE 23 min after arrival → tier 3."""
        recs = [_rec("NURSING_NOTE", "2025-12-31T15:22:00", sbp=132)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"
        assert result["sbp"] == 132

    def test_nursing_note_outside_window(self):
        """NURSING_NOTE 125 min after arrival → beyond 120-min window."""
        recs = [_rec("NURSING_NOTE", "2025-12-31T17:04:00", sbp=132)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_nursing_note_fallback_after_higher_tiers(self):
        """All higher tiers outside their windows → NURSING_NOTE wins."""
        recs = [
            _rec("TRAUMA_HP",    "2025-12-31T17:04:00", sbp=145),  # 125 min > 120
            _rec("ED_NOTE",      "2025-12-31T16:15:00", sbp=160),  # 76 min > 60
            _rec("FLOWSHEET",    "2025-12-31T15:20:00", sbp=130),  # 21 min > 15
            _rec("NURSING_NOTE", "2025-12-31T15:22:00", sbp=132),  # 23 min → ok
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"
        assert result["sbp"] == 132

    def test_nursing_note_at_window_edge(self):
        """NURSING_NOTE at exactly 120 min → included (boundary is <=)."""
        recs = [_rec("NURSING_NOTE", "2025-12-31T16:59:00", sbp=140)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"


# ── tier 4: TABULAR within 120 min ──────────────────────────────────

class TestTier4Tabular:

    def test_tabular_selected(self):
        """TABULAR 15 min after arrival → tier 4."""
        recs = [_rec("TABULAR", "2025-12-31T15:14:00", sbp=116)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_4_TABULAR"
        assert result["sbp"] == 116

    def test_tabular_outside_window(self):
        """TABULAR 125 min after arrival → beyond 120-min window."""
        recs = [_rec("TABULAR", "2025-12-31T17:04:00", sbp=116)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_tabular_last_resort_before_dna(self):
        """All other tiers miss → TABULAR within window → selected."""
        recs = [
            _rec("TRAUMA_HP",    "2025-12-31T17:04:00", sbp=145),  # outside
            _rec("ED_NOTE",      "2025-12-31T16:15:00", sbp=160),  # outside
            _rec("FLOWSHEET",    "2025-12-31T15:20:00", sbp=130),  # outside
            _rec("NURSING_NOTE", "2025-12-31T17:04:00", sbp=132),  # outside
            _rec("TABULAR",      "2025-12-31T15:30:00", sbp=116),  # 31 min → ok
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_4_TABULAR"


# ── cross-tier priority: new vs existing ──────────────────────────

class TestCrossTierPriority:

    def test_trauma_hp_over_nursing_note(self):
        """TRAUMA_HP in window beats NURSING_NOTE in window."""
        recs = [
            _rec("NURSING_NOTE", "2025-12-31T15:05:00", sbp=132),
            _rec("TRAUMA_HP",    "2025-12-31T15:10:00", sbp=145),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"

    def test_nursing_note_over_tabular(self):
        """NURSING_NOTE and TABULAR both qualify → NURSING_NOTE wins (tier 3 > tier 4)."""
        recs = [
            _rec("TABULAR",      "2025-12-31T15:05:00", sbp=116),
            _rec("NURSING_NOTE", "2025-12-31T15:10:00", sbp=132),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"

    def test_flowsheet_over_nursing_note(self):
        """FLOWSHEET in its tight window beats NURSING_NOTE."""
        recs = [
            _rec("NURSING_NOTE", "2025-12-31T15:05:00", sbp=132),
            _rec("FLOWSHEET",    "2025-12-31T15:09:00", sbp=130),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_2_FLOWSHEET"

    def test_ed_note_over_tabular(self):
        """ED_NOTE beats TABULAR when both qualify."""
        recs = [
            _rec("TABULAR", "2025-12-31T15:05:00", sbp=116),
            _rec("ED_NOTE", "2025-12-31T15:10:00", sbp=160),
        ]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["selector_rule"] == "tier_1_ED_NOTE"


# ── audit patient scenarios ─────────────────────────────────────────

class TestAuditPatientScenarios:
    """Regression tests based on vitals_coverage_audit_2026-02-25 findings."""

    def test_timothy_cowan_nursing_note(self):
        """Timothy Cowan: NURSING_NOTE at +23 min → tier 3 selected (was DNA)."""
        recs = [_rec("NURSING_NOTE", "2025-12-18T16:17:00", sbp=132, hr=118)]
        result = select_arrival_vitals(recs, "2025-12-18 15:54:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"
        assert result["sbp"] == 132

    def test_timothy_nachtwey_nursing_note(self):
        """Timothy Nachtwey: NURSING_NOTE at +23 min → tier 3 (was DNA due to missing source)."""
        recs = [
            _rec("NURSING_NOTE", "2025-12-26T01:00:00", sbp=140, hr=96),
            _rec("TABULAR",      "2025-12-26T01:05:00", sbp=138),
        ]
        result = select_arrival_vitals(recs, "2025-12-26 00:37:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"

    def test_anna_dennis_nursing_note_or_trauma_hp(self):
        """Anna Dennis: TRAUMA_HP at +104 min (now within 120) → tier 0."""
        recs = [
            _rec("NURSING_NOTE", "2025-12-31T15:44:00", sbp=134),   # +45 min
            _rec("TRAUMA_HP",    "2025-12-31T16:43:00", sbp=145),   # +104 min
        ]
        result = select_arrival_vitals(recs, "2025-12-31 14:59:00")
        assert result["status"] == "selected"
        # TRAUMA_HP tier 0 at 104 min (within 120) beats NURSING_NOTE tier 3
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"

    def test_charlotte_howlett_nursing_note(self):
        """Charlotte Howlett: TRAUMA_HP at +412 min (outside 120), NURSING_NOTE at +110 min → tier 3."""
        recs = [
            _rec("NURSING_NOTE", "2025-12-30T18:31:00", sbp=136),   # +110 min
            _rec("TRAUMA_HP",    "2025-12-30T23:33:00", sbp=126),   # +412 min
        ]
        result = select_arrival_vitals(recs, "2025-12-30 16:41:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"

    def test_ronald_bittner_cross_midnight(self):
        """Ronald Bittner: arrival 20:38 12/31, NURSING_NOTE at 02:20 01/01 (342 min).
        Cross-midnight extension (8 h) applies → tier 3 selected."""
        recs = [
            _rec("NURSING_NOTE", "2026-01-01T02:20:00", sbp=164, hr=107,
                 rr=21, spo2=96, temp_f=98.1),
        ]
        result = select_arrival_vitals(recs, "2025-12-31 20:38:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE_cross_midnight"
        assert result["sbp"] == 164
        assert result["hr"] == 107


# ── cross-midnight window extension ──────────────────────────────────

class TestCrossMidnight:
    """Tests for cross-midnight window extension (arrival >= 18:00, record next day)."""

    def test_nursing_note_within_8h_selected(self):
        """NURSING_NOTE 342 min (5h42m) after evening arrival on next day → selected."""
        recs = [_rec("NURSING_NOTE", "2026-01-01T02:20:00", sbp=164)]
        result = select_arrival_vitals(recs, "2025-12-31 20:38:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE_cross_midnight"

    def test_trauma_hp_cross_midnight_selected(self):
        """TRAUMA_HP 300 min (5h) after evening arrival on next day → selected."""
        recs = [_rec("TRAUMA_HP", "2026-01-01T01:59:00", sbp=150)]
        result = select_arrival_vitals(recs, "2025-12-31 20:59:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_0_TRAUMA_HP_cross_midnight"

    def test_cross_midnight_beyond_8h_rejected(self):
        """Record 500 min (8h20m) after evening arrival on next day → rejected."""
        recs = [_rec("NURSING_NOTE", "2026-01-01T05:18:00", sbp=130)]
        result = select_arrival_vitals(recs, "2025-12-31 20:58:00")
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_cross_midnight_not_applied_before_18(self):
        """Arrival at 17:59 (before 18:00) → cross-midnight extension NOT applied."""
        recs = [_rec("NURSING_NOTE", "2026-01-01T01:00:00", sbp=130)]
        # 17:59 → 01:00 next day = 421 min, well beyond 120-min normal window
        result = select_arrival_vitals(recs, "2025-12-31 17:59:00")
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_same_day_record_uses_normal_window(self):
        """Same-day record still uses original per-tier window, not cross-midnight."""
        # Evening arrival, but record on SAME day → normal 120-min NURSING_NOTE window
        recs = [_rec("NURSING_NOTE", "2025-12-31T23:30:00", sbp=128)]
        # Arrival at 20:00, record at 23:30 = 210 min > 120 min → should fail
        result = select_arrival_vitals(recs, "2025-12-31 20:00:00")
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_same_day_tier_beats_cross_midnight(self):
        """Same-day qualifying record (higher tier) beats cross-midnight record."""
        recs = [
            _rec("TRAUMA_HP",    "2025-12-31T21:30:00", sbp=140),  # same day, +32 min
            _rec("NURSING_NOTE", "2026-01-01T02:20:00", sbp=164),  # cross-midnight
        ]
        result = select_arrival_vitals(recs, "2025-12-31 20:58:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_0_TRAUMA_HP"  # no cross_midnight suffix
        assert result["sbp"] == 140

    def test_same_tier_same_day_beats_cross_midnight(self):
        """Same-tier same-day record is preferred over cross-midnight record."""
        recs = [
            _rec("NURSING_NOTE", "2025-12-31T22:30:00", sbp=128),  # same day, +92 min
            _rec("NURSING_NOTE", "2026-01-01T02:20:00", sbp=164),  # cross-midnight
        ]
        result = select_arrival_vitals(recs, "2025-12-31 20:58:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE"  # no cross_midnight
        assert result["sbp"] == 128

    def test_cross_midnight_at_exactly_18(self):
        """Arrival at exactly 18:00 → cross-midnight extension applies."""
        recs = [_rec("NURSING_NOTE", "2026-01-01T00:30:00", sbp=145)]
        # 18:00 → 00:30 next day = 390 min, applies with 480-min window
        result = select_arrival_vitals(recs, "2025-12-31 18:00:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_3_NURSING_NOTE_cross_midnight"

    def test_cross_midnight_exactly_at_boundary(self):
        """Record exactly 480 min (8h) after evening arrival → included (boundary)."""
        recs = [_rec("TABULAR", "2026-01-01T04:00:00", sbp=120)]
        result = select_arrival_vitals(recs, "2025-12-31 20:00:00")
        assert result["status"] == "selected"
        assert result["selector_rule"] == "tier_4_TABULAR_cross_midnight"


# ── output schema completeness ──────────────────────────────────────

class TestOutputSchema:

    REQUIRED_KEYS = {
        "status", "selector_rule", "selector_source", "ts", "day",
        "raw_line_id", "confidence", "sbp", "dbp", "map", "hr",
        "rr", "spo2", "temp_c", "temp_f", "abnormal_flags", "abnormal_count",
    }

    def test_selected_has_all_keys(self):
        recs = [_rec("TRAUMA_HP", "2025-12-31T15:10:00")]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_stub_has_all_keys(self):
        result = select_arrival_vitals([], ARRIVAL_TS)
        assert set(result.keys()) == self.REQUIRED_KEYS


# ═══════════════════════════════════════════════════════════════════
#  Tests for extract_arrival_vitals (vitals_daily layer)
# ═══════════════════════════════════════════════════════════════════

import json
import os
from cerebralos.features.vitals_daily import extract_arrival_vitals

# Minimal config sufficient for inline vitals parsing
_MINIMAL_CONFIG = {
    "inline_vitals": {
        "trigger_pattern": r"(?i)(?:^|\b)Vitals\s*:",
    },
    "discharge_inline": {
        "trigger_pattern": r"(?i)^\s*Temp:\s*[\d]+(?:\.\d+)?\s*°?\s*F.*BP:\s*\d+/\d+",
    },
    "flowsheet_table": {
        "header_pattern": r"^Date and Time\tTemp\tPulse\tResp\tBP\tSpO2",
    },
    "ed_triage_table": {
        "header_pattern": r"(?i)ED\s+Triage\s+Vitals\s*\[([^\]]+)\]",
        "col_header_pattern": r"^Temp\tTemp\s+src\tPulse\tResp\tBP\tSpO2",
    },
    "visit_vitals_block": {
        "header_pattern": r"(?i)^\s*Visit\s+Vitals\s*$",
    },
    "metric_patterns": {
        "temp_f": {"guardrails": {"min": 85.0, "max": 115.0}},
        "hr": {"guardrails": {"min": 20, "max": 300}},
        "rr": {"guardrails": {"min": 4, "max": 60}},
        "spo2": {"guardrails": {"min": 50, "max": 100}},
        "bp": {"guardrails": {"sbp_min": 40, "sbp_max": 300, "dbp_min": 20, "dbp_max": 200}},
    },
    "negative_context": {"exclude_line_patterns": []},
}

DAY_ISO = "2025-12-31"


def _item(item_type, dt, text, source_id="SRC001"):
    """Build a minimal timeline item for testing."""
    return {
        "type": item_type,
        "dt": dt,
        "source_id": source_id,
        "time_missing": False,
        "payload": {"text": text},
    }


_INLINE_VITALS_TEXT = (
    "Vitals: Blood pressure 152/87, pulse 65, temperature 98.8 °F (37.1 °C), "
    "temperature source Oral, resp. rate 20, SpO2 97%."
)

_ED_VITALS_TEXT = (
    "Vitals: Blood pressure 140/90, pulse 88, temperature 99.0 °F (37.2 °C), "
    "temperature source Oral, resp. rate 22, SpO2 95%."
)


class TestArrivalVitalsPrimarySurvey:
    """Primary Survey (TRAUMA_HP) items selected first."""

    def test_trauma_hp_inline_selected(self):
        """Inline vitals in a TRAUMA_HP item → PRIMARY_SURVEY."""
        items = [_item("TRAUMA_HP", "2025-12-31T15:10:00", _INLINE_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["status"] == "selected"
        assert result["source_context"] == "PRIMARY_SURVEY"
        assert result["item_type"] == "TRAUMA_HP"
        assert result["vitals"]["sbp"] == 152.0
        assert result["vitals"]["dbp"] == 87.0
        assert result["vitals"]["hr"] == 65.0
        assert result["vitals"]["rr"] == 20.0
        assert result["vitals"]["spo2"] == 97.0
        assert result["vitals"]["temp_f"] == 98.8

    def test_trauma_hp_over_ed_note(self):
        """TRAUMA_HP item beats ED_NOTE when both present."""
        items = [
            _item("ED_NOTE", "2025-12-31T15:05:00", _ED_VITALS_TEXT, "SRC_ED"),
            _item("TRAUMA_HP", "2025-12-31T15:10:00", _INLINE_VITALS_TEXT, "SRC_THP"),
        ]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["source_context"] == "PRIMARY_SURVEY"
        assert result["vitals"]["sbp"] == 152.0

    def test_trauma_hp_qualitative_falls_to_ed(self):
        """TRAUMA_HP with no numeric vitals → ED fallback used."""
        qualitative = (
            "Primary Survey:\n"
            "Airway: patent\nBreathing: even\n"
            "Circulation: HD normal\nDisability: GCS 15\n"
        )
        items = [
            _item("TRAUMA_HP", "2025-12-31T15:00:00", qualitative, "SRC_THP"),
            _item("ED_NOTE", "2025-12-31T15:05:00", _ED_VITALS_TEXT, "SRC_ED"),
        ]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["source_context"] == "ED_FALLBACK"
        assert result["item_type"] == "ED_NOTE"
        assert result["vitals"]["sbp"] == 140.0


class TestArrivalVitalsEDFallback:
    """ED items used when no TRAUMA_HP vitals available."""

    def test_ed_note_selected(self):
        """ED_NOTE item with vitals → ED_FALLBACK."""
        items = [_item("ED_NOTE", "2025-12-31T15:05:00", _ED_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["status"] == "selected"
        assert result["source_context"] == "ED_FALLBACK"
        assert result["vitals"]["sbp"] == 140.0
        assert result["vitals"]["hr"] == 88.0

    def test_ed_nursing_selected(self):
        """ED_NURSING item with vitals → ED_FALLBACK."""
        items = [_item("ED_NURSING", "2025-12-31T15:05:00", _ED_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["source_context"] == "ED_FALLBACK"

    def test_triage_selected(self):
        """TRIAGE item with vitals → ED_FALLBACK."""
        items = [_item("TRIAGE", "2025-12-31T15:05:00", _ED_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["source_context"] == "ED_FALLBACK"


class TestArrivalVitalsDataNotAvailable:
    """DATA NOT AVAILABLE when no qualifying items yield vitals."""

    def test_empty_items(self):
        result = extract_arrival_vitals([], DAY_ISO, _MINIMAL_CONFIG)
        assert result["status"] == "DATA NOT AVAILABLE"
        assert result["source_context"] is None
        assert result["readings_count"] == 0

    def test_no_vitals_in_any_item(self):
        """Items present but no numeric vitals → DNA."""
        items = [
            _item("TRAUMA_HP", "2025-12-31T15:00:00", "No vitals documented.", "S1"),
            _item("ED_NOTE", "2025-12-31T15:10:00", "Patient resting comfortably.", "S2"),
        ]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_unrecognized_item_type_ignored(self):
        """Items with non-primary/non-ED types are not used."""
        items = [_item("PHYSICIAN_NOTE", "2025-12-31T15:05:00", _INLINE_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_all_null_vitals_stub(self):
        """DNA stub has all metric keys set to None."""
        result = extract_arrival_vitals([], DAY_ISO, _MINIMAL_CONFIG)
        for mk in ("temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map"):
            assert result["vitals"][mk] is None


class TestArrivalVitalsOutputSchema:
    """Output schema completeness for extract_arrival_vitals."""

    REQUIRED_KEYS = {
        "status", "source_context", "item_type", "source_item_dt",
        "source_item_id", "vitals", "readings_count", "line_preview",
        "warnings",
    }

    def test_selected_has_all_keys(self):
        items = [_item("TRAUMA_HP", "2025-12-31T15:10:00", _INLINE_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_stub_has_all_keys(self):
        result = extract_arrival_vitals([], DAY_ISO, _MINIMAL_CONFIG)
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_vitals_has_all_metrics(self):
        items = [_item("TRAUMA_HP", "2025-12-31T15:10:00", _INLINE_VITALS_TEXT)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert set(result["vitals"].keys()) == {
            "temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map",
        }


class TestArrivalVitalsVisitVitalsBlock:
    """Visit Vitals block within a TRAUMA_HP item."""

    def test_visit_vitals_in_trauma_hp(self):
        """Visit Vitals block in a TRAUMA_HP item → PRIMARY_SURVEY."""
        text = (
            "Visit Vitals\n"
            "BP\t128/61\n"
            "Pulse\t72\n"
            "Temp\t98.4 °F (36.9 °C)\n"
            "Resp\t16\n"
            "SpO2\t96%\n"
        )
        items = [_item("TRAUMA_HP", "2025-12-31T15:10:00", text)]
        result = extract_arrival_vitals(items, DAY_ISO, _MINIMAL_CONFIG)
        assert result["status"] == "selected"
        assert result["source_context"] == "PRIMARY_SURVEY"
        assert result["vitals"]["sbp"] == 128.0
        assert result["vitals"]["hr"] == 72.0


class TestArrivalVitalsRealPatternRegression:
    """Regression tests based on raw file scan patterns."""

    def test_lee_woodard_pattern(self):
        """Lee Woodard: inline vitals in Secondary Survey of Trauma H&P."""
        text = (
            "Vitals: Blood pressure (!) 152/87, pulse 65, "
            "temperature 98.8 °F (37.1 °C), temperature source Oral, "
            "resp. rate 20, height 5' 10\", weight 156 lb (70.8 kg), SpO2 97%."
        )
        items = [_item("TRAUMA_HP", "2025-12-11T09:08:00", text)]
        result = extract_arrival_vitals(items, "2025-12-11", _MINIMAL_CONFIG)
        assert result["status"] == "selected"
        assert result["source_context"] == "PRIMARY_SURVEY"
        assert result["vitals"]["sbp"] == 152.0
        assert result["vitals"]["hr"] == 65.0
        assert result["vitals"]["spo2"] == 97.0

    def test_betty_roll_ed_fallback(self):
        """Betty Roll: ED Visit Vitals as fallback (separate ED note)."""
        trauma_text = (
            "Primary Survey:\nAirway: patent\nBreathing: even\n"
            "Circulation: HD normal\nDisability: GCS 15\n"
        )
        ed_text = (
            "PHYSICAL EXAM\n"
            "VITAL SIGNS: Visit Vitals\n"
            "Vitals: Blood pressure (!) 177/70, pulse (!) 57, "
            "temperature 98.5 °F (36.9 °C), resp. rate 18, SpO2 94%."
        )
        items = [
            _item("TRAUMA_HP", "2025-12-10T14:00:00", trauma_text, "THP"),
            _item("ED_NOTE", "2025-12-10T14:30:00", ed_text, "ED1"),
        ]
        result = extract_arrival_vitals(items, "2025-12-10", _MINIMAL_CONFIG)
        assert result["source_context"] == "ED_FALLBACK"
        assert result["vitals"]["sbp"] == 177.0
        assert result["vitals"]["hr"] == 57.0

    def test_robert_altmeyer_dna(self):
        """Robert Altmeyer: no numeric vitals in Trauma H&P → DNA."""
        qualitative = (
            "Primary Survey:\nAirway: patent\nBreathing: even\n"
            "Circulation: HD normal\nDisability: GCS 15\nExposure: no deformity\n"
            "Secondary Survey:\nHead: normocephalic\nNeck: no JVD\n"
        )
        items = [_item("TRAUMA_HP", "2025-12-15T10:00:00", qualitative)]
        result = extract_arrival_vitals(items, "2025-12-15", _MINIMAL_CONFIG)
        assert result["status"] == "DATA NOT AVAILABLE"
