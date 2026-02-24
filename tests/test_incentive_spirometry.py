#!/usr/bin/env python3
"""
Tests for incentive_spirometry_v1 feature extractor.

Covers:
  1. Positive IS mention (plan text)
  2. IS order extraction with frequency
  3. PFT spirometry exclusion (false positive guard)
  4. Flowsheet numeric data extraction
  5. Pulmonary hygiene only → weak mention → is_mentioned="no"
  6. No IS data → DNA
  7. Evidence traceability (raw_line_id on every evidence entry)
  8. "Frequent IS use" pattern
  9. Mixed mentions + orders + flowsheet
"""

import pytest

from cerebralos.features.incentive_spirometry_v1 import (
    extract_incentive_spirometry,
    _scan_item,
    _parse_flowsheet_block,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days(items_by_day):
    """Build a minimal days_data dict."""
    days = {}
    for day_key, items in items_by_day.items():
        day_items = []
        for item_type, text in items:
            day_items.append({
                "type": item_type,
                "dt": f"{day_key}T08:00:00",
                "id": f"test_{day_key}",
                "payload": {"text": text},
            })
        days[day_key] = {"items": day_items}
    return {"days": days}


# ── Tests ───────────────────────────────────────────────────────────

class TestExplicitISMention:
    """Test explicit IS mention extraction."""

    def test_plan_mention_pulm_hygiene_is(self):
        text = (
            "Plan:\n"
            "Pain control\n"
            "IVF\n"
            "Pulm Hygiene, incentive spirometry\n"
            "PT/OT when appropriate\n"
        )
        days_data = _make_days({"2025-12-29": [("TRAUMA_HP", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        assert result["mention_count"] >= 1
        assert len(result["evidence"]) >= 1
        assert all("raw_line_id" in e for e in result["evidence"])

    def test_encourage_is_use(self):
        text = (
            "Plan:\n"
            "Pulm Hygiene, encourage incentive spirometry use\n"
            "Home meds\n"
        )
        days_data = _make_days({"2025-12-30": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        assert result["mention_count"] >= 1

    def test_is_encouraged(self):
        text = (
            "Plan:\n"
            "- Pulmonary hygiene, incentive spirometry encouraged.\n"
            "- DVT prophylaxis\n"
        )
        days_data = _make_days({"2025-12-17": [("TRAUMA_HP", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"

    def test_frequent_is_use(self):
        text = (
            "Plan:\n"
            "- Aggressive pulmonary toilet. Frequent IS use.\n"
            "- DVT prophylaxis\n"
        )
        days_data = _make_days({"2025-12-31": [("TRAUMA_HP", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        has_is_use = any(
            m["type"] == "is_use" for m in result["mentions"]
        )
        assert has_is_use

    def test_continue_incentive_spirometer(self):
        text = (
            "After bowel movement, patient medically stable for discharge "
            "to rehab on oxygen.  Continue incentive spirometer, ambulat\n"
        )
        days_data = _make_days({"2026-01-04": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"

    def test_aerobic_addition(self):
        text = (
            "- Needs aerobic addition to incentive spirometer as he had "
            "oxygen needs overnight\n"
        )
        days_data = _make_days({"2026-01-02": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"


class TestISOrder:
    """Test IS order extraction."""

    def test_order_with_frequency(self):
        text = (
            "Link to Procedure Log\n"
            "INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)\n"
            "Respiratory Care\n"
            "Discontinued\n"
        )
        days_data = _make_days({"2026-01-01": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        assert result["order_count"] >= 1
        order = result["orders"][0]
        assert order["frequency"] == "Q2H"
        assert order["order_number"] == "466185479"
        assert "raw_line_id" in order

    def test_order_q1h(self):
        text = (
            "INCENTIVE SPIROMETER Q1H While awake [RT16] (Order 466320539)\n"
        )
        days_data = _make_days({"2025-12-26": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["order_count"] >= 1
        assert result["orders"][0]["frequency"] == "Q1H"


class TestPFTExclusion:
    """Test that PFT spirometry is NOT captured as IS."""

    def test_pft_spirometry_excluded(self):
        text = (
            "PFT results:\n"
            "Spirometry suggests mild-to-moderate restriction\n"
            "FEV1 2.1L, FVC 2.9L\n"
        )
        days_data = _make_days({"2026-01-10": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        # PFT spirometry should NOT trigger is_mentioned
        assert result["is_mentioned"] == "DATA NOT AVAILABLE"
        assert result["mention_count"] == 0


class TestFlowsheetData:
    """Test flowsheet numeric data extraction."""

    def test_flowsheet_with_volumes(self):
        text = (
            "Incentive Spirometry\n"
            "\tInspiratory Capacity Goal (cc) **\tNumber of Breaths **\t"
            "Average Volume (cc) **\tLargest Volume (cc) **\t"
            "Patient Effort **\tAssessment Recommendation **\n"
            "01/07 1401\t2500 cc\t5\t1600\t2000\tGood\t"
            "Continue present therapy\n"
            "01/07 0701\t2500 cc\t5\t1500\t2000\tGood\t"
            "Continue present therapy\n"
            "01/06 1406\t2500 cc\t5\t1500\t1700\tGood\t"
            "Continue present therapy\n"
            "Intake (ml)\n"
        )
        days_data = _make_days({"2026-01-07": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        assert result["is_value_present"] == "yes"
        assert result["measurement_count"] >= 3

        # Check first measurement has expected values
        m = result["measurements"][0]
        assert m["goal_cc"] == 2500
        assert m["largest_volume_cc"] == 2000
        assert m["avg_volume_cc"] == 1600
        assert m["patient_effort"] == "Good"
        assert "raw_line_id" in m

    def test_flowsheet_recommendation_only(self):
        """Some rows have only 'Continue present therapy' with no volumes."""
        text = (
            "Incentive Spirometry\n"
            "Assessment Recommendation **\n"
            "01/27 1635\tContinue present therapy\n"
            "01/27 0950\tContinue present therapy\n"
            "Intake (ml)\n"
        )
        days_data = _make_days({"2026-01-27": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        # Recommendation-only rows still count
        assert result["measurement_count"] >= 1

    def test_flowsheet_with_poor_effort(self):
        text = (
            "Incentive Spirometry\n"
            "\tAssessment Recommendation **\tNumber of Breaths **\t"
            "Average Volume (cc) **\tLargest Volume (cc) **\t"
            "Patient Effort **\n"
            "01/09 0700\t\t10\t500\t500\tPoor\n"
            "Intake (ml)\n"
        )
        days_data = _make_days({"2026-01-09": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_value_present"] == "yes"
        m = result["measurements"][0]
        assert m["patient_effort"] == "Poor"
        assert m["avg_volume_cc"] == 500
        assert m["largest_volume_cc"] == 500

    def test_goals_extraction(self):
        text = (
            "Incentive Spirometry\n"
            "\tInspiratory Capacity Goal (cc) **\tNumber of Breaths **\t"
            "Average Volume (cc) **\tLargest Volume (cc) **\t"
            "Patient Effort **\n"
            "01/02 0745\t1500 cc\t6\t1000\t1250\tGood\n"
            "01/01 0700\t1500 cc\t10\t1300\t1700\tGood\n"
            "Intake (ml)\n"
        )
        days_data = _make_days({"2026-01-02": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert len(result["goals"]) >= 1
        assert result["goals"][0]["value"] == 1500
        assert result["goals"][0]["unit"] == "cc"


class TestPulmHygieneOnly:
    """Test that pulmonary hygiene alone is a weak mention."""

    def test_pulm_hygiene_only_weak(self):
        text = (
            "Plan:\n"
            "- Pulmonary hygiene encouraged.\n"
            "- DVT prophylaxis\n"
        )
        days_data = _make_days({"2025-12-13": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        # Pulmonary hygiene alone is NOT an explicit IS reference
        assert result["is_mentioned"] == "no"
        assert result["mention_count"] >= 1
        has_weak = any(
            m["type"] == "pulm_hygiene_only" for m in result["mentions"]
        )
        assert has_weak


class TestNegativeControl:
    """Test patient with no IS data → DNA."""

    def test_no_is_data(self):
        text = (
            "HPI: Patient is a 45 yo male presenting with GSW...\n"
            "Plan:\n"
            "- Pain control\n"
            "- DVT prophylaxis\n"
        )
        days_data = _make_days({"2025-12-10": [("TRAUMA_HP", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "DATA NOT AVAILABLE"
        assert result["is_value_present"] == "no"
        assert result["mention_count"] == 0
        assert result["measurement_count"] == 0

    def test_empty_days(self):
        result = extract_incentive_spirometry({}, {"days": {}})
        assert result["is_mentioned"] == "DATA NOT AVAILABLE"


class TestEvidenceTraceability:
    """Every evidence entry must have raw_line_id."""

    def test_all_evidence_has_raw_line_id(self):
        text = (
            "Plan:\n"
            "Pulm Hygiene, incentive spirometry\n"
            "INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)\n"
        )
        days_data = _make_days({"2025-12-29": [("TRAUMA_HP", text)]})
        result = extract_incentive_spirometry({}, days_data)

        for ev in result["evidence"]:
            assert "raw_line_id" in ev, (
                f"Evidence missing raw_line_id: {ev}"
            )
            assert len(ev["raw_line_id"]) == 16

    def test_flowsheet_evidence_has_raw_line_id(self):
        text = (
            "Incentive Spirometry\n"
            "\tInspiratory Capacity Goal (cc) **\tNumber of Breaths **\t"
            "Average Volume (cc) **\tLargest Volume (cc) **\t"
            "Patient Effort **\n"
            "01/07 1401\t2500 cc\t5\t1600\t2000\tGood\n"
            "Intake (ml)\n"
        )
        days_data = _make_days({"2026-01-07": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        for ev in result["evidence"]:
            assert "raw_line_id" in ev
        for m in result["measurements"]:
            assert "raw_line_id" in m


class TestMixedContent:
    """Test item with multiple IS signal types."""

    def test_mention_plus_order(self):
        text = (
            "Plan:\n"
            "Pulm Hygiene, incentive spirometry\n"
            "PT/OT when appropriate\n"
            "\n"
            "INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 464432335)\n"
            "Respiratory Care\n"
        )
        days_data = _make_days({"2025-12-18": [("PHYSICIAN_NOTE", text)]})
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        assert result["mention_count"] >= 1
        assert result["order_count"] >= 1
        assert len(result["evidence"]) >= 2

    def test_multi_day_accumulation(self):
        days_data = _make_days({
            "2025-12-29": [
                ("TRAUMA_HP", "Pulm Hygiene, incentive spirometry\n"),
            ],
            "2025-12-30": [
                ("PHYSICIAN_NOTE",
                 "Plan:\n- Pulmonary hygiene encouraged.\n"),
            ],
            "2026-01-01": [
                ("PHYSICIAN_NOTE",
                 "INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466671897)\n"
                 "INCENTIVE SPIROMETER\n"),
            ],
        })
        result = extract_incentive_spirometry({}, days_data)

        assert result["is_mentioned"] == "yes"
        assert result["mention_count"] >= 2  # IS mention + pulm hygiene
        assert result["order_count"] >= 1
