#!/usr/bin/env python3
"""
Tests for patient_bundle_v1 assembler and validator.

Covers:
  - Happy-path assembly with all required + optional artifacts
  - Assembly with optional artifacts absent
  - Required artifact missing → FileNotFoundError
  - Contract validator: valid bundle passes
  - Contract validator: extra top-level key fails
  - Contract validator: missing top-level key fails
  - Deterministic structure (keys + types)
"""

import json
import pytest
from pathlib import Path

from cerebralos.reporting.build_patient_bundle_v1 import (
    assemble_bundle,
    write_bundle,
)
from cerebralos.validation.validate_patient_bundle_contract_v1 import (
    validate_contract,
    ALLOWED_TOP_LEVEL_KEYS,
)


# ── Fixtures ────────────────────────────────────────────────────────

_MINIMAL_EVIDENCE = {
    "meta": {
        "patient_id": "12345",
        "patient_name": "Test Patient",
        "dob": "01/01/1950",
        "slug": "Test_Patient",
        "arrival_datetime": "2025-01-01T08:00:00",
        "discharge_datetime": "2025-01-05T12:00:00",
        "trauma_category": "Blunt",
    },
    "items": [],
}

_MINIMAL_FEATURES = {
    "build": {"version": "1.0"},
    "patient_id": "12345",
    "days": {
        "2025-01-01": {"gcs_daily": {"best": 15}},
        "2025-01-02": {},
    },
    "evidence_gaps": [],
    "features": {
        "mechanism_region_v1": {"mechanism": "MVC"},
        "demographics_v1": {"sex": "M"},
        "vitals_canonical_v1": {
            "days": {
                "2025-01-01": {"records": [{"hr": 80, "sbp": 120}], "count": 1},
            },
        },
        "trauma_daily_plan_by_day_v1": {
            "days": {
                "2025-01-01": {"notes": [{"note_type": "Trauma Progress", "plan_lines": ["Continue care"]}]},
            },
            "total_notes": 1,
        },
        "consultant_day_plans_by_day_v1": {
            "days": {
                "2025-01-01": {"services": {"Ortho": {"items": [{"item_text": "Weight-bearing"}], "item_count": 1}}},
            },
            "total_days": 1,
        },
        "ventilator_settings_v1": {
            "events": [],
            "summary": {"total_events": 0},
        },
        "consultant_events_v1": {"services": ["Ortho"]},
        "radiology_findings_v1": {
            "findings_present": "yes",
            "findings_labels": ["pelvic_fracture", "spinal_fracture"],
            "pneumothorax": None,
            "hemothorax": None,
            "rib_fracture": None,
            "flail_chest": None,
            "solid_organ_injuries": [],
            "intracranial_hemorrhage": [],
            "pelvic_fracture": {"present": True, "raw_line_id": "abc123"},
            "spinal_fracture": {"present": True, "level": "T12", "raw_line_id": "def456"},
            "extremity_fracture": [],
            "source_rule_id": "radiology_findings",
            "evidence": [
                {"raw_line_id": "abc123", "source": "RADIOLOGY", "ts": "2025-01-01T13:51:00", "snippet": "pelvic fracture noted", "role": "finding", "label": "pelvic_fracture"},
            ],
            "notes": [],
            "warnings": [],
        },
        "procedure_operatives_v1": {
            "events": [
                {
                    "ts": "2025-01-02T12:32:00",
                    "source_kind": "PROCEDURE",
                    "category": "operative",
                    "label": "Endotracheal intubation",
                    "raw_line_id": "proc001",
                    "evidence": [{"role": "procedure_event", "snippet": "intubation performed", "raw_line_id": "proc001"}],
                },
            ],
            "procedure_event_count": 1,
            "operative_event_count": 0,
            "anesthesia_event_count": 0,
            "categories_present": ["operative"],
            "evidence": [],
            "warnings": [],
            "notes": [],
            "source_rule_id": "procedure_operatives_v1",
        },
        "lda_events_v1": {
            "devices": [
                {
                    "device_type": "Peripheral IV",
                    "device_label": "PIV #1",
                    "category": "PIV",
                    "placed_ts": "01/01/25 0830",
                    "removed_ts": "01/03/25 1200",
                    "duration_text": "2 days",
                    "site": "Left hand",
                    "source_format": "LDA",
                    "assessment_count": 3,
                    "event_rows": 5,
                    "evidence": [{"raw_line_id": "lda001"}],
                },
            ],
            "lda_device_count": 1,
            "active_devices_count": 0,
            "categories_present": ["PIV"],
            "devices_with_placement": ["PIV #1"],
            "devices_with_removal": ["PIV #1"],
            "source_file": "test.txt",
            "source_rule_id": "lda_events_raw_file",
            "warnings": [],
            "notes": [],
        },
        "dvt_prophylaxis_v1": {
            "pharm_first_ts": "2025-01-01T18:00:00",
            "mech_first_ts": None,
            "first_ts": "2025-01-01T18:00:00",
            "delay_hours": 10.0,
            "delay_flag_24h": False,
            "excluded_reason": None,
            "orders_only_count": 0,
            "pharm_admin_evidence_count": 1,
            "pharm_ambiguous_mention_count": 0,
            "mech_admin_evidence_count": 0,
            "evidence": {"pharm": [{"ts": "2025-01-01T18:00:00", "raw_line_id": "dvt001", "snippet": "enoxaparin 40mg"}], "mech": [], "exclusion": []},
        },
        "gi_prophylaxis_v1": {
            "pharm_first_ts": "2025-01-01T18:00:00",
            "delay_hours": 10.0,
            "delay_flag_48h": False,
            "excluded_reason": None,
            "pharm_admin_evidence_count": 1,
            "pharm_ambiguous_mention_count": 0,
            "orders_only_count": 0,
            "evidence": {"pharm": [{"ts": "2025-01-01T18:00:00", "raw_line_id": "gi001", "snippet": "famotidine 20mg"}], "exclusion": []},
        },
        "seizure_prophylaxis_v1": {
            "detected": False,
            "agents": [],
            "home_med_present": False,
            "first_mention_ts": None,
            "first_admin_ts": None,
            "discontinued": False,
            "discontinued_ts": None,
            "dose_entries": [],
            "admin_evidence_count": 0,
            "mention_evidence_count": 0,
            "evidence": {"admin": [], "mention": [], "discontinued": []},
        },
        "base_deficit_monitoring_v1": {
            "initial_bd_ts": "2025-01-01T08:30:00",
            "initial_bd_value": 4.3,
            "initial_bd_source": "unknown",
            "initial_bd_raw_line_id": "bd001",
            "category1_bd_validated": False,
            "validation_failure_reason": "specimen source not confirmed arterial",
            "trigger_bd_gt4": True,
            "first_trigger_ts": "2025-01-01T08:30:00",
            "bd_series": [
                {"ts": "2025-01-01T08:30:00", "value": 4.3, "specimen": "unknown", "raw_line_id": "bd001", "snippet": "BD 4.3"},
                {"ts": "2025-01-01T14:00:00", "value": 2.1, "specimen": "unknown", "raw_line_id": "bd002", "snippet": "BD 2.1"},
            ],
            "monitoring_windows": [],
            "overall_compliant": False,
            "noncompliance_reasons": ["q2h_until_improving: gap 5.5h"],
            "notes": [],
        },
        "transfusion_blood_products_v1": {
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
        "hemodynamic_instability_pattern_v1": {
            "pattern_present": "yes",
            "hypotension_pattern": {
                "detected": True,
                "reading_count": 2,
                "days_affected": 1,
                "threshold": "SBP < 90",
                "source_rule_id": "hemo_sbp_lt90",
            },
            "map_low_pattern": {
                "detected": False,
                "reading_count": 0,
                "days_affected": 0,
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
            "patterns_detected": ["hypotension"],
            "total_abnormal_readings": 2,
            "total_vitals_readings": 50,
            "source_rule_id": "hemodynamic_instability_pattern_canonical_vitals",
            "evidence": [],
            "notes": [],
            "warnings": [],
        },
        "patient_movement_v1": {
            "entries": [
                {
                    "unit": "Ortho Neuro Trauma Care Center",
                    "date_raw": "01/02",
                    "time_raw": "1741",
                    "event_type": "Discharge",
                    "room": "4630",
                    "bed": "4630-01",
                    "patient_class": "Inpatient",
                    "level_of_care": "Med/Surg",
                    "service": "Trauma",
                    "providers": {"discharge": "Kuhlenschmidt, Kali Marie"},
                    "discharge_disposition": "Home",
                    "raw_line_id": "pm001",
                },
                {
                    "unit": "Ortho Neuro Trauma Care Center",
                    "date_raw": "01/01",
                    "time_raw": "1511",
                    "event_type": "Transfer In",
                    "room": "4630",
                    "bed": "4630-01",
                    "patient_class": "Inpatient",
                    "level_of_care": "Med/Surg",
                    "service": "Trauma",
                    "providers": {"admitting": "Smith, John"},
                    "discharge_disposition": None,
                    "raw_line_id": "pm002",
                },
            ],
            "summary": {
                "movement_event_count": 2,
                "first_movement_ts": "01/01 1511",
                "admission_ts": "01/01 1005",
                "discharge_ts": "01/02 1741",
                "discharge_disposition_final": "Home",
                "transfer_count": 1,
                "units_visited": ["Ortho Neuro Trauma Care Center"],
                "levels_of_care": ["Med/Surg"],
                "services_seen": ["Trauma"],
                "rooms_visited": ["4630"],
                "event_type_counts": {"Discharge": 1, "Transfer In": 1},
                "icu_los_hours": None,
                "icu_los_days": None,
                "icu_admission_count": 0,
            },
            "evidence": [
                {"role": "patient_movement_entry", "snippet": "Discharge 01/02 1741", "raw_line_id": "pm001"},
            ],
            "source_file": "test.txt",
            "source_rule_id": "patient_movement_v1",
            "warnings": [],
            "notes": [],
        },
        "non_trauma_team_day_plans_v1": {
            "days": {
                "2025-01-01": {
                    "services": {
                        "Physical Therapy": {
                            "notes": [
                                {
                                    "dt": "2025-01-01T10:21:00",
                                    "source_id": "42",
                                    "author": "DATA NOT AVAILABLE",
                                    "service": "Physical Therapy",
                                    "note_header": "PHYSICAL THERAPY",
                                    "brief_lines": [
                                        "PHYSICAL THERAPY",
                                        "Patient: Test Patient",
                                        "Assessment: Decreased mobility",
                                        "Plan: PT 5x/week",
                                    ],
                                    "brief_line_count": 4,
                                    "raw_line_id": "ntp001",
                                },
                            ],
                            "note_count": 1,
                        },
                        "Case Management": {
                            "notes": [
                                {
                                    "dt": "2025-01-01T09:32:00",
                                    "source_id": "43",
                                    "author": "DATA NOT AVAILABLE",
                                    "service": "Case Management",
                                    "note_header": "CASE MANAGEMENT",
                                    "brief_lines": [
                                        "ASSESSMENT: SW spoke with pt",
                                        "PLAN: Discharge planning initiated",
                                    ],
                                    "brief_line_count": 2,
                                    "raw_line_id": "ntp002",
                                },
                            ],
                            "note_count": 1,
                        },
                    },
                    "service_count": 2,
                    "note_count": 2,
                },
            },
            "total_days": 1,
            "total_notes": 2,
            "total_services": 2,
            "services_seen": ["Case Management", "Physical Therapy"],
            "source_rule_id": "non_trauma_team_day_plans_v1",
            "warnings": [],
            "notes": [],
        },
        "sbirt_screening_v1": {
            "sbirt_screening_present": "yes",
            "instruments_detected": ["audit_c", "dast_10"],
            "audit_c": {
                "explicit_score": {"value": 4, "ts": "2025-01-01T10:00:00", "source_rule_id": "sbirt_section_audit_c", "evidence": []},
                "responses_present": True,
                "responses": [{"question_id": "audit_c_q1", "question_text": "How often?", "answer": "Weekly", "instrument": "audit_c", "raw_line_id": "sbirt001"}],
                "completion_status": "score_documented",
            },
            "dast_10": {
                "explicit_score": None,
                "responses_present": True,
                "responses": [{"question_id": "dast_10_q1", "question_text": "Used drugs?", "answer": "No", "instrument": "dast_10", "raw_line_id": "sbirt002"}],
                "completion_status": "responses_only",
            },
            "cage": {
                "explicit_score": None,
                "responses_present": False,
                "responses": [],
                "completion_status": "not_performed",
            },
            "flowsheet_responses": [],
            "refusal_documented": False,
            "refusal_evidence": [],
            "substance_use_admission_documented": False,
            "substance_use_admission_evidence": [],
            "evidence": [{"raw_line_id": "sbirt001", "source": "NURSING_NOTE", "ts": "2025-01-01T10:00:00", "snippet": "AUDIT-C Score: 4", "role": "score", "label": "audit_c"}],
            "notes": [],
            "warnings": [],
        },
    },
    "warnings": ["test warning"],
    "warnings_summary": {},
}

_MINIMAL_TIMELINE = {
    "days": {
        "2025-01-01": {"notes": []},
        "2025-01-02": {"notes": []},
    },
}

_NTDS_SUMMARY = {
    "year": 2026,
    "events": [{"event_id": 1, "canonical_name": "E1", "outcome": "Y"}],
}


from typing import Any


def _write_artifact(root: Path, rel: str, data: Any) -> None:
    """Write a JSON artifact under the test root."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def full_outputs(tmp_path):
    """Create a complete set of pipeline artifacts under tmp_path."""
    slug = "Test_Patient"
    _write_artifact(tmp_path, f"evidence/{slug}/patient_evidence_v1.json", _MINIMAL_EVIDENCE)
    _write_artifact(tmp_path, f"features/{slug}/patient_features_v1.json", _MINIMAL_FEATURES)
    _write_artifact(tmp_path, f"timeline/{slug}/patient_days_v1.json", _MINIMAL_TIMELINE)
    _write_artifact(tmp_path, f"ntds/{slug}/ntds_summary_2026_v1.json", _NTDS_SUMMARY)
    _write_artifact(tmp_path, f"ntds/{slug}/ntds_event_1_2026_v1.json", {
        "event_id": 1, "canonical_name": "E1", "outcome": "Y",
    })
    _write_artifact(tmp_path, f"protocols/{slug}/protocol_results_v1.json", [
        {"protocol": "DVT", "outcome": "MET"},
    ])
    _write_artifact(tmp_path, f"reporting/{slug}/TRAUMA_DAILY_NOTES_v5.txt", {})
    # v5 is a text file, rewrite properly
    (tmp_path / f"reporting/{slug}/TRAUMA_DAILY_NOTES_v5.txt").write_text(
        "V5 REPORT", encoding="utf-8"
    )
    return tmp_path, slug


@pytest.fixture
def required_only_outputs(tmp_path):
    """Create only the required artifacts (no NTDS, no protocols, no v5)."""
    slug = "Test_Patient"
    _write_artifact(tmp_path, f"evidence/{slug}/patient_evidence_v1.json", _MINIMAL_EVIDENCE)
    _write_artifact(tmp_path, f"features/{slug}/patient_features_v1.json", _MINIMAL_FEATURES)
    _write_artifact(tmp_path, f"timeline/{slug}/patient_days_v1.json", _MINIMAL_TIMELINE)
    return tmp_path, slug


# ── Assembly tests ──────────────────────────────────────────────────

class TestAssembleBundle:
    def test_happy_path_all_artifacts(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)

        assert set(bundle.keys()) == ALLOWED_TOP_LEVEL_KEYS
        assert bundle["build"]["bundle_version"] == "1.0"
        assert bundle["patient"]["slug"] == slug
        assert bundle["patient"]["patient_name"] == "Test Patient"
        assert bundle["compliance"]["ntds_summary"] is not None
        assert bundle["compliance"]["protocol_results"] is not None
        assert bundle["artifacts"]["v5_report_path"] is not None

    def test_optional_absent(self, required_only_outputs):
        root, slug = required_only_outputs
        bundle = assemble_bundle(slug, outputs_root=root)

        assert set(bundle.keys()) == ALLOWED_TOP_LEVEL_KEYS
        assert bundle["compliance"]["ntds_summary"] is None
        assert bundle["compliance"]["protocol_results"] is None
        assert bundle["artifacts"]["ntds_summary_path"] is None
        assert bundle["artifacts"]["protocol_results_path"] is None
        # Warnings should note the absent optional artifacts
        warning_text = " ".join(bundle["warnings"])
        assert "NTDS" in warning_text
        assert "Protocol" in warning_text

    def test_required_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="patient_evidence_v1.json"):
            assemble_bundle("Nonexistent_Patient", outputs_root=tmp_path)

    def test_daily_section_has_expected_days(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        assert "2025-01-01" in bundle["daily"]
        assert "2025-01-02" in bundle["daily"]

    def test_summary_section_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        assert bundle["summary"]["mechanism"] == {"mechanism": "MVC"}
        assert bundle["summary"]["demographics"] == {"sex": "M"}

    def test_summary_injuries_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        injuries = bundle["summary"]["injuries"]
        assert injuries is not None
        assert injuries["findings_present"] == "yes"
        assert "pelvic_fracture" in injuries["findings_labels"]
        assert injuries["pelvic_fracture"]["present"] is True

    def test_summary_imaging_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        imaging = bundle["summary"]["imaging"]
        assert imaging is not None
        assert imaging["findings_present"] == "yes"
        assert isinstance(imaging["evidence"], list)

    def test_summary_procedures_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        procs = bundle["summary"]["procedures"]
        assert procs is not None
        assert procs["procedure_event_count"] == 1
        assert len(procs["events"]) == 1
        assert procs["events"][0]["label"] == "Endotracheal intubation"

    def test_summary_devices_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        devs = bundle["summary"]["devices"]
        assert devs is not None
        assert devs["lda_device_count"] == 1
        assert len(devs["devices"]) == 1
        assert devs["devices"][0]["category"] == "PIV"

    def test_summary_dvt_prophylaxis_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        dvt = bundle["summary"]["dvt_prophylaxis"]
        assert dvt is not None
        assert dvt["delay_hours"] == 10.0
        assert dvt["delay_flag_24h"] is False

    def test_summary_gi_prophylaxis_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        gi = bundle["summary"]["gi_prophylaxis"]
        assert gi is not None
        assert gi["pharm_first_ts"] == "2025-01-01T18:00:00"

    def test_summary_seizure_prophylaxis_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        szr = bundle["summary"]["seizure_prophylaxis"]
        assert szr is not None
        assert szr["detected"] is False

    def test_summary_base_deficit_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        bd = bundle["summary"]["base_deficit"]
        assert bd is not None
        assert bd["initial_bd_value"] == 4.3
        assert bd["trigger_bd_gt4"] is True
        assert len(bd["bd_series"]) == 2

    def test_summary_transfusions_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        tx = bundle["summary"]["transfusions"]
        assert tx is not None
        assert tx["status"] == "DATA NOT AVAILABLE"
        assert tx["total_events"] == 0

    def test_summary_hemodynamic_instability_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        hemo = bundle["summary"]["hemodynamic_instability"]
        assert hemo is not None
        assert hemo["pattern_present"] == "yes"
        assert "hypotension" in hemo["patterns_detected"]
        assert hemo["total_abnormal_readings"] == 2

    def test_summary_patient_movement_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        pm = bundle["summary"]["patient_movement"]
        assert pm is not None
        assert pm["summary"]["discharge_disposition_final"] == "Home"
        assert pm["summary"]["discharge_ts"] == "01/02 1741"
        assert len(pm["entries"]) == 2

    def test_summary_sbirt_screening_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        sbirt = bundle["summary"]["sbirt_screening"]
        assert sbirt is not None
        assert sbirt["sbirt_screening_present"] == "yes"
        assert "audit_c" in sbirt["instruments_detected"]
        assert sbirt["audit_c"]["explicit_score"]["value"] == 4

    def test_daily_non_trauma_team_plans_populated(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-01"]
        ntp = day.get("non_trauma_team_plans")
        assert ntp is not None
        assert "Physical Therapy" in ntp["services"]
        assert "Case Management" in ntp["services"]
        pt_notes = ntp["services"]["Physical Therapy"]["notes"]
        assert len(pt_notes) == 1
        assert "Decreased mobility" in pt_notes[0]["brief_lines"][2]

    def test_daily_non_trauma_team_plans_null_for_absent_day(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-02"]
        assert day.get("non_trauma_team_plans") is None

    def test_summary_injuries_null_when_absent(self, tmp_path):
        slug = "Bare_Test"
        _write_artifact(tmp_path, f"evidence/{slug}/patient_evidence_v1.json", _MINIMAL_EVIDENCE)
        bare_features = {
            "build": {"version": "1.0"},
            "patient_id": "12345",
            "days": {"2025-01-01": {}},
            "evidence_gaps": [],
            "features": {},
            "warnings": [],
            "warnings_summary": {},
        }
        _write_artifact(tmp_path, f"features/{slug}/patient_features_v1.json", bare_features)
        _write_artifact(tmp_path, f"timeline/{slug}/patient_days_v1.json", _MINIMAL_TIMELINE)
        bundle = assemble_bundle(slug, outputs_root=tmp_path)
        assert bundle["summary"]["injuries"] is None
        assert bundle["summary"]["imaging"] is None
        assert bundle["summary"]["procedures"] is None
        assert bundle["summary"]["devices"] is None
        assert bundle["summary"]["dvt_prophylaxis"] is None
        assert bundle["summary"]["gi_prophylaxis"] is None
        assert bundle["summary"]["seizure_prophylaxis"] is None
        assert bundle["summary"]["base_deficit"] is None
        assert bundle["summary"]["transfusions"] is None
        assert bundle["summary"]["hemodynamic_instability"] is None
        assert bundle["summary"]["patient_movement"] is None
        assert bundle["summary"]["sbirt_screening"] is None

    def test_consultants_section(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        assert bundle["consultants"] == {"services": ["Ortho"]}

    def test_write_and_read_roundtrip(self, full_outputs, tmp_path):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        out_path = tmp_path / "bundle_out" / "patient_bundle_v1.json"
        write_bundle(bundle, out_path)
        assert out_path.exists()
        roundtrip = json.loads(out_path.read_text(encoding="utf-8"))
        assert set(roundtrip.keys()) == ALLOWED_TOP_LEVEL_KEYS


# ── Validator tests ─────────────────────────────────────────────────

class TestValidateContract:
    def test_valid_bundle_passes(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        errors = validate_contract(bundle)
        assert errors == []

    def test_extra_top_level_key(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        bundle["rogue_key"] = "bad"
        errors = validate_contract(bundle)
        assert any("TOP_LEVEL_EXTRA_KEYS" in e for e in errors)

    def test_missing_top_level_key(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        del bundle["patient"]
        errors = validate_contract(bundle)
        assert any("TOP_LEVEL_MISSING_KEYS" in e for e in errors)

    def test_bad_build_type(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = "not a dict"
        data["warnings"] = []
        errors = validate_contract(data)
        assert any("BUILD_TYPE_ERROR" in e for e in errors)

    def test_missing_slug(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = {"bundle_version": "1.0"}
        data["patient"] = {"slug": ""}
        data["warnings"] = []
        errors = validate_contract(data)
        assert any("PATIENT_MISSING_SLUG" in e for e in errors)

    def test_warnings_must_be_list(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = {"bundle_version": "1.0"}
        data["patient"] = {"slug": "Test"}
        data["warnings"] = "not a list"
        errors = validate_contract(data)
        assert any("WARNINGS_TYPE_ERROR" in e for e in errors)

    def test_non_dict_root_fails(self):
        errors = validate_contract([1, 2, 3])
        assert len(errors) == 1
        assert "ROOT_TYPE_ERROR" in errors[0]

    def test_consultants_bad_type_fails(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = {"bundle_version": "1.0"}
        data["patient"] = {"slug": "Test"}
        data["warnings"] = []
        data["consultants"] = "not a dict"
        errors = validate_contract(data)
        assert any("CONSULTANTS_TYPE_ERROR" in e for e in errors)

    def test_consultants_null_passes(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = {"bundle_version": "1.0"}
        data["patient"] = {"slug": "Test"}
        data["warnings"] = []
        data["consultants"] = None
        errors = validate_contract(data)
        assert not any("CONSULTANTS" in e for e in errors)

    def test_summary_missing_injuries_key_fails(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = {"bundle_version": "1.0"}
        data["patient"] = {"slug": "Test"}
        data["warnings"] = []
        data["summary"] = {"mechanism": None}
        errors = validate_contract(data)
        assert any("SUMMARY_MISSING_KEY" in e and "injuries" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "imaging" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "procedures" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "devices" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "dvt_prophylaxis" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "gi_prophylaxis" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "seizure_prophylaxis" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "base_deficit" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "transfusions" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "hemodynamic_instability" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "patient_movement" in e for e in errors)
        assert any("SUMMARY_MISSING_KEY" in e and "sbirt_screening" in e for e in errors)

    def test_summary_with_clinical_keys_null_passes(self):
        data = {k: {} for k in ALLOWED_TOP_LEVEL_KEYS}
        data["build"] = {"bundle_version": "1.0"}
        data["patient"] = {"slug": "Test"}
        data["warnings"] = []
        data["summary"] = {
            "injuries": None, "imaging": None, "procedures": None,
            "devices": None, "dvt_prophylaxis": None,
            "gi_prophylaxis": None, "seizure_prophylaxis": None,
            "base_deficit": None, "transfusions": None,
            "hemodynamic_instability": None,
            "patient_movement": None,
            "sbirt_screening": None,
        }
        errors = validate_contract(data)
        assert not any("SUMMARY_MISSING_KEY" in e for e in errors)

    def test_assembled_bundle_passes_validator_with_new_keys(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        errors = validate_contract(bundle)
        assert errors == []


class TestV5MissingWarning:
    def test_v5_absent_adds_warning(self, required_only_outputs):
        root, slug = required_only_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        assert any("V5 report not found" in w for w in bundle["warnings"])


# ── Daily mapping tests ─────────────────────────────────────────────

class TestDailyNestedDaysMapping:
    """Verify that the assembler reads module.days[date] for day-keyed features."""

    def test_vitals_populated_from_nested_days(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-01"]
        assert day["vitals"] is not None
        assert day["vitals"]["records"][0]["hr"] == 80

    def test_vitals_null_for_absent_day(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-02"]
        assert day["vitals"] is None

    def test_plans_populated_from_nested_days(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-01"]
        assert day["plans"] is not None
        assert day["plans"]["notes"][0]["plan_lines"] == ["Continue care"]

    def test_plans_null_for_absent_day(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-02"]
        assert day["plans"] is None

    def test_consultant_plans_populated_from_nested_days(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-01"]
        assert day["consultant_plans"] is not None
        assert "Ortho" in day["consultant_plans"]["services"]

    def test_consultant_plans_null_for_absent_day(self, full_outputs):
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-02"]
        assert day["consultant_plans"] is None

    def test_ventilator_stays_null_no_days_key(self, full_outputs):
        """Ventilator module has no days sub-dict; should remain null."""
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-01"]
        assert day["ventilator"] is None

    def test_gcs_still_from_feat_days(self, full_outputs):
        """GCS comes from features.days[date].gcs_daily, not features dict."""
        root, slug = full_outputs
        bundle = assemble_bundle(slug, outputs_root=root)
        day = bundle["daily"]["2025-01-01"]
        assert day["gcs"] is not None
        assert day["gcs"]["best"] == 15

    def test_flat_keyed_module_fallback(self, tmp_path):
        """If a module has no 'days' sub-dict, fall back to top-level date key."""
        slug = "Flat_Test"
        _write_artifact(tmp_path, f"evidence/{slug}/patient_evidence_v1.json", _MINIMAL_EVIDENCE)
        flat_features = {
            "build": {"version": "1.0"},
            "patient_id": "12345",
            "days": {"2025-01-01": {}, "2025-01-02": {}},
            "evidence_gaps": [],
            "features": {
                "vitals_canonical_v1": {
                    "2025-01-01": [{"hr": 72}],
                },
            },
            "warnings": [],
            "warnings_summary": {},
        }
        _write_artifact(tmp_path, f"features/{slug}/patient_features_v1.json", flat_features)
        _write_artifact(tmp_path, f"timeline/{slug}/patient_days_v1.json", _MINIMAL_TIMELINE)
        bundle = assemble_bundle(slug, outputs_root=tmp_path)
        day = bundle["daily"]["2025-01-01"]
        assert day["vitals"] == [{"hr": 72}]

    def test_daily_mapping_deterministic(self, full_outputs):
        root, slug = full_outputs
        b1 = assemble_bundle(slug, outputs_root=root)
        b2 = assemble_bundle(slug, outputs_root=root)
        # Exclude build.generated_at_utc for determinism check
        for b in (b1, b2):
            b["build"].pop("generated_at_utc", None)
        assert json.dumps(b1, sort_keys=True) == json.dumps(b2, sort_keys=True)
