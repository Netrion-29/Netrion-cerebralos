#!/usr/bin/env python3
"""Tests for lda_events_v1 feature extractor."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cerebralos.features.lda_events_v1 import extract_lda_events


# ── helpers ──────────────────────────────────────────────────────

def _make_days_with_source(source_file: str):
    return {"meta": {"source_file": source_file}}


def _write_temp(content: str) -> str:
    """Write content to a temp file and return path."""
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


# ── Format A test data ──────────────────────────────────────────

FORMAT_A_BASIC = """\
Triage Assessment\t01/01\t1746\tMatsel, Tiffany M, RN

Service
Emergency



LDAs\t\t
PIV Line, Line
Peripheral IV 01/01/26 Right Antecubital\t\t\t23 assessments
Placed
01/01/26 1754

Removed
01/07/26 1011

Duration
5 days

Peripheral Nerve Catheter
Continuous Nerve Block 01/02/26\t\t\t18 assessments
Placed
01/02/26 1234

Removed
01/21/26 1413

Duration
19 days



Flowsheets\t\t
Blood Glucose\t01/02\t1112
"""

FORMAT_A_WITH_ASSESSMENTS = """\
LDAs\t\t
Drain, Urethral Catheter, NHSN Urethral Catheter
Urethral Catheter 16 fr Anchored\t\t\tPlaced
01/01/26 1330

Removed
01/31/26 1130

Duration
29 days

\t01/05\t1536\tSite Assessment
Clean;Skin intact

Collection Container
Standard drainage bag

Urine Color
Yellow/Straw

Output (ml)
850

\t01/04\t2123\tUrine Color
Yellow/Straw

Output (ml)
650

Flowsheets\t\t
"""


# ── Format B test data ──────────────────────────────────────────

FORMAT_B_BASIC = """\
 Lines / Drains / Airways

Patient Lines/Drains/Airways Status 


Active LDAs 


Name
Placement date
Placement time
Site
Days

PICC Triple Lumen
01/22/26 
1120 
—
1

G-tube; J-tube, PEG; Feeding Tube Percutaneous endoscopic gastrostomy (PEG) LUQ 20 fr
01/15/26 
1255 
LUQ 
8

Urethral Catheter 16 fr Anchored
01/16/26 
1030 
Anchored 
7

Surgical Airway/Trach Shiley 8 mm Distal;Long
01/23/26 
1301 
8 mm 
less than 1


 Exam

Ventilator Settings
"""

NO_LDA_SECTION = """\
Notes
H&P Note\t12/31\t1414\tSmith, John M, MD

