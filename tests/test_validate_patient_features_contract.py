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


# ── Negative tests: inr_series raw_line_id ───────────────────────────


def test_empty_raw_line_id_in_inr_series_rejected():
    """inr_series entry with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "inr_normalization_v1": {
            "inr_series": [
                {"value": 1.2, "raw_line_id": ""},  # empty
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "INR_SERIES_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected INR_SERIES raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_inr_series_rejected():
    """inr_series entry without raw_line_id key must be caught."""
    payload = _minimal_payload(features={
        "inr_normalization_v1": {
            "inr_series": [
                {"value": 1.5},  # missing entirely
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "INR_SERIES_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected INR_SERIES raw_line_id error, got: {errors}"


def test_valid_inr_series_passes():
    """inr_series entries with valid raw_line_id must pass."""
    payload = _minimal_payload(features={
        "inr_normalization_v1": {
            "inr_series": [
                {"value": 1.2, "raw_line_id": "L10-L11"},
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "INR_SERIES_MISSING_RAW_LINE_ID" in e]
    assert not rid_errors, f"Unexpected INR_SERIES error: {errors}"


# ── Negative tests: drift_events[].evidence raw_line_id ──────────────


def test_empty_raw_line_id_in_drift_event_evidence_rejected():
    """drift_events[].evidence entry with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "impression_plan_drift_v1": {
            "evidence": [],
            "drift_events": [
                {
                    "date": "2026-01-01",
                    "evidence": [
                        {"type": "drift", "raw_line_id": ""},  # empty
                    ],
                },
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "IMPRESSION_PLAN_DRIFT_EVENT_EVIDENCE_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected drift event evidence raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_drift_event_evidence_rejected():
    """drift_events[].evidence entry without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "impression_plan_drift_v1": {
            "evidence": [],
            "drift_events": [
                {
                    "date": "2026-01-02",
                    "evidence": [
                        {"type": "drift"},  # missing
                    ],
                },
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "IMPRESSION_PLAN_DRIFT_EVENT_EVIDENCE_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected drift event evidence raw_line_id error, got: {errors}"


def test_valid_drift_event_evidence_passes():
    """drift_events[].evidence with valid raw_line_id must pass."""
    payload = _minimal_payload(features={
        "impression_plan_drift_v1": {
            "evidence": [],
            "drift_events": [
                {
                    "date": "2026-01-01",
                    "evidence": [
                        {"type": "drift", "raw_line_id": "L5-L6"},
                    ],
                },
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "IMPRESSION_PLAN_DRIFT_EVENT_EVIDENCE_MISSING_RAW_LINE_ID" in e
    ]
    assert not rid_errors, f"Unexpected drift event evidence error: {errors}"


# ── Negative tests: ADT transfer events raw_line_id ──────────────────


def test_empty_raw_line_id_in_adt_events_rejected():
    """adt_transfer_timeline_v1 event with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "adt_transfer_timeline_v1": {
            "evidence": [],
            "events": [
                {"type": "transfer", "raw_line_id": ""},  # empty
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "ADT_TRANSFER_EVENTS_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected ADT events raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_adt_events_rejected():
    """adt_transfer_timeline_v1 event without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "adt_transfer_timeline_v1": {
            "evidence": [],
            "events": [
                {"type": "transfer"},  # missing
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "ADT_TRANSFER_EVENTS_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected ADT events raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_adt_evidence_rejected():
    """adt_transfer_timeline_v1 evidence with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "adt_transfer_timeline_v1": {
            "evidence": [
                {"type": "adt", "raw_line_id": ""},  # empty
            ],
            "events": [],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "ADT_TRANSFER_EVIDENCE_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected ADT evidence raw_line_id error, got: {errors}"


# ── Negative tests: PMH / allergies evidence raw_line_id ─────────────


def test_empty_raw_line_id_in_pmh_items_rejected():
    """pmh_items entry with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "pmh_social_allergies_v1": {
            "evidence": [],
            "pmh_items": [
                {"condition": "HTN", "raw_line_id": ""},  # empty
            ],
            "allergies": [],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PMH_SOCIAL_ALLERGIES_PMH_ITEMS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected PMH_ITEMS raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_pmh_items_rejected():
    """pmh_items entry without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "pmh_social_allergies_v1": {
            "evidence": [],
            "pmh_items": [
                {"condition": "DM2"},  # missing
            ],
            "allergies": [],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PMH_SOCIAL_ALLERGIES_PMH_ITEMS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected PMH_ITEMS raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_allergies_rejected():
    """allergies entry with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "pmh_social_allergies_v1": {
            "evidence": [],
            "pmh_items": [],
            "allergies": [
                {"allergen": "PCN", "raw_line_id": ""},  # empty
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PMH_SOCIAL_ALLERGIES_ALLERGIES_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected ALLERGIES raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_pmh_evidence_rejected():
    """pmh_social_allergies_v1 evidence with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "pmh_social_allergies_v1": {
            "evidence": [
                {"type": "pmh", "raw_line_id": ""},  # empty
            ],
            "pmh_items": [],
            "allergies": [],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PMH_SOCIAL_ALLERGIES_EVIDENCE_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected PMH evidence raw_line_id error, got: {errors}"


# ── Negative tests: procedure events raw_line_id ─────────────────────


def test_empty_raw_line_id_in_procedure_events_rejected():
    """procedure_operatives_v1 event with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "procedure_operatives_v1": {
            "evidence": [],
            "events": [
                {"type": "procedure", "raw_line_id": ""},  # empty
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PROCEDURE_OPERATIVES_EVENTS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected procedure events raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_procedure_events_rejected():
    """procedure_operatives_v1 event without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "procedure_operatives_v1": {
            "evidence": [],
            "events": [
                {"type": "procedure"},  # missing
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PROCEDURE_OPERATIVES_EVENTS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected procedure events raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_procedure_evidence_rejected():
    """procedure_operatives_v1 evidence with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "procedure_operatives_v1": {
            "evidence": [
                {"type": "op_note", "raw_line_id": ""},  # empty
            ],
            "events": [],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "PROCEDURE_OPERATIVES_EVIDENCE_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected procedure evidence raw_line_id error, got: {errors}"


# ── Negative tests: urine-output nested evidence ─────────────────────


def test_empty_raw_line_id_in_urine_output_evidence_rejected():
    """urine_output_events_v1 nested evidence with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "urine_output_events_v1": {
            "events": [
                {
                    "date": "2026-01-01",
                    "evidence": [
                        {"type": "uo", "raw_line_id": ""},  # empty
                    ],
                },
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "URINE_OUTPUT_EVIDENCE_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected urine output evidence raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_urine_output_evidence_rejected():
    """urine_output_events_v1 nested evidence without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "urine_output_events_v1": {
            "events": [
                {
                    "date": "2026-01-01",
                    "evidence": [
                        {"type": "uo"},  # missing
                    ],
                },
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "URINE_OUTPUT_EVIDENCE_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected urine output evidence raw_line_id error, got: {errors}"


def test_valid_urine_output_evidence_passes():
    """urine_output_events_v1 nested evidence with valid raw_line_id passes."""
    payload = _minimal_payload(features={
        "urine_output_events_v1": {
            "events": [
                {
                    "date": "2026-01-01",
                    "evidence": [
                        {"type": "uo", "raw_line_id": "L30-L31"},
                    ],
                },
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "URINE_OUTPUT_EVIDENCE_MISSING_RAW_LINE_ID" in e]
    assert not rid_errors, f"Unexpected urine output evidence error: {errors}"


# ── Negative tests: structured labs evidence ──────────────────────────


def test_empty_raw_line_id_in_structured_labs_series_rejected():
    """structured_labs_v1 series entry with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "structured_labs_v1": {
            "panels_by_day": {
                "2026-01-01": {
                    "cbc": {
                        "components": {
                            "wbc": {
                                "status": "available",
                                "series": [
                                    {"value": 10.5, "raw_line_id": ""},  # empty
                                ],
                            },
                        },
                    },
                },
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "STRUCTURED_LABS_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected structured labs raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_structured_labs_series_rejected():
    """structured_labs_v1 series entry without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "structured_labs_v1": {
            "panels_by_day": {
                "2026-01-01": {
                    "bmp": {
                        "components": {
                            "creatinine": {
                                "status": "available",
                                "series": [
                                    {"value": 1.2},  # missing
                                ],
                            },
                        },
                    },
                },
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "STRUCTURED_LABS_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected structured labs raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_structured_labs_pf_ratio_rejected():
    """structured_labs_v1 pf_ratio with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "structured_labs_v1": {
            "panels_by_day": {
                "2026-01-01": {
                    "pf_ratio": {
                        "status": "available",
                        "value": 250,
                        "raw_line_id": "",  # empty
                    },
                },
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "STRUCTURED_LABS_MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected structured labs pf_ratio raw_line_id error, got: {errors}"


def test_valid_structured_labs_passes():
    """structured_labs_v1 with valid raw_line_ids must pass."""
    payload = _minimal_payload(features={
        "structured_labs_v1": {
            "panels_by_day": {
                "2026-01-01": {
                    "cbc": {
                        "components": {
                            "wbc": {
                                "status": "available",
                                "series": [
                                    {"value": 10.5, "raw_line_id": "L1-L2"},
                                ],
                            },
                        },
                    },
                    "pf_ratio": {
                        "status": "available",
                        "value": 300,
                        "raw_line_id": "L10-L11",
                    },
                },
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "STRUCTURED_LABS_MISSING_RAW_LINE_ID" in e]
    assert not rid_errors, f"Unexpected structured labs error: {errors}"


def test_structured_labs_unavailable_component_skipped():
    """structured_labs_v1 component with status != 'available' must be skipped."""
    payload = _minimal_payload(features={
        "structured_labs_v1": {
            "panels_by_day": {
                "2026-01-01": {
                    "cbc": {
                        "components": {
                            "wbc": {
                                "status": "not_ordered",
                                "series": [
                                    {"value": 10.5},  # no raw_line_id, but not 'available'
                                ],
                            },
                        },
                    },
                },
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "STRUCTURED_LABS_MISSING_RAW_LINE_ID" in e]
    assert not rid_errors, f"Non-available component should be skipped: {errors}"


# ── Negative tests: ventilator events raw_line_id ─────────────────────


def test_empty_raw_line_id_in_ventilator_events_rejected():
    """ventilator_settings_v1 event with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "ventilator_settings_v1": {
            "events": [
                {"type": "vent", "raw_line_id": ""},  # empty
            ],
            "summary": {},
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "VENTILATOR_SETTINGS_EVENTS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected ventilator events raw_line_id error, got: {errors}"


def test_missing_raw_line_id_in_ventilator_events_rejected():
    """ventilator_settings_v1 event without raw_line_id must be caught."""
    payload = _minimal_payload(features={
        "ventilator_settings_v1": {
            "events": [
                {"type": "vent"},  # missing
            ],
            "summary": {},
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "VENTILATOR_SETTINGS_EVENTS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected ventilator events raw_line_id error, got: {errors}"


# ── Negative tests: anticoag_context nested lists ─────────────────────


def test_empty_raw_line_id_in_home_anticoagulants_rejected():
    """anticoag_context_v1 home_anticoagulants with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "anticoag_context_v1": {
            "evidence": [],
            "home_anticoagulants": [
                {"drug": "warfarin", "raw_line_id": ""},  # empty
            ],
            "home_antiplatelets": [],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "ANTICOAG_CONTEXT_HOME_ANTICOAGULANTS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected home_anticoagulants raw_line_id error, got: {errors}"


def test_empty_raw_line_id_in_home_antiplatelets_rejected():
    """anticoag_context_v1 home_antiplatelets with raw_line_id='' must be caught."""
    payload = _minimal_payload(features={
        "anticoag_context_v1": {
            "evidence": [],
            "home_anticoagulants": [],
            "home_antiplatelets": [
                {"drug": "aspirin", "raw_line_id": ""},  # empty
            ],
        },
    })
    errors = validate_contract(payload)
    rid_errors = [
        e for e in errors
        if "ANTICOAG_CONTEXT_HOME_ANTIPLATELETS_MISSING_RAW_LINE_ID" in e
    ]
    assert rid_errors, f"Expected home_antiplatelets raw_line_id error, got: {errors}"


# ── Negative tests: evidence-as-dict container ────────────────────────


def test_evidence_as_dict_with_empty_raw_line_id_rejected():
    """Evidence stored as dict-of-lists must still be checked for raw_line_id."""
    payload = _minimal_payload(features={
        "category_activation_v1": {
            "evidence": {
                "pharm": [
                    {"type": "pharm", "raw_line_id": "L1-L2"},
                ],
                "exclusion": [
                    {"type": "exclusion", "raw_line_id": ""},  # empty
                ],
            },
        },
    })
    errors = validate_contract(payload)
    rid_errors = [e for e in errors if "MISSING_RAW_LINE_ID" in e]
    assert rid_errors, f"Expected raw_line_id error in dict evidence, got: {errors}"


# ── Boundary tests: multiple leaked / all-missing ─────────────────────


def test_multiple_leaked_top_level_feature_keys():
    """Multiple known feature keys at top level must all be reported."""
    payload = _minimal_payload()
    payload["dvt_prophylaxis_v1"] = {}
    payload["gi_prophylaxis_v1"] = {}
    errors = validate_contract(payload)
    leaked_errors = [e for e in errors if "LEAKED_FEATURE_KEYS" in e]
    assert leaked_errors, f"Expected LEAKED_FEATURE_KEYS, got: {errors}"
    # Both keys should appear in the error message
    assert "dvt_prophylaxis_v1" in leaked_errors[0]
    assert "gi_prophylaxis_v1" in leaked_errors[0]


def test_all_required_keys_missing():
    """Empty dict must report all required keys as missing."""
    errors = validate_contract({})
    missing_errors = [e for e in errors if "TOP_LEVEL_MISSING_KEYS" in e]
    assert missing_errors, f"Expected TOP_LEVEL_MISSING_KEYS, got: {errors}"
    null_errors = [e for e in errors if "FEATURES_NULL" in e]
    assert null_errors, f"Expected FEATURES_NULL for empty dict, got: {errors}"


def test_features_as_string_rejected():
    """features as a string must trigger FEATURES_TYPE_ERROR."""
    payload = _minimal_payload(features="not_a_dict")
    errors = validate_contract(payload)
    type_errors = [e for e in errors if "FEATURES_TYPE_ERROR" in e]
    assert type_errors, f"Expected FEATURES_TYPE_ERROR for string, got: {errors}"


def test_features_as_int_rejected():
    """features as an integer must trigger FEATURES_TYPE_ERROR."""
    payload = _minimal_payload(features=42)
    errors = validate_contract(payload)
    type_errors = [e for e in errors if "FEATURES_TYPE_ERROR" in e]
    assert type_errors, f"Expected FEATURES_TYPE_ERROR for int, got: {errors}"
