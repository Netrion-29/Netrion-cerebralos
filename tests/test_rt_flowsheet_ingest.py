#!/usr/bin/env python3
"""
Tests for RT_ORDER and IS_FLOWSHEET supplemental ingest handlers.

Validates that the ingest parser correctly detects and emits evidence items
for IS order detail pages and IS flowsheet data sections in the supplemental
zone of DoS-format patient files.
"""

import textwrap
import unittest

from cerebralos.ingest.parse_patient_txt import (
    _parse_supplemental_dos,
    _resolve_flowsheet_year,
)


def _make_lines(text: str) -> list:
    """Convert indented text block to list of lines."""
    return textwrap.dedent(text).strip().split("\n")


class TestRTOrderDetection(unittest.TestCase):
    """Test RT_ORDER evidence item emission."""

    def _run_supp(self, raw_text: str, arrival_dt_str=None):
        lines = _make_lines(raw_text)
        return _parse_supplemental_dos(
            lines, last_dos_idx=-1, arrival_dt_str=arrival_dt_str,
        )

    def test_is_order_captured(self):
        """IS order page emits RT_ORDER item with correct kind and date."""
        raw = """\
        INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)
        Respiratory Care
        Discontinued
        Date: 12/29/2025\tDepartment: Ortho Neuro Trauma Care Center

        Patient Demographics

        Patient Name
        Dougan, Michael E

        INCENTIVE SPIROMETER
        Order: 466185479
        Status:  Discontinued (Patient Discharge)
        """
        items = self._run_supp(raw)
        rt_items = [it for it in items if it.kind == "RT_ORDER"]
        self.assertEqual(len(rt_items), 1)
        self.assertEqual(rt_items[0].datetime, "2025-12-29 00:00:00")
        self.assertIn("INCENTIVE SPIROMETER Q2H", rt_items[0].text)
        self.assertIn("Order: 466185479", rt_items[0].text)

    def test_two_is_orders_captured(self):
        """Multiple IS order pages each emit their own RT_ORDER item."""
        raw = """\
        INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 100001)
        Respiratory Care
        Date: 12/29/2025\tDepartment: Test

        INCENTIVE SPIROMETER
        Order: 100001

        Link to Procedure Log

        Procedure Log


        INCENTIVE SPIROMETER Q1H While awake [RT16] (Order 100002)
        Respiratory Care
        Date: 12/31/2025\tDepartment: Test

        INCENTIVE SPIROMETER
        Order: 100002
        """
        items = self._run_supp(raw)
        rt_items = [it for it in items if it.kind == "RT_ORDER"]
        self.assertEqual(len(rt_items), 2)
        self.assertIn("Q2H", rt_items[0].text)
        self.assertIn("Q1H", rt_items[1].text)

    def test_non_is_order_not_captured(self):
        """Wound/non-IS order pages do not emit RT_ORDER items."""
        raw = """\
        Wound ostomy eval and treat [WOU1] (Order 466214020)
        Wound Ostomy
        Date: 12/29/2025\tDepartment: Test
        """
        items = self._run_supp(raw)
        rt_items = [it for it in items if it.kind == "RT_ORDER"]
        self.assertEqual(len(rt_items), 0)

    def test_rt_order_has_raw_line_id_compatible_lines(self):
        """RT_ORDER items have valid line_start and line_end."""
        raw = """\
        INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)
        Respiratory Care
        Date: 12/29/2025\tDepartment: Test
        """
        items = self._run_supp(raw)
        rt_items = [it for it in items if it.kind == "RT_ORDER"]
        self.assertEqual(len(rt_items), 1)
        self.assertGreater(rt_items[0].line_start, 0)
        self.assertGreaterEqual(rt_items[0].line_end, rt_items[0].line_start)

    def test_rt_order_missing_date(self):
        """RT_ORDER without Date: field gets ts_missing warning."""
        raw = """\
        INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)
        Respiratory Care
        No date here
        """
        items = self._run_supp(raw)
        rt_items = [it for it in items if it.kind == "RT_ORDER"]
        self.assertEqual(len(rt_items), 1)
        self.assertIsNone(rt_items[0].datetime)
        self.assertIn("ts_missing", rt_items[0].warnings)


