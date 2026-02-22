#!/usr/bin/env python3
"""
Tests for INR Normalization v1 — Tier 1 Metric #4.

Covers:
  - INR value range validation (0.5–20.0)
  - PT seconds rejection (not treated as INR)
  - Component name classification
  - Empty series handling
  - Deduplication of INR entries
  - Parse warnings for rejected values
  - Daily fallback timestamp granularity
  - <> qualifier stripping
"""

import pytest

from cerebralos.features.inr_normalization_v1 import (
    _classify_coag_value,
    _is_inr_component,
    _is_pt_component,
    extract_inr_normalization,
)


# ── Component classification tests ─────────────────────────────────

class TestComponentClassification:
    def test_inr_component(self):
        assert _is_inr_component("INR") is True

    def test_inr_case_insensitive(self):
        assert _is_inr_component("inr") is True
        assert _is_inr_component("Inr") is True

    def test_protime_is_pt(self):
        assert _is_pt_component("PROTIME") is True

    def test_pt_is_pt(self):
        assert _is_pt_component("PT") is True

    def test_pro_time_is_pt(self):
        assert _is_pt_component("Pro Time") is True

    def test_inr_not_pt(self):
        assert _is_pt_component("INR") is False

    def test_pt_not_inr(self):
        assert _is_inr_component("PROTIME") is False
        assert _is_inr_component("PT") is False

    def test_random_not_inr(self):
        assert _is_inr_component("Hemoglobin") is False

    def test_random_not_pt(self):
        assert _is_pt_component("WBC") is False


# ── _classify_coag_value tests ─────────────────────────────────────

class TestClassifyCoagValue:
    def test_inr_normal_value(self):
        cls, warn = _classify_coag_value("INR", 1.2)
        assert cls == "inr"
        assert warn is None

    def test_inr_high_therapeutic(self):
        cls, warn = _classify_coag_value("INR", 3.5)
        assert cls == "inr"
        assert warn is None

    def test_inr_at_minimum(self):
        cls, warn = _classify_coag_value("INR", 0.5)
        assert cls == "inr"
        assert warn is None

    def test_inr_at_maximum(self):
        cls, warn = _classify_coag_value("INR", 20.0)
        assert cls == "inr"
        assert warn is None

    def test_inr_below_minimum_rejected(self):
        cls, warn = _classify_coag_value("INR", 0.3)
        assert cls is None
        assert warn is not None
        assert "below min" in warn

    def test_inr_above_maximum_rejected(self):
        cls, warn = _classify_coag_value("INR", 25.0)
        assert cls is None
        assert warn is not None
        assert "exceeds max" in warn

    def test_pt_seconds_classified_correctly(self):
        cls, warn = _classify_coag_value("PROTIME", 11.7)
        assert cls == "pt_seconds"
        assert warn is None

    def test_pt_not_misidentified_as_inr(self):
        """PT seconds (typically 10-15) must NOT be treated as INR."""
        cls, _ = _classify_coag_value("PROTIME", 12.0)
        assert cls == "pt_seconds"
        cls, _ = _classify_coag_value("PT", 11.5)
        assert cls == "pt_seconds"

    def test_null_value_rejected(self):
        cls, warn = _classify_coag_value("INR", None)
        assert cls is None
        assert "null" in warn


# ── extract_inr_normalization integration tests ───────────────────

