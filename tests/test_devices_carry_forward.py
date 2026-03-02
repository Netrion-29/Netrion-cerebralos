#!/usr/bin/env python3
"""Tests for device carry-forward and extubation stop logic.

Covers:
  - absent_wins: ETT/vent tri-state flips to NOT_PRESENT on extubation day
    even when historical "intubated" narrative co-exists.
  - BiPAP/NIV tracked as separate device, not classified as ETT/vent.
  - DNI/DNR language does NOT trigger ETT PRESENT (absent_wins blocks it).
  - Carry-forward chain breaks on NOT_PRESENT and after max gap.
  - bipap_niv included in tracked devices list.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.devices_day import evaluate_devices_for_day
from cerebralos.features.devices_carry_forward import (
    compute_carry_forward_and_day_counts,
    _TRACKED_DEVICES,
)

# ── load production config ───────────────────────────────────────
_RULES_DIR = Path(__file__).resolve().parent.parent / "rules" / "features"
with open(_RULES_DIR / "devices_patterns_v1.json") as f:
    _CONFIG = json.load(f)


# ── helpers ──────────────────────────────────────────────────────

def _item(text: str, source_id: str = "src-1", dt: str = "2025-12-25 08:00",
          item_type: str = "PHYSICIAN_NOTE"):
    """Build a minimal timeline item."""
    return {
        "source_id": source_id,
        "dt": dt,
        "type": item_type,
        "payload": {"text": text},
    }


def _tri(items, day="2025-12-25"):
    """Shorthand: evaluate tri-state for a list of items."""
    result, _ = evaluate_devices_for_day(items, day, _CONFIG)
    return result["tri_state"]


# ═══════════════════════════════════════════════════════════════════
#  Section 1: absent_wins – ETT extubation overrides historical text
# ═══════════════════════════════════════════════════════════════════

class TestAbsentWins(unittest.TestCase):
    """When absent_wins=true and both present + absent match, NOT_PRESENT wins."""

    def test_extubation_overrides_historical_ett(self):
        """'Patient was intubated' + 'Patient extubated' → NOT_PRESENT."""
        tri = _tri([
            _item("Patient was intubated on 12/25 for respiratory failure."),
            _item("Patient extubated this morning; on room air."),
        ])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_copied_cxr_ett_in_place_overridden_by_extubation(self):
        """Copied CXR report 'ETT in place' + extubation note → NOT_PRESENT."""
        tri = _tri([
            _item("CXR: ETT in place, tip at carina. No infiltrate."),
            _item("Patient extubated to nasal cannula at 0630."),
        ])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_extubated_to_bipap(self):
        """'extubated to BiPAP' triggers both absent_wins ETT → NOT_PRESENT."""
        tri = _tri([
            _item("Patient was on ventilator, extubated to BiPAP."),
        ])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_extubated_to_niv(self):
        tri = _tri([_item("Extubated to NIV following successful SBT")])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_extubated_to_hfnc(self):
        tri = _tri([_item("Extubated to high-flow nasal cannula at 14:00")])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_only_present_no_absent_still_present(self):
        """When only present matches exist, PRESENT is still returned."""
        tri = _tri([_item("Ventilator: SIMV, TV 500, FiO2 40%.")])
        self.assertEqual(tri["ett_vent"], "PRESENT")

    def test_only_absent_still_not_present(self):
        """When only absent matches exist, NOT_PRESENT."""
        tri = _tri([_item("Patient extubated. Breathing room air.")])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_foley_does_not_have_absent_wins(self):
        """Foley does NOT use absent_wins — present still wins by default."""
        tri = _tri([
            _item("Foley catheter draining clear urine."),
            _item("Foley removed per MD order."),
        ])
        # Default resolution: PRESENT wins over NOT_PRESENT
        self.assertEqual(tri["foley"], "PRESENT")

    def test_planning_language_does_not_block_present(self):
        """'Once extubated... will need NIV' should NOT make ETT NOT_PRESENT."""
        tri = _tri([
            _item("Ventilator: SIMV, TV 500, FiO2 40%."),
            _item("Once extubated the patient will need to be extubated to NIV."),
        ])
        # Planning language excluded → absent match suppressed → PRESENT wins
        self.assertEqual(tri["ett_vent"], "PRESENT")

    def test_possible_extubation_does_not_block_present(self):
        """'Possible extubation to bipap today' is planning, not actual."""
        tri = _tri([
            _item("On vent, vent settings: AC, TV 450."),
            _item("Possible extubation to bipap today."),
        ])
        self.assertEqual(tri["ett_vent"], "PRESENT")

    def test_eventual_extubation_plan(self):
        """'When eventually extubated' is future conditional."""
        tri = _tri([
            _item("Ventilator mode AC. FiO2 40%."),
            _item("When patient is eventually extubated, he will need BiPAP."),
        ])
        self.assertEqual(tri["ett_vent"], "PRESENT")


# ═══════════════════════════════════════════════════════════════════
#  Section 2: DNI/DNR – should NOT trigger ETT PRESENT
# ═══════════════════════════════════════════════════════════════════

class TestDNI(unittest.TestCase):
    """DNI (do not intubate) language triggers absent pattern, blocking ETT false pos."""

    def test_dni_alone_not_present(self):
        """'do not intubate' matches absent → NOT_PRESENT (not PRESENT via 'intubat')."""
        tri = _tri([_item("Goals of care: do not intubate, comfort measures.")])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_dnr_dni_combined(self):
        """'DNR/DNI' matches absent → NOT_PRESENT."""
        tri = _tri([_item("Code status: DNR/DNI. Family meeting held.")])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")

    def test_do_not_resuscitate_intubate(self):
        tri = _tri([_item("Patient is do not resuscitate/intubate.")])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")


# ═══════════════════════════════════════════════════════════════════
#  Section 3: BiPAP/NIV as separate device
# ═══════════════════════════════════════════════════════════════════

class TestBiPAPNIV(unittest.TestCase):
    """bipap_niv tracked as separate device independent of ett_vent."""

    def test_bipap_niv_in_tracked_devices(self):
        self.assertIn("bipap_niv", _TRACKED_DEVICES)

    def test_bipap_present(self):
        tri = _tri([_item("Patient on BiPAP overnight, settings 10/5.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")

    def test_cpap_present(self):
        tri = _tri([_item("CPAP at bedside for obstructive sleep apnea.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")

    def test_hfnc_present(self):
        tri = _tri([_item("Started on HFNC at 40L, FiO2 50%.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")

    def test_niv_present(self):
        tri = _tri([_item("NIV initiated for acute on chronic respiratory failure.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")

    def test_high_flow_nasal_cannula(self):
        tri = _tri([_item("On high-flow nasal cannula, weaning FiO2.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")

    def test_noninvasive_ventilation(self):
        tri = _tri([_item("Non-invasive ventilation started for COPD exacerbation.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")

    def test_bipap_does_not_trigger_ett_vent(self):
        """'BiPAP' should trigger bipap_niv PRESENT but NOT ett_vent PRESENT."""
        tri = _tri([_item("Patient on BiPAP overnight, tolerated well.")])
        self.assertEqual(tri["bipap_niv"], "PRESENT")
        self.assertEqual(tri["ett_vent"], "UNKNOWN")

    def test_bipap_removed(self):
        tri = _tri([_item("BiPAP discontinued, patient on room air.")])
        self.assertEqual(tri["bipap_niv"], "NOT_PRESENT")

    def test_room_air_absent(self):
        tri = _tri([_item("Patient on room air. No supplemental O2.")])
        self.assertEqual(tri["bipap_niv"], "NOT_PRESENT")

    def test_bipap_present_and_ett_not_present_on_same_day(self):
        """Post-extubation: ETT=NOT_PRESENT, BiPAP=PRESENT."""
        tri = _tri([
            _item("Patient extubated to BiPAP this morning."),
            _item("BiPAP settings: 12/5, FiO2 40%."),
        ])
        self.assertEqual(tri["ett_vent"], "NOT_PRESENT")
        self.assertEqual(tri["bipap_niv"], "PRESENT")


# ═══════════════════════════════════════════════════════════════════
#  Section 4: Carry-forward integration
# ═══════════════════════════════════════════════════════════════════

class TestCarryForward(unittest.TestCase):
    """Carry-forward state machine respects NOT_PRESENT for chain break."""

    def _build_days(self, day_states):
        """Build days_devices from a dict of {day: {device: state}}."""
        return {day: {"canonical": states} for day, states in day_states.items()}

    def test_not_present_breaks_chain(self):
        """ETT goes PRESENT → NOT_PRESENT → chain resets."""
        days = self._build_days({
            "2025-12-25": {"ett_vent": "PRESENT"},
            "2025-12-26": {"ett_vent": "PRESENT"},
            "2025-12-27": {"ett_vent": "NOT_PRESENT"},
            "2025-12-28": {"ett_vent": "UNKNOWN"},
        })
        enrichment, _ = compute_carry_forward_and_day_counts(
            sorted(days.keys()), days, _CONFIG
        )
        self.assertEqual(enrichment["2025-12-25"]["carry_forward"]["ett_vent"], "PRESENT")
        self.assertEqual(enrichment["2025-12-26"]["carry_forward"]["ett_vent"], "PRESENT")
        self.assertEqual(enrichment["2025-12-27"]["carry_forward"]["ett_vent"], "NOT_PRESENT")
        # After NOT_PRESENT, UNKNOWN stays UNKNOWN (chain broken)
        self.assertEqual(enrichment["2025-12-28"]["carry_forward"]["ett_vent"], "UNKNOWN")

    def test_unknown_gap_carries_forward(self):
        """PRESENT → UNKNOWN within max window → PRESENT_INFERRED."""
        days = self._build_days({
            "2025-12-25": {"ett_vent": "PRESENT"},
            "2025-12-26": {"ett_vent": "UNKNOWN"},
            "2025-12-27": {"ett_vent": "UNKNOWN"},
        })
        enrichment, _ = compute_carry_forward_and_day_counts(
            sorted(days.keys()), days, _CONFIG
        )
        self.assertEqual(enrichment["2025-12-26"]["carry_forward"]["ett_vent"], "PRESENT_INFERRED")
        self.assertEqual(enrichment["2025-12-27"]["carry_forward"]["ett_vent"], "PRESENT_INFERRED")

    def test_day_count_resets_on_extubation(self):
        """Consecutive day counter resets to 0 on NOT_PRESENT."""
        days = self._build_days({
            "2025-12-25": {"ett_vent": "PRESENT"},
            "2025-12-26": {"ett_vent": "PRESENT"},
            "2025-12-27": {"ett_vent": "PRESENT"},
            "2025-12-28": {"ett_vent": "NOT_PRESENT"},
        })
        enrichment, _ = compute_carry_forward_and_day_counts(
            sorted(days.keys()), days, _CONFIG
        )
        self.assertEqual(
            enrichment["2025-12-27"]["day_counts"]["ett_vent_consecutive_days"], 3
        )
        self.assertEqual(
            enrichment["2025-12-28"]["day_counts"]["ett_vent_consecutive_days"], 0
        )

    def test_bipap_carry_forward(self):
        """bipap_niv supports carry-forward like other devices."""
        days = self._build_days({
            "2025-12-25": {"bipap_niv": "PRESENT"},
            "2025-12-26": {"bipap_niv": "UNKNOWN"},
        })
        enrichment, _ = compute_carry_forward_and_day_counts(
            sorted(days.keys()), days, _CONFIG
        )
        self.assertEqual(enrichment["2025-12-26"]["carry_forward"]["bipap_niv"], "PRESENT_INFERRED")

    def test_max_carry_forward_expires(self):
        """After max_carry_forward_days of UNKNOWN, chain expires."""
        max_d = _CONFIG.get("_carry_forward", {}).get("max_carry_forward_days", 7)
        day_states = {"2025-12-25": {"ett_vent": "PRESENT"}}
        for i in range(1, max_d + 2):
            d = f"2025-12-{25 + i:02d}"
            day_states[d] = {"ett_vent": "UNKNOWN"}
        days = self._build_days(day_states)
        enrichment, warnings = compute_carry_forward_and_day_counts(
            sorted(days.keys()), days, _CONFIG
        )
        # Day at max_carry should still be inferred
        inferred_day = f"2025-12-{25 + max_d:02d}"
        self.assertEqual(
            enrichment[inferred_day]["carry_forward"]["ett_vent"], "PRESENT_INFERRED"
        )
        # Day beyond max_carry should be UNKNOWN
        expired_day = f"2025-12-{25 + max_d + 1:02d}"
        self.assertEqual(
            enrichment[expired_day]["carry_forward"]["ett_vent"], "UNKNOWN"
        )
        # Should have a warning about expiry
        self.assertTrue(any("carry_forward_expired" in w for w in warnings))


# ═══════════════════════════════════════════════════════════════════
#  Section 5: End-to-end – ETT stops after extubation day
# ═══════════════════════════════════════════════════════════════════

class TestEndToEndExtubation(unittest.TestCase):
    """Simulate a multi-day intubation → extubation scenario."""

    def test_ett_stops_at_extubation(self):
        """4 days intubated, extubation on day 4, days 5+ should not count."""
        # Day 1-3: ventilator present only
        # Day 4: extubation documented with historical 'was intubated'
        # Day 5: historical mention only (was intubated, CXR)
        items_by_day = {
            "2025-12-25": [_item("Ventilator: SIMV, TV 500.", dt="2025-12-25 08:00")],
            "2025-12-26": [_item("On vent, vent settings: AC, TV 450.", dt="2025-12-26 08:00")],
            "2025-12-27": [_item("Ventilator mode AC. FiO2 40%.", dt="2025-12-27 08:00")],
            "2025-12-28": [
                _item("Patient was intubated on 12/25. Now extubated.", dt="2025-12-28 08:00"),
                _item("Successfully extubated to nasal cannula.", dt="2025-12-28 10:00"),
            ],
            "2025-12-29": [
                _item("Patient resting comfortably. No acute distress.", dt="2025-12-29 08:00"),
            ],
        }

        sorted_days = sorted(items_by_day.keys())
        days_devices = {}
        for day in sorted_days:
            result, _ = evaluate_devices_for_day(items_by_day[day], day, _CONFIG)
            days_devices[day] = {"canonical": result["tri_state"]}

        enrichment, _ = compute_carry_forward_and_day_counts(
            sorted_days, days_devices, _CONFIG
        )

        # Days 1-3: PRESENT
        self.assertEqual(enrichment["2025-12-25"]["carry_forward"]["ett_vent"], "PRESENT")
        self.assertEqual(enrichment["2025-12-26"]["carry_forward"]["ett_vent"], "PRESENT")
        self.assertEqual(enrichment["2025-12-27"]["carry_forward"]["ett_vent"], "PRESENT")
        # Day 4: extubation → NOT_PRESENT
        self.assertEqual(enrichment["2025-12-28"]["carry_forward"]["ett_vent"], "NOT_PRESENT")
        # Day 5: chain broken, should NOT be PRESENT or PRESENT_INFERRED
        self.assertIn(
            enrichment["2025-12-29"]["carry_forward"]["ett_vent"],
            ("UNKNOWN", "NOT_PRESENT"),
        )
        # Day count on day 3 should be 3
        self.assertEqual(
            enrichment["2025-12-27"]["day_counts"]["ett_vent_consecutive_days"], 3
        )
        # Day count on day 4+ should be 0
        self.assertEqual(
            enrichment["2025-12-28"]["day_counts"]["ett_vent_consecutive_days"], 0
        )

    def test_extubation_to_bipap_both_tracked(self):
        """Extubation to BiPAP: ETT stops, BiPAP starts on same day."""
        items = {
            "2025-12-25": [_item("Ventilator: SIMV.", dt="2025-12-25 08:00")],
            "2025-12-26": [
                _item("Extubated to BiPAP. Settings 12/5, FiO2 40%.", dt="2025-12-26 08:00"),
            ],
            "2025-12-27": [_item("Continues on BiPAP overnight.", dt="2025-12-27 08:00")],
        }

        sorted_days = sorted(items.keys())
        days_devices = {}
        for day in sorted_days:
            result, _ = evaluate_devices_for_day(items[day], day, _CONFIG)
            days_devices[day] = {"canonical": result["tri_state"]}

        enrichment, _ = compute_carry_forward_and_day_counts(
            sorted_days, days_devices, _CONFIG
        )

        # Day 1: ETT present, no BiPAP
        self.assertEqual(enrichment["2025-12-25"]["carry_forward"]["ett_vent"], "PRESENT")
        # Day 2: ETT stops, BiPAP starts
        self.assertEqual(enrichment["2025-12-26"]["carry_forward"]["ett_vent"], "NOT_PRESENT")
        self.assertEqual(enrichment["2025-12-26"]["carry_forward"]["bipap_niv"], "PRESENT")
        # Day 3: BiPAP continues
        self.assertEqual(enrichment["2025-12-27"]["carry_forward"]["bipap_niv"], "PRESENT")
        # ETT should NOT infer forward from day 1 (chain broken by NOT_PRESENT on day 2)
        self.assertIn(
            enrichment["2025-12-27"]["carry_forward"]["ett_vent"],
            ("UNKNOWN", "NOT_PRESENT"),
        )


if __name__ == "__main__":
    unittest.main()
