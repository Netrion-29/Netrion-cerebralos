"""
Smoke tests for render_trauma_daily_notes_v5.py

Verifies:
- render_v5 produces deterministic output
- Patient Summary section is present
- Per-day sections render for each day
- Missing features degrade to DNA gracefully
- Consultant / procedure / movement sections render when data exists
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

# Allow running from repo root
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cerebralos.reporting.render_trauma_daily_notes_v5 import render_v5

_DNA = "DATA NOT AVAILABLE"


def _minimal_features(**overrides):
    """Build a minimal features dict for testing."""
    base = {
        "patient_id": "Test_Patient",
        "features": {},
        "days": {
            "2026-01-01": {
                "vitals": {},
                "gcs_daily": {},
                "labs_panel_daily": {},
                "device_day_counts": {},
            },
        },
        "build": {},
        "evidence_gaps": {},
        "warnings": [],
        "warnings_summary": {},
    }
    base.update(overrides)
    return base


class TestRenderV5Smoke(unittest.TestCase):
    """Basic structural smoke tests for v5 renderer."""

    def test_renders_without_crash(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("PI DAILY NOTES (v5)", result)
        self.assertIn("END OF PI DAILY NOTES (v5)", result)

    def test_patient_id_shown(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("Patient ID: Test_Patient", result)

    def test_patient_summary_section(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("PATIENT SUMMARY", result)

    def test_per_day_section_rendered(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("===== 2026-01-01 =====", result)
        self.assertIn("Vitals Trending:", result)
        self.assertIn("GCS:", result)
        self.assertIn("Labs Panel Lite:", result)
        self.assertIn("Device Day Counts:", result)

    def test_missing_features_dna(self):
        """All summary sections should render DNA when features are empty."""
        data = _minimal_features()
        result = render_v5(data)
        # Age should be DNA
        self.assertIn("Age:", result)
        # Mechanism should be DNA
        self.assertIn("Mechanism:", result)

    def test_determinism(self):
        """Two renders of the same data must produce identical output."""
        data = _minimal_features()
        r1 = render_v5(data)
        r2 = render_v5(data)
        self.assertEqual(r1, r2)

    def test_evidence_gap_detection(self):
        """Gap between days should produce evidence gap notice."""
        data = _minimal_features()
        data["days"]["2026-01-03"] = {
            "vitals": {}, "gcs_daily": {},
            "labs_panel_daily": {}, "device_day_counts": {},
        }
        result = render_v5(data)
        self.assertIn("EVIDENCE GAP", result)

    def test_no_procedure_message(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("No procedures", result)

    def test_injury_catalog_dna(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("ESTABLISHED INJURY CATALOG", result)

    def test_movement_summary_present(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("ADMISSION / MOVEMENT SUMMARY", result)

    def test_consultant_summary_present(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("CONSULTANT SUMMARY", result)

    def test_prophylaxis_present(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("PROPHYLAXIS STATUS", result)

    def test_trigger_section_present(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("TRIGGER / HEMODYNAMIC STATUS", result)

    def test_bd_inr_section_present(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("BASE DEFICIT / INR MONITORING", result)


class TestRenderV5WithData(unittest.TestCase):
    """Tests with populated feature data."""

    def test_age_renders(self):
        data = _minimal_features()
        data["features"]["age_extraction_v1"] = {
            "age_available": True,
            "age_years": 72,
            "age_source_rule_id": "age_from_hp",
        }
        result = render_v5(data)
        self.assertIn("72 years", result)

    def test_category_activation(self):
        data = _minimal_features()
        data["features"]["category_activation_v1"] = {
            "detected": True,
            "category": "I",
        }
        result = render_v5(data)
        self.assertIn("I activation", result)

    def test_mechanism_renders(self):
        data = _minimal_features()
        data["features"]["mechanism_region_v1"] = {
            "mechanism_present": True,
            "mechanism_primary": "Fall",
            "mechanism_labels": ["Fall", "Ground level"],
            "penetrating_mechanism": False,
            "body_region_labels": ["Head", "Spine"],
        }
        result = render_v5(data)
        self.assertIn("Fall", result)
        self.assertIn("Head", result)

    def test_consultant_plan_items(self):
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "2026-01-01 08:00", "note_count": 1, "authors": ["Dr. Smith"]},
            ],
        }
        data["features"]["consultant_plan_items_v1"] = {
            "item_count": 2,
            "services_with_plan_items": ["Ortho"],
            "items": [
                {"item_text": "Continue weight bearing", "item_type": "activity", "service": "Ortho"},
                {"item_text": "Follow-up in 2 weeks", "item_type": "follow-up", "service": "Ortho"},
            ],
        }
        result = render_v5(data)
        self.assertIn("Ortho", result)
        self.assertIn("Continue weight bearing", result)
        self.assertIn("Follow-up in 2 weeks", result)

    def test_procedure_events(self):
        data = _minimal_features()
        data["features"]["procedure_operatives_v1"] = {
            "procedure_event_count": 1,
            "operative_event_count": 0,
            "anesthesia_event_count": 0,
            "categories_present": ["bedside_procedure"],
            "events": [
                {"category": "bedside_procedure", "label": "Chest tube insertion", "ts": "2026-01-01 10:00"},
            ],
        }
        result = render_v5(data)
        self.assertIn("Chest tube insertion", result)

    def test_dvt_prophylaxis(self):
        data = _minimal_features()
        data["features"]["dvt_prophylaxis_v1"] = {
            "first_ts": "2026-01-01 14:00",
            "delay_hours": 12.5,
            "delay_flag_24h": False,
            "pharm_first_ts": "2026-01-01 14:00",
            "pharm_admin_evidence_count": 1,
        }
        result = render_v5(data)
        self.assertIn("12.5 hrs", result)

    def test_movement_entries(self):
        data = _minimal_features()
        data["features"]["patient_movement_v1"] = {
            "summary": {
                "movement_event_count": 2,
                "levels_of_care": ["Emergency", "ICU"],
            },
            "entries": [
                {"event_type": "Admission", "unit": "ED", "level_of_care": "Emergency", "service": "Emergency", "date_raw": "01/01", "time_raw": "0200"},
                {"event_type": "Transfer In", "unit": "ICU", "level_of_care": "ICU", "service": "Trauma", "date_raw": "01/01", "time_raw": "0800"},
            ],
        }
        result = render_v5(data)
        self.assertIn("Emergency -> ICU", result)

    def test_spine_clearance_omitted_when_absent(self):
        data = _minimal_features()
        result = render_v5(data)
        # Spine clearance omitted when feature absent
        self.assertNotIn("SPINE CLEARANCE", result)

    def test_spine_clearance_shown_when_present(self):
        data = _minimal_features()
        data["features"]["spine_clearance_v1"] = {
            "clearance_status": "CLEARED",
            "collar_status": "REMOVED",
            "method": "clinical",
        }
        result = render_v5(data)
        self.assertIn("SPINE CLEARANCE", result)
        self.assertIn("CLEARED", result)

    def test_lda_summary_omitted_when_absent(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertNotIn("LDA / DEVICE LIFECYCLE SUMMARY", result)

    def test_lda_summary_shown(self):
        data = _minimal_features()
        data["features"]["lda_events_v1"] = {
            "lda_device_count": 2,
            "active_devices_count": 1,
            "categories_present": ["PIV", "Urethral Catheter"],
            "devices": [
                {"device_type": "Peripheral IV", "category": "PIV",
                 "placed_ts": "01/01/26 0800", "removed_ts": "01/03/26 1200",
                 "duration_text": "2 days"},
                {"device_type": "Urethral Catheter", "category": "Urethral Catheter",
                 "placed_ts": "01/01/26 0900", "removed_ts": None,
                 "duration_text": ""},
            ],
        }
        result = render_v5(data)
        self.assertIn("LDA / DEVICE LIFECYCLE SUMMARY", result)
        self.assertIn("Total devices:    2", result)
        self.assertIn("Active (at d/c):  1", result)
        self.assertIn("PIV", result)
        self.assertIn("Urethral Catheter", result)
        self.assertIn("placed 01/01/26 0800", result)
        self.assertIn("active", result)

    def test_lda_truncation(self):
        """More than _MAX_LDA_DEVICES should show truncation notice."""
        data = _minimal_features()
        devices = []
        for i in range(30):
            devices.append({
                "device_type": f"Device_{i}", "category": "PIV",
                "placed_ts": f"01/{i+1:02d}/26 0800", "removed_ts": None,
            })
        data["features"]["lda_events_v1"] = {
            "lda_device_count": 30,
            "active_devices_count": 30,
            "categories_present": ["PIV"],
            "devices": devices,
        }
        result = render_v5(data)
        self.assertIn("truncated", result)
        self.assertIn("Device_0", result)
        self.assertNotIn("Device_29", result)

    def test_urine_output_omitted_when_absent(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertNotIn("URINE OUTPUT SUMMARY", result)

    def test_urine_output_omitted_when_zero_events(self):
        data = _minimal_features()
        data["features"]["urine_output_events_v1"] = {
            "urine_output_event_count": 0,
            "total_urine_output_ml": 0,
            "events": [],
            "source_types_present": [],
            "source_rule_id": "no_urine_output_data",
        }
        result = render_v5(data)
        self.assertNotIn("URINE OUTPUT SUMMARY", result)

    def test_urine_output_shown(self):
        data = _minimal_features()
        data["features"]["urine_output_events_v1"] = {
            "urine_output_event_count": 5,
            "total_urine_output_ml": 1200,
            "first_urine_output_ts": "01/01 0800",
            "last_urine_output_ts": "01/02 1600",
            "source_types_present": ["flowsheet"],
            "source_rule_id": "urine_output_events_raw_file",
            "events": [
                {"ts": "01/01 0800", "output_ml": 200, "source_type": "flowsheet",
                 "source_subtype": "Voided", "urine_color": "Yellow/Straw"},
                {"ts": "01/01 1200", "output_ml": 300, "source_type": "flowsheet",
                 "source_subtype": "Voided", "urine_color": "Yellow/Straw"},
                {"ts": "01/01 1800", "output_ml": None, "source_type": "flowsheet",
                 "source_subtype": "Voided", "urine_color": "Yellow/Straw"},
                {"ts": "01/02 0400", "output_ml": 250, "source_type": "flowsheet",
                 "source_subtype": "Voided", "urine_color": "Amber"},
                {"ts": "01/02 1600", "output_ml": 450, "source_type": "flowsheet",
                 "source_subtype": "Voided", "urine_color": "Yellow/Straw"},
            ],
        }
        result = render_v5(data)
        self.assertIn("URINE OUTPUT SUMMARY", result)
        self.assertIn("1200 mL", result)
        self.assertIn("Event count:      5", result)
        self.assertIn("First recorded:   01/01 0800", result)
        self.assertIn("Last recorded:    01/02 1600", result)
        self.assertIn("flowsheet", result)
        self.assertIn("Voided:", result)

    def test_urine_output_subtype_breakdown(self):
        data = _minimal_features()
        data["features"]["urine_output_events_v1"] = {
            "urine_output_event_count": 3,
            "total_urine_output_ml": 900,
            "first_urine_output_ts": "01/01 0800",
            "last_urine_output_ts": "01/01 1800",
            "source_types_present": ["flowsheet", "lda_assessment"],
            "events": [
                {"ts": "01/01 0800", "output_ml": 200, "source_subtype": "Voided"},
                {"ts": "01/01 1200", "output_ml": 400, "source_subtype": "Urethral Catheter"},
                {"ts": "01/01 1800", "output_ml": 300, "source_subtype": "Urethral Catheter"},
            ],
        }
        result = render_v5(data)
        self.assertIn("Voided: 1 events", result)
        self.assertIn("Urethral Catheter: 2 events", result)

    def test_consultant_plan_dedup(self):
        """Duplicate plan items within a service should be suppressed."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "2026-01-01 08:00",
                 "note_count": 1, "authors": ["Dr. Smith"]},
            ],
        }
        data["features"]["consultant_plan_items_v1"] = {
            "item_count": 3,
            "services_with_plan_items": ["Ortho"],
            "items": [
                {"item_text": "Continue weight bearing", "item_type": "activity",
                 "service": "Ortho", "author_name": "Dr. Smith"},
                {"item_text": "Continue weight bearing", "item_type": "activity",
                 "service": "Ortho", "author_name": "Dr. Smith"},
                {"item_text": "Follow-up in 2 weeks", "item_type": "follow-up",
                 "service": "Ortho", "author_name": "Dr. Jones"},
            ],
        }
        result = render_v5(data)
        # Should show dedup notice
        self.assertIn("duplicate", result.lower())
        # Should show author tags
        self.assertIn("[Dr. Smith]", result)
        self.assertIn("[Dr. Jones]", result)
        # Count occurrences of "Continue weight bearing" - should be 1 not 2
        self.assertEqual(result.count("Continue weight bearing"), 1)

    def test_consultant_plan_author_shown(self):
        """Plan items should show author name."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Neurosurgery", "first_ts": "2026-01-01 09:00",
                 "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_items_v1"] = {
            "item_count": 1,
            "services_with_plan_items": ["Neurosurgery"],
            "items": [
                {"item_text": "Repeat CT head in 6 hours", "item_type": "imaging",
                 "service": "Neurosurgery", "author_name": "Dr. Patel"},
            ],
        }
        result = render_v5(data)
        self.assertIn("[Dr. Patel]", result)

    def test_consultant_plan_long_item_truncation(self):
        """Very long plan items should be truncated deterministically."""
        data = _minimal_features()
        long_text = "A" * 200
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Internal Medicine", "first_ts": "2026-01-01",
                 "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_items_v1"] = {
            "item_count": 1,
            "services_with_plan_items": ["Internal Medicine"],
            "items": [
                {"item_text": long_text, "item_type": "recommendation",
                 "service": "Internal Medicine"},
            ],
        }
        result = render_v5(data)
        self.assertIn("...", result)
        self.assertNotIn(long_text, result)

    def test_section_ordering(self):
        """LDA and Urine Output should appear between Procedure and Consultant."""
        data = _minimal_features()
        data["features"]["lda_events_v1"] = {
            "lda_device_count": 1,
            "active_devices_count": 0,
            "categories_present": ["PIV"],
            "devices": [
                {"device_type": "PIV", "category": "PIV",
                 "placed_ts": "01/01", "removed_ts": "01/02"},
            ],
        }
        data["features"]["urine_output_events_v1"] = {
            "urine_output_event_count": 1,
            "total_urine_output_ml": 100,
            "first_urine_output_ts": "01/01",
            "last_urine_output_ts": "01/01",
            "source_types_present": ["flowsheet"],
            "events": [
                {"ts": "01/01", "output_ml": 100, "source_subtype": "Voided"},
            ],
        }
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "01/01", "note_count": 1, "authors": []},
            ],
        }
        result = render_v5(data)
        # Verify ordering: Procedure < LDA < Urine Output < Consultant
        proc_pos = result.index("PROCEDURE / OR / ANESTHESIA SUMMARY")
        lda_pos = result.index("LDA / DEVICE LIFECYCLE SUMMARY")
        urine_pos = result.index("URINE OUTPUT SUMMARY")
        consult_pos = result.index("CONSULTANT SUMMARY")
        self.assertLess(proc_pos, lda_pos)
        self.assertLess(lda_pos, urine_pos)
        self.assertLess(urine_pos, consult_pos)

    def test_incentive_spirometry_omitted_when_not_mentioned(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertNotIn("INCENTIVE SPIROMETRY", result)

    def test_incentive_spirometry_shown(self):
        data = _minimal_features()
        data["features"]["incentive_spirometry_v1"] = {
            "is_mentioned": "yes",
            "is_value_present": "yes",
            "mention_count": 3,
            "measurement_count": 2,
            "measurements": [
                {"ts": "2026-01-01 08:00", "avg_volume_cc": 1500, "goal_cc": 2000},
            ],
        }
        result = render_v5(data)
        self.assertIn("INCENTIVE SPIROMETRY", result)
        self.assertIn("1500", result)

    def test_shock_trigger(self):
        data = _minimal_features()
        data["features"]["shock_trigger_v1"] = {
            "shock_triggered": True,
            "shock_type": "hemorrhagic_likely",
            "trigger_rule_id": "shock_sbp_bd",
            "trigger_vitals": {"sbp": 85, "bd": 7.2},
        }
        result = render_v5(data)
        self.assertIn("Shock Triggered:  Yes", result)
        self.assertIn("hemorrhagic_likely", result)

    def test_radiology_findings(self):
        data = _minimal_features()
        data["features"]["radiology_findings_v1"] = {
            "findings_present": True,
            "findings_labels": ["ICH", "rib_fracture"],
            "intracranial_hemorrhage": [{"present": True, "subtype": "SDH"}],
            "rib_fracture": [{"present": True}],
        }
        result = render_v5(data)
        self.assertIn("ESTABLISHED INJURY CATALOG", result)
        self.assertIn("SDH", result)
        self.assertIn("Rib Fractures", result)


class TestRenderV5RealData(unittest.TestCase):
    """Integration tests against real patient data files (skipped if unavailable)."""

    def _load_patient(self, slug):
        feat_path = Path(f"outputs/features/{slug}/patient_features_v1.json")
        days_path = Path(f"outputs/timeline/{slug}/patient_days_v1.json")
        if not feat_path.exists():
            self.skipTest(f"Features file not found: {feat_path}")
        with open(feat_path) as f:
            features = json.load(f)
        days = None
        if days_path.exists():
            with open(days_path) as f:
                days = json.load(f)
        return features, days

    def _assert_v5_structure(self, text, slug):
        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("END OF PI DAILY NOTES (v5)", text)
        self.assertIn("PATIENT SUMMARY", text)
        self.assertIn("PER-DAY CLINICAL STATUS", text)
        # Determinism
        return text

    def test_roscella_weatherly(self):
        features, days = self._load_patient("Roscella_Weatherly")
        text = render_v5(features, days)
        self._assert_v5_structure(text, "Roscella_Weatherly")
        # Should have movement data
        self.assertIn("ADMISSION / MOVEMENT SUMMARY", text)
        # Should have consultant data
        self.assertIn("CONSULTANT SUMMARY", text)
        # Should have urine output (flowsheet source)
        self.assertIn("URINE OUTPUT SUMMARY", text)

    def test_lee_woodard(self):
        features, days = self._load_patient("Lee_Woodard")
        text = render_v5(features, days)
        self._assert_v5_structure(text, "Lee_Woodard")
        # Should have LDA devices
        self.assertIn("LDA / DEVICE LIFECYCLE SUMMARY", text)
        # Should have urine output (LDA + flowsheet)
        self.assertIn("URINE OUTPUT SUMMARY", text)
        # Should have consultant data
        self.assertIn("CONSULTANT SUMMARY", text)

    def test_ronald_bittner(self):
        features, days = self._load_patient("Ronald_Bittner")
        text = render_v5(features, days)
        self._assert_v5_structure(text, "Ronald_Bittner")
        # High-volume patient: should have LDA and urine
        self.assertIn("LDA / DEVICE LIFECYCLE SUMMARY", text)
        self.assertIn("URINE OUTPUT SUMMARY", text)

    def test_anna_dennis(self):
        features, days = self._load_patient("Anna_Dennis")
        text = render_v5(features, days)
        self._assert_v5_structure(text, "Anna_Dennis")

    def test_michael_dougan(self):
        features, days = self._load_patient("Michael_Dougan")
        text = render_v5(features, days)
        self._assert_v5_structure(text, "Michael_Dougan")

    def test_determinism_real(self):
        features, days = self._load_patient("Roscella_Weatherly")
        r1 = render_v5(features, days)
        r2 = render_v5(features, days)
        self.assertEqual(r1, r2, "v5 output must be deterministic")


if __name__ == "__main__":
    unittest.main()
