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
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 2,
            "services_with_actionables": ["Ortho"],
            "category_counts": {"activity": 1, "follow_up": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": "Continue weight bearing", "category": "activity",
                 "source_item_type": "activity", "service": "Ortho", "author_name": "Dr. Smith"},
                {"action_text": "Follow-up in 2 weeks", "category": "follow_up",
                 "source_item_type": "follow-up", "service": "Ortho", "author_name": "Dr. Smith"},
            ],
            "warnings": [],
            "notes": [],
        }
        result = render_v5(data)
        self.assertIn("Ortho", result)
        self.assertIn("Continue weight bearing", result)
        self.assertIn("Follow-up in 2 weeks", result)
        self.assertIn("Actionable Plan Items: 2", result)
        self.assertIn("Activity / Mobility:", result)
        self.assertIn("Follow-Up:", result)

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
        """Duplicate plan items within a service should be suppressed (fallback path)."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "2026-01-01 08:00",
                 "note_count": 1, "authors": ["Dr. Smith"]},
            ],
        }
        # No actionables → fallback to plan_items_v1
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
        """Actionable items should show author name."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Neurosurgery", "first_ts": "2026-01-01 09:00",
                 "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 1,
            "services_with_actionables": ["Neurosurgery"],
            "category_counts": {"imaging": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": "Repeat CT head in 6 hours", "category": "imaging",
                 "source_item_type": "imaging", "service": "Neurosurgery",
                 "author_name": "Dr. Patel"},
            ],
            "warnings": [],
            "notes": [],
        }
        result = render_v5(data)
        self.assertIn("[Dr. Patel]", result)

    def test_consultant_plan_long_item_truncation(self):
        """Very long actionable items should be truncated deterministically."""
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
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 1,
            "services_with_actionables": ["Internal Medicine"],
            "category_counts": {"recommendation": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": long_text, "category": "recommendation",
                 "source_item_type": "recommendation",
                 "service": "Internal Medicine", "author_name": ""},
            ],
            "warnings": [],
            "notes": [],
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


