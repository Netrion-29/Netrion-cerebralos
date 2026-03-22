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
    _outcome_badge,
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
        "age": {"age": 71},
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
            "vitals": [{"hr": 88, "sbp": 130, "dbp": 72, "resp": 18, "spo2": 97}],
            "labs": {"cbc": {"wbc": 8.2, "hgb": 12.5}},
            "gcs": {"best": 15, "eye": 4, "verbal": 5, "motor": 6},
            "ventilator": None,
            "plans": {"disposition": "Admit to floor"},
            "consultant_plans": {"Ortho": "Non-operative management"},
        },
        "2026-01-02": {
            "vitals": [{"hr": 78, "sbp": 124}],
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
        assert "E4" in html
        assert "V5" in html
        assert "M6" in html

    def test_labs_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Labs" in html
        assert "cbc" in html

    def test_consultant_plans_rendered(self):
        html = render_casefile(_FULL_BUNDLE)
        assert "Non-operative management" in html

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

    def test_absent_consultants_omits_section(self):
        html = render_casefile(_MINIMAL_BUNDLE)
        # Header card "Consultants" should not appear
        count = html.count("Consultants")
        assert count == 0

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
