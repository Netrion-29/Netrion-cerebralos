"""Tests for validate_patient_features_contract_v1."""

from cerebralos.validation.validate_patient_features_contract_v1 import (
    KNOWN_FEATURE_KEYS,
    validate_contract,
)


def test_demographics_v1_in_known_feature_keys():
    """demographics_v1 must be registered in KNOWN_FEATURE_KEYS."""
    assert "demographics_v1" in KNOWN_FEATURE_KEYS


def test_validate_contract_accepts_minimal_demographics():
    """validate_contract accepts a minimal payload with demographics_v1."""
    payload = {
        "build": "test",
        "patient_id": "Test_Patient",
        "days": [],
        "evidence_gaps": [],
        "features": {
            "demographics_v1": {"sex": "Male"},
        },
        "warnings": [],
        "warnings_summary": {},
    }
    errors = validate_contract(payload)
    assert errors == [], f"Unexpected contract errors: {errors}"


def test_ventilator_settings_v1_in_known_feature_keys():
    """ventilator_settings_v1 must be registered in KNOWN_FEATURE_KEYS."""
    assert "ventilator_settings_v1" in KNOWN_FEATURE_KEYS


def test_validate_contract_accepts_minimal_ventilator_settings():
    """validate_contract accepts a minimal payload with ventilator_settings_v1."""
    payload = {
        "build": "test",
        "patient_id": "Test_Patient",
        "days": [],
        "evidence_gaps": [],
        "features": {
            "ventilator_settings_v1": {
                "events": [],
                "summary": {
                    "total_events": 0,
                    "days_with_vent_data": 0,
                    "mechanical_vent_days": [],
                    "niv_days": [],
                    "params_found": [],
                },
            },
        },
        "warnings": [],
        "warnings_summary": {},
    }
    errors = validate_contract(payload)
    assert errors == [], f"Unexpected contract errors: {errors}"
