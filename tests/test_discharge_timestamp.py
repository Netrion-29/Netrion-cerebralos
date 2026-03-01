#!/usr/bin/env python3
"""Tests for discharge timestamp extraction from ADT Events table in parse_patient_txt.

Covers:
  1. bracket [DISCHARGE] present → discharge_datetime is None (handled by feature layer)
  2. DoS format, ADT Events has Discharge row → discharge_datetime extracted
  3. DoS format, no ADT Discharge row → discharge_datetime is None
  4. Transfer/Disposition rows do not masquerade as Discharge
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from cerebralos.ingest.parse_patient_txt import _extract_header_dos


class TestDischargeFromADTEvents(unittest.TestCase):
    """discharge_datetime extraction from _extract_header_dos."""

    # ── Fixture: DoS header with ADT Events including Discharge ──

    DOS_HEADER_WITH_DISCHARGE = [
        "Ronald E Bittner",
        "72 year old male",
        "12/19/1953",
        "",
        "12/31/25 2038\tEMERGENCY DEPT GW\t11040\t21\tEmergency\tAdmission",
        "01/01/26 0138\tEMERGENCY DEPT GW\t11040\t21\tEmergency\tTransfer Out",
        "01/01/26 0138\tEMERGENCY DEPT MC\t1858\t09\tEmergency\tTransfer In",
        "01/01/26 0227\tSRG TRAUMA CV ICU 7480\t4814\t4814-01\tTrauma\tTransfer In",
        "01/27/26 2056\tSRG TRAUMA CV ICU 7480\t4814\t4814-01\tTrauma\tDischarge",
        "",
    ]

    # ── Fixture: DoS header with ADT Events, NO Discharge row ──

    DOS_HEADER_NO_DISCHARGE = [
        "Test Patient",
        "55 year old female",
        "03/15/1970",
        "",
        "12/31/25 0800\tEMERGENCY DEPT MC\t1001\t01\tEmergency\tAdmission",
        "12/31/25 1200\tEMERGENCY DEPT MC\t1001\t01\tTrauma\tPatient Update",
        "01/01/26 0600\tSRG TRAUMA CV ICU 7480\t4001\t4001-01\tTrauma\tTransfer In",
        "",
    ]

    # ── Fixture: Transfer Out/In rows only (no Admission, no Discharge) ──

    DOS_HEADER_TRANSFERS_ONLY = [
        "Transfer Only Patient",
        "40 year old male",
        "06/01/1985",
        "",
        "01/02/26 0800\tSRG TRAUMA CV ICU 7480\t4001\t4001-01\tTrauma\tTransfer Out",
        "01/02/26 0800\tORTHO NEURO TR CRE CTR\t4512\t4512-01\tTrauma\tTransfer In",
        "",
    ]

    # ── Fixture: Discharge Disposition text in non-ADT context ──

    DOS_HEADER_DISPOSITION_TEXT = [
        "Disposition Patient",
        "60 year old female",
        "01/01/1966",
        "",
        "12/29/25 0900\tEMERGENCY DEPT MC\t1001\t01\tEmergency\tAdmission",
        "",
        "Discharge Disposition: Rehab-Inpt",
        "Long Term Acute Care Facility Discharged To: Select Specialty",
        "Discharge Plan: LTAC",
        "",
    ]

    # ── Test 1: DoS with ADT Discharge row → extracted ──

    def test_dos_adt_discharge_extracted(self):
        header = _extract_header_dos(self.DOS_HEADER_WITH_DISCHARGE)
        self.assertEqual(header.get("DISCHARGE_DATETIME"), "2026-01-27 20:56:00")
        # ARRIVAL_TIME should also be present
        self.assertEqual(header.get("ARRIVAL_TIME"), "2025-12-31 20:38:00")

    # ── Test 2: DoS without ADT Discharge row → None ──

    def test_dos_no_adt_discharge_returns_none(self):
        header = _extract_header_dos(self.DOS_HEADER_NO_DISCHARGE)
        self.assertIsNone(header.get("DISCHARGE_DATETIME"))
        # ARRIVAL_TIME must still work
        self.assertEqual(header.get("ARRIVAL_TIME"), "2025-12-31 08:00:00")

    # ── Test 3: Transfer rows do not masquerade as Discharge ──

    def test_transfers_do_not_masquerade_as_discharge(self):
        header = _extract_header_dos(self.DOS_HEADER_TRANSFERS_ONLY)
        self.assertIsNone(header.get("DISCHARGE_DATETIME"))

    # ── Test 4: Disposition text does not masquerade as Discharge ──

    def test_disposition_text_ignored(self):
        header = _extract_header_dos(self.DOS_HEADER_DISPOSITION_TEXT)
        self.assertIsNone(header.get("DISCHARGE_DATETIME"))
        # ARRIVAL_TIME should be extracted
        self.assertEqual(header.get("ARRIVAL_TIME"), "2025-12-29 09:00:00")

    # ── Test 5: Multiple Discharge rows → last wins ──

    def test_multiple_discharge_rows_last_wins(self):
        lines = [
            "Multi Discharge Patient",
            "50 year old male",
            "01/01/1975",
            "",
            "01/01/26 0800\tEMERGENCY DEPT MC\t1001\t01\tEmergency\tAdmission",
            "01/05/26 1400\tSRG UNIT\t2001\t2001-01\tTrauma\tDischarge",
            "01/05/26 1400\tSRG UNIT\t2001\t2001-01\tTrauma\tAdmission",
            "01/10/26 1100\tSRG UNIT\t2001\t2001-01\tTrauma\tDischarge",
            "",
        ]
        header = _extract_header_dos(lines)
        # Last Discharge row wins
        self.assertEqual(header.get("DISCHARGE_DATETIME"), "2026-01-10 11:00:00")


class TestBracketFormatDischarge(unittest.TestCase):
    """Bracket-format patients have no ADT Events → no discharge_datetime in meta.

    Their discharge comes from [DISCHARGE] bracket items in the feature layer.
    """

    def test_bracket_format_has_no_discharge_datetime(self):
        """_extract_header_dos is never called for bracket format.

        This test validates that bracket-format evidence meta has no
        DISCHARGE_DATETIME — we test via the full build path.
        """
        from cerebralos.ingest.parse_patient_txt import _build_evidence_object
        bracket_path = REPO_ROOT / "data_raw" / "Larry_Corne.txt"
        if not bracket_path.is_file():
            self.skipTest("Larry_Corne.txt not available")
        slug = "Larry_Corne"
        evidence = _build_evidence_object(bracket_path, slug)
        # Bracket format uses _extract_header(), not _extract_header_dos()
        # so DISCHARGE_DATETIME won't be in the header
        self.assertIsNone(evidence["meta"].get("discharge_datetime"))


if __name__ == "__main__":
    unittest.main()
