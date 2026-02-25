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
    _extract_adt_headerless,
    _dedup_events,
    _validate_chronology,
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

# ── Headerless ADT lines (from Ronald Bittner) ──────────────────

SAMPLE_HEADERLESS_LINES = [
    "Ronald E Bittner",
    "72 year old male",
    "12/19/1953",
    "",
    "12/31/25 2038\tEMERGENCY DEPT GW\t11040\t21\tEmergency\tAdmission",
    "01/01/26 0138\tEMERGENCY DEPT GW\t11040\t21\tEmergency\tTransfer Out",
    "01/01/26 0138\tEMERGENCY DEPT MC\t1858\t09\tEmergency\tTransfer In",
    "01/01/26 0144\tEMERGENCY DEPT MC\t1858\t09\tTrauma\tPatient Update",
    "01/01/26 0209\tEMERGENCY DEPT MC\t1858\t09\tTrauma\tTransfer Out",
    "01/01/26 0209\tEMERGENCY DEPT MC\tMCTRANSITION\tNONE\tTrauma\tTransfer In",
    "01/01/26 0227\tEMERGENCY DEPT MC\tMCTRANSITION\tNONE\tTrauma\tTransfer Out",
    "01/01/26 0227\tSRG TRAUMA CV ICU 7480\t4814\t4814-01\tTrauma\tTransfer In",
    "01/27/26 2056\tSRG TRAUMA CV ICU 7480\t4814\t4814-01\tTrauma\tDischarge",
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


# ── v2 tests: headerless ADT fallback ─────────────────────────────

class TestHeaderlessADT(unittest.TestCase):
    """Test headerless ADT row extraction (Ronald Bittner pattern)."""

    def test_headerless_extracts_all_rows(self):
        events = _extract_adt_headerless(SAMPLE_HEADERLESS_LINES)
        self.assertEqual(len(events), 9)

    def test_headerless_first_admission(self):
        events = _extract_adt_headerless(SAMPLE_HEADERLESS_LINES)
        self.assertEqual(events[0]["event_type"], "Admission")
        self.assertEqual(events[0]["unit"], "EMERGENCY DEPT GW")
        self.assertEqual(events[0]["timestamp_iso"], "2025-12-31 20:38:00")

    def test_headerless_last_discharge(self):
        events = _extract_adt_headerless(SAMPLE_HEADERLESS_LINES)
        self.assertEqual(events[-1]["event_type"], "Discharge")
        self.assertEqual(events[-1]["unit"], "SRG TRAUMA CV ICU 7480")

    def test_headerless_raw_line_id(self):
        events = _extract_adt_headerless(
            SAMPLE_HEADERLESS_LINES, raw_line_id_prefix="header_headerless",
        )
        for ev in events:
            self.assertTrue(ev["raw_line_id"].startswith("header_headerless:"))

    def test_headerless_via_public_api(self):
        days_data = {
            "meta": {"raw_header_lines": SAMPLE_HEADERLESS_LINES},
            "days": {},
        }
        result = extract_adt_transfer_timeline({"days": {}}, days_data)
        self.assertEqual(len(result["events"]), 9)
        self.assertTrue(
            any("source=raw_header_lines_headerless" in n for n in result["notes"])
        )

    def test_header_preferred_over_headerless(self):
        """Standard header extraction wins over headerless fallback."""
        events_std = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        events_hl = _extract_adt_headerless(SAMPLE_HEADER_LINES)
        # Both should find events, but standard should be used first
        self.assertEqual(len(events_std), 7)
        self.assertGreaterEqual(len(events_hl), 7)


# ── v2 tests: dedup ───────────────────────────────────────────────

class TestDedup(unittest.TestCase):
    """Test defensive deduplication."""

    def test_no_dupes_passthrough(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        warnings = []
        deduped = _dedup_events(events, warnings)
        self.assertEqual(len(deduped), len(events))
        self.assertEqual(warnings, [])

    def test_exact_dupe_removed(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        # Duplicate the first event
        events_duped = events + [events[0].copy()]
        warnings = []
        deduped = _dedup_events(events_duped, warnings)
        self.assertEqual(len(deduped), len(events))
        self.assertEqual(len(warnings), 1)
        self.assertIn("duplicate_adt_row_dropped", warnings[0])

    def test_same_timestamp_different_event_kept(self):
        """Transfer Out + Transfer In at same time are NOT dupes."""
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        warnings = []
        deduped = _dedup_events(events, warnings)
        # Lines 10-11 have 12/29/25 1518 Transfer Out + Transfer In
        ts_1518 = [e for e in deduped if e["timestamp_raw"] == "12/29/25 1518"]
        self.assertEqual(len(ts_1518), 2)
        types = {e["event_type"] for e in ts_1518}
        self.assertEqual(types, {"Transfer Out", "Transfer In"})


# ── v2 tests: chronology validation ───────────────────────────────

class TestChronologyValidation(unittest.TestCase):
    """Test chronology warning generation."""

    def test_ordered_no_warnings(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        warnings = []
        _validate_chronology(events, warnings)
        self.assertEqual(warnings, [])

    def test_out_of_order_warns(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        # Swap first two to create chronology break
        swapped = [events[1], events[0]] + events[2:]
        warnings = []
        _validate_chronology(swapped, warnings)
        self.assertGreaterEqual(len(warnings), 1)
        self.assertIn("chronology_break", warnings[0])


# ── v2 tests: enriched summary ────────────────────────────────────

class TestEnrichedSummary(unittest.TestCase):
    """Test enriched summary fields added in v2."""

    def test_empty_events_has_all_keys(self):
        summary = _build_summary([])
        for key in [
            "los_days", "event_type_counts", "services_seen",
            "rooms_visited", "patient_update_count",
            "last_unit", "last_room", "last_bed",
        ]:
            self.assertIn(key, summary)

    def test_event_type_counts(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        etc = summary["event_type_counts"]
        self.assertEqual(etc["Admission"], 1)
        self.assertEqual(etc["Discharge"], 1)
        self.assertEqual(etc["Transfer Out"], 2)
        self.assertEqual(etc["Transfer In"], 2)
        self.assertEqual(etc["Patient Update"], 1)

    def test_services_seen(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        self.assertIn("Trauma", summary["services_seen"])
        self.assertIn("Emergency", summary["services_seen"])
        # Sorted
        self.assertEqual(summary["services_seen"], sorted(summary["services_seen"]))

    def test_rooms_visited_excludes_mctransition(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        self.assertNotIn("MCTRANSITION", summary["rooms_visited"])
        self.assertNotIn("NONE", summary["rooms_visited"])
        self.assertIn("1857", summary["rooms_visited"])

    def test_patient_update_count(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        self.assertEqual(summary["patient_update_count"], 1)

    def test_last_location(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        self.assertEqual(summary["last_unit"], "ORTHO NEURO TR CRE CTR")
        self.assertEqual(summary["last_room"], "4507")
        self.assertEqual(summary["last_bed"], "4507-01")

    def test_los_days(self):
        events = _extract_adt_from_lines(SAMPLE_HEADER_LINES)
        summary = _build_summary(events)
        self.assertIsNotNone(summary["los_days"])
        # los_hours ≈ 226.5 → los_days ≈ 9.4
        self.assertAlmostEqual(summary["los_days"], 9.4, delta=0.5)

    def test_headerless_summary(self):
        """Headerless extraction produces correct enriched summary."""
        events = _extract_adt_headerless(SAMPLE_HEADERLESS_LINES)
        summary = _build_summary(events)
        self.assertEqual(summary["adt_event_count"], 9)
        self.assertEqual(summary["first_admission_ts"], "2025-12-31 20:38:00")
        self.assertEqual(summary["discharge_ts"], "2026-01-27 20:56:00")
        self.assertEqual(summary["last_unit"], "SRG TRAUMA CV ICU 7480")
        self.assertIn("Emergency", summary["services_seen"])
        self.assertIn("Trauma", summary["services_seen"])
        self.assertEqual(summary["patient_update_count"], 1)
        # 3 units: EMERGENCY DEPT GW, EMERGENCY DEPT MC, SRG TRAUMA CV ICU 7480
        self.assertEqual(len(summary["units_visited"]), 3)


if __name__ == "__main__":
    unittest.main()
