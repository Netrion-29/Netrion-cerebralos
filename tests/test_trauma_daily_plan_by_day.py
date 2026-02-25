#!/usr/bin/env python3
"""
Tests for trauma_daily_plan_by_day_v1 extractor and v5 integration.
"""

import unittest
from cerebralos.features.trauma_daily_plan_by_day_v1 import (
    extract_trauma_daily_plan_by_day,
    _detect_note_type,
    _extract_author,
    _extract_impression,
    _extract_plan,
    _is_radiology_read,
    _make_raw_line_id,
)


# ── Sample note texts ──────────────────────────────────────────────

SAMPLE_TRAUMA_PROGRESS_NOTE = """Signed

Trauma Progress Note
Allison Kimmel, PA-C


HPI: Ronald Bittner is a 72 yo male with a PMH significant for PE, DM, and obesity.

CC: No acute complaints

SUBJECTIVE:
Resting in bed
Stable overnight

PE:
General: 72 year old obese male in no acute distress
Vitals: Blood pressure 132/64, pulse 99, SpO2 92%.

Radiographs: No results found.

Labs:
Recent Labs
WBC 12.6
HGB 13.8

Prophylaxis:
Antibiotics: no
GI prophylaxis:  yes
DVT prophylaxis: Mechanical yes, pharmacologic yes

 Impression: 72 y.o. yo male s/p fall backwards while loading hay bales with
            - Unstable T8 distraction fracture
            - Right sided rib fractures 5-7, 9-10
            - Acute hypoxic respiratory failure requiring O2 therapy
            - PMH: PE, DM, and obesity

Plan:
-  ICU
- NSGY consult.  Awaiting brace, supposed to come in today
            - Strict T&L precautions, logroll
            - Bedrest
            - Activity per NSGY
- Hospitalist consult for geriatric protocol
- PCCM consulted for increased O2 requirement
- Multimodal pain control
            - ES block
- Lovenox for DVT ppx
- PT/OT evaluation when appropriate
- SW to follow for dispo needs


Allison Kimmel, PA-C

I have seen and examined patient on the above stated date.

Roberto C Iglesias, MD


Revision HistoryToggle Section Visibility
"""

SAMPLE_TERTIARY_SURVEY_NOTE = """Signed


Trauma Tertiary Survey Note
Abraham J Kiesel, PA-C


HPI: 92 yo female with PMH of diabetes presents as transfer from St. Vincent.

SUBJECTIVE:
Awaiting kypho.  Denies numbness tingling.

PE:
General: nad
Vitals: Blood pressure 149/73, pulse 82, SpO2 95%.

Radiographs: No results found.

Labs:
Recent Labs
WBC 5.9
HGB 10.6

Impression:  92 yo female s/p fall 12/20 with
            - T11 SP fracture
            - acute T12 compression fracture

Plan:
IR consult for kyphoplasty
Hospitalist for geriatric trauma protocol
Pain control
IVF
NPO
Pulm Hygiene, incentive spirometry
PT/OT when appropriate
SW/CM for dispo needs


Abraham J Kiesel, PA-C

I have seen and examined patient on the above stated date.

Roberto C Iglesias, MD


Revision History
"""

SAMPLE_RADIOLOGY_READ = """Signed

Narrative & Impression
INDICATION: Trauma evaluation
COMPARISON: None
TECHNIQUE: CT of the chest with IV contrast

FINDINGS:
No acute cardiopulmonary abnormality.

IMPRESSION: Normal CT chest.
"""

SAMPLE_HOSPITALIST_NOTE = """Signed

Deaconess Care Group Hospital Progress Note
John Smith, MD

Assessment and Plan:
1. Fall with rib fractures
   - Continue pain management
   - PT/OT to continue
2. Hypertension
   - Continue current meds
"""

SAMPLE_NOTE_NO_PLAN = """Signed

Trauma Progress Note
Test Provider, NP

HPI: Patient doing well today.

SUBJECTIVE:
No complaints

PE:
General: nad

Impression: Stable patient
"""


# ═══════════════════════════════════════════════════════════════════
# Extractor Unit Tests
# ═══════════════════════════════════════════════════════════════════

