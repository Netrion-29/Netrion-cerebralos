#!/usr/bin/env python3
"""
Tests for PI RN Casefile v1 renderer.

Covers:
  - Happy-path render from minimal bundle
  - Required section presence in output HTML
  - Omission / fail-closed when optional sections are absent
  - Deterministic output for same bundle input
  - Output path generation via render_casefile_to_file
  - NTDS badge rendering
  - Day accordion rendering
  - LOS computation
"""

import json
import re
import pytest
from pathlib import Path

from cerebralos.reporting.render_pi_rn_casefile_v1 import (
    render_casefile,
    render_casefile_to_file,
    _compute_los,
    _render_vitals,
    _render_gcs,
    _render_labs,
    _render_plans,
    _render_consultant_plans,
    _outcome_badge,
    _render_status_bar,
    _render_compliance_snapshot,
    _render_admission_snapshot,
    _render_first_day_snapshot,
    _render_primary_injuries,
    _render_imaging_studies,
    _render_procedures,
    _render_devices,
    _render_prophylaxis,
    _render_resuscitation,
)


# ── Test fixtures ───────────────────────────────────────────────────

_FULL_BUNDLE = {
    "build": {
        "bundle_version": "1.0",
        "generated_at_utc": "2026-03-22T12:00:00Z",
        "assembler": "build_patient_bundle_v1",
    },
    "patient": {
        "patient_id": "12345",
        "patient_name": "Betty Lynette Roll",
        "dob": "3/10/1954",
        "slug": "Betty_Roll",
        "arrival_datetime": "2026-01-01 10:05:00",
        "discharge_datetime": "2026-01-05 17:41:00",
        "trauma_category": "Blunt",
    },
    "summary": {
        "mechanism": {
            "mechanism_present": "yes",
            "mechanism_primary": "fall",
            "mechanism_labels": ["fall"],
            "penetrating_mechanism": False,
            "body_region_present": "yes",
            "body_region_labels": ["head", "chest", "spine"],
        },
        "pmh": {
            "pmh_items": [
                {"text": "Hypertension"},
                {"text": "Diabetes"},
            ],
            "social_items": [],
            "allergy_items": [],
        },
        "anticoagulants": {
            "on_anticoagulant": True,
            "agents": ["Warfarin"],
        },
        "demographics": {"sex": "F"},
        "activation": {"category": "Level II"},
        "shock_trigger": {"shock_triggered": False},
        "age": {"age_years": 71, "age": 71},
        "injuries": {
            "findings_present": "yes",
            "findings_labels": ["rib_fracture", "spinal_fracture"],
            "pneumothorax": None,
            "hemothorax": None,
            "rib_fracture": {
                "present": True,
                "count": 5,
                "rib_numbers": ["5", "6", "7", "9", "10"],
                "laterality": "right",
                "raw_line_id": "rib001",
            },
            "flail_chest": None,
            "solid_organ_injuries": [],
            "intracranial_hemorrhage": [
                {"subtype": "sdh", "present": True, "raw_line_id": "ich001"},
            ],
            "pelvic_fracture": None,
            "spinal_fracture": {"present": True, "level": "T12", "raw_line_id": "sp001"},
            "extremity_fracture": [
                {"bone": "femur", "present": True, "laterality": "left", "pathologic": False, "raw_line_id": "ef001"},
            ],
            "source_rule_id": "radiology_findings",
            "evidence": [
                {"raw_line_id": "rib001", "source": "RADIOLOGY", "ts": "2026-01-01T13:00:00", "snippet": "5 right-sided rib fractures", "role": "finding", "label": "rib_fracture"},
                {"raw_line_id": "sp001", "source": "RADIOLOGY", "ts": "2026-01-01T14:00:00", "snippet": "T12 compression fracture", "role": "finding", "label": "spinal_fracture"},
            ],
            "notes": [],
            "warnings": [],
        },
        "imaging": {
            "findings_present": "yes",
            "findings_labels": ["rib_fracture", "spinal_fracture"],
            "evidence": [
                {"raw_line_id": "rib001", "source": "RADIOLOGY", "ts": "2026-01-01T13:00:00", "snippet": "5 right-sided rib fractures", "role": "finding", "label": "rib_fracture"},
                {"raw_line_id": "sp001", "source": "RADIOLOGY", "ts": "2026-01-01T14:00:00", "snippet": "T12 compression fracture", "role": "finding", "label": "spinal_fracture"},
            ],
            "notes": [],
            "warnings": [],
        },
        "procedures": {
            "events": [
                {
                    "ts": "2026-01-02T12:32:00",
                    "source_kind": "PROCEDURE",
                    "category": "operative",
                    "label": "Endotracheal intubation",
                    "raw_line_id": "proc001",
                    "evidence": [{"role": "procedure_event", "snippet": "intubation", "raw_line_id": "proc001"}],
                },
                {
                    "ts": "2026-01-03T09:15:00",
                    "source_kind": "OP_NOTE",
                    "category": "operative",
                    "label": "Percutaneous tracheostomy",
                    "raw_line_id": "proc002",
                    "preop_dx": "rib fractures",
                    "evidence": [{"role": "procedure_event", "snippet": "tracheostomy", "raw_line_id": "proc002"}],
                },
            ],
            "procedure_event_count": 0,
            "operative_event_count": 2,
            "anesthesia_event_count": 0,
            "categories_present": ["operative"],
            "evidence": [],
            "warnings": [],
            "notes": [],
            "source_rule_id": "procedure_operatives_v1",
        },
        "devices": {
            "devices": [
                {
                    "device_type": "Peripheral IV",
                    "device_label": "PIV #1",
                    "category": "PIV",
                    "placed_ts": "01/01/26 1030",
                    "removed_ts": "01/03/26 0800",
                    "duration_text": "2 days",
                    "site": "Left hand",
                    "source_format": "LDA",
                    "assessment_count": 5,
                    "event_rows": 8,
                    "evidence": [{"raw_line_id": "lda001"}],
                },
                {
                    "device_type": "Triple Lumen Catheter",
                    "device_label": "Central Line #1",
                    "category": "Central Line",
                    "placed_ts": "01/01/26 1200",
                    "removed_ts": None,
                    "duration_text": None,
                    "site": "Right subclavian",
                    "source_format": "LDA",
                    "assessment_count": 3,
                    "event_rows": 4,
                    "evidence": [{"raw_line_id": "lda002"}],
                },
            ],
            "lda_device_count": 2,
            "active_devices_count": 1,
            "categories_present": ["Central Line", "PIV"],
            "devices_with_placement": ["Central Line #1", "PIV #1"],
            "devices_with_removal": ["PIV #1"],
            "source_file": "test.txt",
            "source_rule_id": "lda_events_raw_file",
            "warnings": [],
            "notes": [],
        },
        "dvt_prophylaxis": {
            "pharm_first_ts": "2026-01-01T20:00:00",
            "mech_first_ts": None,
            "first_ts": "2026-01-01T20:00:00",
            "delay_hours": 9.9,
            "delay_flag_24h": False,
            "excluded_reason": None,
            "orders_only_count": 0,
            "pharm_admin_evidence_count": 1,
            "pharm_ambiguous_mention_count": 0,
            "mech_admin_evidence_count": 0,
            "evidence": {"pharm": [], "mech": [], "exclusion": []},
        },
        "gi_prophylaxis": {
            "pharm_first_ts": "2026-01-01T20:05:00",
            "delay_hours": 10.0,
            "delay_flag_48h": False,
            "excluded_reason": None,
            "pharm_admin_evidence_count": 1,
            "pharm_ambiguous_mention_count": 0,
            "orders_only_count": 0,
            "evidence": {"pharm": [], "exclusion": []},
        },
        "seizure_prophylaxis": {
            "detected": True,
            "agents": ["Levetiracetam"],
            "home_med_present": False,
            "first_mention_ts": "2026-01-01T12:00:00",
            "first_admin_ts": "2026-01-01T14:00:00",
            "discontinued": False,
            "discontinued_ts": None,
            "dose_entries": [{"agent": "Levetiracetam", "dose_text": "500mg", "route": "IV", "frequency": "BID"}],
            "admin_evidence_count": 2,
            "mention_evidence_count": 1,
            "evidence": {"admin": [], "mention": [], "discontinued": []},
        },
        "base_deficit": {
            "initial_bd_ts": "2026-01-01T08:30:00",
            "initial_bd_value": 4.3,
            "initial_bd_source": "unknown",
            "initial_bd_raw_line_id": "bd001",
            "category1_bd_validated": False,
            "validation_failure_reason": "specimen source not confirmed arterial",
            "trigger_bd_gt4": True,
            "first_trigger_ts": "2026-01-01T08:30:00",
            "bd_series": [
                {"ts": "2026-01-01T08:30:00", "value": 4.3, "specimen": "unknown", "raw_line_id": "bd001", "snippet": "BD 4.3"},
                {"ts": "2026-01-01T14:00:00", "value": 2.1, "specimen": "unknown", "raw_line_id": "bd002", "snippet": "BD 2.1"},
            ],
            "monitoring_windows": [],
            "overall_compliant": False,
            "noncompliance_reasons": ["q2h_until_improving: gap 5.5h"],
            "notes": [],
        },
        "transfusions": {
            "status": "DATA NOT AVAILABLE",
            "products_detected": [],
            "mtp_activated": False,
            "txa_administered": False,
            "prbc_events": 0,
            "ffp_events": 0,
            "platelet_events": 0,
            "cryo_events": 0,
            "total_events": 0,
            "evidence": [],
        },
        "hemodynamic_instability": {
            "pattern_present": "yes",
            "hypotension_pattern": {
                "detected": True,
                "reading_count": 3,
                "days_affected": 2,
                "threshold": "SBP < 90",
                "source_rule_id": "hemo_sbp_lt90",
            },
            "map_low_pattern": {
                "detected": True,
                "reading_count": 6,
                "days_affected": 5,
                "threshold": "MAP < 65",
                "source_rule_id": "hemo_map_lt65",
            },
            "tachycardia_pattern": {
                "detected": False,
                "reading_count": 0,
                "days_affected": 0,
                "threshold": "HR > 120",
                "source_rule_id": "hemo_hr_gt120",
            },
            "patterns_detected": ["hypotension", "map_low"],
            "total_abnormal_readings": 9,
            "total_vitals_readings": 245,
            "source_rule_id": "hemodynamic_instability_pattern_canonical_vitals",
            "evidence": [],
            "notes": [],
            "warnings": [],
        },
    },
    "compliance": {
        "ntds_summary": [{"events": 21}],
        "ntds_event_outcomes": {
            "1": {"event_id": 1, "canonical_name": "AKI", "outcome": "NO"},
            "9": {"event_id": 9, "canonical_name": "Delirium", "outcome": "YES"},
            "5": {"event_id": 5, "canonical_name": "CAUTI", "outcome": "EXCLUDED"},
            "8": {"event_id": 8, "canonical_name": "DVT", "outcome": "UNABLE_TO_DETERMINE"},
        },
        "protocol_results": [
            {"protocol": "DVT Prophylaxis", "outcome": "COMPLIANT"},
            {"protocol": "Spinal Clearance", "outcome": "NON_COMPLIANT"},
        ],
    },
    "daily": {
        "2026-01-01": {
            "vitals": {
                "records": [{"hr": 88, "sbp": 130, "dbp": 72, "resp": 18, "spo2": 97}],
                "count": 1,
                "abnormal_total": 0,
            },
            "labs": {
                "latest": {
                    "Hemoglobin": {
                        "component": "Hemoglobin",
                        "value_num": 12.5,
                        "value_raw": "12.5",
                        "flags": [],
                        "unit": "GM/DL",
                    },
                    "Glucose": {
                        "component": "Glucose",
                        "value_num": 320.0,
                        "value_raw": "320",
                        "flags": ["H"],
                        "unit": "MG/DL",
                    },
                },
                "daily": {},
                "series": {},
            },
            "gcs": {
                "arrival_gcs_value": 15,
                "arrival_gcs": {"value": 15, "intubated": False, "source": "TRAUMA_HP", "dt": "2026-01-01T10:10:00", "timestamp_quality": "exact"},
                "best_gcs": {"value": 15, "intubated": False, "source": "TRAUMA_HP", "dt": "2026-01-01T10:10:00", "timestamp_quality": "exact"},
                "worst_gcs": {"value": 15, "intubated": False, "source": "TRAUMA_HP", "dt": "2026-01-01T10:10:00", "timestamp_quality": "exact"},
                "all_readings": [{"value": 15, "intubated": False, "source": "TRAUMA_HP"}],
                "warnings": [],
            },
            "ventilator": None,
            "plans": None,
            "consultant_plans": {
                "services": {
                    "Ortho": {
                        "items": [
                            {
                                "ts": "2026-01-01T12:00:00",
                                "author_name": "Dr. Jones",
                                "item_text": "Non-operative management of L2 fracture",
                                "item_type": "recommendation",
                                "evidence": [],
                            }
                        ]
                    }
                },
                "service_count": 1,
                "item_count": 1,
            },
        },
        "2026-01-02": {
            "vitals": {
                "records": [{"hr": 78, "sbp": 124}],
                "count": 1,
                "abnormal_total": 0,
            },
            "labs": None,
            "gcs": None,
            "ventilator": None,
            "plans": None,
            "consultant_plans": None,
        },
    },
    "consultants": {
        "consultant_present": "yes",
        "consultant_services_count": 2,
        "consultant_services": ["Ortho", "Neurosurgery"],
        "source_rule_id": "consultant_events",
        "warnings": [],
        "notes": [],
    },
    "artifacts": {
        "evidence_path": "outputs/evidence/Betty_Roll/patient_evidence_v1.json",
        "timeline_path": "outputs/timeline/Betty_Roll/patient_days_v1.json",
        "features_path": "outputs/features/Betty_Roll/patient_features_v1.json",
        "ntds_summary_path": "outputs/ntds/Betty_Roll/ntds_summary_2026_v1.json",
        "protocol_results_path": None,
        "v5_report_path": "outputs/reporting/Betty_Roll/TRAUMA_DAILY_NOTES_v5.txt",
    },
    "warnings": ["test warning"],
}

