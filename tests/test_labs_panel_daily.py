"""
Tests for labs_panel_daily.py — base-deficit sign preservation.

Verifies:
- Base Deficit values pass through with correct sign
- Base Excess values are negated (BD = -BE — clinical convention)
- Missing / None values degrade to DNA
- Mixed days render correctly
- CBC / BMP / Coags panels resolve without regressions
"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cerebralos.features.labs_panel_daily import build_labs_panel_daily

_DNA = "DATA NOT AVAILABLE"


def _make_labs_block(daily: dict | None = None) -> dict:
    """Build a minimal labs block for testing."""
    return {
        "daily": daily or {},
        "series": {},
        "latest": {},
    }


# ════════════════════════════════════════════════════════════════════
# Base Deficit sign preservation
# ════════════════════════════════════════════════════════════════════


class TestBaseDeficitSignPreservation(unittest.TestCase):
    """BD values extracted from 'Base Deficit' component keep their sign."""

    def test_positive_bd_stays_positive(self):
        labs = _make_labs_block({"Base Deficit": {"last": 7.2, "first": 7.2, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], 7.2)

    def test_negative_bd_stays_negative(self):
        labs = _make_labs_block({"Base Deficit": {"last": -2.3, "first": -2.3, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], -2.3)

    def test_zero_bd_stays_zero(self):
        labs = _make_labs_block({"Base Deficit": {"last": 0.0, "first": 0.0, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], 0.0)


class TestBaseExcessNegation(unittest.TestCase):
    """BD values extracted from 'Base Excess' component are negated (BD = -BE)."""

    def test_positive_be_becomes_negative_bd(self):
        """BE of +3.5 → BD of -3.5 (alkalotic, no deficit)."""
        labs = _make_labs_block({"Base Excess": {"last": 3.5, "first": 3.5, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], -3.5)

    def test_negative_be_becomes_positive_bd(self):
        """BE of -6.0 → BD of 6.0 (metabolic acidosis)."""
        labs = _make_labs_block({"Base Excess": {"last": -6.0, "first": -6.0, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], 6.0)

    def test_large_positive_be_negated(self):
        """BE of +18.6 → BD of -18.6."""
        labs = _make_labs_block({"Base Excess": {"last": 18.6, "first": 18.6, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], -18.6)

    def test_zero_be_stays_zero(self):
        """BE of 0.0 → BD of 0.0 (no change)."""
        labs = _make_labs_block({"Base Excess": {"last": 0.0, "first": 0.0, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], 0.0)

    def test_be_case_insensitive(self):
        """Component name matching is case-insensitive."""
        labs = _make_labs_block({"base excess": {"last": 5.0, "first": 5.0, "n_values": 1}})
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        self.assertAlmostEqual(panel["base_deficit"]["value"], -5.0)


class TestBaseDeficitPreference(unittest.TestCase):
    """When both BD and BE are present, BD takes priority (first in candidates)."""

    def test_bd_preferred_over_be(self):
        labs = _make_labs_block({
            "Base Deficit": {"last": 4.0, "first": 4.0, "n_values": 1},
            "Base Excess": {"last": -4.0, "first": -4.0, "n_values": 1},
        })
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["base_deficit"], dict)
        # Should use Base Deficit directly (no negation)
        self.assertAlmostEqual(panel["base_deficit"]["value"], 4.0)


class TestBaseDeficitMissing(unittest.TestCase):
    """Missing / None BD values degrade to DNA."""

    def test_no_bd_or_be(self):
        labs = _make_labs_block({})
        panel = build_labs_panel_daily(labs)
        self.assertEqual(panel["base_deficit"], _DNA)

    def test_bd_with_none_last(self):
        labs = _make_labs_block({"Base Deficit": {"last": None, "first": None, "n_values": 0}})
        panel = build_labs_panel_daily(labs)
        self.assertEqual(panel["base_deficit"], _DNA)

    def test_empty_labs_block(self):
        panel = build_labs_panel_daily({})
        self.assertEqual(panel["base_deficit"], _DNA)


class TestBaseDeficitAbnormalFlag(unittest.TestCase):
    """Abnormal flag propagates correctly."""

    def test_abnormal_flag_preserved(self):
        labs = _make_labs_block({
            "Base Deficit": {
                "last": 8.1, "first": 8.1, "n_values": 1,
                "abnormal_flag_present": True,
            }
        })
        panel = build_labs_panel_daily(labs)
        self.assertTrue(panel["base_deficit"]["abnormal"])

    def test_abnormal_flag_default_false(self):
        labs = _make_labs_block({
            "Base Deficit": {"last": 1.0, "first": 1.0, "n_values": 1}
        })
        panel = build_labs_panel_daily(labs)
        self.assertFalse(panel["base_deficit"]["abnormal"])


# ════════════════════════════════════════════════════════════════════
# Panel shape regressions
# ════════════════════════════════════════════════════════════════════


class TestPanelShapeRegression(unittest.TestCase):
    """Ensure CBC / BMP / Coags / Lactate still resolve correctly."""

    def test_cbc_resolves(self):
        labs = _make_labs_block({
            "White Blood Cell Count": {"last": 12.5, "first": 12.5, "n_values": 1},
            "Hemoglobin": {"last": 10.2, "first": 10.2, "n_values": 1},
        })
        panel = build_labs_panel_daily(labs)
        self.assertAlmostEqual(panel["cbc"]["WBC"]["value"], 12.5)
        self.assertAlmostEqual(panel["cbc"]["Hgb"]["value"], 10.2)

    def test_lactate_resolves(self):
        labs = _make_labs_block({
            "Lactate": {"last": 2.1, "first": 2.1, "n_values": 1}
        })
        panel = build_labs_panel_daily(labs)
        self.assertIsInstance(panel["lactate"], dict)
        self.assertAlmostEqual(panel["lactate"]["value"], 2.1)

    def test_full_panel_keys(self):
        panel = build_labs_panel_daily({})
        for key in ("cbc", "bmp", "coags", "lactate", "base_deficit"):
            self.assertIn(key, panel)


if __name__ == "__main__":
    unittest.main()