class TestISFlowsheetDetection(unittest.TestCase):
    """Test IS_FLOWSHEET evidence item emission."""

    def _run_supp(self, raw_text: str, arrival_dt_str=None):
        lines = _make_lines(raw_text)
        return _parse_supplemental_dos(
            lines, last_dos_idx=-1, arrival_dt_str=arrival_dt_str,
        )

    def test_flowsheet_captured(self):
        """IS flowsheet with column headers and data rows emits IS_FLOWSHEET."""
        raw = """\
        Incentive Spirometry
        \tInspiratory Capacity Goal (cc) **\tNumber of Breaths **\tAverage Volume (cc) **\tLargest Volume (cc) **\tPatient Effort **
        01/07 1401\t2500 cc\t5\t1600\t2000\tGood
        01/06 0748\t2500 cc\t8\t1500\t1700\tGood

        Intake (ml)
        \tP.O.\tOral Rehydration
        """
        items = self._run_supp(raw, arrival_dt_str="2025-12-29 07:22:00")
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(fs_items), 1)
        self.assertIn("Incentive Spirometry", fs_items[0].text)
        self.assertIn("01/07 1401", fs_items[0].text)
        self.assertIn("2500 cc", fs_items[0].text)

    def test_flowsheet_timestamp_resolved(self):
        """IS_FLOWSHEET datetime resolves year from arrival context."""
        raw = """\
        Incentive Spirometry
        \tNumber of Breaths **\tAverage Volume (cc) **
        01/07 1401\t5\t1600

        Intake (ml)
        """
        items = self._run_supp(raw, arrival_dt_str="2025-12-29 07:22:00")
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(fs_items), 1)
        # Jan after Dec admission → 2026
        self.assertEqual(fs_items[0].datetime, "2026-01-07 14:01:00")

    def test_flowsheet_same_year(self):
        """Flowsheet month same as arrival month → same year."""
        raw = """\
        Incentive Spirometry
        \tNumber of Breaths **
        12/30 0800\t5

        Intake (ml)
        """
        items = self._run_supp(raw, arrival_dt_str="2025-12-29 07:22:00")
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(fs_items), 1)
        self.assertEqual(fs_items[0].datetime, "2025-12-30 08:00:00")

    def test_flowsheet_without_col_headers_skipped(self):
        """'Incentive Spirometry' without ** column headers is not emitted."""
        raw = """\
        Incentive Spirometry
        Some random text here
        01/07 1401 data
        """
        items = self._run_supp(raw, arrival_dt_str="2025-12-29 07:22:00")
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(fs_items), 0)

    def test_flowsheet_stops_at_intake(self):
        """IS_FLOWSHEET block does not include 'Intake (ml)' section."""
        raw = """\
        Incentive Spirometry
        \tNumber of Breaths **
        01/07 1401\t5

        Intake (ml)
        \tP.O.
        01/07 0825\t360 mL
        """
        items = self._run_supp(raw, arrival_dt_str="2025-12-29 07:22:00")
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(fs_items), 1)
        self.assertNotIn("360 mL", fs_items[0].text)

    def test_multiline_flowsheet_format(self):
        """Multi-line flowsheet format (Ronald Bittner 2nd instance) captured."""
        raw = """\
        Incentive Spirometry
        Assessment Recommendation **
        01/27 1635\t
        Continue present therapy
        01/27 1632\t
        Continue present therapy

        Intake (ml)
        """
        items = self._run_supp(raw, arrival_dt_str="2026-01-01 00:00:00")
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(fs_items), 1)
        self.assertIn("01/27 1635", fs_items[0].text)

    def test_no_regression_on_radiology(self):
        """RADIOLOGY items still captured alongside new handlers."""
        raw = """\
        CT CHEST W CONTRAST
        Narrative & Impression
        No acute findings.
        Exam Ended: 12/29/25 16:21 CST
        Reading Physician Information

        Incentive Spirometry
        \tNumber of Breaths **
        01/07 1401\t5

        Intake (ml)
        """
        items = self._run_supp(raw, arrival_dt_str="2025-12-29 07:22:00")
        rad_items = [it for it in items if it.kind == "RADIOLOGY"]
        fs_items = [it for it in items if it.kind == "IS_FLOWSHEET"]
        self.assertEqual(len(rad_items), 1)
        self.assertEqual(len(fs_items), 1)


class TestResolveFlowsheetYear(unittest.TestCase):
    """Test _resolve_flowsheet_year helper."""

    def test_cross_year_boundary(self):
        """January flowsheet after December admission → next year."""
        self.assertEqual(
            _resolve_flowsheet_year("01/07", "2025-12-29 07:22:00"),
            2026,
        )

    def test_same_month(self):
        """Same month as admission → same year."""
        self.assertEqual(
            _resolve_flowsheet_year("12/30", "2025-12-29 07:22:00"),
            2025,
        )

    def test_no_arrival(self):
        """No arrival date → None."""
        self.assertIsNone(
            _resolve_flowsheet_year("01/07", None),
        )

    def test_invalid_mmdd(self):
        """Bad MM/DD → None."""
        self.assertIsNone(
            _resolve_flowsheet_year("xx/yy", "2025-12-29 07:22:00"),
        )


