#!/usr/bin/env python3
"""
Tests for trauma_daily_plan_by_day_v1 extractor and v5 integration.
"""

import unittest
from cerebralos.features.trauma_daily_plan_by_day_v1 import (
    extract_trauma_daily_plan_by_day,
    _detect_note_type,
    _classify_general_note_type,
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

    def test_non_esa_daily_captured_as_hospitalist(self):
        """Daily Progress Note from non-ESA Deaconess Care Group is captured."""
        items = [_make_physician_note_item(SAMPLE_ESA_DAILY_PROGRESS_NOTE_NON_ESA)]
        days_data = _make_days_data({"2025-12-25": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2025-12-25"]["notes"][0]
        self.assertEqual(note["note_type"], "Hospital Progress Note")
        self.assertGreater(len(note["plan_lines"]), 0)

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

    def test_hospitalist_captured(self):
        """Hospitalist note with Assessment and Plan captured."""
        items = [_make_physician_note_item(SAMPLE_HOSPITALIST_NOTE)]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2026-01-03"]["notes"][0]
        self.assertEqual(note["note_type"], "Hospital Progress Note")
        self.assertGreater(len(note["plan_lines"]), 0)
        combined = " ".join(note["plan_lines"])
        self.assertIn("rib fracture", combined.lower())

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


# ── Tests for general note classification ──────────────────────────


class TestClassifyGeneralNoteType(unittest.TestCase):
    def test_hospitalist_hospital_progress_note(self):
        text = "Signed\n\nDeaconess Care Group\nHospital Progress Note\n"
        self.assertEqual(_classify_general_note_type(text), "Hospital Progress Note")

    def test_hospitalist_deaconess_care_group_only(self):
        text = "Signed\n\nDeaconess Care Group\nPatient Name: Test\n"
        self.assertEqual(_classify_general_note_type(text), "Hospital Progress Note")

    def test_critical_care(self):
        text = "Signed\n\nDeaconess Pulmonary / Critical Care Group\nSummary\n"
        self.assertEqual(_classify_general_note_type(text), "Critical Care Progress Note")

    def test_critical_care_ampersand(self):
        text = "Signed\n\nDeaconess Pulmonary & Critical Care Group\n"
        self.assertEqual(_classify_general_note_type(text), "Critical Care Progress Note")

    def test_neurology(self):
        text = "Signed\n\nNEUROLOGY INPATIENT CONSULT PROGRESS NOTE\n"
        self.assertEqual(_classify_general_note_type(text), "Neurology Progress Note")

    def test_cardiology_heart_group(self):
        text = "Signed\n\nHeart Group Daily Progress Note\n"
        self.assertEqual(_classify_general_note_type(text), "Cardiology Progress Note")

    def test_electrophysiology(self):
        text = "Signed\n\nElectrophysiology Daily Progress Note\n"
        self.assertEqual(_classify_general_note_type(text), "Electrophysiology Progress Note")

    def test_palliative_care(self):
        text = "Signed\n\nPalliative Care Nurse Practitioner Progress Note\n"
        self.assertEqual(_classify_general_note_type(text), "Palliative Care Progress Note")

    def test_speech_language_pathology(self):
        text = "Signed\n\nSpeech Language Pathology:\nClinical Swallow\n"
        self.assertEqual(_classify_general_note_type(text), "Speech Language Pathology")

    def test_unclassifiable_returns_none(self):
        text = "Signed\n\nPHYSICAL THERAPY\nPatient: Test\n"
        self.assertIsNone(_classify_general_note_type(text))

    def test_infectious_disease(self):
        text = "Signed\n\nInfectious Disease Consult Progress Note\nDr. Smith\n"
        self.assertEqual(_classify_general_note_type(text), "Infectious Disease Progress Note")

    def test_medication_order_returns_none(self):
        text = "[PHYSICIAN_NOTE] 2025-12-17\nDEA #: FV5998919\n"
        self.assertIsNone(_classify_general_note_type(text))

    def test_trauma_header_not_classified_by_general(self):
        """Trauma headers should be handled by _detect_note_type, not general."""
        text = "Signed\n\nTrauma Progress Note\nTest Provider, NP\n"
        self.assertIsNone(_classify_general_note_type(text))


# ── Tests for Assessment/Plan: extraction ──────────────────────────

SAMPLE_HOSPITALIST_AP_SLASH = """Signed

Deaconess Care Group
Hospital Progress Note
Patient Name:  Test Patient

Assessment/Plan:

Unstable T8 fracture as well as right 5th-7th rib fractures
Management per Trauma.  Pain control per Trauma.

Diabetes mellitus type 2
Continue sliding scale insulin.

DVT Prophylaxis:  SCDs

This has been electronically signed.
"""


class TestAssessmentPlanExtraction(unittest.TestCase):
    def test_ap_slash_plan_extracted(self):
        """Assessment/Plan: with slash — plan content extracted."""
        lines = _extract_plan(SAMPLE_HOSPITALIST_AP_SLASH)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("T8 fracture", combined)
        self.assertIn("insulin", combined)

    def test_ap_slash_terminates_at_attestation(self):
        """Plan extraction stops at 'This has been electronically'."""
        lines = _extract_plan(SAMPLE_HOSPITALIST_AP_SLASH)
        combined = " ".join(lines)
        self.assertNotIn("electronically", combined)

    def test_ap_slash_no_impression(self):
        """Assessment/Plan: combined format has no separate impression."""
        lines = _extract_impression(SAMPLE_HOSPITALIST_AP_SLASH)
        self.assertEqual(len(lines), 0)

    def test_ap_and_plan_extracted(self):
        """Assessment and Plan: with 'and' — plan content extracted."""
        lines = _extract_plan(SAMPLE_HOSPITALIST_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("rib fracture", combined.lower())

    def test_ap_integration_full(self):
        """Full integration: hospitalist A/P note captured end-to-end."""
        items = [_make_physician_note_item(SAMPLE_HOSPITALIST_AP_SLASH)]
        days_data = _make_days_data({"2026-01-05": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2026-01-05"]["notes"][0]
        self.assertEqual(note["note_type"], "Hospital Progress Note")
        self.assertGreater(len(note["plan_lines"]), 0)
        self.assertEqual(len(note["impression_lines"]), 0)

    def test_trauma_still_preferred(self):
        """Trauma header matched by _detect_note_type, not general classifier."""
        items = [_make_physician_note_item(SAMPLE_TRAUMA_PROGRESS_NOTE)]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        note = result["days"]["2026-01-03"]["notes"][0]
        self.assertEqual(note["note_type"], "Trauma Progress Note")

    def test_no_plan_general_note_silently_skipped(self):
        """General note without plan markers is silently skipped (no warning)."""
        text = (
            "Signed\n"
            "\n"
            "Deaconess Care Group\n"
            "Hospital Progress Note\n"
            "\n"
            "Subjective: No complaints\n"
        )
        items = [_make_physician_note_item(text)]
        days_data = _make_days_data({"2026-01-05": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertEqual(len(result["warnings"]), 0)


# ═══════════════════════════════════════════════════════════════════
# Specialty Classifier Expansion Tests
# ═══════════════════════════════════════════════════════════════════

# ── Sample specialty notes (real header patterns from chart data) ──

SAMPLE_NEUROSURGERY_NOTE = """\
Signed

Neurosurgery - tSAH s/p falls (Troffkin)

S: Sitting in chair. Speech improving. Worked with therapy. MWFT in place.

O:
Visit Vitals
BP      119/61
Pulse   82
Temp    98.0 °F (36.7 °C) (Oral)
SpO2    95%

Neurological/Musculoskeletal:
A&O x3. Conversant with mild dysarthria. Following commands.
Strength 5/5 all extremities. PERRL.

Radiology:
CT HEAD WO CONTRAST
Result Date: 12/15/2025
IMPRESSION: Stable bilateral tSAH. No midline shift.

A/P: This is a 83 y.o. male admitted after multiple falls. Films reviewed with \
Dr. Troffkin. CT scan of the head does show some traumatic subarachnoid blood \
bilaterally. CTA does not reveal any underlying vascular abnormalities. \
Would not recommend surgery for above findings.
- Ok for transfer out of ICU from NS standpoint
- Q4h neuro checks
- HOB >/=30
- Mechanical DVT ppx. Ok for pharmacologic DVT ppx.
- SBP < 150
- Advance diet/activity
- PT/OT
- F/u prn

Discussed with/ answered all of the patient/family's questions, agreeable to plan

Trevor Troffkin, MD
"""

SAMPLE_NEUROSURGERY_NOTE_NO_PLAN = """\
Signed

Neurosurgery- L5 compression fx (Cannon)

Kyphoplasty now scheduled for 12/15. Continue current recommendations \
with brace and activity as tolerated.

Travis Cannon, MD
"""

SAMPLE_NEPHROLOGY_NOTE = """\
[PHYSICIAN_NOTE] 2025-12-29 07:24:00
Signed

Expand All Collapse All

PROGRESS NOTE
DEACONESS CLINIC NEPHROLOGY

Service date: 7:24 AM 12/29/2025
DEMOGRAPHICS:
Name: Floy Geary
Age: 81 y.o.    DOB: 6/10/1944    Sex: female    MRN: 2164162

SUBJECTIVE and Interval history:
No new complaints. Clinical events noted. Labs reviewed.

OBJECTIVE:
Vitals:
BP      154/62
Pulse   68
Temp    98.1 °F (36.7 °C) (Oral)

Assessment and Plan:

Hyponatremia 123-127-129-132
-renal function intact with baseline Cr 0.8-0.9
-AKI with Cr up to
-UA with proteinuria and hematuria
-Recommend bladder scan
-Electrolytes noted-- bicarbonate 22, K 4.4
-Volume status noted
-No acute indications for RRT
-Renally dose abx, renal diet
-Will continue monitoring

We will continue to follow the patient.
"""

SAMPLE_RENAL_BRIEF_NOTE = """\
[PHYSICIAN_NOTE] 2025-12-25 17:47:00
Signed

Renal brief note - contacted for consult, chart/OSH documents reviewed, \
had sodium 123 at 1038 AM and presented with fall. Repeat Na 125 here. \
Serial sodiums ordered called to nephrology. Full consultation to follow.
"""

SAMPLE_HEME_ONC_NOTE = """\
[PHYSICIAN_NOTE] 2025-12-27 14:04:00
Addendum

DEACONESS HEMATOLOGY/ONCOLOGY
Inpatient follow up note

Patient: Valerie Parker    MRN: 123456

Assessment:
Known CLL, leukocytosis improving.

Plan:
- Continue monitoring WBC trend
- Hold chemo during acute admission
- Hematology to follow daily
- Transfuse for Hgb < 7

John Doe, MD
"""

SAMPLE_PLASTICS_NOTE = """\
Signed

Full consult note to follow

Plastics consulted 1/23 for bilateral nasal bone fracture

CT reviewed, displaced, would benefit from closed reduction

Impression: Displaced bilateral nasal bone fracture

Plan:
- Closed reduction under sedation
- Schedule for tomorrow AM
- Pre-op labs

Jane Smith, MD
"""


class TestClassifyGeneralNoteTypeExpanded(unittest.TestCase):
    """Tests for new specialty classifier patterns."""

    def test_neurosurgery(self):
        text = "Signed\n\nNeurosurgery - tSAH s/p falls (Troffkin)\n\nS: Sitting"
        self.assertEqual(_classify_general_note_type(text), "Neurosurgery Progress Note")

    def test_neurosurgery_no_space_before_dash(self):
        text = "Signed\n\nNeurosurgery- L5 compression fx (Cannon)\n"
        self.assertEqual(_classify_general_note_type(text), "Neurosurgery Progress Note")

    def test_neurosurgery_en_dash(self):
        text = "Signed\n\nNeurosurgery \u2013 ICH with IVH (Troffkin)\n"
        self.assertEqual(_classify_general_note_type(text), "Neurosurgery Progress Note")

    def test_nephrology_deaconess_clinic(self):
        text = "Signed\n\nPROGRESS NOTE\nDEACONESS CLINIC NEPHROLOGY\n"
        self.assertEqual(_classify_general_note_type(text), "Nephrology Progress Note")

    def test_nephrology_standalone(self):
        text = "Signed\n\nNEPHROLOGY CONSULT\n"
        self.assertEqual(_classify_general_note_type(text), "Nephrology Progress Note")

    def test_renal_brief_note(self):
        text = "Signed\n\nRenal brief note - contacted for consult\n"
        self.assertEqual(_classify_general_note_type(text), "Nephrology Progress Note")

    def test_heme_onc(self):
        text = "Signed\n\nDEACONESS HEMATOLOGY/ONCOLOGY\nInpatient follow up note\n"
        self.assertEqual(
            _classify_general_note_type(text), "Hematology/Oncology Progress Note"
        )

    def test_heme_onc_dot_separator(self):
        text = "Signed\n\nHEMATOLOGY.ONCOLOGY\nFollow up\n"
        self.assertEqual(
            _classify_general_note_type(text), "Hematology/Oncology Progress Note"
        )

    def test_plastics(self):
        text = "Signed\n\nPlastics consulted 1/23 for bilateral nasal bone fracture\n"
        self.assertEqual(_classify_general_note_type(text), "Plastics Progress Note")

    def test_plastic_singular(self):
        text = "Signed\n\nPlastic consult for wound closure\n"
        self.assertEqual(_classify_general_note_type(text), "Plastics Progress Note")

    def test_ortho_not_classified(self):
        """Orthopedics does not arrive as PHYSICIAN_NOTE; should not classify."""
        text = "Signed\n\nOrthopedic Surgery Consult\n"
        self.assertIsNone(_classify_general_note_type(text))


class TestAPSlashExtraction(unittest.TestCase):
    """Tests for A/P: (abbreviated Assessment/Plan) section extraction."""

    def test_ap_slash_plan_extracted(self):
        lines = _extract_plan(SAMPLE_NEUROSURGERY_NOTE)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("transfer out of ICU", combined)
        self.assertIn("Q4h neuro checks", combined)

    def test_ap_slash_terminates_at_signature(self):
        lines = _extract_plan(SAMPLE_NEUROSURGERY_NOTE)
        combined = " ".join(lines)
        self.assertNotIn("Trevor Troffkin", combined)

    def test_ap_slash_no_separate_impression(self):
        """A/P: is a combined section; _extract_impression must return empty."""
        lines = _extract_impression(SAMPLE_NEUROSURGERY_NOTE)
        self.assertEqual(lines, [])

    def test_neurosurgery_no_plan_silently_skipped(self):
        """Neurosurgery note without Plan/A-P section is silently skipped."""
        items = [_make_physician_note_item(SAMPLE_NEUROSURGERY_NOTE_NO_PLAN)]
        days_data = _make_days_data({"2025-12-11": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0)
        # Non-trauma notes without plan → no warning (fail-closed, silent)
        self.assertEqual(len(result["warnings"]), 0)


# ═══════════════════════════════════════════════════════════════════
# TRAUMA_HP Source-Container Tests
# ═══════════════════════════════════════════════════════════════════

# ── Sample TRAUMA_HP notes (real-pattern fixtures) ─────────────────

SAMPLE_TRAUMA_HP_SIMPLE = """\
Signed       

Expand All Collapse All

Trauma H & P
Rachel N Bertram, NP
 
 
Alert History: Category 2 alert at 1118.  I arrived in the ED to evaluate the patient at 1200 
 
HPI: 84 yo male with PMH of HLD, HTN and seizures who presented after reportedly being found down in his garage.

PE:
General: Elderly male, C-collar in place
Vitals: Blood pressure 155/82, pulse 74, SpO2 97%.

Radiographs: CT C/T/L spine reviewed.

Labs:
Recent Labs
WBC 5.5
HGB 12.1

 Impression: 84 yo male s/p fall with
            - C2 type 3 dens fracture, nondisplaced
            - L1 compression fracture, chronic vs acute
            - Right parietal scalp laceration

Plan:
- NSGY consult, Ally made aware, bedrest
- Hospitalist consult per geri trauma protocol
- NPO
- IVF
- Pain control as needed
- local wound care
- Home meds resumed
- Lovenox on hold pending NSGY consult
- PT/OT once cleared by NSGY
- SW/CM to see for dispo needs

Rachel N Bertram, NP

I have seen and examined patient on the above stated date.

Roberto C Iglesias, MD

Revision HistoryToggle Section Visibility
"""

SAMPLE_TRAUMA_HP_COMPOSITE = """\
Signed       

Expand All Collapse All

Trauma H & P
Sarah M Meehan, NP
 
 
Alert History: Category II alert at 0143. Patient evaluated in the ED at 0215.
 
HPI: Patient is a 72 yo male with PMH significant for PE, DM, and obesity.

PE:
General: 72 yo obese male, C-collar in place
Vitals: Blood pressure 148/72, pulse 88, SpO2 91%.

Labs:
Recent Labs
WBC 14.2
HGB 14.0

 Impression: 72 yo male s/p fall backwards while loading hay bales with
            - Unstable T8 distraction fracture
            - Right sided rib fractures 5-7, 9-10
            - Acute hypoxic respiratory failure

Plan:
- Will admit to trauma ICU
- NSGY consult
            - Strict T&L precautions, logroll
            - Bedrest
- Hospitalist consult for geriatric protocol
- Pain control
- NPO
- Hold DVT prophylaxis
- Aggressive pulmonary toilet
- PT/OT evaluation when appropriate
- SW to follow for dispo needs

Sarah M Meehan, NP

I have seen and examined patient on the above stated date.

Roberto C Iglesias, MD

[embedded consult note follows]

Neurosurgery Consult
Another Provider, MD

Impression: Same patient evaluated by neurosurgery.

Plan :
 
I reviewed past medical history and records.
Repeat EEG
Continue supportive care per critical care team

Another Provider, MD
"""

SAMPLE_TRAUMA_HP_NO_PLAN = """\
Signed       

Expand All Collapse All

Trauma H & P
Test Provider, NP

Alert History: Category 2 alert at 0900.

HPI: 65 yo female s/p MVC.

PE:
General: Female in mild distress.

Impression: 65 yo female s/p MVC with chest wall contusion.

Test Provider, NP
"""


def _make_trauma_hp_item(text, dt="2026-01-01T02:20:00", source_id="0"):
    """Build a minimal TRAUMA_HP timeline item."""
    return {
        "type": "TRAUMA_HP",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


class TestTraumaHPExtraction(unittest.TestCase):
    """Unit tests for TRAUMA_HP extraction via prefer_first logic."""

    def test_simple_trauma_hp_plan(self):
        """TRAUMA_HP with single Plan: section extracts correctly."""
        lines = _extract_plan(SAMPLE_TRAUMA_HP_SIMPLE, prefer_first=True)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("NSGY consult", combined)
        self.assertIn("Hospitalist consult", combined)
        self.assertIn("Pain control", combined)

    def test_simple_trauma_hp_impression(self):
        lines = _extract_impression(SAMPLE_TRAUMA_HP_SIMPLE, prefer_first=True)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("C2 type 3 dens fracture", combined)

    def test_composite_trauma_hp_uses_first_plan(self):
        """Composite TRAUMA_HP with multiple Plan: sections uses the first."""
        lines = _extract_plan(SAMPLE_TRAUMA_HP_COMPOSITE, prefer_first=True)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        # First Plan content (trauma H&P)
        self.assertIn("Will admit to trauma ICU", combined)
        self.assertIn("NSGY consult", combined)
        # Should NOT contain embedded consult plan
        self.assertNotIn("Repeat EEG", combined)
        self.assertNotIn("reviewed past medical history", combined)

    def test_composite_trauma_hp_impression_correct(self):
        """Composite TRAUMA_HP impression comes from the H&P section."""
        lines = _extract_impression(SAMPLE_TRAUMA_HP_COMPOSITE, prefer_first=True)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("Unstable T8 distraction fracture", combined)
        # Should NOT contain embedded consult impression
        self.assertNotIn("evaluated by neurosurgery", combined)

    def test_trauma_hp_no_plan_returns_empty(self):
        """TRAUMA_HP without Plan: section returns empty list (fail-closed)."""
        lines = _extract_plan(SAMPLE_TRAUMA_HP_NO_PLAN, prefer_first=True)
        self.assertEqual(len(lines), 0)

    def test_trauma_hp_plan_terminates_at_attestation(self):
        """Plan extraction stops at attestation line."""
        lines = _extract_plan(SAMPLE_TRAUMA_HP_SIMPLE, prefer_first=True)
        combined = " ".join(lines)
        self.assertNotIn("I have seen and examined", combined)
        self.assertNotIn("Roberto C Iglesias", combined)

    def test_prefer_first_false_unchanged_for_physician_note(self):
        """Default prefer_first=False still works for PHYSICIAN_NOTE text."""
        lines = _extract_plan(SAMPLE_TRAUMA_PROGRESS_NOTE, prefer_first=False)
        self.assertGreater(len(lines), 0)
        combined = " ".join(lines)
        self.assertIn("NSGY consult", combined)


class TestTraumaHPIntegration(unittest.TestCase):
    """Integration tests for TRAUMA_HP source container."""

    def test_trauma_hp_extracted_end_to_end(self):
        """TRAUMA_HP item is extracted with note_type 'Trauma H&P'."""
        items = [_make_trauma_hp_item(SAMPLE_TRAUMA_HP_SIMPLE)]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        self.assertEqual(result["source_rule_id"], "trauma_daily_plan_from_progress_notes")
        note = result["days"]["2026-01-01"]["notes"][0]
        self.assertEqual(note["note_type"], "Trauma H&P")
        self.assertEqual(note["author"], "Rachel N Bertram, NP")
        self.assertGreater(len(note["plan_lines"]), 0)
        self.assertGreater(len(note["impression_lines"]), 0)
        self.assertEqual(len(note["raw_line_id"]), 16)

    def test_trauma_hp_composite_correct_extraction(self):
        """Composite TRAUMA_HP extracts first Plan, not embedded consult."""
        items = [_make_trauma_hp_item(SAMPLE_TRAUMA_HP_COMPOSITE)]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2026-01-01"]["notes"][0]
        combined = " ".join(note["plan_lines"])
        self.assertIn("Will admit to trauma ICU", combined)
        self.assertNotIn("Repeat EEG", combined)

    def test_trauma_hp_no_plan_emits_warning(self):
        """TRAUMA_HP without Plan: emits warning (it's a trauma note)."""
        items = [_make_trauma_hp_item(SAMPLE_TRAUMA_HP_NO_PLAN)]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 0)
        self.assertGreater(len(result["warnings"]), 0)
        self.assertIn("Trauma H&P", result["warnings"][0])
        self.assertIn("no extractable Plan", result["warnings"][0])

    def test_trauma_hp_empty_text_skipped(self):
        """TRAUMA_HP with empty text is silently skipped."""
        items = [_make_trauma_hp_item("")]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0)

    def test_trauma_hp_and_physician_note_same_day(self):
        """TRAUMA_HP and PHYSICIAN_NOTE on same day both extracted."""
        items = [
            _make_trauma_hp_item(SAMPLE_TRAUMA_HP_SIMPLE, dt="2026-01-01T02:20:00"),
            _make_physician_note_item(
                SAMPLE_TRAUMA_PROGRESS_NOTE, source_id="61",
                dt="2026-01-01T12:00:00",
            ),
        ]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 2)
        note_types = {n["note_type"] for n in result["days"]["2026-01-01"]["notes"]}
        self.assertIn("Trauma H&P", note_types)
        self.assertIn("Trauma Progress Note", note_types)

    def test_trauma_hp_deterministic(self):
        """Same input produces same output (deterministic)."""
        items = [_make_trauma_hp_item(SAMPLE_TRAUMA_HP_SIMPLE)]
        days_data = _make_days_data({"2026-01-01": items})
        r1 = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        r2 = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(r1, r2)

    def test_trauma_hp_in_qualifying_note_types(self):
        """'Trauma H&P' appears in qualifying_note_types_found."""
        items = [_make_trauma_hp_item(SAMPLE_TRAUMA_HP_SIMPLE)]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertIn("Trauma H&P", result["qualifying_note_types_found"])

    def test_consult_note_still_excluded(self):
        """CONSULT_NOTE items remain excluded after TRAUMA_HP addition."""
        items = [{
            "type": "CONSULT_NOTE",
            "dt": "2026-01-01T09:00:00",
            "source_id": "99",
            "payload": {"text": SAMPLE_TRAUMA_HP_SIMPLE},
        }]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0)

    def test_ed_note_still_excluded(self):
        """ED_NOTE items remain excluded."""
        items = [{
            "type": "ED_NOTE",
            "dt": "2026-01-01T01:00:00",
            "source_id": "88",
            "payload": {"text": SAMPLE_TRAUMA_HP_SIMPLE},
        }]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0)

    def test_trauma_hp_without_hp_header_skipped(self):
        """TRAUMA_HP container without 'Trauma H & P' header is skipped."""
        generic_payload = (
            "Signed\n\nExpand All Collapse All\n\n"
            "Generic Consult Note\nSome Provider, MD\n\n"
            "HPI: Patient seen for follow-up.\n\n"
            "Impression: Stable.\n\n"
            "Plan:\n- Continue current management\n- Follow up in 1 week\n\n"
            "Some Provider, MD\n"
        )
        items = [_make_trauma_hp_item(generic_payload)]
        days_data = _make_days_data({"2026-01-01": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0,
                         "TRAUMA_HP without Trauma H & P header must be skipped")


class TestSpecialtyIntegration(unittest.TestCase):
    """Integration tests for new specialty note extraction."""

    def test_neurosurgery_full_extraction(self):
        items = [_make_physician_note_item(SAMPLE_NEUROSURGERY_NOTE)]
        days_data = _make_days_data({"2025-12-15": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2025-12-15"]["notes"][0]
        self.assertEqual(note["note_type"], "Neurosurgery Progress Note")
        combined = " ".join(note["plan_lines"])
        self.assertIn("transfer out of ICU", combined)
        self.assertTrue(note["raw_line_id"])

    def test_nephrology_full_extraction(self):
        items = [_make_physician_note_item(SAMPLE_NEPHROLOGY_NOTE)]
        days_data = _make_days_data({"2025-12-29": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2025-12-29"]["notes"][0]
        self.assertEqual(note["note_type"], "Nephrology Progress Note")
        combined = " ".join(note["plan_lines"])
        self.assertIn("Hyponatremia", combined)

    def test_renal_brief_note_no_plan_skipped(self):
        """Renal brief note without Plan section is silently skipped."""
        items = [_make_physician_note_item(SAMPLE_RENAL_BRIEF_NOTE)]
        days_data = _make_days_data({"2025-12-25": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0)
        self.assertEqual(len(result["warnings"]), 0)

    def test_heme_onc_full_extraction(self):
        items = [_make_physician_note_item(SAMPLE_HEME_ONC_NOTE)]
        days_data = _make_days_data({"2025-12-27": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2025-12-27"]["notes"][0]
        self.assertEqual(note["note_type"], "Hematology/Oncology Progress Note")
        combined = " ".join(note["plan_lines"])
        self.assertIn("monitoring WBC", combined)

    def test_plastics_full_extraction(self):
        items = [_make_physician_note_item(SAMPLE_PLASTICS_NOTE)]
        days_data = _make_days_data({"2026-01-25": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 1)
        note = result["days"]["2026-01-25"]["notes"][0]
        self.assertEqual(note["note_type"], "Plastics Progress Note")
        combined = " ".join(note["plan_lines"])
        self.assertIn("Closed reduction", combined)

    def test_mixed_specialty_and_trauma(self):
        """Trauma and specialty notes on same day both extracted."""
        items = [
            _make_physician_note_item(
                SAMPLE_TRAUMA_PROGRESS_NOTE, source_id="61",
                dt="2026-01-03T06:56:00",
            ),
            _make_physician_note_item(
                SAMPLE_NEUROSURGERY_NOTE, source_id="62",
                dt="2026-01-03T10:00:00",
            ),
        ]
        days_data = _make_days_data({"2026-01-03": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)

        self.assertEqual(result["total_notes"], 2)
        note_types = {n["note_type"] for n in result["days"]["2026-01-03"]["notes"]}
        self.assertIn("Trauma Progress Note", note_types)
        self.assertIn("Neurosurgery Progress Note", note_types)

    def test_consult_note_type_excluded(self):
        """CONSULT_NOTE items are not processed, even with matching text."""
        items = [{
            "type": "CONSULT_NOTE",
            "dt": "2025-12-15T09:00:00",
            "source_id": "99",
            "payload": {"text": SAMPLE_NEUROSURGERY_NOTE},
        }]
        days_data = _make_days_data({"2025-12-15": items})
        result = extract_trauma_daily_plan_by_day({"days": {}}, days_data)
        self.assertEqual(result["total_notes"], 0)


if __name__ == "__main__":
    unittest.main()