class TestDetectNoteType(unittest.TestCase):
    def test_trauma_progress_note(self):
        self.assertEqual(_detect_note_type(SAMPLE_TRAUMA_PROGRESS_NOTE), "Trauma Progress Note")

    def test_tertiary_survey(self):
        self.assertEqual(_detect_note_type(SAMPLE_TERTIARY_SURVEY_NOTE), "Trauma Tertiary Survey Note")

    def test_radiology_not_qualifying(self):
        self.assertIsNone(_detect_note_type(SAMPLE_RADIOLOGY_READ))

    def test_hospitalist_not_qualifying(self):
        self.assertIsNone(_detect_note_type(SAMPLE_HOSPITALIST_NOTE))

    def test_empty_text(self):
        self.assertIsNone(_detect_note_type(""))


class TestExtractAuthor(unittest.TestCase):
    def test_pa_c(self):
        self.assertEqual(_extract_author(SAMPLE_TRAUMA_PROGRESS_NOTE), "Allison Kimmel, PA-C")

    def test_pa_c_tertiary(self):
        self.assertEqual(_extract_author(SAMPLE_TERTIARY_SURVEY_NOTE), "Abraham J Kiesel, PA-C")

    def test_empty_text(self):
        self.assertEqual(_extract_author(""), "DATA NOT AVAILABLE")


