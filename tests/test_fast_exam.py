#!/usr/bin/env python3
"""
Tests for FAST Exam Extraction v1.

Covers:
  - Primary Survey FAST line parsing (all known patterns)
  - TRAUMA_HP with no Primary Survey → DNA
  - TRAUMA_HP with Primary Survey but no FAST line → DNA + warning
  - No TRAUMA_HP at all → DNA
  - Non-TRAUMA_HP items ignored
  - Multiple TRAUMA_HP items → earliest wins
  - Evidence traceability (raw_line_id present)
  - Result classification accuracy
  - Edge cases (whitespace, case insensitivity)
"""

import hashlib
import sys
from pathlib import Path

import pytest

# Ensure project root is on import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.fast_exam_v1 import (
    _extract_fast_from_text,
    _make_raw_line_id,
    extract_fast_exam,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days_data(items_by_day):
    """Build a minimal days_data dict from {day_iso: [items]}."""
    days = {}
    for day_iso, items in items_by_day.items():
        days[day_iso] = {"items": items}
    return {"days": days, "meta": {}}


def _make_trauma_hp_item(text, dt="2025-12-18T16:17:00", source_id="0"):
    """Build a minimal TRAUMA_HP timeline item."""
    return {
        "type": "TRAUMA_HP",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _make_ed_note_item(text, dt="2025-12-18T17:00:00", source_id="99"):
    """Build a minimal ED_NOTE timeline item."""
    return {
        "type": "ED_NOTE",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


_PS_TEMPLATE = """\
[TRAUMA_HP] {dt}
Signed

Trauma H & P

HPI: Patient presents as trauma.

Primary Survey:
            Airway: patent
            Breathing: even, nonlabored
            Circulation: normal
            Disability: GCS GCS 15
            Exposure: no deformity
            {fast_line}

PMH: PAST MEDICAL HISTORY
"""


def _ps_text(fast_line, dt="2025-12-18 16:17:00"):
    """Build TRAUMA_HP text with a given FAST line in Primary Survey."""
    return _PS_TEMPLATE.format(fast_line=fast_line, dt=dt)


_NO_PS_TEXT = """\
[TRAUMA_HP] 2025-12-18 16:17:00
Signed

Trauma H & P

HPI: Patient presents. No Primary Survey section here.

PMH: none
"""


# ═══════════════════════════════════════════════════════════════════
# 1. FAST line parsing — all known patterns
# ═══════════════════════════════════════════════════════════════════

class TestFastLinePatterns:
    """Test each known FAST line pattern produces correct classification."""

    def test_fast_no(self):
        """FAST: No → performed=no, result=null."""
        text = _ps_text("FAST: No")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "no"
        assert result["fast_result"] is None
        assert result["fast_raw_text"] == "No"

    def test_fast_not_indicated(self):
        """FAST: Not indicated → performed=no, result=null."""
        text = _ps_text("FAST: Not indicated")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "no"
        assert result["fast_result"] is None
        assert result["fast_raw_text"] == "Not indicated"

    def test_fast_no_not_indicated(self):
        """FAST: No not indicated → performed=no, result=null."""
        text = _ps_text("FAST: No not indicated")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "no"
        assert result["fast_result"] is None

    def test_fast_yes_negative(self):
        """FAST: Yes - negative → performed=yes, result=negative."""
        text = _ps_text("FAST: Yes - negative")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "negative"

    def test_fast_yes_positive(self):
        """FAST: Yes - positive → performed=yes, result=positive."""
        text = _ps_text("FAST: Yes - positive")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "positive"

    def test_fast_yes_physician_negative(self):
        """FAST: Yes (per T Burry, MD) - negative → performed=yes, result=negative."""
        text = _ps_text("FAST: Yes (per T Burry, MD) - negative")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "negative"
        assert result["fast_raw_text"] == "Yes (per T Burry, MD) - negative"

    def test_fast_yes_physician_positive(self):
        """FAST: Yes (per Dr. Smith) - positive → performed=yes, result=positive."""
        text = _ps_text("FAST: Yes (per Dr. Smith) - positive")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "positive"

    def test_fast_yes_bare(self):
        """FAST: Yes (no result qualifier) → performed=yes, result=indeterminate."""
        text = _ps_text("FAST: Yes")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "indeterminate"

    def test_fast_yes_indeterminate_explicit(self):
        """FAST: Yes - indeterminate → performed=yes, result=indeterminate."""
        text = _ps_text("FAST: Yes - indeterminate")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "indeterminate"


# ═══════════════════════════════════════════════════════════════════
# 2. Source type filtering
# ═══════════════════════════════════════════════════════════════════

class TestSourceTypeFiltering:
    """Only TRAUMA_HP items should be processed."""

    def test_non_trauma_hp_ignored(self):
        """ED_NOTE items with FAST line should NOT be extracted."""
        text = _ps_text("FAST: No")
        result = _extract_fast_from_text(text, "2025-12-18T17:00:00", "ED_NOTE", "99")
        assert result is None

    def test_radiology_ignored(self):
        """RADIOLOGY items should not be processed."""
        text = _ps_text("FAST: Yes - negative")
        result = _extract_fast_from_text(text, "2025-12-18T17:00:00", "RADIOLOGY", "10")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# 3. Section boundaries
# ═══════════════════════════════════════════════════════════════════

class TestSectionBoundaries:
    """Primary Survey section start/end detection."""

    def test_fast_outside_primary_survey_not_extracted(self):
        """FAST line outside Primary Survey section is ignored."""
        text = """\
[TRAUMA_HP] 2025-12-18 16:17:00

HPI: Patient presents.
FAST: Yes - negative

Primary Survey:
            Airway: patent
            Disability: GCS 15

PMH: none
"""
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is None

    def test_fast_after_secondary_survey_not_extracted(self):
        """FAST line after Secondary Survey header is outside Primary Survey."""
        text = """\
Primary Survey:
            Airway: patent
            Disability: GCS 15

Secondary Survey:
            FAST: Yes - positive

PMH: none
"""
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is None

    def test_primary_survey_ends_at_pmh(self):
        """Primary Survey section ends at PMH header."""
        text = _ps_text("FAST: No")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "no"


# ═══════════════════════════════════════════════════════════════════
# 4. Fail-closed scenarios (full extract_fast_exam)
# ═══════════════════════════════════════════════════════════════════

class TestFailClosed:
    """Fail-closed behaviour for missing data."""

    def test_no_trauma_hp(self):
        """No TRAUMA_HP items → DNA."""
        days_data = _make_days_data({
            "2025-12-18": [_make_ed_note_item("Some ED note with FAST: No")],
        })
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "DATA NOT AVAILABLE"
        assert result["fast_result"] is None
        assert result["fast_source_rule_id"] == "no_trauma_hp"
        assert result["evidence"] == []

    def test_trauma_hp_no_primary_survey(self):
        """TRAUMA_HP exists but no Primary Survey section → DNA."""
        item = _make_trauma_hp_item(_NO_PS_TEXT)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "DATA NOT AVAILABLE"
        assert result["fast_source_rule_id"] == "no_trauma_hp_primary_survey"

    def test_primary_survey_no_fast_line(self):
        """Primary Survey exists but no FAST line → DNA + warning."""
        text = """\
[TRAUMA_HP] 2025-12-18 16:17:00

Primary Survey:
            Airway: patent
            Breathing: even
            Circulation: normal
            Disability: GCS 15
            Exposure: no deformity

PMH: none
"""
        item = _make_trauma_hp_item(text)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "DATA NOT AVAILABLE"
        assert result["fast_source_rule_id"] == "trauma_hp_primary_survey_no_fast_line"
        assert "fast_missing_in_primary_survey" in result["warnings"]

    def test_empty_days(self):
        """Empty days_data → DNA."""
        result = extract_fast_exam({"days": {}}, {"days": {}})
        assert result["fast_performed"] == "DATA NOT AVAILABLE"
        assert result["fast_source_rule_id"] == "no_trauma_hp"


# ═══════════════════════════════════════════════════════════════════
# 5. Full extraction (extract_fast_exam)
# ═══════════════════════════════════════════════════════════════════

class TestFullExtraction:
    """End-to-end extraction through public API."""

    def test_fast_no_full(self):
        """Full extraction of FAST: No."""
        text = _ps_text("FAST: No")
        item = _make_trauma_hp_item(text)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "no"
        assert result["fast_result"] is None
        assert result["fast_ts"] == "2025-12-18T16:17:00"
        assert result["fast_source"] == "TRAUMA_HP:Primary_Survey:FAST"
        assert result["fast_source_rule_id"] == "trauma_hp_primary_survey"
        assert result["raw_line_id"] is not None
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["raw_line_id"] == result["raw_line_id"]

    def test_fast_yes_negative_full(self):
        """Full extraction of FAST: Yes (per T Burry, MD) - negative."""
        text = _ps_text("FAST: Yes (per T Burry, MD) - negative")
        item = _make_trauma_hp_item(text)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "negative"
        assert len(result["evidence"]) == 1
        assert "FAST:" in result["evidence"][0]["snippet"]

    def test_fast_not_indicated_full(self):
        """Full extraction of FAST: Not indicated."""
        text = _ps_text("FAST: Not indicated")
        item = _make_trauma_hp_item(text)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "no"
        assert result["fast_result"] is None
        assert result["fast_source_rule_id"] == "trauma_hp_primary_survey"

    def test_earliest_day_wins(self):
        """When multiple days have TRAUMA_HP, earliest day's result wins."""
        text_day1 = _ps_text("FAST: No")
        text_day2 = _ps_text("FAST: Yes - positive")
        item1 = _make_trauma_hp_item(text_day1, dt="2025-12-18T16:00:00", source_id="0")
        item2 = _make_trauma_hp_item(text_day2, dt="2025-12-19T10:00:00", source_id="1")
        days_data = _make_days_data({
            "2025-12-18": [item1],
            "2025-12-19": [item2],
        })
        result = extract_fast_exam({"days": {}}, days_data)
        # Day 1 (earliest) should win
        assert result["fast_performed"] == "no"
        assert result["fast_ts"] == "2025-12-18T16:00:00"

    def test_ed_note_with_fast_not_extracted(self):
        """ED_NOTE containing FAST line should not produce a result."""
        ed_text = """\
[ED_NOTE] 2025-12-18 17:00:00

Primary Survey:
            FAST: Yes - negative

Assessment: trauma patient
"""
        ed_item = _make_ed_note_item(ed_text)
        days_data = _make_days_data({"2025-12-18": [ed_item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "DATA NOT AVAILABLE"
        assert result["fast_source_rule_id"] == "no_trauma_hp"


# ═══════════════════════════════════════════════════════════════════
# 6. Evidence traceability
# ═══════════════════════════════════════════════════════════════════

class TestEvidenceTraceability:
    """raw_line_id correctness and determinism."""

    def test_raw_line_id_is_sha256(self):
        """raw_line_id is a valid 64-char hex SHA-256."""
        text = _ps_text("FAST: No")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        rid = result["raw_line_id"]
        assert len(rid) == 64
        # Verify it's valid hex
        int(rid, 16)

    def test_raw_line_id_deterministic(self):
        """Same input always produces same raw_line_id."""
        text = _ps_text("FAST: No")
        r1 = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        r2 = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert r1["raw_line_id"] == r2["raw_line_id"]

    def test_raw_line_id_changes_with_source_id(self):
        """Different source_id → different raw_line_id."""
        text = _ps_text("FAST: No")
        r1 = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        r2 = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "1")
        assert r1["raw_line_id"] != r2["raw_line_id"]

    def test_make_raw_line_id_matches_expected(self):
        """_make_raw_line_id produces expected sha256."""
        payload = "TRAUMA_HP|0|FAST: No"
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        result = _make_raw_line_id("TRAUMA_HP", "0", "FAST: No")
        assert result == expected

    def test_full_extraction_evidence_has_raw_line_id(self):
        """Full extraction evidence entries have raw_line_id."""
        text = _ps_text("FAST: Yes - negative")
        item = _make_trauma_hp_item(text)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["raw_line_id"] is not None
        assert len(result["evidence"]) == 1
        ev = result["evidence"][0]
        assert "raw_line_id" in ev
        assert ev["raw_line_id"] == result["raw_line_id"]


# ═══════════════════════════════════════════════════════════════════
# 7. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Whitespace, casing, and unusual formatting."""

    def test_extra_whitespace_in_fast_line(self):
        """Extra whitespace around FAST value is handled."""
        text = _ps_text("FAST:   No  ")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "no"

    def test_case_insensitive_fast(self):
        """fast: no (lowercase) is recognised."""
        text = """\
Primary Survey:
            Airway: patent
            fast: no

PMH: none
"""
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "no"

    def test_case_insensitive_yes_negative(self):
        """FAST: YES - Negative (mixed case)."""
        text = _ps_text("FAST: YES - Negative")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "negative"

    def test_empty_text(self):
        """Empty text returns None."""
        result = _extract_fast_from_text("", "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is None

    def test_null_dt(self):
        """Null dt still produces result with fast_ts=None."""
        text = _ps_text("FAST: No")
        result = _extract_fast_from_text(text, None, "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_ts"] is None

    def test_unrecognised_fast_value(self):
        """Unrecognised value → yes + indeterminate (fail-closed)."""
        text = _ps_text("FAST: Pending results")
        result = _extract_fast_from_text(text, "2025-12-18T16:17:00", "TRAUMA_HP", "0")
        assert result is not None
        assert result["fast_performed"] == "yes"
        assert result["fast_result"] == "indeterminate"

    def test_output_schema_keys_complete(self):
        """Full extraction result has all required schema keys."""
        text = _ps_text("FAST: No")
        item = _make_trauma_hp_item(text)
        days_data = _make_days_data({"2025-12-18": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        required_keys = {
            "fast_performed", "fast_result", "fast_ts", "fast_source",
            "fast_source_rule_id", "fast_raw_text", "raw_line_id",
            "evidence", "notes", "warnings",
        }
        assert required_keys.issubset(set(result.keys()))

    def test_dna_result_schema_keys_complete(self):
        """DNA result has all required schema keys."""
        result = extract_fast_exam({"days": {}}, {"days": {}})
        required_keys = {
            "fast_performed", "fast_result", "fast_ts", "fast_source",
            "fast_source_rule_id", "fast_raw_text", "raw_line_id",
            "evidence", "notes", "warnings",
        }
        assert required_keys.issubset(set(result.keys()))


# ═══════════════════════════════════════════════════════════════════
# 8. Result timestamp propagation
# ═══════════════════════════════════════════════════════════════════

class TestTimestamp:
    """fast_ts comes from the TRAUMA_HP item dt."""

    def test_ts_from_item_dt(self):
        """fast_ts matches the item's dt field."""
        text = _ps_text("FAST: No")
        item = _make_trauma_hp_item(text, dt="2025-12-20T09:30:00")
        days_data = _make_days_data({"2025-12-20": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_ts"] == "2025-12-20T09:30:00"

    def test_ts_none_when_item_has_no_dt(self):
        """fast_ts is None when item has no dt."""
        text = _ps_text("FAST: Yes - positive")
        item = _make_trauma_hp_item(text, dt=None)
        days_data = _make_days_data({"2025-12-20": [item]})
        result = extract_fast_exam({"days": {}}, days_data)
        assert result["fast_performed"] == "yes"
        assert result["fast_ts"] is None
