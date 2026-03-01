#!/usr/bin/env python3
"""
Tests for patient_days meta propagation.

Verifies that build_patient_days correctly propagates meta fields
from evidence -> timeline, including discharge_datetime (PR #71+).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.timeline.build_patient_days import build_patient_days


def _make_evidence(meta: dict, items: list | None = None) -> dict:
    return {"meta": meta, "items": items or []}


class TestMetaPropagation:
    def test_discharge_datetime_propagated(self):
        """discharge_datetime present in evidence meta → appears in timeline meta."""
        ev = _make_evidence({
            "patient_id": "12345",
            "arrival_datetime": "2026-01-01 17:50:00",
            "discharge_datetime": "2026-01-03 10:18:00",
        })
        result = build_patient_days(ev)
        assert result["meta"]["discharge_datetime"] == "2026-01-03 10:18:00"

    def test_discharge_datetime_none_when_absent(self):
        """discharge_datetime absent from evidence meta → None in timeline meta."""
        ev = _make_evidence({
            "patient_id": "12345",
            "arrival_datetime": "2026-01-01 17:50:00",
        })
        result = build_patient_days(ev)
        assert result["meta"]["discharge_datetime"] is None

    def test_discharge_datetime_explicit_none(self):
        """discharge_datetime explicitly None in evidence meta → None in timeline meta."""
        ev = _make_evidence({
            "patient_id": "12345",
            "arrival_datetime": "2026-01-01 17:50:00",
            "discharge_datetime": None,
        })
        result = build_patient_days(ev)
        assert result["meta"]["discharge_datetime"] is None

    def test_arrival_and_patient_id_still_propagated(self):
        """Existing fields still propagated correctly alongside discharge."""
        ev = _make_evidence({
            "patient_id": "99999",
            "arrival_datetime": "2026-01-05 08:00:00",
            "discharge_datetime": "2026-01-10 14:30:00",
        })
        result = build_patient_days(ev)
        assert result["meta"]["patient_id"] == "99999"
        assert result["meta"]["arrival_datetime"] == "2026-01-05 08:00:00"
        assert result["meta"]["day0_date"] == "2026-01-05"
        assert result["meta"]["discharge_datetime"] == "2026-01-10 14:30:00"
