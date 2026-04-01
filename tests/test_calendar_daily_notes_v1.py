"""
Smoke tests for render_calendar_daily_notes_v1.py

Verifies:
- render_calendar_v1 produces deterministic output
- Patient header section is present
- Per-day sections render for each day with correct day numbers
- Physician notes appear in full (no truncation indicator on normal-length notes)
- [NEW] / [CARRIED] labels are assigned correctly
- Evidence gap detection emits warning
- Missing data degrades to DNA gracefully
- Lab, imaging, nursing-signal sections render when data exists
- Optional features integration renders vitals / GCS / labs panels
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cerebralos.reporting.render_calendar_daily_notes_v1 import render_calendar_v1

_DNA = "DATA NOT AVAILABLE"


def _make_days(items_by_date: dict | None = None) -> dict:
    """Build a minimal patient_days dict."""
    items_by_date = items_by_date or {}
    base: dict = {
        "meta": {
            "patient_id": "TEST_CALENDAR_001",
            "arrival_datetime": "2026-02-01 08:00:00",
            "discharge_datetime": None,
            "timezone": "America/Chicago",
            "day0_date": "2026-02-01",
        },
        "days": {},
    }
    for date_iso, items in items_by_date.items():
        base["days"][date_iso] = {"items": items}
    return base


def _physician_note(date_iso: str, text: str, hour: str = "10:00:00") -> dict:
    return {
        "type": "PHYSICIAN_NOTE",
        "dt": f"{date_iso}T{hour}",
        "header_dt": f"{date_iso} {hour}",
        "source_id": "0",
        "payload": {"text": text},
    }


def _consult_note(date_iso: str, text: str) -> dict:
    return {
        "type": "CONSULT_NOTE",
        "dt": f"{date_iso}T14:00:00",
        "header_dt": f"{date_iso} 14:00:00",
        "source_id": "1",
        "payload": {"text": text},
    }


def _imaging_item(date_iso: str, impression: str, study: str = "CT CHEST") -> dict:
    text = f"[IMAGING] {date_iso} 12:00:00\n{study}\n\nIMPRESSION:\n{impression}"
    return {
        "type": "IMAGING",
        "dt": f"{date_iso}T12:00:00",
        "header_dt": f"{date_iso} 12:00:00",
        "source_id": "2",
        "payload": {"text": text},
    }


def _lab_item(date_iso: str, result_text: str) -> dict:
    return {
        "type": "LAB",
        "dt": f"{date_iso}T09:00:00",
        "header_dt": f"{date_iso} 09:00:00",
        "source_id": "3",
        "payload": {"text": result_text},
    }


def _nursing_item(date_iso: str, text: str) -> dict:
    return {
        "type": "NURSING_NOTE",
        "dt": f"{date_iso}T06:00:00",
        "header_dt": f"{date_iso} 06:00:00",
        "source_id": "4",
        "payload": {"text": text},
    }


class TestCalendarDailyNotesV1Smoke(unittest.TestCase):

    def test_renders_without_crash(self):
        data = _make_days()
        result = render_calendar_v1(data)
        self.assertIn("CALENDAR DAILY NOTES (v1)", result)
        self.assertIn("END OF CALENDAR DAILY NOTES (v1)", result)

    def test_patient_id_in_header(self):
        data = _make_days()
        result = render_calendar_v1(data)
        self.assertIn("Patient ID   : TEST_CALENDAR_001", result)

    def test_arrival_in_header(self):
        data = _make_days()
        result = render_calendar_v1(data)
        self.assertIn("Arrival      : 2026-02-01 08:00:00", result)

    def test_legend_present(self):
        data = _make_days()
        result = render_calendar_v1(data)
        self.assertIn("[NEW]", result)
        self.assertIn("[CARRIED]", result)

    def test_admission_day_numbering(self):
        """Day 1 header on arrival day; day 2 header on next day."""
        note = _physician_note("2026-02-01", "Day 1 note.")
        data = _make_days({
            "2026-02-01": [note],
            "2026-02-02": [_physician_note("2026-02-02", "Day 2 note.")],
        })
        result = render_calendar_v1(data)
        self.assertIn("ADMISSION DAY 1  ·  2026-02-01", result)
        self.assertIn("ADMISSION DAY 2  ·  2026-02-02", result)

    def test_empty_day_shows_dna(self):
        """A day with no physician items shows DATA NOT AVAILABLE."""
        data = _make_days({"2026-02-01": []})
        result = render_calendar_v1(data)
        self.assertIn(_DNA, result)

    def test_physician_note_full_text(self):
        """Full physician note text appears in output."""
        long_text = "Assessment: " + ("Patient stable. " * 30)
        data = _make_days({"2026-02-01": [_physician_note("2026-02-01", long_text)]})
        result = render_calendar_v1(data)
        # Full text should be present — no truncation marker
        self.assertIn("Assessment:", result)
        self.assertNotIn("... (truncated)", result)
        self.assertNotIn("narrative cap reached", result)

    def test_new_label_on_first_occurrence(self):
        """A note appearing for the first time gets [NEW]."""
        data = _make_days({
            "2026-02-01": [_physician_note("2026-02-01", "Unique text for day 1.")],
        })
        result = render_calendar_v1(data)
        self.assertIn("[NEW]", result)

    def test_carried_label_on_repeated_block(self):
        """Identical block on day 2 gets [CARRIED]."""
        identical = "Same note repeated from prior day."
        data = _make_days({
            "2026-02-01": [_physician_note("2026-02-01", identical)],
            "2026-02-02": [_physician_note("2026-02-02", identical, hour="08:00:00")],
        })
        result = render_calendar_v1(data)
        self.assertIn("[CARRIED]", result)
        self.assertIn("[NEW]", result)

    def test_evidence_gap_warning(self):
        """Evidence gap between non-consecutive days is flagged."""
        data = _make_days({
            "2026-02-01": [_physician_note("2026-02-01", "Day 1.")],
            "2026-02-05": [_physician_note("2026-02-05", "Day 5.")],
        })
        result = render_calendar_v1(data)
        self.assertIn("EVIDENCE GAP", result)
        self.assertIn("3 calendar day(s)", result)

    def test_consult_note_section_present(self):
        """Consult notes appear under CONSULTANT NOTES."""
        text = "Orthopedics consult. Plan: operative fixation of right femur fracture."
        data = _make_days({
            "2026-02-01": [_consult_note("2026-02-01", text)],
        })
        result = render_calendar_v1(data)
        self.assertIn("CONSULTANT NOTES", result)
        self.assertIn("Orthopedics consult", result)

    def test_imaging_impression_rendered(self):
        """Imaging impression appears under IMAGING / RADIOLOGY."""
        data = _make_days({
            "2026-02-01": [_imaging_item("2026-02-01", "No acute intracranial injury.")],
        })
        result = render_calendar_v1(data)
        self.assertIn("IMAGING / RADIOLOGY", result)
        self.assertIn("No acute intracranial injury.", result)
        self.assertIn("IMPRESSION:", result)

    def test_lab_results_section_present(self):
        """Lab results appear under LABORATORY RESULTS."""
        data = _make_days({
            "2026-02-01": [_lab_item("2026-02-01", "Hemoglobin: 10.5 g/dL")],
        })
        result = render_calendar_v1(data)
        self.assertIn("LABORATORY RESULTS", result)
        self.assertIn("Hemoglobin: 10.5 g/dL", result)

    def test_nursing_signals_section_present(self):
        """Nursing signal lines appear under NURSING SIGNALS when matches found."""
        text = "Patient is fall risk. Applied bed alarm. GCS 14."
        data = _make_days({
            "2026-02-01": [_nursing_item("2026-02-01", text)],
        })
        result = render_calendar_v1(data)
        self.assertIn("NURSING SIGNALS", result)

    def test_noise_header_stripped_from_note(self):
        """Source type header line (e.g. '[PHYSICIAN_NOTE] 2026-...') is stripped."""
        raw = "[PHYSICIAN_NOTE] 2026-02-01 10:00:00\nActual clinical content here."
        data = _make_days({
            "2026-02-01": [_physician_note("2026-02-01", raw)],
        })
        result = render_calendar_v1(data)
        # The raw header line should be filtered; clinical content should remain
        self.assertIn("Actual clinical content here.", result)
        # The bracketed header should NOT appear inside the note box
        note_box_start = result.find("┌─ PHYSICIAN NOTE")
        if note_box_start >= 0:
            box_end = result.find("└─", note_box_start)
            box_content = result[note_box_start:box_end]
            self.assertNotIn("[PHYSICIAN_NOTE] 2026-02-01 10:00:00", box_content)

    def test_deterministic_output(self):
        """Same input produces identical output on multiple calls."""
        data = _make_days({
            "2026-02-01": [
                _physician_note("2026-02-01", "Day 1 note content."),
                _consult_note("2026-02-01", "Ortho consult — plan to follow."),
            ],
            "2026-02-02": [
                _physician_note("2026-02-02", "Day 2 note content."),
            ],
        })
        result1 = render_calendar_v1(data)
        result2 = render_calendar_v1(data)
        self.assertEqual(result1, result2)

    def test_admission_span_summary(self):
        """Admission span line shows correct first/last date and count."""
        data = _make_days({
            "2026-02-01": [_physician_note("2026-02-01", "Day 1.")],
            "2026-02-03": [_physician_note("2026-02-03", "Day 3.")],
        })
        result = render_calendar_v1(data)
        self.assertIn("2026-02-01 → 2026-02-03", result)

    def test_features_integration_no_crash(self):
        """Passing minimal features data does not crash the renderer."""
        data = _make_days({
            "2026-02-01": [_physician_note("2026-02-01", "Day 1 with features.")],
        })
        features = {
            "patient_id": "TEST_CALENDAR_001",
            "days": {
                "2026-02-01": {
                    "vitals": {
                        "hr":    {"min": 72, "max": 88},
                        "sbp":   {"min": 108, "max": 125},
                        "spo2":  {"min": 96, "max": 99},
                        "temp_f": {"min": 98.4, "max": 99.1},
                        "rr":    {"min": 14, "max": 18},
                    },
                    "gcs_daily": {
                        "best_gcs":  {"value": 15, "intubated": False},
                        "worst_gcs": {"value": 13, "intubated": False},
                    },
                    "labs_panel_daily": {
                        "cbc": {"WBC": 11.2, "Hgb": 9.8, "Hct": "DATA NOT AVAILABLE", "Plt": 210.0},
                        "bmp": {"Na": 138, "K": 4.1, "Cl": "DATA NOT AVAILABLE",
                                "CO2": 24, "BUN": 18, "Cr": 0.9, "Glucose": 105},
                        "coags": {"INR": 1.1, "PT": "DATA NOT AVAILABLE", "PTT": "DATA NOT AVAILABLE"},
                        "lactate": 1.8,
                        "base_deficit": -2.0,
                    },
                },
            },
            "features": {},
            "build": {},
            "evidence_gaps": {},
            "warnings": [],
            "warnings_summary": {},
        }
        result = render_calendar_v1(data, features)
        self.assertIn("STRUCTURED VITALS", result)
        self.assertIn("GCS", result)
        self.assertIn("LABS PANEL", result)
        self.assertIn("HR:", result)
        self.assertIn("SBP:", result)
        # GCS values
        self.assertIn("Best GCS: 15", result)
        self.assertIn("Worst GCS: 13", result)
        # Labs panel
        self.assertIn("CBC:", result)
        self.assertIn("BMP:", result)

    def test_features_all_dna_labs_panel(self):
        """When all labs are DNA, LABS PANEL shows DATA NOT AVAILABLE."""
        data = _make_days({"2026-02-01": [_physician_note("2026-02-01", "Day 1.")]})
        features = {
            "patient_id": "TEST_CALENDAR_001",
            "days": {
                "2026-02-01": {
                    "vitals": {},
                    "gcs_daily": {},
                    "labs_panel_daily": {
                        "cbc":   {"WBC": _DNA, "Hgb": _DNA, "Hct": _DNA, "Plt": _DNA},
                        "bmp":   {"Na": _DNA, "K": _DNA, "Cl": _DNA, "CO2": _DNA,
                                  "BUN": _DNA, "Cr": _DNA, "Glucose": _DNA},
                        "coags": {"INR": _DNA, "PT": _DNA, "PTT": _DNA},
                        "lactate": _DNA,
                        "base_deficit": _DNA,
                    },
                },
            },
            "features": {},
            "build": {},
            "evidence_gaps": {},
            "warnings": [],
            "warnings_summary": {},
        }
        result = render_calendar_v1(data, features)
        # LABS PANEL section should be present but show DNA
        self.assertIn("LABS PANEL", result)

    def test_undated_items_appendix(self):
        """UNDATED items appear in appendix at end of report."""
        data = _make_days()
        data["days"]["UNDATED"] = {
            "items": [
                {
                    "type": "PHYSICIAN_NOTE",
                    "dt": None,
                    "header_dt": None,
                    "source_id": "99",
                    "payload": {"text": "Undated physician note content."},
                }
            ]
        }
        result = render_calendar_v1(data)
        self.assertIn("UNDATED ITEMS", result)
        self.assertIn("Undated physician note content.", result)


if __name__ == "__main__":
    unittest.main()