class TestExtractImpression(unittest.TestCase):
    def test_impression_extracted(self):
        lines = _extract_impression(SAMPLE_TRAUMA_PROGRESS_NOTE)
        self.assertGreater(len(lines), 0)
        # Should contain the fracture diagnosis
        combined = " ".join(lines)
        self.assertIn("Unstable T8 distraction fracture", combined)

    def test_impression_bounded_by_plan(self):
        lines = _extract_impression(SAMPLE_TRAUMA_PROGRESS_NOTE)
        combined = " ".join(lines)
        # Should NOT contain plan items
        self.assertNotIn("NSGY consult", combined)
        self.assertNotIn("ICU", combined)

    def test_tertiary_impression(self):
        lines = _extract_impression(SAMPLE_TERTIARY_SURVEY_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("T11 SP fracture", combined)


class TestExtractPlan(unittest.TestCase):
    def test_plan_extracted(self):
        lines = _extract_plan(SAMPLE_TRAUMA_PROGRESS_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("NSGY consult", combined)
        self.assertIn("ICU", combined)

    def test_plan_terminates_at_attestation(self):
        lines = _extract_plan(SAMPLE_TRAUMA_PROGRESS_NOTE)
        combined = " ".join(lines)
        # Should NOT contain attestation text
        self.assertNotIn("I have seen and examined", combined)
        self.assertNotIn("Roberto C Iglesias", combined)
        self.assertNotIn("Revision History", combined)

    def test_tertiary_plan(self):
        lines = _extract_plan(SAMPLE_TERTIARY_SURVEY_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("kyphoplasty", combined)
        self.assertIn("Pain control", combined)

    def test_no_plan_section(self):
        lines = _extract_plan(SAMPLE_NOTE_NO_PLAN)
        self.assertEqual(len(lines), 0)


class TestIsRadiologyRead(unittest.TestCase):
    def test_radiology_detected(self):
        self.assertTrue(_is_radiology_read(SAMPLE_RADIOLOGY_READ))

    def test_progress_note_not_radiology(self):
        self.assertFalse(_is_radiology_read(SAMPLE_TRAUMA_PROGRESS_NOTE))


class TestRawLineId(unittest.TestCase):
    def test_deterministic(self):
        id1 = _make_raw_line_id("61", "2026-01-03T06:56:00", "plan text")
        id2 = _make_raw_line_id("61", "2026-01-03T06:56:00", "plan text")
        self.assertEqual(id1, id2)
        self.assertEqual(len(id1), 16)

    def test_different_inputs(self):
        id1 = _make_raw_line_id("61", "2026-01-03T06:56:00", "plan A")
        id2 = _make_raw_line_id("62", "2026-01-03T06:56:00", "plan A")
        self.assertNotEqual(id1, id2)


# ═══════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════

def _make_days_data(items_by_day):
    """Build minimal patient_days_v1 structure for testing."""
    days = {}
    for day_iso, items in items_by_day.items():
        days[day_iso] = {"items": items}
    return {"days": days, "meta": {}}


def _make_physician_note_item(text, dt="2026-01-03T06:56:00", source_id="61"):
    """Build a minimal timeline item."""
    return {
        "type": "PHYSICIAN_NOTE",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


class TestExtractTraumaDailyPlanByDay(unittest.TestCase):
    def test_single_note(self):
        items = [_make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE)]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["source_rule_id"], "trauma_daily_plan_from_progress_notes")
        self.assertEqual(result["total_notes"], 1)
        self.assertEqual(result["total_days"], 1)
        self.assertIn("2026-01-03", result["days"])

        note = result["days"]["2026-01-03"]["notes"][0]
        self.assertEqual(note["note_type"], "Trauma Progress Note")
        self.assertEqual(note["author"], "Allison Kimmel, PA-C")
        self.assertGreater(len(note["plan_lines"]), 0)
        self.assertGreater(len(note["impression_lines"]), 0)
        self.assertEqual(len(note["raw_line_id"]), 16)

    def test_tertiary_survey_note(self):
        items = [_make_physician_note_item(SAMPLE_TERTIARY_SURVEY_NOTE)]
        days_data = _make_days_data({"2025-12-31": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2025-12-31"]["notes"][0]
        self.assertEqual(note["note_type"], "Trauma Tertiary Survey Note")

    def test_multiple_days(self):
        items1 = [_make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE, dt="2026-01-03T06:56:00")]
        items2 = [_make_physician_note_item(SAMPLE_TERTIARY_SURVEY_NOTE, dt="2026-01-04T10:10:00", source_id="62")]
        days_data = _make_days_data({"2026-01-03": items1, "2026-01-04": items2})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 2)
        self.assertEqual(result["total_days"], 2)
        self.assertIn("2026-01-03", result["days"])
        self.assertIn("2026-01-04", result["days"])
        self.assertEqual(len(result["qualifying_note_types_found"]), 2)

    def test_radiology_skipped(self):
        items = [
            _make_physician_note_item(SAMPLE_RADIOLOGY_READ),
            _make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE, source_id="62"),
        ]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        self.assertEqual(result["days"]["2026-01-03"]["notes"][0]["note_type"], "Trauma Progress Note")

    def test_hospitalist_skipped(self):
        items = [_make_physician_note_item(SAMPLE_HOSPITALIST_NOTE)]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertEqual(result["source_rule_id"], "no_qualifying_notes")

    def test_no_qualifying_notes(self):
        items = [{"type": "LAB", "dt": "2026-01-03T06:00:00", "payload": {"text": "WBC 12.6"}}]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["source_rule_id"], "no_qualifying_notes")
        self.assertEqual(result["total_notes"], 0)
        self.assertEqual(result["total_days"], 0)
        self.assertEqual(result["days"], {})
        self.assertGreater(len(result["notes"]), 0)  # Explanation note

    def test_empty_days(self):
        days_data = {"days": {}, "meta": {}}
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["source_rule_id"], "no_qualifying_notes")
        self.assertEqual(result["total_notes"], 0)

    def test_undated_items_skipped(self):
        items = [_make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE)]
        days_data = _make_days_data({"__UNDATED__": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertEqual(result["source_rule_id"], "no_qualifying_notes")

    def test_note_without_plan_emits_warning(self):
        items = [_make_physician_note_item(SAMPLE_NOTE_NO_PLAN)]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertGreater(len(result["warnings"]), 0)
        self.assertIn("no extractable Plan", result["warnings"][0])

    def test_deterministic_output(self):
        items = [_make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE)]
        days_data = _make_days_data({"2026-01-03": items})
        r1 = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        r2 = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(r1, r2)

    def test_non_physician_items_skipped(self):
        items = [
            {"type": "CONSULT_NOTE", "dt": "2026-01-03T07:00:00", "source_id": "99",
             "payload": {"text": SAMPLE_TRAUMA_PROGRESS_NOTE}},
        ]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        # CONSULT_NOTE should not be matched, only PHYSICIAN_NOTE
        self.assertEqual(result["total_notes"], 0)


# ═══════════════════════════════════════════════════════════════════
# v5 Renderer Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestV5TraumaDailyPlanRendering(unittest.TestCase):
    """Test that v5 renderer surfaces trauma daily plan in per-day blocks."""

    def _make_features_data(self, trauma_plan_data=None):
        """Build minimal features_data for v5 renderer."""
        features = {}
        if trauma_plan_data is not None:
            features["trauma_daily_plan_by_day_v1"] = trauma_plan_data
        return {
            "patient_id": "Test_Patient",
            "build": {"version": "v1"},
            "days": {"2026-01-03": {}},
            "evidence_gaps": {"gap_count": 0, "max_gap_days": 0, "gaps": []},
            "features": features,
            "warnings": [],
            "warnings_summary": {},
        }

    def test_trauma_plan_renders_when_present(self):
        from cerebralos.reporting.render_trauma_daily_notes_v5 import render_v5

        trauma_plan = {
            "days": {
                "2026-01-03": {
                    "notes": [{
                        "note_type": "Trauma Progress Note",
                        "author": "Test Provider, NP",
                        "dt": "2026-01-03T06:56:00",
                        "source_id": "61",
                        "impression_lines": ["72 yo male s/p fall"],
                        "plan_lines": ["-  ICU", "- NSGY consult"],
                        "impression_line_count": 1,
                        "plan_line_count": 2,
                        "raw_line_id": "abc123def456gh78",
                    }],
                },
            },
            "total_notes": 1,
            "total_days": 1,
            "qualifying_note_types_found": ["Trauma Progress Note"],
            "source_rule_id": "trauma_daily_plan_from_progress_notes",
            "warnings": [],
            "notes": [],
        }
        data = self._make_features_data(trauma_plan)
        result = render_v5(data)

        self.assertIn("Trauma Daily Plan:", result)
        self.assertIn("[Trauma Progress Note]", result)
        self.assertIn("Test Provider, NP", result)
        self.assertIn("ICU", result)
        self.assertIn("NSGY consult", result)

    def test_no_plan_renders_nothing(self):
        from cerebralos.reporting.render_trauma_daily_notes_v5 import render_v5

        trauma_plan = {
            "days": {},
            "total_notes": 0,
            "total_days": 0,
            "qualifying_note_types_found": [],
            "source_rule_id": "no_qualifying_notes",
            "warnings": [],
            "notes": [],
        }
        data = self._make_features_data(trauma_plan)
        result = render_v5(data)

        self.assertNotIn("Trauma Daily Plan:", result)

    def test_plan_only_on_correct_day(self):
        from cerebralos.reporting.render_trauma_daily_notes_v5 import render_v5

        trauma_plan = {
            "days": {
                "2026-01-04": {
                    "notes": [{
                        "note_type": "Trauma Progress Note",
                        "author": "Test Provider, NP",
                        "dt": "2026-01-04T07:00:00",
                        "source_id": "62",
                        "impression_lines": [],
                        "plan_lines": ["- Wean vent"],
                        "impression_line_count": 0,
                        "plan_line_count": 1,
                        "raw_line_id": "aaaa1111bbbb2222",
                    }],
                },
            },
            "total_notes": 1,
            "total_days": 1,
            "qualifying_note_types_found": ["Trauma Progress Note"],
            "source_rule_id": "trauma_daily_plan_from_progress_notes",
            "warnings": [],
            "notes": [],
        }
        data = self._make_features_data(trauma_plan)
        # Day 2026-01-03 is in feature_days but no plan for it
        data["days"]["2026-01-04"] = {}
        result = render_v5(data)

        # Plan should appear under 2026-01-04 day header
        lines = result.split("\n")
        day04_found = False
        plan_found = False
        for ln in lines:
            if "2026-01-04" in ln and "=====" in ln:
                day04_found = True
            if day04_found and "Trauma Daily Plan:" in ln:
                plan_found = True
                break
        self.assertTrue(plan_found, "Plan should appear under 2026-01-04")

    def test_missing_feature_graceful(self):
        from cerebralos.reporting.render_trauma_daily_notes_v5 import render_v5

        data = self._make_features_data()  # No trauma_plan_by_day feature
        result = render_v5(data)
        # Should not crash, no "Trauma Daily Plan:" section
        self.assertNotIn("Trauma Daily Plan:", result)

    def test_plan_renders_after_device_counts(self):
        from cerebralos.reporting.render_trauma_daily_notes_v5 import render_v5

        trauma_plan = {
            "days": {
                "2026-01-03": {
                    "notes": [{
                        "note_type": "Trauma Progress Note",
                        "author": "Test Provider, NP",
                        "dt": "2026-01-03T06:56:00",
                        "source_id": "61",
                        "impression_lines": [],
                        "plan_lines": ["- Test plan"],
                        "impression_line_count": 0,
                        "plan_line_count": 1,
                        "raw_line_id": "test123456789012",
                    }],
                },
            },
            "total_notes": 1,
            "total_days": 1,
            "qualifying_note_types_found": ["Trauma Progress Note"],
            "source_rule_id": "trauma_daily_plan_from_progress_notes",
            "warnings": [],
            "notes": [],
        }
        data = self._make_features_data(trauma_plan)
        result = render_v5(data)

        # Device Day Counts should appear before Trauma Daily Plan
        device_pos = result.index("Device Day Counts:")
        plan_pos = result.index("Trauma Daily Plan:")
        self.assertLess(device_pos, plan_pos)


if __name__ == "__main__":
    unittest.main()
