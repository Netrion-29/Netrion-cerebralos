#!/usr/bin/env python3
"""
Tests for consultant_plan_items_v1 feature extractor.

Covers:
  - Plan section header detection
  - Plan section termination
  - Noise line filtering
  - Item type classification
  - Deduplication
  - Timeline-to-service matching
  - Fail-closed behaviour
  - Evidence traceability
  - Determinism
"""

import unittest

from cerebralos.features.consultant_plan_items_v1 import (
    _classify_item_type,
    _dt_matches,
    _extract_plan_sections,
    _is_noise_line,
    _normalize_item_text,
    _parse_plan_items,
    extract_consultant_plan_items,
)


# ═══════════════════════════════════════════════════════════════════
#  Plan section header detection
# ═══════════════════════════════════════════════════════════════════


class TestExtractPlanSections(unittest.TestCase):
    """Test _extract_plan_sections with various header formats."""

    def test_assessment_and_plan_colon(self):
        text = "Subjective:\nPatient complains...\n\nAssessment and Plan:\nStart metformin.\nFollow up in 2 weeks.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("Assessment and Plan:", sections[0][1])
        self.assertIn("Start metformin", sections[0][2])

    def test_assessment_ampersand_plan(self):
        text = "Objective:\nVitals stable.\n\nAssessment & Plan\nContinue antibiotics.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("Continue antibiotics", sections[0][2])

    def test_assessment_slash_plan(self):
        text = "Assessment/Plan:  This is a 55 yo female.\nSugarachnoid hemorrhage.\n\nDisposition: home\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("55 yo female", sections[0][2])

    def test_ap_with_inline_content(self):
        text = "A/P: This is a 88 y.o. female who presents s/p fall.\n- Favor mobilization.\n- No plans for bracing.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("88 y.o. female", sections[0][2])
        self.assertIn("Favor mobilization", sections[0][2])

    def test_plan_colon(self):
        text = "History:\nAdmitted yesterday.\n\nPlan:\nCheck proBNP.\nAdjust medications.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("Check proBNP", sections[0][2])

    def test_recommendations_header(self):
        text = "Assessment:\nFall risk.\n\nRecommendations\nSkin Tear Instructions:\n1.  Leave foam dressing in place.\n2.  Avoid peeling back dressing.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertIn("Skin Tear Instructions", sections[0][2])

    def test_no_plan_section(self):
        text = "Subjective:\nPatient feels better.\n\nObjective:\nVitals stable.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 0)

    def test_termination_on_separator(self):
        text = "Plan:\nStart medication.\n_______________\nSignature block\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertNotIn("Signature block", sections[0][2])

    def test_termination_on_electronic_signature(self):
        text = "Plan:\nOrder TTE.\nElectronically signed by Dr. Smith\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertNotIn("Electronically signed", sections[0][2])

    def test_termination_on_next_section(self):
        text = "Assessment and Plan:\nContinue care.\n\nMedications\nAspirin 81mg\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertNotIn("Aspirin", sections[0][2])

    def test_termination_on_addendum(self):
        text = "Plan:\nFavor mobilization.\n\nAddendum: pt seen and examined.\n"
        sections = _extract_plan_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertNotIn("Addendum", sections[0][2])

    def test_multiple_plan_sections(self):
        """Multiple distinct plan headers in one note (e.g., Assessment then Plan)."""
        text = "Assessment:\nSAH, nasal fracture.\n\nPlan:\nICU admission.\nENT consult.\n"
        sections = _extract_plan_sections(text)
        # Should get 2 sections: Assessment and Plan
        self.assertGreaterEqual(len(sections), 1)


# ═══════════════════════════════════════════════════════════════════
#  Noise line filtering
# ═══════════════════════════════════════════════════════════════════