_MINIMAL_BUNDLE = {
    "build": {
        "bundle_version": "1.0",
        "generated_at_utc": "2026-03-22T12:00:00Z",
        "assembler": "build_patient_bundle_v1",
    },
    "patient": {
        "patient_id": "DATA_NOT_AVAILABLE",
        "patient_name": "Minimal Patient",
        "dob": "",
        "slug": "Minimal_Patient",
        "arrival_datetime": None,
        "discharge_datetime": None,
        "trauma_category": "DATA_NOT_AVAILABLE",
    },
    "summary": {
        "mechanism": None,
        "pmh": None,
        "anticoagulants": None,
        "demographics": None,
        "activation": None,
        "shock_trigger": None,
        "age": None,
        "injuries": None,
        "imaging": None,
        "procedures": None,
        "devices": None,
        "dvt_prophylaxis": None,
        "gi_prophylaxis": None,
        "seizure_prophylaxis": None,
        "base_deficit": None,
        "transfusions": None,
        "hemodynamic_instability": None,
    },
    "compliance": {
        "ntds_summary": None,
        "ntds_event_outcomes": None,
        "protocol_results": None,
    },
    "daily": {},
    "consultants": None,
    "artifacts": {
        "evidence_path": "outputs/evidence/Minimal_Patient/patient_evidence_v1.json",
        "timeline_path": "outputs/timeline/Minimal_Patient/patient_days_v1.json",
        "features_path": "outputs/features/Minimal_Patient/patient_features_v1.json",
        "ntds_summary_path": None,
        "protocol_results_path": None,
        "v5_report_path": None,
    },
    "warnings": [],
}


