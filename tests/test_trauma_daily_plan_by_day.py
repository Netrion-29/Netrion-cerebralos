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


# ── Sample notes for expanded header patterns ───────────────────────

SAMPLE_TRAUMA_TERTIARY_NOTE = """Signed

Trauma Tertiary Note
Austin Mark Buettner, PA-C


HPI: George Kraus is a 87 yo male with a PMH significant for CKD.

SUBJECTIVE:
No acute complaints

PE:
General: Elderly male in no acute distress
Vitals: Blood pressure 138/72, pulse 76, SpO2 95%.

Radiographs: No results found.

Labs:
Recent Labs
WBC 8.2
HGB 10.1

Prophylaxis:
Antibiotics: no
GI prophylaxis: yes
DVT prophylaxis: Mechanical yes, pharmacologic yes

Impression: 87 y.o. male s/p fall with
            - T12 compression fracture
            - Rib fractures 9-11 on left

Plan:
- Floor status
- IR consult for kyphoplasty
- Pain control
- PT/OT evaluation
- Lovenox for DVT ppx
- SW for dispo needs

Austin Mark Buettner, PA-C

I have seen and examined patient on the above stated date.

Kali Kuhlenschmidt, MD

Revision HistoryToggle Section Visibility
"""

SAMPLE_TRAUMA_TERTIARY_PROGRESS_NOTE = """Signed


Trauma Tertiary Progress Note
Jessica J Anderson, NP


HPI: 55 y.o. female with a PMH significant for migraines.

SUBJECTIVE:
No new issues
Awaiting US results

PE:
General: Well-developed female in no acute distress.
Vitals: Blood pressure 106/64, pulse 80, SpO2 99%.

Labs:
Recent Labs
WBC 5.0
HGB 12.5

Prophylaxis:
Antibiotics: no
GI prophylaxis: no
DVT prophylaxis: Mechanical yes, pharmacologic no

 Impression: 55 y.o. female s/p syncope with fall with
            - Small left frontal SAH
            - Possible nasal bone fracture

Plan:
- ENT consulted. Non-op. Follow up 1 week.
- Hospitalist following. Syncope workup.
- General diet
- Lovenox for dvt ppx
- PT/OT eval - cleared for home

Jessica J Anderson, NP

I have seen and examined patient on the above stated date.

Roberto C Iglesias, MD

MyChart now allows progress notes to be visible to patients.
"""

SAMPLE_TRAUMA_OVERNIGHT_PROGRESS_NOTE = """Signed

Trauma Overnight Progress Note:

Called by the RN who states that patient's pupils are unequal.
I went to evaluate patient who is unresponsive.
Dr. Field is my attending this evening.

Sarah M Meehan, NP

Cosigned by:\tField, Matthew S, MD at 12/22/25 0527
Revision HistoryToggle Section Visibility
"""

SAMPLE_ESA_DAILY_PROGRESS_NOTE = """Signed

Daily Progress Note

Evansville Surgical Associates
 12/25/2025

Chief Complaint:  When will i get out here

Subjective:  No adverse events overnight

Labs:
Recent Labs
WBC 5.7
HGB 7.9

Objective
General Patient not in any distress

Assessment:
Active Hospital Problems
Diagnosis
MVC (motor vehicle collision), initial encounter

Plan:  Admit to  45/46
- Telemetry
- General diet
- Pain control as needed
- Ambulate as tolerated
- Hold lovenox due to hematoma
Echocardiogram this a.m.

Electronically signed by Derek M West, NP on 12/25/2025 at 6:20 AM.

Kevin W McConnell, MD

Revision HistoryToggle Section Visibility
"""

SAMPLE_ESA_DAILY_PROGRESS_NOTE_NON_ESA = """Signed

Daily Progress Note

Deaconess Care Group
 12/25/2025

Chief Complaint: Follow up

Subjective: No complaints

Assessment:
Stable

Plan:
- Continue current management

John Smith, MD
"""

SAMPLE_ESA_BRIEF_PROGRESS_NOTE = """Signed

ESA Brief Progress Note
Attempted to see patient on morning rounds.  Patient has already in dialysis suite.  We will attempt to see patient later after returning from dialysis.

Austin Mark Buettner, PA-C
Cosigned by:\tMcConnell, Kevin W, MD at 12/24/25 1341
Revision HistoryToggle Section Visibility
"""