class TestRenderV5ConsultantActionables(unittest.TestCase):
    """Tests for consultant summary with actionables-based rendering."""

    def test_actionables_category_grouping(self):
        """Actionables should be grouped by service then category."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 2,
            "consultant_services": [
                {"service": "Orthopedics", "first_ts": "2026-01-01 08:00",
                 "note_count": 1, "authors": ["Dr. Smith"]},
                {"service": "Neurosurgery", "first_ts": "2026-01-01 09:00",
                 "note_count": 1, "authors": ["Dr. Patel"]},
            ],
        }
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 4,
            "services_with_actionables": ["Neurosurgery", "Orthopedics"],
            "category_counts": {"activity": 1, "imaging": 2, "discharge": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": "NWB on RUE", "category": "activity",
                 "source_item_type": "activity", "service": "Orthopedics",
                 "author_name": "Dr. Smith"},
                {"action_text": "Repeat CT head 6h", "category": "imaging",
                 "source_item_type": "imaging", "service": "Neurosurgery",
                 "author_name": "Dr. Patel"},
                {"action_text": "Repeat MRI spine", "category": "imaging",
                 "source_item_type": "imaging", "service": "Neurosurgery",
                 "author_name": "Dr. Patel"},
                {"action_text": "Ok to d/c from NSG", "category": "discharge",
                 "source_item_type": "discharge", "service": "Neurosurgery",
                 "author_name": "Dr. Patel"},
            ],
            "warnings": [],
            "notes": [],
        }
        result = render_v5(data)
        # Category labels should appear
        self.assertIn("Imaging:", result)
        self.assertIn("Activity / Mobility:", result)
        self.assertIn("Discharge:", result)
        # Category summary line
        self.assertIn("Categories:", result)
        # Actionable count
        self.assertIn("Actionable Plan Items: 4", result)
        # Service grouping
        self.assertIn("[Neurosurgery]", result)
        self.assertIn("[Orthopedics]", result)

    def test_actionables_category_display_order(self):
        """Categories should render in protocol-meaningful order."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "IM", "first_ts": "2026-01-01", "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 3,
            "services_with_actionables": ["IM"],
            "category_counts": {"discharge": 1, "imaging": 1, "medication": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": "Ok to d/c", "category": "discharge",
                 "source_item_type": "discharge", "service": "IM", "author_name": ""},
                {"action_text": "CT head", "category": "imaging",
                 "source_item_type": "imaging", "service": "IM", "author_name": ""},
                {"action_text": "Start abx", "category": "medication",
                 "source_item_type": "medication", "service": "IM", "author_name": ""},
            ],
            "warnings": [],
            "notes": [],
        }
        result = render_v5(data)
        # Imaging should appear before Medication, which should appear before Discharge
        img_pos = result.index("Imaging:")
        med_pos = result.index("Medication:")
        dis_pos = result.index("Discharge:")
        self.assertLess(img_pos, med_pos)
        self.assertLess(med_pos, dis_pos)

    def test_fallback_to_plan_items_when_no_actionables(self):
        """When consultant_plan_actionables_v1 is absent, fall back to plan_items_v1."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "2026-01-01", "note_count": 1, "authors": []},
            ],
        }
        # No actionables feature — only plan_items
        data["features"]["consultant_plan_items_v1"] = {
            "item_count": 1,
            "services_with_plan_items": ["Ortho"],
            "items": [
                {"item_text": "WBAT on LLE", "item_type": "activity",
                 "service": "Ortho", "author_name": "Dr. Smith"},
            ],
        }
        result = render_v5(data)
        self.assertIn("Plan Items: 1", result)
        self.assertIn("WBAT on LLE", result)
        # Should NOT show "Actionable Plan Items"
        self.assertNotIn("Actionable Plan Items", result)

    def test_fallback_when_actionables_zero(self):
        """When actionable_count is 0 but plan_items exist, use fallback."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "2026-01-01", "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 0,
            "services_with_actionables": [],
            "category_counts": {},
            "source_rule_id": "no_actionables_extracted",
            "actionables": [],
            "warnings": [],
            "notes": [],
        }
        data["features"]["consultant_plan_items_v1"] = {
            "item_count": 1,
            "services_with_plan_items": ["Ortho"],
            "items": [
                {"item_text": "WBAT on LLE", "item_type": "activity",
                 "service": "Ortho", "author_name": "Dr. Smith"},
            ],
        }
        result = render_v5(data)
        self.assertIn("Plan Items: 1", result)
        self.assertNotIn("Actionable Plan Items", result)

    def test_no_consultant_data_shows_dna(self):
        """No consultant features → shows 'No consultant services documented'."""
        data = _minimal_features()
        result = render_v5(data)
        self.assertIn("CONSULTANT SUMMARY", result)
        self.assertIn("No consultant services documented", result)

    def test_multiple_categories_per_service(self):
        """Multiple categories under one service should each have a heading."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "IM", "first_ts": "2026-01-01", "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 3,
            "services_with_actionables": ["IM"],
            "category_counts": {"medication": 2, "monitoring_labs": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": "Start Nimodipine", "category": "medication",
                 "source_item_type": "medication", "service": "IM", "author_name": "Dr. A"},
                {"action_text": "Resume Wellbutrin", "category": "medication",
                 "source_item_type": "medication", "service": "IM", "author_name": "Dr. A"},
                {"action_text": "Labs: A1c, TSH", "category": "monitoring_labs",
                 "source_item_type": "recommendation", "service": "IM", "author_name": "Dr. A"},
            ],
            "warnings": [],
            "notes": [],
        }
        result = render_v5(data)
        self.assertIn("Medication:", result)
        self.assertIn("Monitoring / Labs:", result)
        self.assertIn("[IM] (3 actionable(s)):", result)

    def test_actionables_determinism(self):
        """Actionable rendering must be deterministic."""
        data = _minimal_features()
        data["features"]["consultant_events_v1"] = {
            "consultant_present": True,
            "consultant_services_count": 1,
            "consultant_services": [
                {"service": "Ortho", "first_ts": "2026-01-01", "note_count": 1, "authors": []},
            ],
        }
        data["features"]["consultant_plan_actionables_v1"] = {
            "actionable_count": 2,
            "services_with_actionables": ["Ortho"],
            "category_counts": {"activity": 1, "imaging": 1},
            "source_rule_id": "consultant_actionables_from_plan_items",
            "actionables": [
                {"action_text": "NWB on RUE", "category": "activity",
                 "source_item_type": "activity", "service": "Ortho", "author_name": ""},
                {"action_text": "Repeat XR", "category": "imaging",
                 "source_item_type": "imaging", "service": "Ortho", "author_name": ""},
            ],
            "warnings": [],
            "notes": [],
        }
        r1 = render_v5(data)
        r2 = render_v5(data)
        self.assertEqual(r1, r2)


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
        # Should have consultant data with actionables
        self.assertIn("CONSULTANT SUMMARY", text)
        self.assertIn("Actionable Plan Items:", text)
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
        # Should have consultant data with actionables
        self.assertIn("CONSULTANT SUMMARY", text)
        self.assertIn("Actionable Plan Items:", text)

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


class TestRenderV5RefinementV3(unittest.TestCase):
    """Tests for daily-notes-v5-refinement-v3 fixes.

    Covers: FAST wording, SBIRT instrument wording, procedure None
    descriptions, IS blank measurement suppression, GCS non-arrival
    suppression, note section line cap increase, LDA DNA-timestamp.
    """

    # ── Fix #4: FAST "None at <ts>" → "Performed — result not documented" ──

    def test_fast_none_result_with_timestamp(self):
        """When FAST was performed but result is None, render clear message."""
        data = _minimal_features()
        data["features"]["fast_exam_v1"] = {
            "fast_performed": True,
            "fast_result": None,
            "fast_ts": "2026-01-01T10:00:00",
        }
        result = render_v5(data)
        self.assertIn("Performed at 2026-01-01T10:00:00", result)
        self.assertIn("result not documented", result)
        self.assertNotIn("None at", result)

    def test_fast_string_none_result(self):
        """The string 'None' from upstream should also trigger clear wording."""
        data = _minimal_features()
        data["features"]["fast_exam_v1"] = {
            "fast_performed": True,
            "fast_result": "None",
            "fast_ts": "2026-01-01T10:00:00",
        }
        result = render_v5(data)
        self.assertIn("result not documented", result)
        self.assertNotIn("  FAST:             None at", result)

    def test_fast_valid_result_unchanged(self):
        """FAST with a real result should render as before."""
        data = _minimal_features()
        data["features"]["fast_exam_v1"] = {
            "fast_performed": True,
            "fast_result": "Negative",
            "fast_ts": "2026-01-01T10:00:00",
        }
        result = render_v5(data)
        self.assertIn("FAST:             Negative at 2026-01-01T10:00:00", result)

    # ── Fix #6: SBIRT "none identified" → "instrument type not documented" ──

    def test_sbirt_no_instruments_wording(self):
        """SBIRT present with empty instruments should say 'instrument type not documented'."""
        data = _minimal_features()
        data["features"]["sbirt_screening_v1"] = {
            "sbirt_screening_present": True,
            "instruments_detected": [],
        }
        result = render_v5(data)
        self.assertIn("instrument type not documented", result)
        self.assertNotIn("none identified", result)

    def test_sbirt_with_instruments_unchanged(self):
        """SBIRT with instruments should render them normally."""
        data = _minimal_features()
        data["features"]["sbirt_screening_v1"] = {
            "sbirt_screening_present": True,
            "instruments_detected": ["audit_c", "sbirt_flowsheet"],
        }
        result = render_v5(data)
        self.assertIn("audit_c, sbirt_flowsheet", result)

    # ── Fix #2: Procedure "None" description ──

    def test_procedure_none_label_suppressed(self):
        """Procedure events with 'None' label should render clear placeholder."""
        data = _minimal_features()
        data["features"]["procedure_operatives_v1"] = {
            "procedure_event_count": 1,
            "operative_event_count": 0,
            "anesthesia_event_count": 0,
            "categories_present": ["anesthesia"],
            "events": [
                {"category": "anesthesia", "label": "None", "ts": "2026-01-01 10:00"},
            ],
        }
        result = render_v5(data)
        self.assertIn("(description not documented)", result)
        self.assertNotIn("[anesthesia] None", result)

    def test_procedure_empty_label_suppressed(self):
        """Procedure events with empty label should render placeholder."""
        data = _minimal_features()
        data["features"]["procedure_operatives_v1"] = {
            "procedure_event_count": 1,
            "operative_event_count": 0,
            "anesthesia_event_count": 0,
            "categories_present": ["bedside_procedure"],
            "events": [
                {"category": "bedside_procedure", "label": "", "ts": "2026-01-01 10:00"},
            ],
        }
        result = render_v5(data)
        self.assertIn("(description not documented)", result)

    def test_procedure_valid_label_unchanged(self):
        """Procedure with a valid label should render normally."""
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
        self.assertNotIn("description not documented", result)

    # ── Fix #3: IS blank measurement suppression ──

    def test_is_blank_measurements_suppressed(self):
        """IS measurement rows with no values should be suppressed."""
        data = _minimal_features()
        data["features"]["incentive_spirometry_v1"] = {
            "is_mentioned": "yes",
            "is_value_present": "yes",
            "mention_count": 5,
            "measurement_count": 3,
            "measurements": [
                {"ts": "2026-01-01 08:00", "avg_volume_cc": None, "goal_cc": None,
                 "largest_volume_cc": None, "patient_effort": None},
                {"ts": "2026-01-01 12:00", "avg_volume_cc": 1500, "goal_cc": 2000},
                {"ts": "2026-01-01 16:00"},
            ],
        }
        result = render_v5(data)
        self.assertIn("1500", result)
        self.assertIn("suppressed", result)
        # The blank rows (ts only) should NOT appear as bare timestamps
        self.assertNotIn("2026-01-01 08:00: \n", result)
        self.assertNotIn("2026-01-01 16:00: \n", result)

    def test_is_effort_none_string_suppressed(self):
        """IS measurement 'effort=None' string should not render."""
        data = _minimal_features()
        data["features"]["incentive_spirometry_v1"] = {
            "is_mentioned": "yes",
            "is_value_present": "yes",
            "mention_count": 2,
            "measurement_count": 1,
            "measurements": [
                {"ts": "2026-01-01 08:00", "avg_volume_cc": 1000,
                 "largest_volume_cc": 1300, "patient_effort": "None"},
            ],
        }
        result = render_v5(data)
        self.assertIn("avg=1000cc max=1300cc", result)
        self.assertNotIn("effort=None", result)

    # ── Fix #5: Arrival GCS on non-arrival days ──

    def test_gcs_arrival_day_shows_arrival_gcs(self):
        """Arrival day should still show Arrival GCS even if DNA."""
        data = _minimal_features()
        data["days"] = {
            "2026-01-01": {
                "vitals": {},
                "gcs_daily": {"arrival_gcs": _DNA, "best_gcs": 15, "worst_gcs": 15},
                "labs_panel_daily": {},
                "device_day_counts": {},
            },
        }
        result = render_v5(data)
        self.assertIn("Arrival GCS: DATA NOT AVAILABLE", result)

    def test_gcs_non_arrival_day_suppresses_dna(self):
        """Non-arrival days should NOT show 'Arrival GCS: DATA NOT AVAILABLE'."""
        data = _minimal_features()
        data["days"] = {
            "2026-01-01": {
                "vitals": {},
                "gcs_daily": {"arrival_gcs": {"value": 15, "source": "HP", "dt": "2026-01-01T02:00:00"},
                              "best_gcs": 15, "worst_gcs": 15},
                "labs_panel_daily": {},
                "device_day_counts": {},
            },
            "2026-01-02": {
                "vitals": {},
                "gcs_daily": {"arrival_gcs": _DNA, "best_gcs": 14, "worst_gcs": 14},
                "labs_panel_daily": {},
                "device_day_counts": {},
            },
        }
        result = render_v5(data)
        # Day 1 should show arrival GCS
        self.assertIn("Arrival GCS: 15", result)
        # Count of "Arrival GCS: DATA NOT AVAILABLE" should be 0 in per-day sections
        # (the patient summary may show it from neuro trigger but that's separate)
        per_day_start = result.index("PER-DAY CLINICAL STATUS")
        per_day_text = result[per_day_start:]
        self.assertNotIn("Arrival GCS: DATA NOT AVAILABLE", per_day_text)

    # ── Fix #1: Note section line cap increased ──

    def test_note_section_shows_more_lines(self):
        """Note sections should show up to 50 lines (not 15)."""
        data = _minimal_features()
        # Create a 30-line impression
        impression_text = "\n".join(f"Line {i+1} of impression" for i in range(30))
        data["features"]["note_sections_v1"] = {
            "sections_present": True,
            "impression": {"present": True, "text": impression_text},
        }
        result = render_v5(data)
        # Line 20 should now be visible (was truncated at 15 before)
        self.assertIn("Line 20 of impression", result)
        self.assertIn("Line 30 of impression", result)
        # Should not show truncation notice for 30 lines
        self.assertNotIn("more lines)", result)

    def test_note_section_truncates_at_50(self):
        """Note sections with >50 lines should still truncate."""
        data = _minimal_features()
        impression_text = "\n".join(f"Line {i+1}" for i in range(60))
        data["features"]["note_sections_v1"] = {
            "sections_present": True,
            "impression": {"present": True, "text": impression_text},
        }
        result = render_v5(data)
        self.assertIn("Line 50", result)
        self.assertIn("(+10 more lines)", result)
        self.assertNotIn("Line 51", result)

    # ── Fix #7: LDA DNA-timestamp polish ──

    def test_lda_dna_placed_ts_polished(self):
        """LDA devices with DNA placed_ts should render 'placement time unknown'."""
        data = _minimal_features()
        data["features"]["lda_events_v1"] = {
            "lda_device_count": 1,
            "active_devices_count": 1,
            "categories_present": ["PIV"],
            "devices": [
                {"device_type": "Peripheral IV", "category": "PIV",
                 "placed_ts": _DNA, "removed_ts": None},
            ],
        }
        result = render_v5(data)
        self.assertIn("placement time unknown", result)
        self.assertNotIn("placed DATA NOT AVAILABLE", result)


# ════════════════════════════════════════════════════════════════════
# B7 — Clinical Narrative Integration
# ════════════════════════════════════════════════════════════════════

from cerebralos.reporting.render_trauma_daily_notes_v5 import (
    _is_noise_line,
    _filter_narrative_text,
    _extract_day_narratives,
    _render_day_narrative,
    _MAX_NARRATIVE_LINES_PER_DAY,
    _MAX_NARRATIVE_LINES_PER_NOTE,
    _MAX_NARRATIVE_NOTES_PER_DAY,
)


def _timeline_item(itype, text, dt="2026-01-01T08:00:00"):
    """Build a minimal timeline item for testing."""
    return {"type": itype, "dt": dt, "payload": {"text": text}}


def _days_data_with_items(items, day_key="2026-01-01"):
    """Build a minimal days_data dict containing the given items."""
    return {"days": {day_key: {"items": items}}, "meta": {}}


class TestB7NoiseFilter(unittest.TestCase):
    """Tests for _is_noise_line deterministic noise filtering."""

    # ── Noise lines that MUST be suppressed ──

    def test_ros_denies_bullet(self):
        self.assertTrue(_is_noise_line("- denies chest pain"))
        self.assertTrue(_is_noise_line("  denies nausea"))

    def test_ros_header(self):
        self.assertTrue(_is_noise_line("Review of Systems:"))
        self.assertTrue(_is_noise_line("  ROS:"))

    def test_mar_hold_threshold(self):
        self.assertTrue(_is_noise_line("hold if SBP <90"))

    def test_mar_header(self):
        self.assertTrue(_is_noise_line("Medication Administration Record"))

    def test_nursing_line_maintenance(self):
        self.assertTrue(_is_noise_line("- site clean, dry, intact"))

    def test_device_status(self):
        self.assertTrue(_is_noise_line("- IV site clean and patent"))

    def test_mychart_disclaimer(self):
        self.assertTrue(_is_noise_line("MyChart progress notes will allow"))

    def test_dictation_disclaimer(self):
        self.assertTrue(_is_noise_line(
            "DISCLAIMER: This report may be partly dictated by voice recognition technology software"
        ))

    def test_epic_ui_artifact(self):
        self.assertTrue(_is_noise_line("Revision History Toggle"))

    def test_signature_line(self):
        self.assertTrue(_is_noise_line("Cosigned by: Dr. Smith"))

    def test_signed_marker(self):
        self.assertTrue(_is_noise_line("  Signed"))
        self.assertTrue(_is_noise_line("  cosign needed"))

    def test_vitals_header(self):
        self.assertTrue(_is_noise_line("Visit Vitals"))
        self.assertTrue(_is_noise_line("  Vitals:"))

    def test_vitals_label_only(self):
        self.assertTrue(_is_noise_line("  BP"))
        self.assertTrue(_is_noise_line("Pulse"))
        self.assertTrue(_is_noise_line("SpO2"))

    def test_vitals_value_with_unit(self):
        self.assertTrue(_is_noise_line("72 bpm"))
        self.assertTrue(_is_noise_line("94%"))

    def test_bp_value_only(self):
        self.assertTrue(_is_noise_line("117/74"))

    def test_height_value_only(self):
        self.assertTrue(_is_noise_line("5' 8\""))

    def test_blank_line(self):
        self.assertTrue(_is_noise_line(""))
        self.assertTrue(_is_noise_line("   "))

    def test_source_type_header(self):
        self.assertTrue(_is_noise_line("[PHYSICIAN_NOTE] something"))

    def test_radiology_stub(self):
        self.assertTrue(_is_noise_line("No results found."))
        self.assertTrue(_is_noise_line("radiology"))

    def test_solo_numeric_value(self):
        self.assertTrue(_is_noise_line("69"))
        self.assertTrue(_is_noise_line("21"))
        self.assertTrue(_is_noise_line("  98.4"))

    def test_temperature_reading(self):
        self.assertTrue(_is_noise_line("98.4 \u00b0F (36.9 \u00b0C) (Oral)"))

    def test_ehr_abnormal_flag(self):
        self.assertTrue(_is_noise_line("(!) 304 lb 10.8 oz (138.2 kg)"))

    def test_smoking_status_value(self):
        self.assertTrue(_is_noise_line("Never"))
        self.assertTrue(_is_noise_line("Former"))

    def test_standalone_date(self):
        self.assertTrue(_is_noise_line("1/5/2026"))
        self.assertTrue(_is_noise_line("  12/31/2025"))

    def test_author_name_line(self):
        self.assertTrue(_is_noise_line("Ally Wood, NP"))
        self.assertTrue(_is_noise_line("Rachel N Bertram, NP"))

    # ── Clinical lines that MUST be kept ──

    def test_keeps_chief_complaint(self):
        self.assertFalse(_is_noise_line("CC: intubated and sedated"))

    def test_keeps_assessment_plan(self):
        self.assertFalse(_is_noise_line("A/P: This is a 72 y.o. male"))

    def test_keeps_clinical_finding(self):
        self.assertFalse(_is_noise_line("Lungs: Breath sounds present and equal bilaterally"))

    def test_keeps_plan_bullet(self):
        self.assertFalse(_is_noise_line("- Will plan to treat in a hard TLSO brace."))

    def test_keeps_subjective(self):
        self.assertFalse(_is_noise_line("S: Intubated for worsening hypercapnia"))

    def test_keeps_gcs_inline(self):
        self.assertFalse(_is_noise_line("GCS: 10T"))

    def test_keeps_pe_header(self):
        self.assertFalse(_is_noise_line("PE:"))

    def test_keeps_embedded_vitals(self):
        """Vitals embedded in prose (e.g., PE section) must survive."""
        self.assertFalse(_is_noise_line(
            "Vitals: Blood pressure 116/66, pulse 68, temperature 98.4 \u00b0F (36.9 \u00b0C)"
        ))


class TestB7FilterNarrativeText(unittest.TestCase):
    """Tests for _filter_narrative_text (multi-line filtering)."""

    def test_strips_noise_keeps_content(self):
        raw = "Signed\nCC: intubated\n\n\n\nA/P: plan here\n117/74\n"
        lines = _filter_narrative_text(raw)
        self.assertIn("CC: intubated", lines)
        self.assertIn("A/P: plan here", lines)
        self.assertNotIn("Signed", lines)
        self.assertNotIn("117/74", lines)

    def test_collapses_consecutive_blanks(self):
        raw = "line1\n\n\n\nline2"
        lines = _filter_narrative_text(raw)
        self.assertEqual(lines, ["line1", "line2"])

    def test_empty_input_returns_empty(self):
        self.assertEqual(_filter_narrative_text(""), [])
        self.assertEqual(_filter_narrative_text("   \n  \n"), [])


class TestB7ExtractDayNarratives(unittest.TestCase):
    """Tests for _extract_day_narratives."""

    def test_skips_lab_and_radiology(self):
        items = [
            _timeline_item("LAB", "WBC 12.3"),
            _timeline_item("RADIOLOGY", "CT head normal"),
        ]
        result = _extract_day_narratives(items)
        self.assertEqual(result, [])

    def test_keeps_physician_note(self):
        items = [_timeline_item("PHYSICIAN_NOTE", "CC: fall\nA/P: observe")]
        result = _extract_day_narratives(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "PHYSICIAN_NOTE")

    def test_sorted_by_dt(self):
        items = [
            _timeline_item("PHYSICIAN_NOTE", "Late note", dt="2026-01-01T14:00:00"),
            _timeline_item("CONSULT_NOTE", "Early consult", dt="2026-01-01T08:00:00"),
        ]
        result = _extract_day_narratives(items)
        self.assertEqual(result[0]["type"], "CONSULT_NOTE")
        self.assertEqual(result[1]["type"], "PHYSICIAN_NOTE")

    def test_empty_payload_skipped(self):
        items = [_timeline_item("PHYSICIAN_NOTE", "")]
        self.assertEqual(_extract_day_narratives(items), [])


class TestB7RenderDayNarrative(unittest.TestCase):
    """Tests for _render_day_narrative (full render path)."""

    def test_narrative_renders_with_type_tag(self):
        items = [_timeline_item("PHYSICIAN_NOTE", "S: fever\nA/P: antibiotics")]
        lines = _render_day_narrative(items)
        self.assertTrue(any("Clinical Narrative:" in l for l in lines))
        self.assertTrue(any("[PHYSICIAN_NOTE]" in l for l in lines))
        self.assertTrue(any("S: fever" in l for l in lines))

    def test_empty_items_returns_empty(self):
        self.assertEqual(_render_day_narrative([]), [])

    def test_narrative_absent_for_skip_types_only(self):
        items = [_timeline_item("LAB", "WBC 12"), _timeline_item("RADIOLOGY", "CT ok")]
        self.assertEqual(_render_day_narrative(items), [])

    def test_per_note_cap(self):
        """Notes longer than _MAX_NARRATIVE_LINES_PER_NOTE get truncated."""
        big_text = "\n".join(f"Clinical line {i}" for i in range(_MAX_NARRATIVE_LINES_PER_NOTE + 10))
        items = [_timeline_item("PHYSICIAN_NOTE", big_text)]
        lines = _render_day_narrative(items)
        text = "\n".join(lines)
        self.assertIn("truncated", text)
        # Should not contain lines beyond the cap
        self.assertNotIn(f"Clinical line {_MAX_NARRATIVE_LINES_PER_NOTE + 5}", text)

    def test_per_day_cap(self):
        """Total narrative lines across notes capped at _MAX_NARRATIVE_LINES_PER_DAY."""
        items = []
        for i in range(10):
            text = "\n".join(f"Note{i} line{j}" for j in range(10))
            items.append(_timeline_item("PHYSICIAN_NOTE", text, dt=f"2026-01-01T{8+i:02d}:00:00"))
        lines = _render_day_narrative(items)
        text = "\n".join(lines)
        self.assertIn("narrative cap reached", text)

    def test_notes_per_day_cap(self):
        """No more than _MAX_NARRATIVE_NOTES_PER_DAY notes rendered."""
        items = []
        for i in range(_MAX_NARRATIVE_NOTES_PER_DAY + 3):
            items.append(_timeline_item("PHYSICIAN_NOTE", f"Short note {i}", dt=f"2026-01-01T{8+i:02d}:00:00"))
        lines = _render_day_narrative(items)
        text = "\n".join(lines)
        self.assertIn("suppressed", text)

    def test_determinism(self):
        """Same input produces identical output across runs."""
        items = [
            _timeline_item("PHYSICIAN_NOTE", "CC: fall\nA/P: observe", dt="2026-01-01T08:00:00"),
            _timeline_item("CONSULT_NOTE", "Consult text here", dt="2026-01-01T10:00:00"),
        ]
        r1 = _render_day_narrative(items)
        r2 = _render_day_narrative(items)
        self.assertEqual(r1, r2)


class TestB7NarrativeIntegration(unittest.TestCase):
    """Integration: narrative renders in full render_v5 output."""

    def test_narrative_renders_when_days_data_present(self):
        data = _minimal_features()
        items = [_timeline_item("PHYSICIAN_NOTE", "CC: trauma\nA/P: observe")]
        days_data = _days_data_with_items(items)
        result = render_v5(data, days_data=days_data)
        self.assertIn("Clinical Narrative:", result)
        self.assertIn("[PHYSICIAN_NOTE]", result)
        self.assertIn("CC: trauma", result)

    def test_narrative_absent_when_no_days_data(self):
        data = _minimal_features()
        result = render_v5(data)
        self.assertNotIn("Clinical Narrative:", result)

    def test_narrative_absent_when_days_data_empty(self):
        data = _minimal_features()
        result = render_v5(data, days_data={"days": {}, "meta": {}})
        self.assertNotIn("Clinical Narrative:", result)

    def test_narrative_absent_for_day_with_only_labs(self):
        data = _minimal_features()
        items = [_timeline_item("LAB", "WBC 12.3")]
        days_data = _days_data_with_items(items)
        result = render_v5(data, days_data=days_data)
        self.assertNotIn("Clinical Narrative:", result)

    def test_noise_suppressed_in_full_render(self):
        data = _minimal_features()
        text = "Signed\nCC: trauma\n117/74\nA/P: plan\nNever"
        items = [_timeline_item("PHYSICIAN_NOTE", text)]
        days_data = _days_data_with_items(items)
        result = render_v5(data, days_data=days_data)
        self.assertIn("CC: trauma", result)
        self.assertIn("A/P: plan", result)
        # Noise must be absent
        lines = result.split("\n")
        narrative_lines = [l.strip() for l in lines if l.strip()]
        self.assertNotIn("Signed", narrative_lines)
        self.assertNotIn("117/74", narrative_lines)
        self.assertNotIn("Never", narrative_lines)


if __name__ == "__main__":
    unittest.main()
