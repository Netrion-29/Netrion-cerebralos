#!/usr/bin/env python3
"""
Tests for ADT Transfer Timeline v1 extractor.

Covers:
  - Basic ADT table parsing from header lines
  - Basic ADT table parsing from timeline item text
  - Timestamp normalisation (MM/DD/YY HHMM → ISO)
  - Event type whitelist (unknown types dropped)
  - Summary derivation (counts, timestamps, units, LOS)
  - Fail-closed: no ADT table → empty result
  - raw_line_id traceability on all events and evidence
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cerebralos.features.adt_transfer_timeline_v1 import (
    _normalise_adt_timestamp,
    _extract_adt_from_lines,
    _build_summary,
    extract_adt_transfer_timeline,
)


# ── Sample ADT table lines (tab-delimited, from Michael_Dougan) ──

SAMPLE_HEADER_LINES = [
    "Michael E Dougan",
    "67 year old male",
    "10/7/1958",
    "",
    "",
    "ADT Events",
    "",
    "\tUnit\tRoom\tBed\tService\tEvent",
    "12/29/25 0722\tEMERGENCY DEPT MC\t1857\t16\tEmergency\tAdmission",
    "12/29/25 1023\tEMERGENCY DEPT MC\t1857\t16\tTrauma\tPatient Update",
    "12/29/25 1518\tEMERGENCY DEPT MC\t1857\t16\tTrauma\tTransfer Out",
    "12/29/25 1518\tEMERGENCY DEPT MC\tMCTRANSITION\tNONE\tTrauma\tTransfer In",
    "12/29/25 1537\tEMERGENCY DEPT MC\tMCTRANSITION\tNONE\tTrauma\tTransfer Out",
    "12/29/25 1537\tORTHO NEURO TR CRE CTR\t4512\t4512-01\tTrauma\tTransfer In",
    "01/07/26 1754\tORTHO NEURO TR CRE CTR\t4507\t4507-01\tTrauma\tDischarge",
    "",
    "",
]


class TestTimestampNormalisation(unittest.TestCase):
    """Test MM/DD/YY HHMM → ISO datetime conversion."""

    def test_standard_format(self):
        result = _normalise_adt_timestamp("12/29/25 0722")
        self.assertEqual(result, "2025-12-29 07:22:00")

    def test_year_rollover(self):
        result = _normalise_adt_timestamp("01/07/26 1754")
        self.assertEqual(result, "2026-01-07 17:54:00")

    def test_four_digit_year(self):
        result = _normalise_adt_timestamp("12/29/2025 0722")
        self.assertEqual(result, "2025-12-29 07:22:00")

    def test_invalid_returns_none(self):
        self.assertIsNone(_normalise_adt_timestamp("bad data"))
        self.assertIsNone(_normalise_adt_timestamp(""))
        self.assertIsNone(_normalise_adt_timestamp("12/29/25"))

    def test_old_year_pivot(self):
        # 80+ → 1900s
        result = _normalise_adt_timestamp("01/01/95 0000")
        self.assertEqual(result, "1995-01-01 00:00:00")


class TestExtractFromLines(unittest.TestCase):
    """Test core line-by-line ADT table parsing."""

    def test_basic_extraction(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        self.assertEqual(len(events), 7)
        # First event: Admission
        self.assertEqual(events[0]["event_type"], "Admission")
        self.assertEqual(events[0]["unit"], "EMERGENCY DEPT MC")
        self.assertEqual(events[0]["timestamp_iso"], "2025-12-29 07:22:00")
        # Last event: Discharge
        self.assertEqual(events[-1]["event_type"], "Discharge")
        self.assertEqual(events[-1]["unit"], "ORTHO NEURO TR CRE CTR")

    def test_raw_line_id_present(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES, raw_line_id_prefix="header")
        for ev in events:
            self.assertIn("raw_line_id", ev)
            self.assertTrue(ev["raw_line_id"].startswith("header:"))

    def test_all_fields_populated(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        required_keys = {
            "timestamp_raw", "timestamp_iso", "unit", "room",
            "bed", "service", "event_type", "raw_line_id",
        }
        for ev in events:
            self.assertEqual(set(ev.keys()), required_keys)

    def test_no_adt_section(self):
        lines = [
            "Some random text",
            "No ADT here",
            "",
        ]
        events = _extract_adt_from_lines(lines)
        self.assertEqual(events, [])

    def test_unknown_event_type_dropped(self):
        lines = [
            "ADT Events",
            "",
            "\tUnit\tRoom\tBed\tService\tEvent",
            "12/29/25 0722\tED\t100\t1\tEmergency\tAdmission",
            "12/29/25 0800\tED\t100\t1\tEmergency\tUnknownEventType",
            "12/29/25 0900\tED\t100\t1\tEmergency\tDischarge",
            "",
        ]
        events = _extract_adt_from_lines(lines)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "Admission")
        self.assertEqual(events[1]["event_type"], "Discharge")


class TestBuildSummary(unittest.TestCase):
    """Test summary derivation from parsed events."""

    def test_empty_events(self):
        summary = _build_summary([])
        self.assertEqual(summary["adt_event_count"], 0)
        self.assertIsNone(summary["first_admission_ts"])
        self.assertEqual(summary["transfer_count"], 0)
        self.assertIsNone(summary["discharge_ts"])
        self.assertEqual(summary["units_visited"], [])
        self.assertIsNone(summary["los_hours"])

    def test_full_summary(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        self.assertEqual(summary["adt_event_count"], 7)
        self.assertEqual(summary["first_admission_ts"], "2025-12-29 07:22:00")
        self.assertEqual(summary["discharge_ts"], "2026-01-07 17:54:00")
        self.assertIsNotNone(summary["los_hours"])
        self.assertGreater(summary["los_hours"], 0)
        # Units visited (unique, first-seen order)
        self.assertIn("EMERGENCY DEPT MC", summary["units_visited"])
        self.assertIn("ORTHO NEURO TR CRE CTR", summary["units_visited"])

    def test_transfer_count(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        # 2 Transfer Out + 2 Transfer In → max(2,2) = 2
        self.assertEqual(summary["transfer_count"], 2)

    def test_los_calculation(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        # 12/29/25 07:22 → 01/07/26 17:54 ≈ 226.5 hours
        self.assertAlmostEqual(summary["los_hours"], 226.5, delta=1.0)


class TestExtractPublicAPI(unittest.TestCase):
    """Test the public extract_adt_transfer_timeline function."""

    def test_from_header_lines(self):
        days_data = {
            "meta": {"raw_header_lines": SAMPLE_HEADER_LINES},
            "days": {},
        }
        result = extract_adt_transfer_timeline({"days": {}}, days_data)
        self.assertEqual(len(result["events"]), 7)
        self.assertEqual(result["summary"]["adt_event_count"], 7)
        self.assertTrue(any("source=raw_header_lines" in n for n in result["notes"]))

    def test_from_timeline_items(self):
        adt_text = "\n".join([
            "Some preamble text",
            "ADT Events",
            "",
            "\tUnit\tRoom\tBed\tService\tEvent",
            "12/24/25 1419\tEMERGENCY DEPT MC\t1857\t16\tEmergency\tAdmission",
            "12/26/25 1517\tORTHO NEURO TR CRE CTR\t4640\t4640-01\tTrauma\tDischarge",
            "",
            "Some text after",
        ])
        days_data = {
            "meta": {},
            "days": {
                "2025-12-24": {
                    "items": [
                        {
                            "type": "PHYSICIAN_NOTE",
                            "payload": {"text": adt_text},
                        }
                    ]
                }
            },
        }
        result = extract_adt_transfer_timeline({"days": {}}, days_data)
        self.assertEqual(len(result["events"]), 2)
        self.assertTrue(any("source=timeline_item" in n for n in result["notes"]))

    def test_no_adt_data(self):
        days_data = {
            "meta": {},
            "days": {
                "2025-01-01": {
                    "items": [
                        {
                            "type": "PHYSICIAN_NOTE",
                            "payload": {"text": "No ADT here"},
                        }
                    ]
                }
            },
        }
        result = extract_adt_transfer_timeline({"days": {}}, days_data)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["summary"]["adt_event_count"], 0)
        self.assertIn("no_adt_table_found", result["notes"])

    def test_evidence_has_raw_line_id(self):
        days_data = {
            "meta": {"raw_header_lines": SAMPLE_HEADER_LINES},
            "days": {},
        }
        result = extract_adt_transfer_timeline({"days": {}}, days_data)
        for ev in result["evidence"]:
            self.assertIn("raw_line_id", ev)

    def test_header_wins_over_items(self):
        """Header source takes priority; items are not checked."""
        adt_text_item = "\n".join([
            "ADT Events",
            "",
            "\tUnit\tRoom\tBed\tService\tEvent",
            "01/01/25 0800\tICU\t200\t2\tTrauma\tAdmission",
            "",
        ])
        days_data = {
            "meta": {"raw_header_lines": SAMPLE_HEADER_LINES},
            "days": {
                "2025-01-01": {
                    "items": [{"type": "NOTE", "payload": {"text": adt_text_item}}]
                }
            },
        }
        result = extract_adt_transfer_timeline({"days": {}}, days_data)
        # Should use header (7 events), not item (1 event)
        self.assertEqual(len(result["events"]), 7)
        self.assertTrue(any("source=raw_header_lines" in n for n in result["notes"]))


if __name__ == "__main__":
    unittest.main()