Flowsheets
Blood Glucose\t01/02\t1112
"""


# ═══════════════════════════════════════════════════════════════════
# Test Cases
# ═══════════════════════════════════════════════════════════════════


class TestLdaEventsSmoke(unittest.TestCase):
    """Basic structural tests."""

    def test_no_source_file(self):
        result = extract_lda_events({}, {})
        self.assertEqual(result["lda_device_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_lda_section")
        self.assertEqual(result["devices"], [])

    def test_no_lda_section(self):
        path = _write_temp(NO_LDA_SECTION)
        try:
            result = extract_lda_events({}, _make_days_with_source(path))
            self.assertEqual(result["lda_device_count"], 0)
            self.assertEqual(result["source_rule_id"], "no_lda_section")
        finally:
            os.unlink(path)

    def test_has_required_keys(self):
        path = _write_temp(FORMAT_A_BASIC)
        try:
            result = extract_lda_events({}, _make_days_with_source(path))
            required = {
                "devices", "lda_device_count", "active_devices_count",
                "categories_present", "devices_with_placement",
                "devices_with_removal", "source_file", "source_rule_id",
                "warnings", "notes",
            }
            self.assertTrue(required.issubset(set(result.keys())))
        finally:
            os.unlink(path)

    def test_determinism(self):
        path = _write_temp(FORMAT_A_BASIC)
        try:
            r1 = extract_lda_events({}, _make_days_with_source(path))
            r2 = extract_lda_events({}, _make_days_with_source(path))
            # Compare serialized to ensure determinism
            self.assertEqual(
                json.dumps(r1, sort_keys=True),
                json.dumps(r2, sort_keys=True),
            )
        finally:
            os.unlink(path)


class TestFormatA(unittest.TestCase):
    """Tests for Format A (Summary LDA) parsing."""

    def setUp(self):
        self.path = _write_temp(FORMAT_A_BASIC)

    def tearDown(self):
        os.unlink(self.path)

    def test_device_count(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(result["lda_device_count"], 2)

    def test_source_rule_id(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(result["source_rule_id"], "lda_events_raw_file")

    def test_piv_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        devs = result["devices"]
        piv = [d for d in devs if d["category"] == "PIV"]
        self.assertEqual(len(piv), 1)
        self.assertEqual(piv[0]["placed_ts"], "01/01/26 1754")
        self.assertEqual(piv[0]["removed_ts"], "01/07/26 1011")
        self.assertEqual(piv[0]["duration_text"], "5 days")

    def test_nerve_catheter_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        devs = result["devices"]
        nc = [d for d in devs if d["category"] == "Peripheral Nerve Catheter"]
        self.assertEqual(len(nc), 1)
        self.assertEqual(nc[0]["placed_ts"], "01/02/26 1234")
        self.assertEqual(nc[0]["removed_ts"], "01/21/26 1413")

    def test_categories_present(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        cats = result["categories_present"]
        self.assertIn("PIV", cats)
        self.assertIn("Peripheral Nerve Catheter", cats)

    def test_devices_with_placement_and_removal(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(len(result["devices_with_placement"]), 2)
        self.assertEqual(len(result["devices_with_removal"]), 2)

    def test_active_devices_count_zero_when_all_removed(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(result["active_devices_count"], 0)

    def test_evidence_has_raw_line_id(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        for dev in result["devices"]:
            self.assertTrue(len(dev["evidence"]) > 0)
            for e in dev["evidence"]:
                self.assertIn("raw_line_id", e)
                self.assertTrue(len(e["raw_line_id"]) == 64)  # SHA-256 hex

    def test_source_format_summary(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        for dev in result["devices"]:
            self.assertEqual(dev["source_format"], "summary")


class TestFormatAWithAssessments(unittest.TestCase):
    """Tests for Format A with assessment rows."""

    def setUp(self):
        self.path = _write_temp(FORMAT_A_WITH_ASSESSMENTS)

    def tearDown(self):
        os.unlink(self.path)

    def test_device_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(result["lda_device_count"], 1)

    def test_urethral_catheter_fields(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        dev = result["devices"][0]
        self.assertEqual(dev["category"], "Urethral Catheter")
        self.assertEqual(dev["placed_ts"], "01/01/26 1330")
        self.assertEqual(dev["removed_ts"], "01/31/26 1130")
        self.assertEqual(dev["duration_text"], "29 days")

    def test_assessment_rows_captured(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        dev = result["devices"][0]
        self.assertTrue(len(dev["event_rows"]) >= 2)
        # First assessment at 01/05 1536
        ts_list = [r["ts_raw"] for r in dev["event_rows"]]
        self.assertIn("01/05 1536", ts_list)
        self.assertIn("01/04 2123", ts_list)

    def test_assessment_fields_present(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        dev = result["devices"][0]
        # The assessment at 01/05 1536 should have Output (ml) field
        for row in dev["event_rows"]:
            if row["ts_raw"] == "01/05 1536":
                self.assertIn("Output (ml)", row["fields"])
                break


class TestFormatB(unittest.TestCase):
    """Tests for Format B (Event-log Active LDA) parsing."""

    def setUp(self):
        self.path = _write_temp(FORMAT_B_BASIC)

    def tearDown(self):
        os.unlink(self.path)

    def test_device_count(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(result["lda_device_count"], 4)

    def test_picc_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        picc = [d for d in result["devices"] if d["category"] == "PICC"]
        self.assertEqual(len(picc), 1)
        self.assertEqual(picc[0]["placed_ts"], "01/22/26 1120")
        self.assertIsNone(picc[0]["removed_ts"])

    def test_feeding_tube_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        ft = [d for d in result["devices"] if d["category"] == "Feeding Tube"]
        self.assertEqual(len(ft), 1)
        self.assertIn("01/15/26", ft[0]["placed_ts"])

    def test_urethral_catheter_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        uc = [d for d in result["devices"] if d["category"] == "Urethral Catheter"]
        self.assertEqual(len(uc), 1)
        self.assertIn("01/16/26", uc[0]["placed_ts"])

    def test_trach_extracted(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        trach = [d for d in result["devices"] if d["category"] == "Surgical Airway/Trach"]
        self.assertEqual(len(trach), 1)
        self.assertIn("01/23/26", trach[0]["placed_ts"])

    def test_source_format_event_log(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        for dev in result["devices"]:
            self.assertEqual(dev["source_format"], "event_log")

    def test_active_devices_count(self):
        # All 4 devices have placement but no removal in event-log format
        result = extract_lda_events({}, _make_days_with_source(self.path))
        self.assertEqual(result["active_devices_count"], 4)

    def test_evidence_has_raw_line_id(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        for dev in result["devices"]:
            self.assertTrue(len(dev["evidence"]) > 0)
            for e in dev["evidence"]:
                self.assertIn("raw_line_id", e)

    def test_site_dash_normalized(self):
        result = extract_lda_events({}, _make_days_with_source(self.path))
        picc = [d for d in result["devices"] if d["category"] == "PICC"]
        # "—" should be normalized to None
        self.assertIsNone(picc[0]["site"])


class TestRealData(unittest.TestCase):
    """Tests against real patient data files (skipped if not present)."""

    def _patient_path(self, name: str) -> str:
        base = Path(__file__).resolve().parent.parent / "data_raw"
        for fname in os.listdir(base):
            if fname.replace(" ", "_").replace(".txt", "") == name.replace(" ", "_"):
                return str(base / fname)
            if name.replace("_", " ") in fname:
                return str(base / fname)
        return ""

    def _features_path(self, slug: str) -> str:
        base = Path(__file__).resolve().parent.parent / "outputs" / "features" / slug
        p = base / "patient_features_v1.json"
        return str(p) if p.is_file() else ""

    def test_roscella_weatherly(self):
        path = self._patient_path("Roscella_Weatherly")
        if not path:
            self.skipTest("Roscella_Weatherly raw data not found")
        result = extract_lda_events({}, _make_days_with_source(path))
        self.assertGreater(result["lda_device_count"], 0)
        self.assertEqual(result["source_rule_id"], "lda_events_raw_file")
        # Roscella has a PIV with placement and removal
        piv = [d for d in result["devices"] if d["category"] == "PIV"]
        self.assertTrue(len(piv) > 0)
        self.assertIsNotNone(piv[0]["placed_ts"])
        self.assertIsNotNone(piv[0]["removed_ts"])

    def test_lee_woodard(self):
        path = self._patient_path("Lee_Woodard")
        if not path:
            self.skipTest("Lee_Woodard raw data not found")
        result = extract_lda_events({}, _make_days_with_source(path))
        self.assertGreater(result["lda_device_count"], 0)
        # Lee has a Urethral Catheter with assessments
        uc = [d for d in result["devices"] if d["category"] == "Urethral Catheter"]
        self.assertTrue(len(uc) > 0)

    def test_ronald_bittner(self):
        path = self._patient_path("Ronald_Bittner")
        if not path:
            self.skipTest("Ronald_Bittner raw data not found")
        result = extract_lda_events({}, _make_days_with_source(path))
        self.assertGreater(result["lda_device_count"], 0)
        # Bittner should have PICC, Urethral Catheter, Surgical Airway, Feeding Tube
        cats = result["categories_present"]
        self.assertIn("PICC", cats)

    def test_anna_dennis_no_lda(self):
        path = self._patient_path("Anna_Dennis")
        if not path:
            self.skipTest("Anna_Dennis raw data not found")
        result = extract_lda_events({}, _make_days_with_source(path))
        self.assertEqual(result["lda_device_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_lda_section")

    def test_determinism_real(self):
        path = self._patient_path("Roscella_Weatherly")
        if not path:
            self.skipTest("Roscella_Weatherly raw data not found")
        r1 = extract_lda_events({}, _make_days_with_source(path))
        r2 = extract_lda_events({}, _make_days_with_source(path))
        self.assertEqual(
            json.dumps(r1, sort_keys=True),
            json.dumps(r2, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
