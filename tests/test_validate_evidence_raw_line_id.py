"""Tests for validate_evidence_raw_line_id."""

from cerebralos.validation.validate_evidence_raw_line_id import validate


def test_valid_evidence_passes():
    """Evidence with all valid raw_line_id values passes."""
    data = {
        "items": [
            {"raw_line_id": "L10-L12", "type": "diagnosis"},
            {"raw_line_id": "L20-L22", "type": "medication"},
        ],
    }
    errors = validate(data)
    assert errors == [], f"Unexpected errors: {errors}"


def test_missing_raw_line_id_fails():
    """Evidence item without raw_line_id key must fail."""
    data = {
        "items": [
            {"type": "diagnosis"},  # no raw_line_id
        ],
    }
    errors = validate(data)
    assert len(errors) == 1
    assert "EVIDENCE_MISSING_RAW_LINE_ID" in errors[0]


def test_empty_raw_line_id_fails():
    """Evidence item with raw_line_id='' must fail."""
    data = {
        "items": [
            {"raw_line_id": "", "type": "diagnosis"},
        ],
    }
    errors = validate(data)
    assert len(errors) == 1
    assert "EVIDENCE_MISSING_RAW_LINE_ID" in errors[0]


def test_none_raw_line_id_fails():
    """Evidence item with raw_line_id=None must fail."""
    data = {
        "items": [
            {"raw_line_id": None, "type": "diagnosis"},
        ],
    }
    errors = validate(data)
    assert len(errors) == 1
    assert "EVIDENCE_MISSING_RAW_LINE_ID" in errors[0]


def test_missing_items_key_fails():
    """Evidence JSON without 'items' key must fail."""
    data = {"meta": {"patient_slug": "test"}}
    errors = validate(data)
    assert len(errors) == 1
    assert "MISSING_ITEMS_KEY" in errors[0]


def test_items_wrong_type_fails():
    """Evidence with 'items' as a dict instead of list must fail."""
    data = {"items": {"foo": "bar"}}
    errors = validate(data)
    assert len(errors) == 1
    assert "ITEMS_NOT_LIST" in errors[0]


def test_empty_items_passes():
    """Evidence with empty items list passes (no violations)."""
    data = {"items": []}
    errors = validate(data)
    assert errors == []


def test_mixed_valid_and_invalid():
    """Multiple items: counts only the missing/empty ones."""
    data = {
        "items": [
            {"raw_line_id": "L1-L2", "type": "a"},
            {"raw_line_id": "", "type": "b"},       # empty
            {"type": "c"},                            # missing
            {"raw_line_id": "L5-L6", "type": "d"},
        ],
    }
    errors = validate(data)
    assert len(errors) == 1
    assert "2/4" in errors[0]  # 2 invalid out of 4