class TestExtractINRNormalization:
    def _make_features(self, inr_entries, pt_entries=None, day_iso="2025-12-18"):
        """Build a minimal pat_features dict with INR and optionally PT."""
        series = {}
        if inr_entries:
            series["INR"] = [
                {
                    "observed_dt": e.get("dt", f"{day_iso}T10:00:00"),
                    "value_num": e["value"],
                    "value_raw": str(e["value"]),
                    "source_line": e.get("source_line"),
                    "flags": [],
                }
                for e in inr_entries
            ]
        if pt_entries:
            series["PROTIME"] = [
                {
                    "observed_dt": e.get("dt", f"{day_iso}T10:00:00"),
                    "value_num": e["value"],
                    "value_raw": str(e["value"]),
                    "source_line": e.get("source_line"),
                    "flags": [],
                }
                for e in pt_entries
            ]
        return {
            "days": {
                day_iso: {
                    "labs": {
                        "series": series,
                        "daily": {},
                    },
                },
            },
        }

    def test_no_inr_values(self):
        pat = {"days": {"2025-12-18": {"labs": {"series": {}, "daily": {}}}}}
        result = extract_inr_normalization(pat)
        assert result["initial_inr_value"] is None
        assert result["inr_count"] == 0
        assert any("DATA NOT AVAILABLE" in n for n in result["notes"])

    def test_single_inr(self):
        pat = self._make_features([{"value": 1.2}])
        result = extract_inr_normalization(pat)
        assert result["initial_inr_value"] == 1.2
        assert result["inr_count"] == 1
        assert result["initial_inr_source_lab"] == "INR"
        assert len(result["inr_series"]) == 1
        assert result["inr_series"][0]["raw_line_id"] is not None

    def test_multiple_inr_values(self):
        pat = self._make_features([
            {"value": 1.1, "dt": "2025-12-18T06:00:00"},
            {"value": 1.0, "dt": "2025-12-18T14:00:00"},
        ])
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 2
        assert result["initial_inr_value"] == 1.1  # first by timestamp

    def test_pt_seconds_not_included(self):
        """PT values must not appear in INR series."""
        pat = self._make_features(
            inr_entries=[{"value": 1.0}],
            pt_entries=[{"value": 11.7}],
        )
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 1
        # Only INR, not PROTIME
        for e in result["inr_series"]:
            assert e["source_lab"] == "INR"

    def test_out_of_range_inr_rejected(self):
        """INR values outside 0.5–20.0 should be rejected."""
        pat = self._make_features([{"value": 0.3}])
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 0
        assert any("below min" in w for w in result["parse_warnings"])

    def test_extreme_high_inr_rejected(self):
        pat = self._make_features([{"value": 25.0}])
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 0
        assert any("exceeds max" in w for w in result["parse_warnings"])

    def test_inr_value_rounding(self):
        """Values are rounded to 2 decimal places."""
        pat = self._make_features([{"value": 1.234567}])
        result = extract_inr_normalization(pat)
        assert result["initial_inr_value"] == 1.23

    def test_multi_day_inr(self):
        """INR values across multiple days."""
        pat = {
            "days": {
                "2025-12-18": {
                    "labs": {
                        "series": {
                            "INR": [
                                {
                                    "observed_dt": "2025-12-18T10:00:00",
                                    "value_num": 1.1,
                                    "value_raw": "1.1",
                                    "source_line": None,
                                    "flags": [],
                                },
                            ],
                        },
                        "daily": {},
                    },
                },
                "2025-12-19": {
                    "labs": {
                        "series": {
                            "INR": [
                                {
                                    "observed_dt": "2025-12-19T08:00:00",
                                    "value_num": 1.4,
                                    "value_raw": "1.4",
                                    "source_line": None,
                                    "flags": [],
                                },
                            ],
                        },
                        "daily": {},
                    },
                },
            },
        }
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 2
        assert result["initial_inr_value"] == 1.1
        assert result["inr_series"][-1]["inr_value"] == 1.4

    def test_empty_days(self):
        pat = {"days": {}}
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 0

    def test_daily_fallback(self):
        """If only daily data exists (no series), should still pick up INR."""
        pat = {
            "days": {
                "2025-12-18": {
                    "labs": {
                        "series": {},
                        "daily": {
                            "INR": {
                                "last": 1.4,
                                "first": 1.4,
                            },
                        },
                    },
                },
            },
        }
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 1
        assert result["initial_inr_value"] == 1.4

    def test_daily_fallback_ts_is_day_level(self):
        """Daily fallback must NOT invent sub-day timestamps."""
        pat = {
            "days": {
                "2025-12-18": {
                    "labs": {
                        "series": {},
                        "daily": {
                            "INR": {
                                "last": 1.2,
                                "first": 1.2,
                            },
                        },
                    },
                },
            },
        }
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 1
        entry = result["inr_series"][0]
        # ts must be date-only, no T00:00:00 appended
        assert entry["ts"] == "2025-12-18"
        assert "T" not in entry["ts"]
        assert entry["ts_granularity"] == "day"

    def test_series_entry_has_datetime_granularity(self):
        """Series-sourced entries must have ts_granularity='datetime'."""
        pat = self._make_features([{"value": 1.0}])
        result = extract_inr_normalization(pat)
        assert result["inr_series"][0]["ts_granularity"] == "datetime"

    def test_qualifier_lt_stripped(self):
        """'<' qualifier should be stripped from value_raw."""
        pat = {
            "days": {
                "2025-12-18": {
                    "labs": {
                        "series": {
                            "INR": [
                                {
                                    "observed_dt": "2025-12-18T10:00:00",
                                    "value_num": None,
                                    "value_raw": "<0.8",
                                    "source_line": None,
                                    "flags": [],
                                },
                            ],
                        },
                        "daily": {},
                    },
                },
            },
        }
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 1
        assert result["initial_inr_value"] == 0.8

    def test_qualifier_gt_stripped(self):
        """'>' qualifier should be stripped from value_raw."""
        pat = {
            "days": {
                "2025-12-18": {
                    "labs": {
                        "series": {
                            "INR": [
                                {
                                    "observed_dt": "2025-12-18T10:00:00",
                                    "value_num": None,
                                    "value_raw": ">10.0",
                                    "source_line": None,
                                    "flags": [],
                                },
                            ],
                        },
                        "daily": {},
                    },
                },
            },
        }
        result = extract_inr_normalization(pat)
        assert result["inr_count"] == 1
        assert result["initial_inr_value"] == 10.0
