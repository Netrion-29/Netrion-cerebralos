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
        import json
        assert json.dumps(b1, sort_keys=True) == json.dumps(b2, sort_keys=True)