SAMPLE_ESA_BRIEF_UPDATE = """Signed

ESA Brief Update

Spoke with GI re: PEG tube, will discuss with the family.

Marisa Biehle, PA-C

Cosigned by:\tIglesias, Roberto C, MD at 12/29/25 1200
Revision HistoryToggle Section Visibility
"""

SAMPLE_ESA_QUICK_UPDATE = """Signed

ESA Quick Update Note

Anesthesia contacted for ESBs at 0900. Ok for transfer to floor today. Diet as tolerated. PT and OT evals.

Lindsey Jamerson, PA-C
Revision HistoryToggle Section Visibility
"""

SAMPLE_ESA_TRAUMA_BRIEF_NOTE = """Signed

ESA TRAUMA BRIEF NOTE

Spoke with hospitalist service, Dr. Haroon.  Patient is medical cardiac arrest, which then resulted an MVC.  He has no traumatic injuries.

Hospitalist services agreed to assume care.  Trauma Service will sign off, please call with any questions or concerns.

Joshua C Barajas, PA-C

Cosigned by:\tField, Matthew S, MD at 12/18/25 2110
Revision HistoryToggle Section Visibility
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
# Expanded Header Unit Tests
# ═══════════════════════════════════════════════════════════════════

class TestDetectNoteTypeExpanded(unittest.TestCase):
    """Tests for newly-added trauma note header patterns."""

    def test_trauma_tertiary_note(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_TRAUMA_TERTIARY_NOTE),
            "Trauma Tertiary Note",
        )

    def test_trauma_tertiary_progress_note(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_TRAUMA_TERTIARY_PROGRESS_NOTE),
            "Trauma Tertiary Progress Note",
        )

    def test_trauma_overnight_progress_note(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_TRAUMA_OVERNIGHT_PROGRESS_NOTE),
            "Trauma Overnight Progress Note",
        )

    def test_daily_progress_note_esa(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_ESA_DAILY_PROGRESS_NOTE),
            "Daily Progress Note",
        )

    def test_daily_progress_note_non_esa_rejected(self):
        """Daily Progress Note from non-ESA service should NOT qualify."""
        self.assertIsNone(
            _detect_note_type(SAMPLE_ESA_DAILY_PROGRESS_NOTE_NON_ESA),
        )

    def test_esa_brief_progress_note(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_ESA_BRIEF_PROGRESS_NOTE),
            "ESA Brief Progress Note",
        )

    def test_esa_brief_update(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_ESA_BRIEF_UPDATE),
            "ESA Brief Update",
        )

    def test_esa_quick_update_note(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_ESA_QUICK_UPDATE),
            "ESA Quick Update Note",
        )

    def test_esa_trauma_brief_note(self):
        self.assertEqual(
            _detect_note_type(SAMPLE_ESA_TRAUMA_BRIEF_NOTE),
            "ESA TRAUMA BRIEF NOTE",
        )


class TestExtractImpressionExpanded(unittest.TestCase):
    """Tests for impression/assessment extraction from expanded headers."""

    def test_tertiary_note_impression(self):
        lines = _extract_impression(SAMPLE_TRAUMA_TERTIARY_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("T12 compression fracture", combined)

    def test_tertiary_progress_impression(self):
        lines = _extract_impression(SAMPLE_TRAUMA_TERTIARY_PROGRESS_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("Small left frontal SAH", combined)

    def test_esa_daily_assessment_as_impression(self):
        """ESA Daily Progress Note uses Assessment: instead of Impression:."""
        lines = _extract_impression(SAMPLE_ESA_DAILY_PROGRESS_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("MVC", combined)


class TestExtractPlanExpanded(unittest.TestCase):
    """Tests for plan extraction from expanded header patterns."""

    def test_tertiary_note_plan(self):
        lines = _extract_plan(SAMPLE_TRAUMA_TERTIARY_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("kyphoplasty", combined)
        self.assertIn("Floor status", combined)

    def test_tertiary_progress_plan(self):
        lines = _extract_plan(SAMPLE_TRAUMA_TERTIARY_PROGRESS_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("ENT consulted", combined)
        self.assertIn("Lovenox for dvt ppx", combined)

    def test_tertiary_progress_plan_terminates_at_mychar(self):
        lines = _extract_plan(SAMPLE_TRAUMA_TERTIARY_PROGRESS_NOTE)
        combined = " ".join(lines)
        self.assertNotIn("MyChart", combined)

    def test_overnight_no_plan(self):
        """Trauma Overnight Progress Note is narrative; no Plan: section."""
        lines = _extract_plan(SAMPLE_TRAUMA_OVERNIGHT_PROGRESS_NOTE)
        self.assertEqual(len(lines), 0)

    def test_esa_daily_plan(self):
        lines = _extract_plan(SAMPLE_ESA_DAILY_PROGRESS_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("Telemetry", combined)
        self.assertIn("Pain control", combined)

    def test_esa_brief_no_plan(self):
        """ESA Brief Progress Note has no Plan: section."""
        lines = _extract_plan(SAMPLE_ESA_BRIEF_PROGRESS_NOTE)
        self.assertEqual(len(lines), 0)

    def test_esa_brief_update_no_plan(self):
        lines = _extract_plan(SAMPLE_ESA_BRIEF_UPDATE)
        self.assertEqual(len(lines), 0)

    def test_esa_quick_update_no_plan(self):
        lines = _extract_plan(SAMPLE_ESA_QUICK_UPDATE)
        self.assertEqual(len(lines), 0)

    def test_esa_trauma_brief_no_plan(self):
        lines = _extract_plan(SAMPLE_ESA_TRAUMA_BRIEF_NOTE)
        self.assertEqual(len(lines), 0)


class TestIntegrationExpandedHeaders(unittest.TestCase):
    """Integration tests for expanded header extraction."""

    def test_tertiary_note_full_extraction(self):
        items = [_make_physician_note_item(SAMPLE_TRAUMA_TERTIARY_NOTE)]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        self.assertEqual(result["source_rule_id"], "trauma_daily_plan_from_progress_notes")
        note = result["days"]["2026-01-01"]["notes"][0]
        self.assertEqual(note["note_type"], "Trauma Tertiary Note")
        self.assertGreater(len(note["plan_lines"]), 0)
        self.assertGreater(len(note["impression_lines"]), 0)

    def test_tertiary_progress_note_full(self):
        items = [_make_physician_note_item(SAMPLE_TRAUMA_TERTIARY_PROGRESS_NOTE)]
        days_data = _make_days_data({"2026-01-02": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2026-01-02"]["notes"][0]
        self.assertEqual(note["note_type"], "Trauma Tertiary Progress Note")

    def test_esa_daily_progress_note_full(self):
        items = [_make_physician_note_item(SAMPLE_ESA_DAILY_PROGRESS_NOTE)]
        days_data = _make_days_data({"2025-12-25": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2025-12-25"]["notes"][0]
        self.assertEqual(note["note_type"], "Daily Progress Note")
        self.assertGreater(len(note["plan_lines"]), 0)
        # Assessment: should be captured as impression_lines
        self.assertGreater(len(note["impression_lines"]), 0)

    def test_non_esa_daily_skipped(self):
        """Daily Progress Note from non-ESA service should be skipped."""
        items = [_make_physician_note_item(SAMPLE_ESA_DAILY_PROGRESS_NOTE_NON_ESA)]
        days_data = _make_days_data({"2025-12-25": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertEqual(result["source_rule_id"], "no_qualifying_notes")

    def test_esa_brief_emits_warning(self):
        """ESA Brief notes qualify but have no Plan → warning emitted, note skipped."""
        items = [_make_physician_note_item(SAMPLE_ESA_BRIEF_PROGRESS_NOTE)]
        days_data = _make_days_data({"2025-12-23": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertGreater(len(result["warnings"]), 0)
        self.assertIn("no extractable Plan", result["warnings"][0])

    def test_overnight_note_emits_warning(self):
        """Trauma Overnight Progress Note (narrative) has no Plan → warning."""
        items = [_make_physician_note_item(SAMPLE_TRAUMA_OVERNIGHT_PROGRESS_NOTE)]
        days_data = _make_days_data({"2025-12-21": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertGreater(len(result["warnings"]), 0)

    def test_mixed_old_and_new_headers(self):
        """Old and new headers in the same day both get extracted."""
        items = [
            _make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE, source_id="61"),
            _make_physician_note_item(SAMPLE_TRAUMA_TERTIARY_NOTE, source_id="62",
                                      dt="2026-01-03T10:00:00"),
        ]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 2)
        note_types = {n["note_type"] for n in result["days"]["2026-01-03"]["notes"]}
        self.assertIn("Trauma Progress Note", note_types)
        self.assertIn("Trauma Tertiary Note", note_types)


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