class TestIsNoiseLine(unittest.TestCase):
    """Test _is_noise_line correctly filters non-plan content."""

    def test_empty_line(self):
        self.assertTrue(_is_noise_line(""))

    def test_whitespace_only(self):
        self.assertTrue(_is_noise_line("   "))

    def test_attestation(self):
        self.assertTrue(_is_noise_line(
            "I have seen and examined patient on the above stated date."
        ))

    def test_credential_line(self):
        self.assertTrue(_is_noise_line("Roberto C Iglesias, MD"))

    def test_credential_np(self):
        self.assertTrue(_is_noise_line("Claire Stevenson, NP"))

    def test_date_only(self):
        self.assertTrue(_is_noise_line("1/1/2026"))

    def test_time_only(self):
        self.assertTrue(_is_noise_line("6:00 PM"))

    def test_seen_at(self):
        self.assertTrue(_is_noise_line("Seen at 0540"))

    def test_disclaimer(self):
        self.assertTrue(_is_noise_line(
            "Disclaimer: Beginning in the spring of 2021, MyChart will allow..."
        ))

    def test_untitled_image(self):
        self.assertTrue(_is_noise_line("untitled image"))

    def test_courtesy(self):
        self.assertTrue(_is_noise_line(
            "Thank you for allowing us to participate in the care of your patient"
        ))

    def test_phone(self):
        self.assertTrue(_is_noise_line("Pager: 812-428-1792"))

    def test_order_ref(self):
        self.assertTrue(_is_noise_line("Order: 466673714"))

    def test_service_title(self):
        self.assertTrue(_is_noise_line("Deaconess Clinic"))

    def test_code_status(self):
        self.assertTrue(_is_noise_line("Code, full"))
        self.assertTrue(_is_noise_line("Full code status"))

    def test_short_line(self):
        self.assertTrue(_is_noise_line("ab"))

    def test_real_plan_item_is_not_noise(self):
        self.assertFalse(_is_noise_line("Start Nimodipine"))

    def test_long_plan_item_is_not_noise(self):
        self.assertFalse(_is_noise_line(
            "ICU admission for monitoring of subarachnoid hemorrhage"
        ))

    def test_recommendation_is_not_noise(self):
        self.assertFalse(_is_noise_line(
            "Leave foam dressing in place for 5 days"
        ))

    def test_electronic_signature(self):
        self.assertTrue(_is_noise_line(
            "This has been electronically signed by:"
        ))


# ═══════════════════════════════════════════════════════════════════
#  Item text normalization
# ═══════════════════════════════════════════════════════════════════


class TestNormalizeItemText(unittest.TestCase):
    """Test _normalize_item_text strips bullets and whitespace."""

    def test_dash_bullet(self):
        self.assertEqual(_normalize_item_text("- Start medication"), "Start medication")

    def test_numbered_period(self):
        self.assertEqual(_normalize_item_text("1. ICU admission"), "ICU admission")

    def test_numbered_paren(self):
        self.assertEqual(_normalize_item_text("2) Follow up"), "Follow up")

    def test_bullet_char(self):
        self.assertEqual(_normalize_item_text("• Continue care"), "Continue care")

    def test_whitespace_collapse(self):
        self.assertEqual(
            _normalize_item_text("  Start    medication   "),
            "Start medication",
        )

    def test_no_bullet(self):
        self.assertEqual(
            _normalize_item_text("ICU admission"),
            "ICU admission",
        )


# ═══════════════════════════════════════════════════════════════════
#  Item type classification
# ═══════════════════════════════════════════════════════════════════


class TestClassifyItemType(unittest.TestCase):
    """Test _classify_item_type deterministic keyword tagging."""

    def test_medication(self):
        self.assertEqual(_classify_item_type("Start Nimodipine"), "medication")
        self.assertEqual(_classify_item_type("Continue Wellbutrin"), "medication")
        self.assertEqual(_classify_item_type("IV hydralazine p.r.n."), "medication")

    def test_imaging(self):
        self.assertEqual(_classify_item_type("Order TTE"), "imaging")
        self.assertEqual(_classify_item_type("Repeat CT head in 6 hours"), "imaging")

    def test_procedure(self):
        self.assertEqual(_classify_item_type("ORIF right clavicle"), "procedure")
        self.assertEqual(_classify_item_type("Plan for surgery"), "procedure")

    def test_follow_up(self):
        self.assertEqual(
            _classify_item_type("Follow up in 1-2 weeks"),
            "follow-up",
        )
        self.assertEqual(
            _classify_item_type("Recommend f/u in 1-2 weeks for repeat XR"),
            "follow-up",
        )

    def test_activity(self):
        self.assertEqual(
            _classify_item_type("May use R arm for writing/feeding, otherwise NWB on RUE"),
            "activity",
        )
        self.assertEqual(
            _classify_item_type("Adjust bronchopulmonary hygiene"),
            "activity",
        )

    def test_discharge(self):
        self.assertEqual(
            _classify_item_type("Ok to d/c from a neurosurgery standpoint"),
            "discharge",
        )

    def test_recommendation_default(self):
        self.assertEqual(
            _classify_item_type("Subarachnoid hemorrhage management"),
            "recommendation",
        )


