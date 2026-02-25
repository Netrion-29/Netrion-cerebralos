#!/usr/bin/env python3
"""
Tests for spine_clearance_v1 feature extraction.

Covers:
  - Empty / no-data → DATA NOT AVAILABLE (fail-closed)
  - Order Questions block parsing (YES/YES, NO/YES, YES/NO)
  - Inline spine clearance format
  - Phrase-based clearance detection
  - Phrase-based not-cleared detection
  - Conflicting signals → latest wins or fail-closed
  - Collar status detection
  - Region extraction from phrases
  - Determinism (identical output on re-run)
  - Order precedence over phrases
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cerebralos.features.spine_clearance_v1 import extract_spine_clearance

_DNA = "DATA NOT AVAILABLE"


def _make_days_data(items_by_day=None):
    """Build a minimal patient_days_v1 structure."""
    days = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}
    return {"meta": {"patient_id": "test"}, "days": days}


def _make_item(text, dt=None, item_type="PHYSICIAN_NOTE", raw_line_id=None):
    """Build a minimal timeline item."""
    item = {
        "type": item_type,
        "payload": {"text": text},
    }
    if dt:
        item["dt"] = dt
    if raw_line_id:
        item["raw_line_id"] = raw_line_id
    else:
        item["raw_line_id"] = "test_item_001"
    return item


# ═══════════════════════════════════════════════════════════════════
# Test: Empty / no data
# ═══════════════════════════════════════════════════════════════════

def test_empty_days():
    """No items at all → DNA."""
    result = extract_spine_clearance({"days": {}}, _make_days_data())
    assert result["clearance_status"] == _DNA
    assert result["method"] == _DNA
    assert result["collar_status"] == _DNA
    assert result["order_count"] == 0
    assert result["cleared_phrase_count"] == 0
    assert result["source_rule_id"] == "spine_clearance_v1"


def test_no_spine_content():
    """Items with unrelated content → DNA."""
    data = _make_days_data({
        "2025-12-05": [
            _make_item("Patient presents with chest pain. No relevant findings."),
        ],
    })
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == _DNA
    assert result["method"] == _DNA
    assert "no_spine_clearance_documentation_found" in result["notes"]


# ═══════════════════════════════════════════════════════════════════
# Test: Order Questions — structured block format
# ═══════════════════════════════════════════════════════════════════

def test_order_questions_both_yes():
    """Both regions YES → clearance_status=YES."""
    text = (
        "Ordered On\n12/18/2025 1704\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tYes\n"
        "Thoracic/Spine Lumbar Clearance\tYes\n"
    )
    data = _make_days_data({"2025-12-18": [_make_item(text, dt="2025-12-18T17:04:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "ORDER"
    assert result["order_count"] >= 2
    assert len(result["regions"]) == 2
    for r in result["regions"]:
        assert r["clearance"] == "YES"


def test_order_questions_cervical_no():
    """Cervical NO → clearance_status=NO."""
    text = (
        "Ordered On\n12/18/2025 1704\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tNo\n"
        "Thoracic/Spine Lumbar Clearance\tYes\n"
    )
    data = _make_days_data({"2025-12-18": [_make_item(text, dt="2025-12-18T17:04:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert result["method"] == "ORDER"


def test_order_questions_tl_no():
    """T/L NO → clearance_status=NO."""
    text = (
        "Ordered On\n12/18/2025 1716\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tYes\n"
        "Thoracic/Spine Lumbar Clearance\tNo\n"
    )
    data = _make_days_data({"2025-12-18": [_make_item(text, dt="2025-12-18T17:16:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert result["method"] == "ORDER"


def test_order_questions_cervical_only_yes():
    """Only cervical YES, no T/L → YES + note."""
    text = (
        "Ordered On\n12/18/2025 1704\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tYes\n"
    )
    data = _make_days_data({"2025-12-18": [_make_item(text, dt="2025-12-18T17:04:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "ORDER"


# ═══════════════════════════════════════════════════════════════════
# Test: Inline spine clearance format
# ═══════════════════════════════════════════════════════════════════

def test_inline_spine_clearance():
    """Inline format: 'Spine Clearance Cervical Spine Clearance: Yes; ...'"""
    text = (
        "Spine Clearance Cervical Spine Clearance: Yes; "
        "Thoracic/Spine Lumbar Clearance: Yes [NUR1015] (Order 464708792)"
    )
    data = _make_days_data({"2025-12-19": [_make_item(text, dt="2025-12-19T07:40:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "ORDER"


def test_inline_spine_clearance_mixed():
    """Inline format with mixed answers."""
    text = (
        "Spine Clearance Cervical Spine Clearance: Yes; "
        "Thoracic/Spine Lumbar Clearance: No [NUR1015]"
    )
    data = _make_days_data({"2025-12-18": [_make_item(text, dt="2025-12-18T17:04:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert result["method"] == "ORDER"


# ═══════════════════════════════════════════════════════════════════
# Test: Phrase-based clearance
# ═══════════════════════════════════════════════════════════════════

def test_phrase_spine_cleared():
    """'spine cleared' phrase → YES."""
    text = "PT/OT when appropriate. C spine cleared. Continue meds."
    data = _make_days_data({"2025-12-05": [_make_item(text, dt="2025-12-05T19:41:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "CLINICAL"
    assert result["cleared_phrase_count"] >= 1


def test_phrase_collar_cleared():
    """'collar cleared' phrase → YES."""
    text = "C-collar cleared, may discontinue."
    data = _make_days_data({"2025-12-06": [_make_item(text, dt="2025-12-06T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "CLINICAL"


def test_phrase_spine_not_cleared():
    """'spine not cleared' → NO."""
    text = "Spine not cleared. Continue collar."
    data = _make_days_data({"2025-12-05": [_make_item(text, dt="2025-12-05T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert result["method"] == "CLINICAL"


def test_phrase_continue_collar():
    """'continue collar' → NO."""
    text = "Continue c-collar. Awaiting imaging results."
    data = _make_days_data({"2025-12-05": [_make_item(text, dt="2025-12-05T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert result["method"] == "CLINICAL"


def test_phrase_c_and_tls_cleared():
    """'C and TLS spine cleared' → YES with regions."""
    text = "PT/OT when appropriate. C and TLS spine cleared (no pain - did not image)."
    data = _make_days_data({"2025-12-05": [_make_item(text, dt="2025-12-05T19:41:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "CLINICAL"


def test_phrase_tl_not_cleared():
    """'T/L-spine not cleared' → NO."""
    text = "C spine cleared. T/L-spine not cleared. Continue precautions."
    data = _make_days_data({"2025-12-07": [_make_item(text, dt="2025-12-07T10:08:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    # Has both cleared and not-cleared; same timestamp → fail-closed to NO
    # Actually, "C spine cleared" (cleared) + "T/L-spine not cleared" (not-cleared)
    # Both in same item so same dt. Conflicting → fail-closed
    assert result["clearance_status"] == "NO"
    assert result["method"] == "CLINICAL"


# ═══════════════════════════════════════════════════════════════════
# Test: Conflicting signals
# ═══════════════════════════════════════════════════════════════════

def test_conflicting_latest_wins():
    """Cleared first, then not-cleared later → NO (latest wins)."""
    data = _make_days_data({
        "2025-12-05": [
            _make_item("C spine cleared.", dt="2025-12-05T10:00:00"),
        ],
        "2025-12-06": [
            _make_item("Spine not cleared. Reassess.", dt="2025-12-06T08:00:00"),
        ],
    })
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert "conflicting_signals_latest_is_not_cleared" in result["notes"]


def test_conflicting_cleared_latest():
    """Not-cleared first, then cleared later → YES (latest wins)."""
    data = _make_days_data({
        "2025-12-05": [
            _make_item("Spine not cleared.", dt="2025-12-05T10:00:00"),
        ],
        "2025-12-06": [
            _make_item("C spine cleared.", dt="2025-12-06T10:00:00"),
        ],
    })
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert "conflicting_signals_latest_is_cleared" in result["notes"]


# ═══════════════════════════════════════════════════════════════════
# Test: Collar status
# ═══════════════════════════════════════════════════════════════════

def test_collar_present():
    """Collar in place → PRESENT."""
    text = "C-collar in place. Patient resting."
    data = _make_days_data({"2025-12-05": [_make_item(text, dt="2025-12-05T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["collar_status"] == "PRESENT"


def test_collar_removed():
    """Collar removed → REMOVED."""
    text = "Collar removed per protocol."
    data = _make_days_data({"2025-12-05": [_make_item(text, dt="2025-12-05T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["collar_status"] == "REMOVED"


def test_collar_removed_takes_precedence():
    """Both collar present and removed → REMOVED (removed takes precedence)."""
    data = _make_days_data({
        "2025-12-05": [
            _make_item("C-collar in place.", dt="2025-12-05T10:00:00"),
            _make_item("Collar removed.", dt="2025-12-05T14:00:00"),
        ],
    })
    result = extract_spine_clearance({"days": {}}, data)
    assert result["collar_status"] == "REMOVED"


# ═══════════════════════════════════════════════════════════════════
# Test: Order precedence over phrases
# ═══════════════════════════════════════════════════════════════════

def test_order_precedence_over_phrases():
    """Order says NO but phrases say cleared → NO (order wins)."""
    order_text = (
        "Ordered On\n12/18/2025 1704\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tNo\n"
        "Thoracic/Spine Lumbar Clearance\tNo\n"
    )
    phrase_text = "C spine cleared. All good."
    data = _make_days_data({
        "2025-12-18": [
            _make_item(order_text, dt="2025-12-18T17:04:00"),
            _make_item(phrase_text, dt="2025-12-18T18:00:00"),
        ],
    })
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "NO"
    assert result["method"] == "ORDER"


# ═══════════════════════════════════════════════════════════════════
# Test: Determinism
# ═══════════════════════════════════════════════════════════════════

def test_determinism():
    """Same input → same output on repeated calls."""
    text = (
        "Ordered On\n12/18/2025 1704\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tYes\n"
        "Thoracic/Spine Lumbar Clearance\tYes\n"
    )
    data = _make_days_data({"2025-12-18": [_make_item(text, dt="2025-12-18T17:04:00")]})

    r1 = extract_spine_clearance({"days": {}}, data)
    r2 = extract_spine_clearance({"days": {}}, data)
    assert r1 == r2


# ═══════════════════════════════════════════════════════════════════
# Test: Evidence traceability
# ═══════════════════════════════════════════════════════════════════

def test_evidence_has_raw_line_id():
    """All evidence entries must have raw_line_id."""
    text = "C spine cleared. Continue monitoring."
    data = _make_days_data({"2025-12-05": [
        _make_item(text, dt="2025-12-05T10:00:00", raw_line_id="RLI_001"),
    ]})
    result = extract_spine_clearance({"days": {}}, data)
    for ev in result["evidence"]:
        assert "raw_line_id" in ev, f"Evidence missing raw_line_id: {ev}"


def test_green_card_overlap_note():
    """Output must contain green-card overlap note."""
    result = extract_spine_clearance({"days": {}}, _make_days_data())
    overlap_notes = [n for n in result["notes"] if "green_card_overlap" in n]
    assert len(overlap_notes) == 1


# ═══════════════════════════════════════════════════════════════════
# Test: Multiple orders → latest wins
# ═══════════════════════════════════════════════════════════════════

def test_multiple_orders_latest_wins():
    """Two orders: first NO, later YES → latest (YES) wins."""
    text1 = (
        "Ordered On\n12/18/2025 1704\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tNo\n"
        "Thoracic/Spine Lumbar Clearance\tNo\n"
    )
    text2 = (
        "Ordered On\n12/19/2025 0740\n\n"
        "Order Questions\n\n"
        "Question\tAnswer\n"
        "Cervical Spine Clearance\tYes\n"
        "Thoracic/Spine Lumbar Clearance\tYes\n"
    )
    data = _make_days_data({
        "2025-12-18": [_make_item(text1, dt="2025-12-18T17:04:00")],
        "2025-12-19": [_make_item(text2, dt="2025-12-19T07:40:00")],
    })
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "ORDER"


def test_spine_precautions_discontinued():
    """'spine precautions discontinued' → YES."""
    text = "Spine precautions discontinued per attending."
    data = _make_days_data({"2025-12-06": [_make_item(text, dt="2025-12-06T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "CLINICAL"


def test_remove_collar():
    """'remove collar' → YES clearance + REMOVED collar."""
    text = "Remove collar. Patient tolerating well."
    data = _make_days_data({"2025-12-06": [_make_item(text, dt="2025-12-06T10:00:00")]})
    result = extract_spine_clearance({"days": {}}, data)
    assert result["clearance_status"] == "YES"
    assert result["method"] == "CLINICAL"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