# ── Tests ───────────────────────────────────────────────────────────

class TestRenderCasefile:
    def test_happy_path_produces_valid_html(self):
        html = render_casefile(_FULL_BUNDLE)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "Betty Lynette Roll" in html

    def test_required_sections_present(self):
        html = render_casefile(_FULL_BUNDLE)
        # Patient info card
        assert "Patient Information" in html
        # MOI
        assert "Mechanism of Injury" in html
        assert "fall" in html
        # PMH
        assert "PMH" in html
        assert "Hypertension" in html
        assert "Warfarin" in html
        # Consultants
        assert "Consultants" in html
        assert "Ortho" in html
        assert "Neurosurgery" in html
        # NTDS
        assert "NTDS Hospital Event Outcomes" in html
        assert "AKI" in html
        assert "Delirium" in html
        # Protocol compliance
        assert "Protocol Compliance" in html
        assert "DVT Prophylaxis" in html
        # Day cards
        assert "Hospital Day 1" in html
        assert "Hospital Day 2" in html
        assert "2026-01-01" in html

    def test_ntds_badges_present(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "badge-yes" in html
        assert "badge-no" in html
        assert "badge-excluded" in html
        assert "badge-utd" in html

    def test_vitals_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "HR" in html
        assert "88" in html
        assert "SBP" in html

    def test_gcs_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "GCS" in html
        assert "15" in html
        assert "gcs-ok" in html

    def test_labs_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Labs" in html
        assert "Hemoglobin" in html
        assert "12.5" in html

    def test_consultant_plans_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Non-operative management of L2 fracture" in html
        assert "Ortho" in html

    def test_warnings_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Warnings" in html
        assert "test warning" in html

    def test_footer_has_build_info(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "bundle v1.0" in html
        assert "build_patient_bundle_v1" in html


class TestFailClosed:
    def test_minimal_bundle_renders_without_error(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert html.startswith("<!DOCTYPE html>")
        assert "Minimal Patient" in html

    def test_absent_ntds_omits_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "NTDS Hospital Event Outcomes" not in html

    def test_absent_protocols_omits_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Protocol Compliance" not in html

    def test_absent_moi_omits_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Mechanism of Injury" not in html

    def test_absent_pmh_omits_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        # PMH card should not appear when both pmh and anticoagulants are null
        assert "PMH / Anticoagulants" not in html

    def test_absent_consultants_omits_card(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        # Detail card should not appear when consultants are null
        assert 'card-title">Consultants</div>' not in html

    def test_empty_daily_shows_no_day_cards(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Hospital Day" not in html

    def test_no_warnings_omits_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        # The Warnings card title should not appear (CSS comment is ok)
        assert '>Warnings</div>' not in html


class TestDeterministic:
    def test_same_input_same_output(self):
        html1 = render_casefile(_FULL_BUNDLE)
        html2 = render_casefile(_FULL_BUNDLE)
        assert html1 == html2

    def test_day_order_is_chronological(self):
        html = render_casefile(_FULL_BUNDLE)
        idx_day1 = html.index("2026-01-01")
        idx_day2 = html.index("2026-01-02")
        assert idx_day1 < idx_day2


class TestOutputPath:
    def test_render_to_file(self, tmp_path):
        bundle_path = tmp_path / "patient_bundle_v1.json"
        bundle_path.write_text(
            json.dumps(_FULL_BUNDLE, indent=2), encoding="utf-8"
        )
        out_path = tmp_path / "casefile" / "casefile_v1.html"
        render_casefile_to_file(bundle_path, out_path)
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Betty Lynette Roll" in content

    def test_missing_bundle_file(self, tmp_path):
        from cerebralos.reporting.render_pi_rn_casefile_v1 import main as cli_main
        import sys
        old_argv = sys.argv
        sys.argv = [
            "render_pi_rn_casefile_v1",
            "--bundle", str(tmp_path / "nonexistent.json"),
            "--out", str(tmp_path / "out.html"),
        ]
        try:
            rc = cli_main()
            assert rc == 1
        finally:
            sys.argv = old_argv


class TestLOS:
    def test_compute_los_valid(self):
        assert _compute_los("2026-01-01 10:00:00", "2026-01-05 17:00:00") == 4

    def test_compute_los_same_day(self):
        assert _compute_los("2026-01-01 10:00:00", "2026-01-01 17:00:00") == 0

    def test_compute_los_none(self):
        assert _compute_los(None, "2026-01-05") is None
        assert _compute_los("2026-01-01", None) is None

    def test_compute_los_iso_format(self):
        assert _compute_los("2026-01-01T08:00:00", "2026-01-03T12:00:00") == 2


class TestCanonicalVitals:
    """Tests for canonical vitals_canonical_v1 shape: {"records": [...]}."""

    _CANONICAL_VITALS = {
        "records": [
            {
                "ts": "2026-01-01T11:23:00",
                "day": "2026-01-01",
                "source": "NURSING_NOTE",
                "confidence": 50,
                "raw_line_id": "abf573bcc8f62f87",
                "sbp": 181.0,
                "dbp": 74.0,
                "map": 109.7,
                "hr": 62.0,
                "rr": 18.0,
                "spo2": 92.0,
                "temp_c": 36.9,
                "temp_f": 98.5,
                "o2_device": None,
                "o2_flow_lpm": None,
            }
        ]
    }

    def test_canonical_shape_renders(self):
        html = _render_vitals(self._CANONICAL_VITALS)
        assert "Vitals" in html
        assert "62.0" in html   # hr
        assert "181.0" in html  # sbp
        assert "18.0" in html   # rr

    def test_canonical_temp_rendered(self):
        html = _render_vitals(self._CANONICAL_VITALS)
        assert "Temp" in html
        assert "98.5" in html   # temp_f preferred over temp_c

    def test_flat_list_still_works(self):
        html = _render_vitals([{"hr": 88, "sbp": 130, "resp": 18}])
        assert "88" in html
        assert "130" in html
        assert "RR" in html

    def test_empty_records_returns_empty(self):
        assert _render_vitals({"records": []}) == ""

    def test_none_returns_empty(self):
        assert _render_vitals(None) == ""


class TestErrorBadge:
    def test_error_badge_has_correct_class(self):
        badge = _outcome_badge("ERROR")
        assert "badge-error" in badge

    def test_error_badge_case_insensitive(self):
        badge = _outcome_badge("error")
        assert "badge-error" in badge


# ── Clinical Status Bar tests ────────────────────────────────────

class TestClinicalStatusBar:
    def test_status_bar_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "status-bar" in html

    def test_activation_chip_present(self):
        out = _render_status_bar(_FULL_BUNDLE)
        assert "Activation" in out
        assert "Level" in out

    def test_shock_not_triggered(self):
        out = _render_status_bar(_FULL_BUNDLE)
        assert "Not Triggered" in out

    def test_shock_triggered_yes(self):
        b = {"summary": {"shock_trigger": {"shock_triggered": "yes"}}}
        out = _render_status_bar(b)
        assert "Triggered" in out
        assert "sc-alert" in out

    def test_shock_triggered_bool_true(self):
        b = {"summary": {"shock_trigger": {"shock_triggered": True}}}
        out = _render_status_bar(b)
        assert "sc-alert" in out

    def test_anticoag_yes(self):
        out = _render_status_bar(_FULL_BUNDLE)
        assert "Anticoagulation" in out
        assert "sc-alert" in out

    def test_anticoag_no(self):
        b = {"summary": {"anticoagulants": {"on_anticoagulant": False}}}
        out = _render_status_bar(b)
        assert "sc-ok" in out

    def test_anticoag_absent(self):
        out = _render_status_bar(_MINIMAL_BUNDLE)
        assert "Anticoagulation" in out

    def test_penetrating_no(self):
        out = _render_status_bar(_FULL_BUNDLE)
        assert "Penetrating" in out
        assert "sc-ok" in out

    def test_penetrating_yes(self):
        b = {"summary": {"mechanism": {"penetrating_mechanism": True}}}
        out = _render_status_bar(b)
        assert "sc-alert" in out

    def test_discharge_status_discharged(self):
        out = _render_status_bar(_FULL_BUNDLE)
        assert "Discharged" in out

    def test_discharge_status_active(self):
        b = {"patient": {"arrival_datetime": "2026-01-01", "discharge_datetime": None}}
        out = _render_status_bar(b)
        assert "Active" in out

    def test_minimal_bundle_renders_status_bar(self):
        out = _render_status_bar(_MINIMAL_BUNDLE)
        assert "status-bar" in out


# ── Compliance Snapshot tests ────────────────────────────────────

class TestComplianceSnapshot:
    def test_snapshot_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "compliance-snap" in html

    def test_ntds_yes_count(self):
        out = _render_compliance_snapshot(_FULL_BUNDLE)
        assert "NTDS YES" in out
        # 1 YES event in fixture
        assert '>1</div>' in out

    def test_ntds_utd_count(self):
        out = _render_compliance_snapshot(_FULL_BUNDLE)
        assert "NTDS UTD" in out
        # UNABLE_TO_DETERMINE (DVT event) must count toward UTD bucket
        assert 'csnap-utd' in out
        # Exactly 1 UTD event in fixture
        assert '<div class="cn">1</div>' in out.split('NTDS UTD')[0].split('csnap-box')[-1]

    def test_protocol_nc_count(self):
        out = _render_compliance_snapshot(_FULL_BUNDLE)
        assert "Protocol NC" in out

    def test_compliance_absent_omits_section(self):
        out = _render_compliance_snapshot(_MINIMAL_BUNDLE)
        assert out == ""

    def test_zero_counts_green(self):
        b = {
            "compliance": {
                "ntds_event_outcomes": {
                    "1": {"outcome": "NO"},
                    "2": {"outcome": "NO"},
                },
                "protocol_results": [{"outcome": "COMPLIANT"}],
            }
        }
        out = _render_compliance_snapshot(b)
        assert "csnap-clear" in out
        assert "csnap-yes" not in out


# ── Admission Snapshot tests ─────────────────────────────────────

class TestAdmissionSnapshot:
    def test_snapshot_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Admission Snapshot" in html

    def test_arrival_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "2026-01-01" in out

    def test_mechanism_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "Fall" in out

    def test_age_sex_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "71" in out
        assert "F" in out

    def test_body_regions_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "Head" in out
        assert "Chest" in out

    def test_consultants_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "Ortho" in out
        assert "Neurosurgery" in out

    def test_pmh_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "Hypertension" in out

    def test_anticoag_agents_shown(self):
        out = _render_admission_snapshot(_FULL_BUNDLE)
        assert "Warfarin" in out

    def test_minimal_bundle_still_renders(self):
        out = _render_admission_snapshot(_MINIMAL_BUNDLE)
        assert "Admission Snapshot" in out
        # All fields should be dashes
        assert "\u2014" in out


# ── First-Day Snapshot tests ─────────────────────────────────────

class TestFirstDaySnapshot:
    def test_snapshot_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Day 1 Clinical Snapshot" in html

    def test_vitals_in_snapshot(self):
        out = _render_first_day_snapshot(_FULL_BUNDLE)
        assert "88" in out   # HR
        assert "130" in out  # SBP

    def test_gcs_in_snapshot(self):
        out = _render_first_day_snapshot(_FULL_BUNDLE)
        assert "GCS" in out
        assert "15" in out

    def test_labs_in_snapshot(self):
        out = _render_first_day_snapshot(_FULL_BUNDLE)
        assert "Hemoglobin" in out
        assert "12.5" in out

    def test_earliest_day_selected(self):
        """Snapshot uses the chronologically earliest day."""
        b = {
            "daily": {
                "2026-01-03": {"vitals": [{"hr": 99}]},
                "2026-01-01": {"vitals": [{"hr": 77}]},
                "2026-01-02": {"vitals": [{"hr": 88}]},
            }
        }
        out = _render_first_day_snapshot(b)
        assert "77" in out
        assert "2026-01-01" in out

    def test_empty_daily_omits_snapshot(self):
        out = _render_first_day_snapshot(_MINIMAL_BUNDLE)
        assert out == ""

    def test_no_vitals_no_gcs_omits_snapshot(self):
        b = {"daily": {"2026-01-01": {"vitals": None, "gcs": None, "labs": None, "ventilator": None}}}
        out = _render_first_day_snapshot(b)
        assert out == ""

    def test_deterministic_first_day(self):
        out1 = _render_first_day_snapshot(_FULL_BUNDLE)
        out2 = _render_first_day_snapshot(_FULL_BUNDLE)
        assert out1 == out2


# ── Above-the-fold ordering test ─────────────────────────────────

class TestAboveFoldOrdering:
    def test_status_bar_before_compliance(self):
        html = render_casefile(_FULL_BUNDLE)
        assert html.index("status-bar") < html.index("compliance-snap")

    def test_compliance_before_admission(self):
        html = render_casefile(_FULL_BUNDLE)
        assert html.index("compliance-snap") < html.index("Admission Snapshot")

    def test_admission_before_first_day(self):
        html = render_casefile(_FULL_BUNDLE)
        assert html.index("Admission Snapshot") < html.index("Day 1 Clinical Snapshot")

    def test_above_fold_before_detail(self):
        html = render_casefile(_FULL_BUNDLE)
        assert html.index("Day 1 Clinical Snapshot") < html.index("Patient Information")


# ── Plans rendering ─────────────────────────────────────────────────

class TestPlansRendering:
    """Verify _render_plans handles real nested notes shape."""

    def test_notes_shape_renders_note_type(self):
        plans = {
            "notes": [
                {
                    "note_type": "Trauma Progress Note",
                    "author": "Dr. Smith",
                    "dt": "2026-01-01T11:00:00",
                    "impression_lines": ["s/p fall"],
                    "plan_lines": ["Serial neuro checks"],
                    "raw_line_id": "abc",
                }
            ]
        }
        out = _render_plans(plans)
        assert "Trauma Progress Note" in out
        assert "Dr. Smith" in out
        assert "plan-note-header" in out

    def test_notes_impression_and_plan_lines(self):
        plans = {
            "notes": [
                {
                    "note_type": "Note",
                    "author": "",
                    "impression_lines": ["Acute SDH"],
                    "plan_lines": ["Maintain SBP < 150"],
                }
            ]
        }
        out = _render_plans(plans)
        assert "Acute SDH" in out
        assert "Maintain SBP" in out
        assert "impression-lines" in out
        assert "plan-lines" in out

    def test_empty_notes_returns_empty(self):
        assert _render_plans({"notes": []}) == ""
        assert _render_plans(None) == ""
        assert _render_plans({}) == ""

    def test_legacy_flat_dict_fallback(self):
        out = _render_plans({"disposition": "Admit to floor"})
        assert "disposition" in out
        assert "Admit to floor" in out

    def test_legacy_string_fallback(self):
        out = _render_plans("Transfer to ICU")
        assert "Transfer to ICU" in out


# ── Consultant plans rendering ──────────────────────────────────────

class TestConsultantPlansRendering:
    """Verify _render_consultant_plans handles real nested services shape."""

    def test_services_shape_renders_service_name(self):
        cp = {
            "services": {
                "Ortho": {
                    "items": [
                        {
                            "item_text": "Non-op management",
                            "author_name": "Dr. Jones",
                            "ts": "2026-01-01T12:00:00",
                            "item_type": "recommendation",
                            "evidence": [],
                        }
                    ]
                }
            },
            "service_count": 1,
            "item_count": 1,
        }
        out = _render_consultant_plans(cp)
        assert "Ortho" in out
        assert "consult-service-name" in out
        assert "Non-op management" in out
        assert "Dr. Jones" in out

    def test_multiple_services_sorted(self):
        cp = {
            "services": {
                "Neurosurgery": {"items": [{"item_text": "Repeat CT", "author_name": "", "ts": ""}]},
                "Cardiology": {"items": [{"item_text": "Echo ordered", "author_name": "", "ts": ""}]},
            },
            "service_count": 2,
            "item_count": 2,
        }
        out = _render_consultant_plans(cp)
        assert "Cardiology" in out
        assert "Neurosurgery" in out
        # Sorted: Cardiology before Neurosurgery
        assert out.index("Cardiology") < out.index("Neurosurgery")

    def test_empty_services_returns_empty(self):
        assert _render_consultant_plans({"services": {}}) == ""
        assert _render_consultant_plans(None) == ""
        assert _render_consultant_plans({}) == ""

    def test_legacy_flat_dict_fallback(self):
        out = _render_consultant_plans({"Ortho": "Non-op management"})
        assert "Ortho" in out
        assert "Non-op management" in out


# ── GCS rendering ───────────────────────────────────────────────────

class TestGCSRendering:
    """Verify _render_gcs handles real and legacy shapes."""

    def test_real_shape_renders_score(self):
        gcs = {
            "arrival_gcs_value": 15,
            "best_gcs": {"value": 15},
            "worst_gcs": {"value": 15},
            "all_readings": [],
            "warnings": [],
        }
        out = _render_gcs(gcs)
        assert "GCS" in out
        assert "15" in out
        assert "gcs-ok" in out

    def test_moderate_severity(self):
        gcs = {"arrival_gcs_value": 10, "best_gcs": {"value": 10}, "worst_gcs": {"value": 10}}
        out = _render_gcs(gcs)
        assert "gcs-mod" in out

    def test_severe_severity(self):
        gcs = {"arrival_gcs_value": 6, "best_gcs": {"value": 6}, "worst_gcs": {"value": 6}}
        out = _render_gcs(gcs)
        assert "gcs-severe" in out

    def test_best_worst_range_shown(self):
        gcs = {"arrival_gcs_value": 12, "best_gcs": {"value": 14}, "worst_gcs": {"value": 10}}
        out = _render_gcs(gcs)
        assert "Best 14" in out
        assert "Worst 10" in out

    def test_legacy_shape_fallback(self):
        gcs = {"best": 14, "eye": 4, "verbal": 5, "motor": 5}
        out = _render_gcs(gcs)
        assert "GCS Total: 14" in out
        assert "E4" in out

    def test_empty_returns_empty(self):
        assert _render_gcs(None) == ""
        assert _render_gcs({}) == ""


# ── Labs rendering ──────────────────────────────────────────────────

class TestLabsRendering:
    """Verify _render_labs handles real and legacy shapes."""

    def test_real_shape_renders_components(self):
        labs = {
            "latest": {
                "Hemoglobin": {"value_raw": "12.5", "value_num": 12.5, "flags": [], "unit": "GM/DL"},
            },
            "daily": {},
            "series": {},
        }
        out = _render_labs(labs)
        assert "Hemoglobin" in out
        assert "12.5" in out
        assert "GM/DL" in out

    def test_flagged_lab_highlighted(self):
        labs = {
            "latest": {
                "Glucose": {"value_raw": "320", "value_num": 320.0, "flags": ["H"], "unit": "MG/DL"},
            },
            "daily": {},
            "series": {},
        }
        out = _render_labs(labs)
        assert "lab-flag" in out
        assert "(H)" in out
        assert "320" in out

    def test_empty_latest_returns_empty(self):
        assert _render_labs({"latest": {}, "daily": {}, "series": {}}) == ""
        assert _render_labs(None) == ""

    def test_legacy_panel_shape_fallback(self):
        labs = {"cbc": {"wbc": 8.2, "rbc": 4.5}}
        out = _render_labs(labs)
        assert "cbc" in out
        assert "8.2" in out


# ── Empty section suppression ───────────────────────────────────────

class TestEmptySectionSuppression:
    """Null or empty sections produce no HTML."""

    def test_null_plans_suppressed(self):
        assert _render_plans(None) == ""

    def test_null_consultant_plans_suppressed(self):
        assert _render_consultant_plans(None) == ""

    def test_null_gcs_suppressed(self):
        assert _render_gcs(None) == ""

    def test_null_labs_suppressed(self):
        assert _render_labs(None) == ""

    def test_empty_dict_suppressed(self):
        assert _render_plans({}) == ""
        assert _render_consultant_plans({}) == ""
        assert _render_gcs({}) == ""
        assert _render_labs({}) == ""

    def test_canonical_labs_empty_latest_suppressed(self):
        """Canonical shape with empty latest must not fall into legacy fallback."""
        assert _render_labs({"latest": {}, "daily": {}, "series": {}}) == ""


# ── Day-card section ordering ───────────────────────────────────────

class TestDayCardSectionOrdering:
    """Sections within a day card appear in the correct order.

    Anchors on day-section-title text which only appears inside rendered
    day-body divs, not in the <style> block.
    """

    def test_vitals_before_gcs_before_labs_before_consults(self):
        html = render_casefile(_FULL_BUNDLE)
        # Locate inside rendered body using section-title markers
        body_start = html.index("day-body")
        vitals_pos = html.index('>Vitals<', body_start)
        gcs_pos = html.index('>GCS<', body_start)
        labs_pos = html.index('>Labs<', body_start)
        consult_pos = html.index('>Consultant Plans<', body_start)
        assert vitals_pos < gcs_pos
        assert gcs_pos < labs_pos
        assert labs_pos < consult_pos


# ── Primary Injuries tests ──────────────────────────────────────────

class TestPrimaryInjuries:
    def test_injuries_section_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Primary Injuries" in html

    def test_rib_fracture_rendered(self):
        out = _render_primary_injuries(_FULL_BUNDLE)
        assert "Rib Fracture" in out
        assert "Count: 5" in out
        assert "right" in out.lower()

    def test_spinal_fracture_level_shown(self):
        out = _render_primary_injuries(_FULL_BUNDLE)
        assert "Spinal Fracture" in out
        assert "T12" in out

    def test_intracranial_hemorrhage_shown(self):
        out = _render_primary_injuries(_FULL_BUNDLE)
        assert "Intracranial Hemorrhage" in out
        assert "SDH" in out

    def test_solid_organ_injury_grade(self):
        bundle = {"summary": {"injuries": {
            "findings_present": "yes",
            "findings_labels": ["solid_organ"],
            "solid_organ_injuries": [
                {"organ": "liver", "present": True, "grade": "3", "raw_line_id": "soi1"},
            ],
            "intracranial_hemorrhage": [],
            "extremity_fracture": [],
        }}}
        out = _render_primary_injuries(bundle)
        assert "Solid Organ Injury" in out
        assert "Liver" in out
        assert "AAST Grade 3" in out

    def test_extremity_fracture_shown(self):
        out = _render_primary_injuries(_FULL_BUNDLE)
        assert "Extremity Fracture" in out
        assert "Femur" in out
        assert "left" in out.lower()

    def test_absent_injuries_omits_section(self):
        out = _render_primary_injuries(_MINIMAL_BUNDLE)
        assert out == ""

    def test_no_findings_omits_section(self):
        bundle = {"summary": {"injuries": {
            "findings_present": "no",
            "findings_labels": [],
        }}}
        out = _render_primary_injuries(bundle)
        assert out == ""

    def test_deterministic(self):
        out1 = _render_primary_injuries(_FULL_BUNDLE)
        out2 = _render_primary_injuries(_FULL_BUNDLE)
        assert out1 == out2

    def test_section_ordering_after_moi(self):
        html = render_casefile(_FULL_BUNDLE)
        moi_pos = html.index("Mechanism of Injury")
        injuries_pos = html.index("Primary Injuries")
        procedures_pos = html.index("Operative / Procedural Timeline")
        devices_pos = html.index("Lines / Drains / Airways")
        proph_pos = html.index("Prophylaxis Summary")
        pmh_pos = html.index("PMH / Anticoagulants")
        assert moi_pos < injuries_pos < procedures_pos < devices_pos < proph_pos < pmh_pos


# ── Imaging Studies tests ────────────────────────────────────────────

class TestImagingStudies:
    def test_imaging_section_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Imaging Studies" in html

    def test_evidence_items_shown(self):
        out = _render_imaging_studies(_FULL_BUNDLE)
        assert "RADIOLOGY" in out
        assert "rib_fracture" in out.lower() or "Rib Fracture" in out
        assert "2026-01-01" in out

    def test_snippet_shown(self):
        out = _render_imaging_studies(_FULL_BUNDLE)
        assert "right-sided rib fractures" in out

    def test_absent_imaging_omits_section(self):
        out = _render_imaging_studies(_MINIMAL_BUNDLE)
        assert out == ""

    def test_no_evidence_omits_section(self):
        bundle = {"summary": {"imaging": {
            "findings_present": "yes",
            "evidence": [],
        }}}
        out = _render_imaging_studies(bundle)
        assert out == ""

    def test_deterministic(self):
        out1 = _render_imaging_studies(_FULL_BUNDLE)
        out2 = _render_imaging_studies(_FULL_BUNDLE)
        assert out1 == out2


# ── Procedures tests ────────────────────────────────────────────────

class TestProcedures:
    def test_procedures_section_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Operative / Procedural Timeline" in html

    def test_event_label_shown(self):
        out = _render_procedures(_FULL_BUNDLE)
        assert "Endotracheal intubation" in out
        assert "Percutaneous tracheostomy" in out

    def test_category_badge_shown(self):
        out = _render_procedures(_FULL_BUNDLE)
        assert "proc-cat-operative" in out

    def test_timestamp_shown(self):
        out = _render_procedures(_FULL_BUNDLE)
        assert "2026-01-02" in out

    def test_preop_dx_shown(self):
        out = _render_procedures(_FULL_BUNDLE)
        assert "rib fractures" in out

    def test_summary_counts(self):
        out = _render_procedures(_FULL_BUNDLE)
        assert "2 events" in out
        assert "2 operatives" in out

    def test_absent_procedures_omits_section(self):
        out = _render_procedures(_MINIMAL_BUNDLE)
        assert out == ""

    def test_no_events_omits_section(self):
        bundle = {"summary": {"procedures": {
            "events": [],
            "procedure_event_count": 0,
        }}}
        out = _render_procedures(bundle)
        assert out == ""

    def test_deterministic(self):
        out1 = _render_procedures(_FULL_BUNDLE)
        out2 = _render_procedures(_FULL_BUNDLE)
        assert out1 == out2

    def test_anesthesia_category_badge(self):
        bundle = {"summary": {"procedures": {
            "events": [
                {"ts": "2026-01-01T10:00:00", "source_kind": "ANESTHESIA_CONSULT",
                 "category": "anesthesia", "label": "Peripheral Nerve Block",
                 "raw_line_id": "a1", "evidence": []},
            ],
            "procedure_event_count": 0,
            "operative_event_count": 0,
            "anesthesia_event_count": 1,
            "categories_present": ["anesthesia"],
            "evidence": [], "warnings": [], "notes": [],
            "source_rule_id": "procedure_operatives_v1",
        }}}
        out = _render_procedures(bundle)
        assert "proc-cat-anesthesia" in out
        assert "Peripheral Nerve Block" in out

    def test_cpt_codes_shown(self):
        bundle = {"summary": {"procedures": {
            "events": [
                {"ts": "2026-01-01T10:00:00", "source_kind": "PROCEDURE",
                 "category": "operative", "label": "Test Proc",
                 "raw_line_id": "c1", "cpt_codes": ["31600", "99213"],
                 "evidence": []},
            ],
            "procedure_event_count": 1,
            "operative_event_count": 0,
            "anesthesia_event_count": 0,
            "categories_present": ["operative"],
            "evidence": [], "warnings": [], "notes": [],
            "source_rule_id": "procedure_operatives_v1",
        }}}
        out = _render_procedures(bundle)
        assert "31600" in out
        assert "99213" in out

    def test_long_label_truncated(self):
        long_label = "A" * 200
        bundle = {"summary": {"procedures": {
            "events": [
                {"ts": "2026-01-01T10:00:00", "source_kind": "PROCEDURE",
                 "category": "operative", "label": long_label,
                 "raw_line_id": "t1", "evidence": []},
            ],
            "procedure_event_count": 1,
            "operative_event_count": 0,
            "anesthesia_event_count": 0,
            "categories_present": ["operative"],
            "evidence": [], "warnings": [], "notes": [],
            "source_rule_id": "procedure_operatives_v1",
        }}}
        out = _render_procedures(bundle)
        assert "..." in out
        assert long_label not in out


# ── Devices (LDA) tests ────────────────────────────────────────────

class TestDevices:
    def test_devices_section_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Lines / Drains / Airways" in html

    def test_device_type_shown(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "Peripheral IV" in out
        assert "Triple Lumen Catheter" in out

    def test_category_badge_shown(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "dev-cat" in out
        assert "PIV" in out
        assert "Central Line" in out

    def test_placement_shown(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "01/01/26 1030" in out

    def test_removal_shown(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "01/03/26 0800" in out

    def test_duration_shown(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "2 days" in out

    def test_site_shown(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "Left hand" in out
        assert "Right subclavian" in out

    def test_active_status_badge(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "dev-active" in out
        assert "Active" in out

    def test_removed_status_badge(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "dev-removed" in out
        assert "Removed" in out

    def test_summary_counts(self):
        out = _render_devices(_FULL_BUNDLE)
        assert "2 devices" in out
        assert "1 active" in out

    def test_absent_devices_omits_section(self):
        out = _render_devices(_MINIMAL_BUNDLE)
        assert out == ""

    def test_empty_devices_list_omits_section(self):
        bundle = {"summary": {"devices": {"devices": [], "lda_device_count": 0}}}
        out = _render_devices(bundle)
        assert out == ""

    def test_deterministic(self):
        out1 = _render_devices(_FULL_BUNDLE)
        out2 = _render_devices(_FULL_BUNDLE)
        assert out1 == out2


# ── Prophylaxis tests ──────────────────────────────────────────────

class TestProphylaxis:
    def test_prophylaxis_section_present_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Prophylaxis Summary" in html

    def test_dvt_prophylaxis_shown(self):
        out = _render_prophylaxis(_FULL_BUNDLE)
        assert "DVT Prophylaxis" in out
        assert "Pharmacologic started" in out

    def test_dvt_delay_hours_shown(self):
        out = _render_prophylaxis(_FULL_BUNDLE)
        assert "9.9h" in out

    def test_gi_prophylaxis_shown(self):
        out = _render_prophylaxis(_FULL_BUNDLE)
        assert "GI Prophylaxis" in out
        assert "Started" in out

    def test_seizure_prophylaxis_detected(self):
        out = _render_prophylaxis(_FULL_BUNDLE)
        assert "Seizure Prophylaxis" in out
        assert "Levetiracetam" in out
        assert "proph-detected" in out

    def test_seizure_admin_time_shown(self):
        out = _render_prophylaxis(_FULL_BUNDLE)
        assert "2026-01-01T14:00:00" in out

    def test_dvt_excluded(self):
        bundle = {"summary": {"dvt_prophylaxis": {
            "excluded_reason": "THERAPEUTIC_ANTICOAG",
            "pharm_first_ts": None, "mech_first_ts": None,
            "delay_hours": None, "delay_flag_24h": None,
        }}}
        out = _render_prophylaxis(bundle)
        assert "proph-excluded" in out
        assert "THERAPEUTIC_ANTICOAG" in out

    def test_dvt_delay_flag(self):
        bundle = {"summary": {"dvt_prophylaxis": {
            "pharm_first_ts": "2026-01-03T10:00:00",
            "mech_first_ts": None,
            "delay_hours": 48.0, "delay_flag_24h": True,
            "excluded_reason": None,
        }}}
        out = _render_prophylaxis(bundle)
        assert "proph-delay" in out
        assert "delayed &gt;24h" in out or "delayed >24h" in out

    def test_gi_delay_flag(self):
        bundle = {"summary": {"gi_prophylaxis": {
            "pharm_first_ts": "2026-01-04T10:00:00",
            "delay_hours": 72.0, "delay_flag_48h": True,
            "excluded_reason": None,
        }}}
        out = _render_prophylaxis(bundle)
        assert "proph-delay" in out
        assert "delayed &gt;48h" in out or "delayed >48h" in out

    def test_seizure_not_detected(self):
        bundle = {"summary": {"seizure_prophylaxis": {
            "detected": False, "agents": [],
            "first_admin_ts": None, "discontinued": False,
            "discontinued_ts": None,
        }}}
        out = _render_prophylaxis(bundle)
        assert "proph-not-detected" in out
        assert "Not detected" in out

    def test_seizure_discontinued(self):
        bundle = {"summary": {"seizure_prophylaxis": {
            "detected": True, "agents": ["Phenytoin"],
            "first_admin_ts": "2026-01-01T12:00:00",
            "discontinued": True, "discontinued_ts": "2026-01-03T08:00:00",
        }}}
        out = _render_prophylaxis(bundle)
        assert "Phenytoin" in out
        assert "D/C" in out
        assert "2026-01-03" in out

    def test_absent_prophylaxis_omits_section(self):
        out = _render_prophylaxis(_MINIMAL_BUNDLE)
        assert out == ""

    def test_all_none_omits_section(self):
        bundle = {"summary": {"dvt_prophylaxis": None, "gi_prophylaxis": None, "seizure_prophylaxis": None}}
        out = _render_prophylaxis(bundle)
        assert out == ""

    def test_deterministic(self):
        out1 = _render_prophylaxis(_FULL_BUNDLE)
        out2 = _render_prophylaxis(_FULL_BUNDLE)
        assert out1 == out2


# ── Fail-closed: new clinical sections ──────────────────────────────

class TestFailClosedClinicalSections:
    def test_absent_injuries_no_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Primary Injuries" not in html

    def test_absent_imaging_no_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Imaging Studies" not in html

    def test_absent_procedures_no_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Operative / Procedural Timeline" not in html

    def test_absent_devices_no_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Lines / Drains / Airways" not in html

    def test_absent_prophylaxis_no_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Prophylaxis Summary" not in html


# ── Resuscitation / Hemodynamic Summary tests ───────────────────────

class TestResuscitationRendering:
    """Tests for the Resuscitation / Hemodynamic Summary card."""

    def test_section_present_in_full_bundle(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Resuscitation / Hemodynamic Summary" in html

    def test_section_absent_when_all_null(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        assert "Resuscitation / Hemodynamic Summary" not in html

    def test_hemodynamic_instability_detected(self):
        html = _render_resuscitation(_FULL_BUNDLE)
        assert "Instability detected" in html
        assert "Hemodynamic Instability" in html

    def test_hemodynamic_instability_pattern_details(self):
        html = _render_resuscitation(_FULL_BUNDLE)
        assert "Hypotension" in html
        assert "SBP &lt; 90" in html or "SBP < 90" in html
        assert "Map Low" in html
        assert "MAP &lt; 65" in html or "MAP < 65" in html

    def test_hemodynamic_no_instability(self):
        bundle = _make_bundle_with_resus(
            hemodynamic_instability={
                "pattern_present": "no",
                "hypotension_pattern": {"detected": False, "reading_count": 0, "days_affected": 0, "threshold": "SBP < 90", "source_rule_id": "x"},
                "map_low_pattern": {"detected": False, "reading_count": 0, "days_affected": 0, "threshold": "MAP < 65", "source_rule_id": "x"},
                "tachycardia_pattern": {"detected": False, "reading_count": 0, "days_affected": 0, "threshold": "HR > 120", "source_rule_id": "x"},
                "patterns_detected": [],
                "total_abnormal_readings": 0,
                "total_vitals_readings": 100,
                "source_rule_id": "x",
                "evidence": [], "notes": [], "warnings": [],
            },
        )
        html = _render_resuscitation(bundle)
        assert "No instability detected" in html

    def test_blood_products_no_data(self):
        html = _render_resuscitation(_FULL_BUNDLE)
        assert "No blood products documented" in html

    def test_blood_products_with_events(self):
        bundle = _make_bundle_with_resus(
            transfusions={
                "status": "DETECTED",
                "products_detected": ["pRBC", "FFP"],
                "mtp_activated": True,
                "txa_administered": True,
                "prbc_events": 4,
                "ffp_events": 2,
                "platelet_events": 0,
                "cryo_events": 0,
                "total_events": 6,
                "evidence": [],
            },
        )
        html = _render_resuscitation(bundle)
        assert "6 transfusion events" in html
        assert "pRBC: 4" in html
        assert "FFP: 2" in html
        assert "MTP activated" in html
        assert "TXA administered" in html

    def test_base_deficit_trigger(self):
        html = _render_resuscitation(_FULL_BUNDLE)
        assert "BD trigger" in html
        assert "non-compliant" in html.lower()
        assert "Initial BD: 4.3" in html

    def test_base_deficit_no_data(self):
        bundle = _make_bundle_with_resus(
            base_deficit={
                "initial_bd_ts": None,
                "initial_bd_value": None,
                "initial_bd_source": "unknown",
                "initial_bd_raw_line_id": None,
                "category1_bd_validated": False,
                "validation_failure_reason": "DATA NOT AVAILABLE: no BD values found",
                "trigger_bd_gt4": None,
                "first_trigger_ts": None,
                "bd_series": [],
                "monitoring_windows": [],
                "overall_compliant": None,
                "noncompliance_reasons": [],
                "notes": ["DATA NOT AVAILABLE: no BD values found"],
            },
        )
        html = _render_resuscitation(bundle)
        assert "No base deficit data" in html

    def test_base_deficit_within_range(self):
        bundle = _make_bundle_with_resus(
            base_deficit={
                "initial_bd_ts": "2026-01-01T08:00:00",
                "initial_bd_value": 2.0,
                "initial_bd_source": "unknown",
                "initial_bd_raw_line_id": "x",
                "category1_bd_validated": False,
                "validation_failure_reason": None,
                "trigger_bd_gt4": False,
                "first_trigger_ts": None,
                "bd_series": [{"ts": "2026-01-01T08:00:00", "value": 2.0, "specimen": "unknown", "raw_line_id": "x", "snippet": "BD 2.0"}],
                "monitoring_windows": [],
                "overall_compliant": None,
                "noncompliance_reasons": [],
                "notes": [],
            },
        )
        html = _render_resuscitation(bundle)
        assert "BD within range" in html

    def test_deterministic_output(self):
        html1 = _render_resuscitation(_FULL_BUNDLE)
        html2 = _render_resuscitation(_FULL_BUNDLE)
        assert html1 == html2

    def test_fail_closed_empty_string_when_no_data(self):
        bundle = {"summary": {}}
        assert _render_resuscitation(bundle) == ""

    def test_fail_closed_non_dict_values(self):
        bundle = {
            "summary": {
                "base_deficit": "not a dict",
                "transfusions": 42,
                "hemodynamic_instability": [],
            },
        }
        assert _render_resuscitation(bundle) == ""


def _make_bundle_with_resus(
    base_deficit=None,
    transfusions=None,
    hemodynamic_instability=None,
):
    """Create a bundle with specific resuscitation data for targeted testing."""
    import copy
    bundle = copy.deepcopy(_MINIMAL_BUNDLE)
    if base_deficit is not None:
        bundle["summary"]["base_deficit"] = base_deficit
    if transfusions is not None:
        bundle["summary"]["transfusions"] = transfusions
    if hemodynamic_instability is not None:
        bundle["summary"]["hemodynamic_instability"] = hemodynamic_instability
    return bundle