# ═══════════════════════════════════════════════════════════════════
#  Datetime matching
# ═══════════════════════════════════════════════════════════════════


class TestDtMatches(unittest.TestCase):
    """Test _dt_matches ISO dt to MM/DD + HHMM matching."""

    def test_exact_match(self):
        self.assertTrue(_dt_matches("2026-01-01T10:20:00", "01/01", "1020"))

    def test_different_time(self):
        self.assertFalse(_dt_matches("2026-01-01T10:20:00", "01/01", "1030"))

    def test_different_date(self):
        self.assertFalse(_dt_matches("2026-01-01T10:20:00", "01/02", "1020"))

    def test_invalid_dt(self):
        self.assertFalse(_dt_matches("not-a-date", "01/01", "1020"))

    def test_invalid_time_raw(self):
        self.assertFalse(_dt_matches("2026-01-01T10:20:00", "01/01", "abc"))

    def test_midnight(self):
        self.assertTrue(_dt_matches("2026-01-01T00:00:00", "01/01", "0000"))


# ═══════════════════════════════════════════════════════════════════
#  Parse plan items
# ═══════════════════════════════════════════════════════════════════


class TestParsePlanItems(unittest.TestCase):
    """Test _parse_plan_items from section body."""

    def test_bullet_items(self):
        body = "- Start Nimodipine\n- ICU admission\n- ENT consult\n"
        items = _parse_plan_items(
            body, "Internal Medicine", "2026-01-01T05:53:00",
            "Duran, Adriano M", "abc123", "Plan:",
        )
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["item_text"], "Start Nimodipine")
        self.assertEqual(items[0]["service"], "Internal Medicine")
        self.assertEqual(items[0]["item_type"], "medication")

    def test_numbered_items(self):
        body = "1.  Leave foam dressing in place for 5 days.\n2.  Avoid peeling back dressing.\n"
        items = _parse_plan_items(
            body, "Wound/Ostomy", "2026-01-01T13:16:00",
            "Wills, Abigail", "def456", "Recommendations",
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["item_text"], "Leave foam dressing in place for 5 days.")

    def test_plain_text_items(self):
        body = "Check proBNP and procalcitonin\nAdjust bronchopulmonary hygiene\n"
        items = _parse_plan_items(
            body, "Internal Medicine", "2026-01-04T14:26:00",
            "Arora, Avi", "ghi789", "Plan:",
        )
        self.assertGreaterEqual(len(items), 2)

    def test_noise_filtered(self):
        body = "Start medication.\nRoberto C Iglesias, MD\n1/1/2026\nuntitled image\n"
        items = _parse_plan_items(
            body, "ENT", "2026-01-01T10:20:00",
            "Chacko, Chris E", "jkl012", "Assessment and Plan:",
        )
        # Only "Start medication" should survive
        texts = [i["item_text"] for i in items]
        self.assertIn("Start medication.", texts)
        self.assertTrue(all("Iglesias" not in t for t in texts))

    def test_evidence_present(self):
        body = "Start Nimodipine\n"
        items = _parse_plan_items(
            body, "Internal Medicine", "2026-01-01T05:53:00",
            "Duran, Adriano M", "abc123", "Plan:",
        )
        self.assertEqual(len(items), 1)
        ev = items[0]["evidence"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["role"], "consultant_plan_item")
        self.assertIn("raw_line_id", ev[0])
        self.assertTrue(len(ev[0]["raw_line_id"]) > 0)

    def test_empty_body(self):
        items = _parse_plan_items(
            "", "Internal Medicine", "2026-01-01T05:53:00",
            "Duran, Adriano M", "abc123", "Plan:",
        )
        self.assertEqual(len(items), 0)


