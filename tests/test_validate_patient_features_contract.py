"""Tests for validate_patient_features_contract_v1."""

from cerebralos.validation.validate_patient_features_contract_v1 import (
    KNOWN_FEATURE_KEYS,
    validate_contract,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _minimal_payload(**overrides):
    """Return a valid minimal payload, with optional key overrides."""
    base = {
        "build": "test",
        "patient_id": "Test_Patient",
        "days": [],
        "evidence_gaps": [],
        "features": {},
        "warnings": [],
        "warnings_summary": {},
    }
    base.update(overrides)
    return base


# ── Existing positive tests ──────────────────────────────────────────


def test_demographics_v1_in_known_feature_keys():
    """demographics_v1 must be registered in KNOWN_FEATURE_KEYS."""
    assert "demographics_v1" in KNOWN_FEATURE_KEYS


def test_validate_contract_accepts_minimal_demographics():
    """validate_contract accepts a minimal payload with demographics_v1."""
    payload = _minimal_payload(features={"demographics_v1": {"sex": "Male"}})
    errors = validate_contract(payload)
    assert errors == [], f"Unexpected contract errors: {errors}"


def test_ventilator_settings_v1_in_known_feature_keys():
    """ventilator_settings_v1 must be registered in KNOWN_FEATURE_KEYS."""
    assert "ventilator_settings_v1" in KNOWN_FEATURE_KEYS


def test_validate_contract_accepts_minimal_ventilator_settings():
    """validate_contract accepts a minimal payload with ventilator_settings_v1."""
    payload = _minimal_payload(features={
        "ventilator_settings_v1": {
            "events": [],
            "summary": {
                "total_events": 0,
                "days_with_vent_data": 0,
                "mechanical_vent_days": [],
                "niv_days": [],
                "params_found": [],
                "vent_modes_found": [],
            },
        },
    })
    errors = validate_contract(payload)
    assert errors == [], f"Unexpected contract errors: {errors}"


# ── AUD-013: KNOWN_FEATURE_KEYS completeness ────────────────────────


def test_trauma_daily_plan_by_day_v1_in_known_keys():
    assert "trauma_daily_plan_by_day_v1" in KNOWN_FEATURE_KEYS


def test_consultant_day_plans_by_day_v1_in_known_keys():
    assert "consultant_day_plans_by_day_v1" in KNOWN_FEATURE_KEYS


def test_non_trauma_team_day_plans_v1_in_known_keys():
    assert "non_trauma_team_day_plans_v1" in KNOWN_FEATURE_KEYS


# ── Negative tests: top-level key violations ─────────────────────────


def test_leaked_top_level_feature_key():
    """A known feature key at top level must trigger LEAKED_FEATURE_KEYS."""
    payload = _minimal_payload()
    payload["dvt_prophylaxis_v1"] = {}  # leaked to top level
    errors = validate_contract(payload)
    leaked_errors = [e for e in errors if "LEAKED_FEATURE_KEYS" in e]
    assert leaked_errors, f"Expected LEAKED_FEATURE_KEYS error, got: {errors}"


def test_missing_required_top_level_key():
    """Omitting a required top-level key must trigger TOP_LEVEL_MISSING_KEYS."""
    payload = _minimal_payload()
    del payload["patient_id"]
    errors = validate_contract(payload)
    missing_errors = [e for e in errors if "TOP_LEVEL_MISSING_KEYS" in e]
    assert missing_errors, f"Expected TOP_LEVEL_MISSING_KEYS error, got: {errors}"


def test_extra_unknown_top_level_key():
    """An unexpected top-level key must trigger TOP_LEVEL_EXTRA_KEYS."""
    payload = _minimal_payload()
    payload["bogus_key"] = 42
    errors = validate_contract(payload)
    extra_errors = [e for e in errors if "TOP_LEVEL_EXTRA_KEYS" in e]
    assert extra_errors, f"Expected TOP_LEVEL_EXTRA_KEYS error, got: {errors}"


def test_features_wrong_type():
    """features must be a dict; a list must trigger FEATURES_TYPE_ERROR."""
    payload = _minimal_payload(features=[])
    errors = validate_contract(payload)
    type_errors = [e for e in errors if "FEATURES_TYPE_ERROR" in e]
    assert type_errors, f"Expected FEATURES_TYPE_ERROR, got: {errors}"


def test_features_null():
    """Null features must trigger FEATURES_NULL."""
    payload = _minimal_payload(features=None)
    errors = validate_contract(payload)
    null_errors = [e for e in errors if "FEATURES_NULL" in e]
    assert null_errors, f"Expected FEATURES_NULL, got: {errors}"


# ── AUD-014: raw_line_id strictness (empty string / missing) ────────


def test_empty_raw_line_id_in_evidence_rejected():
    """An evidence entry with raw_line_id='' must now be caught (AUD-014)."""
    payload = _minimal_payload(features={
        "dvt_prophylaxis_v1": {
            "evidence": [
                {"type": "pharm", "raw_line_id": "abc123"},
                {"type": "pharm", "raw_line_id": ""},  # empty — should fail
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected raw_line_id error for empty string, got: {errors}"


def test_missing_raw_line_id_in_evidence_rejected():
    """An evidence entry without raw_line_id key must be caught."""
    payload = _minimal_payload(features={
        "dvt_prophylaxis_v1": {
            "evidence": [
                {"type": "pharm"},  # missing raw_line_id entirely
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected raw_line_id error for missing key, got: {errors}"


def test_valid_raw_line_id_passes():
    """Evidence entries with valid raw_line_id must pass."""
    payload = _minimal_payload(features={
        "dvt_prophylaxis_v1": {
            "evidence": [
                {"type": "pharm", "raw_line_id": "abc123"},
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "MISSING_RAW_LINE_ID" in e]
    assert not rid_errors, f"Unexpected raw_line_id error: {errors}"


def test_empty_raw_line_id_in_bd_series_rejected():
    """bd_series entry with raw_line_id='' must be caught (AUD-014)."""
    payload = _minimal_payload(features={
        "base_deficit_monitoring_v1": {
            "bd_series": [
                {"value": -4, "raw_line_id": ""},  # empty
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "BD_SERIES_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected BD_SERIES raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_vitals_records_rejected():
    """vitals_canonical_v1 record with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "vitals_canonical_v1": {
            "days": {
                "2026-01-01": {
                    "records": [
                        {"hr": 80, "raw_line_id": ""},  # empty
                    ],
                },
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "VITALS_CANONICAL_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected VITALS_CANONICAL raw_line_id error, got: {errors}"
