#!/usr/bin/env python3
"""Tests for urine_output_events_v1 feature extraction."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cerebralos.features.urine_output_events_v1 import extract_urine_output_events


# ── helpers ──────────────────────────────────────────────────────────

def _make_days_with_source(path):
    """Build minimal days_data dict with meta.source_file."""
    return {"meta": {"source_file": path}}


# ── Synthetic test data ─────────────────────────────────────────────

FORMAT_FLOWSHEET = (
    "Flowsheets\n"
    "\n"
    "Stool Documentation\t01/02\t0830\tStool ml\n"
    "0 ml\n"
    "\n"
    "Stool Unmeasured Occurrence\n"
    "0\n"
    "\n"
    "Urine Documentation\n"
    "\tUrine ml\tUrine Unmeasured Occurrence\tUrine Color\tUrine Appearance\tUrine Odor\tUrine Source\n"
    "01/02 0830\t200 mL\t1\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "01/02 0152\t200 mL\t\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "01/01 1900\t1000 mL\t\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "01/01 1600\t\t1\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "01/01 1212\t600 mL\t\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "01/01 0915\t200 mL\t\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "\n"
    "Vital Signs\t01/02\t1540\t88 more\n"
)

FORMAT_LDA_COLUMNAR = (
    "[REMOVED] Urethral Catheter Anchored\n"
    "Properties\n"
    "Placement date\t01/03/26   -BW\tRemoval date\t01/08/26   -MW\n"
    "Placement time\t1115   -BW\tRemoval time\t1655   -MW\n"
    "Site\tAnchored   -BW\tDays\t5\n"
    "Assessments\n"
    "Assessments\n"
    "Row Name\t01/08/26 1646\t01/08/26 1500\t01/08/26 1155\n"
    "Catheter day\t—\t6   -MW\t—\n"
    "Urine Color\t—\tYellow/Straw   -MW\t—\n"
    "Urine Appearance\t—\tClear   -MW\t—\n"
    "Urine Odor\t—\tNo odor   -MW\t—\n"
    "Output (ml)\t650 ml   -EJ\t—\t700 ml   -EJ\n"
    "Assessment Complete\t—\tYes   -MW\t—\n"
    "\n"
    "User Key\n"
)

FORMAT_LDA_VERTICAL = (
    "LDAs\t\t\n"
    "Drain, Urethral Catheter, NHSN Urethral Catheter\n"
    "Urethral Catheter 16 fr Anchored\t\t\tPlaced\n"
    "12/31/25 0800\n"
    "\n"
    "Removed\n"
    "01/01/26 1200\n"
    "\n"
    "Duration\n"
    "1 day\n"
    "\n"
    "\t01/01\t0615\tUrine Color\n"
    "Amber\n"
    "\n"
    "Urine Appearance\n"
    "Clear\n"
    "\n"
    "Urine Odor\n"
    "No odor\n"
    "\n"
    "Output (ml)\n"
    "450\n"
    "\n"
    "\t12/31\t2318\tPresent on Discharge\n"
    "Yes\n"
    "\n"
    "PIV Line, Line\n"
    "Peripheral IV 12/31/25 Left Antecubital\t\t\t23 assessments\n"
)

FORMAT_FEEDING_TUBE_ONLY = (
    "[REMOVED] G-tube; J-tube, PEG\n"
    "Properties\n"
    "Placement date\t01/03/26   -BW\n"
    "Assessments\n"
    "Assessments\n"
    "Row Name\t01/07/26 0300\t01/06/26 2300\n"
    "Tube Feeding Rate\t55   -MW\t55   -MW\n"
    "Output (ml)\t100 ml   -MW\t200 ml   -MW\n"
    "\n"
    "User Key\n"
)

# Cross-source collision: flowsheet 0ml at same timestamp as LDA actual ml
FORMAT_CROSS_SOURCE = (
    "Flowsheets\n"
    "\n"
    "Urine Documentation\n"
    "\tUrine ml\tUrine Unmeasured Occurrence\tUrine Color\tUrine Appearance\tUrine Odor\tUrine Source\n"
    "01/04 0700\t0 mL\t\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "01/04 1200\t300 mL\t\tYellow/Straw\tClear\tNo odor\tVoided\n"
    "\n"
    "[ACTIVE] Urethral Catheter Anchored\n"
    "Properties\n"
    "Placement date\t01/03/26   -BW\n"
    "Assessments\n"
    "Assessments\n"
    "Row Name\t01/04/26 0700\n"
    "Output (ml)\t250 ml   -MW\n"
    "Urine Color\tYellow/Straw   -MW\n"
    "\n"
    "User Key\n"
)


# ── Test classes ─────────────────────────────────────────────────────


class TestUrineOutputSmoke(unittest.TestCase):
    """Basic smoke tests."""

    def test_no_source_file(self):
        result = extract_urine_output_events({}, {})
        self.assertEqual(result["urine_output_event_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_urine_output_data")
        self.assertEqual(result["events"], [])

    def test_no_urine_data(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("No urine data here\n")
            path = f.name
        try:
            result = extract_urine_output_events({}, _make_days_with_source(path))
            self.assertEqual(result["urine_output_event_count"], 0)
            self.assertEqual(result["source_rule_id"], "no_urine_output_data")
        finally:
            os.unlink(path)

    def test_has_required_keys(self):
        result = extract_urine_output_events({}, {})
        required = {
            "events", "urine_output_event_count", "total_urine_output_ml",
            "first_urine_output_ts", "last_urine_output_ts",
            "source_types_present", "source_rule_id", "warnings", "notes",
        }
        self.assertTrue(required.issubset(set(result.keys())))

    def test_determinism(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(FORMAT_FLOWSHEET)
            path = f.name
        try:
            r1 = extract_urine_output_events({}, _make_days_with_source(path))
            r2 = extract_urine_output_events({}, _make_days_with_source(path))
            self.assertEqual(r1, r2)
        finally:
            os.unlink(path)


class TestFlowsheetUrine(unittest.TestCase):
    """Tests for Flowsheet 'Urine Documentation' extraction."""

    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(FORMAT_FLOWSHEET)
            cls.path = f.name
        cls.result = extract_urine_output_events({}, _make_days_with_source(cls.path))

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_event_count(self):
        self.assertEqual(self.result["urine_output_event_count"], 6)

    def test_total_ml(self):
        # 200 + 200 + 1000 + 600 + 200 = 2200 (the 01/01 1600 row has no mL)
        self.assertEqual(self.result["total_urine_output_ml"], 2200)

    def test_source_type_flowsheet(self):
        self.assertIn("flowsheet", self.result["source_types_present"])

    def test_source_subtype_voided(self):
        for ev in self.result["events"]:
            self.assertEqual(ev["source_subtype"], "Voided")

    def test_urine_color_present(self):
        for ev in self.result["events"]:
            self.assertEqual(ev["urine_color"], "Yellow/Straw")

    def test_evidence_raw_line_id(self):
        for ev in self.result["events"]:
            self.assertTrue(len(ev["evidence"]) > 0)
            self.assertIn("raw_line_id", ev["evidence"][0])

    def test_first_ts(self):
        self.assertEqual(self.result["first_urine_output_ts"], "01/01 0915")

    def test_last_ts(self):
        self.assertEqual(self.result["last_urine_output_ts"], "01/02 0830")

    def test_source_rule_id(self):
        self.assertEqual(self.result["source_rule_id"], "urine_output_events_raw_file")

    def test_unmeasured_row_no_ml(self):
        """Row with Urine Unmeasured Occurrence but no mL should still have color data."""
        unmeasured_events = [e for e in self.result["events"] if e["output_ml"] is None]
        self.assertEqual(len(unmeasured_events), 1)
        self.assertEqual(unmeasured_events[0]["ts"], "01/01 1600")
        self.assertEqual(unmeasured_events[0]["urine_color"], "Yellow/Straw")


class TestLdaColumnarUrine(unittest.TestCase):
    """Tests for LDA columnar assessment row extraction."""

    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(FORMAT_LDA_COLUMNAR)
            cls.path = f.name
        cls.result = extract_urine_output_events({}, _make_days_with_source(cls.path))

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_event_count(self):
        # 3 columns: 01/08 1646 (650ml, no color), 01/08 1500 (no ml, has color),
        # 01/08 1155 (700ml, no color)
        self.assertGreaterEqual(self.result["urine_output_event_count"], 2)

    def test_source_type_lda(self):
        self.assertIn("lda_assessment", self.result["source_types_present"])

    def test_source_subtype_catheter(self):
        for ev in self.result["events"]:
            self.assertEqual(ev["source_subtype"], "Urethral Catheter")

    def test_total_ml(self):
        # 650 + 700 = 1350, middle column has no ml
        self.assertEqual(self.result["total_urine_output_ml"], 1350)

    def test_evidence_raw_line_id(self):
        for ev in self.result["events"]:
            self.assertTrue(len(ev["evidence"]) > 0)
            self.assertIn("raw_line_id", ev["evidence"][0])

    def test_color_on_column_with_it(self):
        """Column 01/08 1500 has Yellow/Straw color."""
        color_events = [e for e in self.result["events"] if e.get("urine_color")]
        self.assertTrue(len(color_events) > 0)


class TestLdaVerticalUrine(unittest.TestCase):
    """Tests for LDA Format A vertical assessment extraction."""

    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(FORMAT_LDA_VERTICAL)
            cls.path = f.name
        cls.result = extract_urine_output_events({}, _make_days_with_source(cls.path))

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_event_count(self):
        self.assertGreaterEqual(self.result["urine_output_event_count"], 1)

    def test_output_ml(self):
        self.assertEqual(self.result["total_urine_output_ml"], 450)

    def test_source_type(self):
        self.assertIn("lda_assessment", self.result["source_types_present"])

    def test_subtype(self):
        for ev in self.result["events"]:
            self.assertEqual(ev["source_subtype"], "Urethral Catheter")

    def test_color(self):
        color_events = [e for e in self.result["events"] if e.get("urine_color")]
        self.assertTrue(len(color_events) > 0)
        self.assertEqual(color_events[0]["urine_color"], "Amber")

    def test_appearance(self):
        app_events = [e for e in self.result["events"] if e.get("urine_appearance")]
        self.assertTrue(len(app_events) > 0)
        self.assertEqual(app_events[0]["urine_appearance"], "Clear")

    def test_evidence_raw_line_id(self):
        for ev in self.result["events"]:
            self.assertTrue(len(ev["evidence"]) > 0)
            self.assertIn("raw_line_id", ev["evidence"][0])


class TestFeedingTubeExcluded(unittest.TestCase):
    """Feeding tube Output (ml) must NOT be extracted as urine."""

    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(FORMAT_FEEDING_TUBE_ONLY)
            cls.path = f.name
        cls.result = extract_urine_output_events({}, _make_days_with_source(cls.path))

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_no_events(self):
        self.assertEqual(self.result["urine_output_event_count"], 0)

    def test_no_ml(self):
        self.assertEqual(self.result["total_urine_output_ml"], 0)


class TestRealData(unittest.TestCase):
    """Real-data tests against patient files."""

    DATA_DIR = os.path.join(
        os.path.dirname(__file__), "..", "data_raw"
    )

    def _extract(self, pat_name):
        path = os.path.join(self.DATA_DIR, f"{pat_name}.txt")
        if not os.path.isfile(path):
            self.skipTest(f"Patient file not found: {path}")
        return extract_urine_output_events({}, _make_days_with_source(path))

    def test_roscella_weatherly(self):
        """Roscella has Urine Documentation flowsheet with explicit mL."""
        result = self._extract("Roscella Weatherly")
        self.assertGreater(result["urine_output_event_count"], 0)
        self.assertIn("flowsheet", result["source_types_present"])
        self.assertGreater(result["total_urine_output_ml"], 0)
        self.assertEqual(result["source_rule_id"], "urine_output_events_raw_file")

    def test_lee_woodard(self):
        """Lee Woodard has LDA urethral catheter assessments with Output (ml)."""
        result = self._extract("Lee Woodard")
        self.assertGreater(result["urine_output_event_count"], 0)
        self.assertIn("lda_assessment", result["source_types_present"])
        self.assertGreater(result["total_urine_output_ml"], 0)

    def test_ronald_bittner(self):
        """Ronald Bittner has extensive LDA columnar catheter assessments."""
        result = self._extract("Ronald Bittner")
        self.assertGreater(result["urine_output_event_count"], 0)
        self.assertIn("lda_assessment", result["source_types_present"])
        self.assertGreater(result["total_urine_output_ml"], 0)

    def test_ronald_bittner_cross_source_dedup(self):
        """Ronald Bittner has timestamp collisions between flowsheet and LDA."""
        result = self._extract("Ronald Bittner")
        # Cross-source dedup should have dropped some zero-ml flowsheet events
        cross_notes = [n for n in result["notes"] if "cross_source_duplicates_dropped" in n]
        self.assertTrue(len(cross_notes) > 0,
                        "Expected cross_source_duplicates_dropped note")

    def test_anna_dennis_no_urine(self):
        """Anna Dennis has no urine data — DNA control."""
        result = self._extract("Anna_Dennis")
        self.assertEqual(result["urine_output_event_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_urine_output_data")

    def test_determinism_real(self):
        """Two runs on same real data must produce identical output."""
        path = os.path.join(self.DATA_DIR, "Roscella Weatherly.txt")
        if not os.path.isfile(path):
            self.skipTest("Patient file not found")
        r1 = extract_urine_output_events({}, _make_days_with_source(path))
        r2 = extract_urine_output_events({}, _make_days_with_source(path))
        self.assertEqual(r1, r2)


class TestCrossSourceDedup(unittest.TestCase):
    """Tests for cross-source dedup (flowsheet 0ml vs LDA actual ml at same ts)."""

    @classmethod
    def setUpClass(cls):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(FORMAT_CROSS_SOURCE)
            cls.path = f.name
        cls.result = extract_urine_output_events({}, _make_days_with_source(cls.path))

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_event_count(self):
        """Flowsheet 0ml at 01/04 0700 should be dropped; LDA 250ml kept. Plus flowsheet 300ml at 1200."""
        self.assertEqual(self.result["urine_output_event_count"], 2)

    def test_total_ml(self):
        """250 (LDA at 0700) + 300 (flowsheet at 1200) = 550."""
        self.assertEqual(self.result["total_urine_output_ml"], 550)

    def test_cross_source_note(self):
        cross_notes = [n for n in self.result["notes"] if "cross_source_duplicates_dropped" in n]
        self.assertTrue(len(cross_notes) > 0)
        self.assertIn("1", cross_notes[0])

    def test_lda_event_kept(self):
        """The LDA event with 250ml at 01/04 0700 should be kept."""
        ev_0700 = [e for e in self.result["events"] if e["ts"] == "01/04 0700"]
        self.assertEqual(len(ev_0700), 1)
        self.assertEqual(ev_0700[0]["output_ml"], 250)
        self.assertEqual(ev_0700[0]["source_type"], "lda_assessment")


if __name__ == "__main__":
    unittest.main()