# ═══════════════════════════════════════════════════════════════════
#  Full extraction (extract_consultant_plan_items)
# ═══════════════════════════════════════════════════════════════════


class TestExtractConsultantPlanItems(unittest.TestCase):
    """Test the public extract_consultant_plan_items API."""

    def _make_features(self, consultant_present="yes", services=None,
                       note_index_entries=None):
        """Helper to build a mock features dict."""
        if services is None:
            services = []
        if note_index_entries is None:
            note_index_entries = []
        return {
            "consultant_events_v1": {
                "consultant_present": consultant_present,
                "consultant_services_count": len(services),
                "consultant_services": services,
                "source_rule_id": "consultant_events_from_note_index",
                "warnings": [],
                "notes": [],
            },
            "note_index_events_v1": {
                "entries": note_index_entries,
            },
        }

    def _make_days_data(self, items_by_date=None):
        """Helper to build a mock days_data dict."""
        if items_by_date is None:
            items_by_date = {}
        days = {}
        for date_key, items in items_by_date.items():
            days[date_key] = {"items": items}
        return {"days": days, "meta": {}}

    def test_no_consultant_events(self):
        features = {}
        days_data = self._make_days_data()
        result = extract_consultant_plan_items(features, days_data)
        self.assertEqual(result["item_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_consultant_events")

    def test_consultant_present_no(self):
        features = self._make_features(consultant_present="no")
        days_data = self._make_days_data()
        result = extract_consultant_plan_items(features, days_data)
        self.assertEqual(result["item_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_consultant_events")

    def test_consultant_present_dna(self):
        features = self._make_features(consultant_present="DATA NOT AVAILABLE")
        days_data = self._make_days_data()
        result = extract_consultant_plan_items(features, days_data)
        self.assertEqual(result["item_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_consultant_events")

    def test_with_consultant_plan(self):
        services = [{
            "service": "Internal Medicine",
            "first_ts": "01/01 0553",
            "last_ts": "01/01 0553",
            "note_count": 1,
            "authors": ["Duran, Adriano M"],
            "note_types": ["Consults"],
            "evidence": [{
                "role": "consultant_event",
                "snippet": "Consults 01/01 0553 Duran, Adriano M, DO [Internal Medicine]",
                "raw_line_id": "abc123",
            }],
        }]
        ni_entries = [{
            "note_type": "Consults",
            "date_raw": "01/01",
            "time_raw": "0553",
            "author_name": "Duran, Adriano M",
            "service": "Internal Medicine",
            "raw_line_id": "abc123",
        }]
        features = self._make_features(
            consultant_present="yes",
            services=services,
            note_index_entries=ni_entries,
        )
        # Add timeline item with plan content
        note_text = (
            "Hospitalist Consultation\n\n"
            "History of Present Illness:\nPatient presents...\n\n"
            "Plan:\n"
            "1. ICU admission\n"
            "2. Start Nimodipine\n"
            "3. Order TTE\n\n"
            "Roberto C Iglesias, MD\n"
        )
        days_data = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T05:53:00",
                "source_id": "13",
                "payload": {"text": note_text},
            }],
        })
        result = extract_consultant_plan_items(features, days_data)
        self.assertGreater(result["item_count"], 0)
        self.assertEqual(result["source_rule_id"], "consultant_plan_from_note_text")
        self.assertIn("Internal Medicine", result["services_with_plan_items"])

        # Check item content
        texts = [i["item_text"] for i in result["items"]]
        self.assertTrue(any("ICU admission" in t for t in texts))
        self.assertTrue(any("Nimodipine" in t for t in texts))

        # Check evidence
        for item in result["items"]:
            self.assertTrue(len(item["evidence"]) > 0)
            self.assertEqual(item["evidence"][0]["role"], "consultant_plan_item")

    def test_deduplication(self):
        """Duplicate items across co-signed notes are deduplicated."""
        services = [{
            "service": "Orthopedics",
            "first_ts": "01/01 0930",
            "last_ts": "01/02 0930",
            "note_count": 2,
            "authors": ["Smith, John"],
            "note_types": ["Consults"],
            "evidence": [
                {
                    "role": "consultant_event",
                    "snippet": "Consults 01/01 0930 Smith, John, MD [Orthopedics]",
                    "raw_line_id": "aaa",
                },
                {
                    "role": "consultant_event",
                    "snippet": "Consults 01/02 0930 Smith, John, MD [Orthopedics]",
                    "raw_line_id": "bbb",
                },
            ],
        }]
        ni_entries = [
            {
                "note_type": "Consults",
                "date_raw": "01/01",
                "time_raw": "0930",
                "author_name": "Smith, John",
                "service": "Orthopedics",
                "raw_line_id": "aaa",
            },
            {
                "note_type": "Consults",
                "date_raw": "01/02",
                "time_raw": "0930",
                "author_name": "Smith, John",
                "service": "Orthopedics",
                "raw_line_id": "bbb",
            },
        ]
        features = self._make_features(
            consultant_present="yes",
            services=services,
            note_index_entries=ni_entries,
        )
        note_text = "Plan:\n- Nonoperative treatment.\n- NWB on RUE\n"
        days_data = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T09:30:00",
                "source_id": "1",
                "payload": {"text": note_text},
            }],
            "2026-01-02": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-02T09:30:00",
                "source_id": "2",
                "payload": {"text": note_text},  # exact same text
            }],
        })
        result = extract_consultant_plan_items(features, days_data)
        # Should deduplicate: same service + same item text
        texts = [i["item_text"] for i in result["items"]]
        self.assertEqual(len(texts), len(set(t.lower() for t in texts)))
        self.assertTrue(len(result["warnings"]) > 0)  # dedup warnings

    def test_determinism(self):
        """Same input produces identical output on repeated runs."""
        services = [{
            "service": "ENT",
            "first_ts": "01/01 1020",
            "last_ts": "01/01 1020",
            "note_count": 1,
            "authors": ["Chacko, Chris E"],
            "note_types": ["Consults"],
            "evidence": [{
                "role": "consultant_event",
                "snippet": "Consults 01/01 1020 Chacko, Chris E, MD [ENT]",
                "raw_line_id": "xyz",
            }],
        }]
        ni_entries = [{
            "note_type": "Consults",
            "date_raw": "01/01",
            "time_raw": "1020",
            "author_name": "Chacko, Chris E",
            "service": "ENT",
            "raw_line_id": "xyz",
        }]
        features = self._make_features(
            consultant_present="yes",
            services=services,
            note_index_entries=ni_entries,
        )
        note_text = "Assessment and Plan:\n- Nasal fracture management.\n- Follow up in 2 weeks.\n"
        days_data = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T10:20:00",
                "source_id": "1",
                "payload": {"text": note_text},
            }],
        })

        r1 = extract_consultant_plan_items(features, days_data)
        r2 = extract_consultant_plan_items(features, days_data)
        self.assertEqual(r1, r2)

    def test_no_timeline_items_matched(self):
        """Consultant events present but no matching timeline items."""
        services = [{
            "service": "Internal Medicine",
            "first_ts": "01/01 0553",
            "last_ts": "01/01 0553",
            "note_count": 1,
            "authors": ["Duran, Adriano M"],
            "note_types": ["Consults"],
            "evidence": [{
                "role": "consultant_event",
                "snippet": "Consults 01/01 0553 Duran, Adriano M, DO [Internal Medicine]",
                "raw_line_id": "abc",
            }],
        }]
        features = self._make_features(
            consultant_present="yes",
            services=services,
        )
        days_data = self._make_days_data()  # empty timeline
        result = extract_consultant_plan_items(features, days_data)
        self.assertEqual(result["item_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_plan_sections_found")


if __name__ == "__main__":
    unittest.main()