class TestGCSFlowsheetDetection(unittest.TestCase):
    """Test GCS_FLOWSHEET evidence item emission via NURSING_NOTE."""

    def _run_supp(self, raw_text: str, arrival_dt_str=None):
        lines = _make_lines(raw_text)
        return _parse_supplemental_dos(
            lines, last_dos_idx=-1, arrival_dt_str=arrival_dt_str,
        )

    def test_gcs_flowsheet_standard_header(self):
        """Flowsheet History with Eye Opening + Verbal + Motor + Score emits NURSING_NOTE."""
        raw = """\
        Flowsheet History
         Personalize
        1/1/2026 0000 CST - 1/5/2026 2359 CST

        Date/Time\tEye Opening\tBest Verbal Response\tBest Motor Response\tGlasgow Coma Scale Score Total
        01/05/26 1607\tSpontaneous A\tOriented A\tObeys commands A\t15 A
        01/04/26 0411\tTo speech D\tConfused D\tObeys commands D\t13 D

        User Key
        """
        items = self._run_supp(raw)
        nn_items = [it for it in items if it.kind == "NURSING_NOTE"]
        self.assertEqual(len(nn_items), 1)
        self.assertIn("Eye Opening", nn_items[0].text)
        self.assertIn("01/05/26 1607", nn_items[0].text)
        self.assertIn("Spontaneous", nn_items[0].text)

    def test_gcs_flowsheet_score_total_variant(self):
        """'Glasgow Coma Scale Score' (without 'Total') also triggers detection."""
        raw = """\
        Flowsheet History
         Personalize
        12/6/2025 0000 CST - 1/5/2026 1455 CST

        Date/Time\tLUE\tEye Opening\tBest Verbal Response\tBest Motor Response\tGlasgow Coma Scale Score\tRUE
        01/05/26 0728\tGrasps A\tSpontaneous A\tOriented A\tObeys commands A\t15 A\tGrasps A

        User Key
        """
        items = self._run_supp(raw)
        nn_items = [it for it in items if it.kind == "NURSING_NOTE"]
        self.assertEqual(len(nn_items), 1)
        self.assertIn("Glasgow Coma Scale Score", nn_items[0].text)

    def test_non_gcs_flowsheet_not_captured(self):
        """Flowsheet History without GCS columns is NOT captured as GCS."""
        raw = """\
        Flowsheet History
         Personalize
        1/1/2026 0000 CST - 1/5/2026 2359 CST

        Date/Time\tHeart Rate\tBlood Pressure\tRespiratory Rate\tSpO2
        01/05/26 1607\t82\t120/80\t16\t98%

        User Key
        """
        items = self._run_supp(raw)
        # No NURSING_NOTE for non-GCS flowsheet (and not SBIRT either)
        nn_items = [it for it in items if it.kind == "NURSING_NOTE"]
        self.assertEqual(len(nn_items), 0)

    def test_gcs_flowsheet_timestamp_parsed(self):
        """GCS flowsheet datetime is extracted from the first data row."""
        raw = """\
        Flowsheet History
         Personalize
        1/1/2026 0000 CST - 1/5/2026 2359 CST

        Date/Time\tEye Opening\tBest Verbal Response\tBest Motor Response\tGlasgow Coma Scale Score Total
        01/05/26 1607\tSpontaneous A\tOriented A\tObeys commands A\t15 A
        01/04/26 0411\tTo speech D\tConfused D\tObeys commands D\t13 D
        """
        items = self._run_supp(raw)
        nn_items = [it for it in items if it.kind == "NURSING_NOTE"]
        self.assertEqual(len(nn_items), 1)
        self.assertEqual(nn_items[0].datetime, "2026-01-05 16:07:00")

    def test_gcs_flowsheet_no_collision_with_sbirt(self):
        """SBIRT and GCS flowsheet sections in same file do not collide."""
        raw = """\
        Flowsheet History
         Personalize

        Date/Time\tDoes the patient have an injury\tAudit-C Score
        01/05/26 1200\tYes\t3

        User Key

        Flowsheet History
         Personalize
        1/1/2026 0000 CST - 1/5/2026 2359 CST

        Date/Time\tEye Opening\tBest Verbal Response\tBest Motor Response\tGlasgow Coma Scale Score
        01/05/26 1607\tSpontaneous A\tOriented A\tObeys commands A\t15 A
        """
        items = self._run_supp(raw)
        nn_items = [it for it in items if it.kind == "NURSING_NOTE"]
        # Should have 2: one SBIRT, one GCS
        self.assertEqual(len(nn_items), 2)
        texts = [it.text for it in nn_items]
        has_sbirt = any("Audit-C Score" in t for t in texts)
        has_gcs = any("Eye Opening" in t for t in texts)
        self.assertTrue(has_sbirt, "SBIRT block should be captured")
        self.assertTrue(has_gcs, "GCS block should be captured")

    def test_gcs_flowsheet_line_tracking(self):
        """GCS NURSING_NOTE items have valid line_start and line_end."""
        raw = """\
        Flowsheet History
         Personalize

        Date/Time\tEye Opening\tBest Verbal Response\tBest Motor Response\tGlasgow Coma Scale Score
        01/05/26 1607\tSpontaneous A\tOriented A\tObeys commands A\t15 A
        """
        items = self._run_supp(raw)
        nn_items = [it for it in items if it.kind == "NURSING_NOTE"]
        self.assertEqual(len(nn_items), 1)
        self.assertGreater(nn_items[0].line_start, 0)
        self.assertGreaterEqual(nn_items[0].line_end, nn_items[0].line_start)


if __name__ == "__main__":
    unittest.main()
