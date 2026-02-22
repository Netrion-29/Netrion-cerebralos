"""
Tests for deterministic arrival vitals selector hierarchy.

Contract §4 hierarchy:
  Tier 0  TRAUMA_HP   within 30 min of arrival
  Tier 1  ED_NOTE     within 60 min (any on arrival day)
  Tier 2  FLOWSHEET   within 15 min of arrival
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
        """TRAUMA_HP record 45 min after arrival → outside 30-min window."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T15:44:00", sbp=145)]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        # Should NOT be tier 0 — 45 min > 30 min
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_before_arrival_rejected(self):
        """TRAUMA_HP record before arrival_ts → outside window (negative delta)."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T14:50:00")]
        result = select_arrival_vitals(recs, ARRIVAL_TS)
        assert result["status"] == "DATA NOT AVAILABLE"

    def test_exactly_at_window_edge(self):
        """TRAUMA_HP at exactly 30 min → included (boundary is <=)."""
        recs = [_rec("TRAUMA_HP", "2025-12-31T15:29:00")]
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
        """TRAUMA_HP outside 30 min; ED_NOTE in 60 min → ED_NOTE wins."""
        recs = [
            _rec("TRAUMA_HP", "2025-12-31T15:44:00", sbp=145),  # 45 min → too late
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
        """Only NURSING_NOTE records → no tier match → stub."""
        recs = [_rec("NURSING_NOTE", "2025-12-31T15:05:00", sbp=120)]
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
