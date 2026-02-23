#!/usr/bin/env python3
"""
Tests for ETOH + UDS Extraction with Timestamp Validation v1.

Covers:
  - ETOH extraction from structured lab series
  - ETOH extraction from raw text fallback
  - UDS extraction from structured lab series
  - UDS extraction from raw text fallback
  - Timestamp validation: VALID, MISSING_TS, OUT_OF_WINDOW
  - Fail-closed behavior when no data present
  - Evidence traceability (raw_line_id)
  - Mixed scenarios (ETOH present, UDS absent and vice versa)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.etoh_uds_v1 import (
    extract_etoh_uds,
    _validate_timestamp,
    _parse_etoh_value,
    _is_etoh_component,
    _is_uds_component,
    _canonical_uds_key,
    _empty_panel,
)


# ── Helper: build minimal days_data ─────────────────────────────────

def _make_days_data(
    items_by_day: dict | None = None,
    arrival_datetime: str | None = "2025-12-18 15:54:00",
    discharge_datetime: str | None = None,
) -> dict:
    """Build a minimal patient_days_v1 structure."""
    days = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}
    return {
        "meta": {
            "arrival_datetime": arrival_datetime,
            "discharge_datetime": discharge_datetime,
            "patient_id": "Test_Patient",
        },
        "days": days,
    }


def _make_pat_features(labs_by_day: dict | None = None) -> dict:
    """Build a minimal pat_features dict with labs.series."""
    days = {}
    if labs_by_day:
        for day_iso, labs in labs_by_day.items():
            days[day_iso] = {"labs": labs}
    return {"days": days}


# ── Tests: helper functions ─────────────────────────────────────────

class TestHelpers:
    def test_parse_etoh_value_numeric(self):
        val, raw = _parse_etoh_value("125")
        assert val == 125.0
        assert raw == "125"

    def test_parse_etoh_value_qualifier(self):
        val, raw = _parse_etoh_value("<10")
        assert val == 10.0
        assert raw == "<10"

    def test_parse_etoh_value_unparseable(self):
        val, raw = _parse_etoh_value("N/A")
        assert val is None
        assert raw == "N/A"

    def test_is_etoh_component(self):
        assert _is_etoh_component("Alcohol Serum") is True
        assert _is_etoh_component("ETOH Level") is True
        assert _is_etoh_component("Ethanol") is True
        assert _is_etoh_component("Glucose") is False
        assert _is_etoh_component("WBC") is False

    def test_is_uds_component(self):
        assert _is_uds_component("THC") is True
        assert _is_uds_component("Cocaine Metabolites Urine") is True
        assert _is_uds_component("Opiate Screen, Urine") is True
        assert _is_uds_component("Barbiturate Screen, Urine") is True
        assert _is_uds_component("Glucose") is False

    def test_canonical_uds_key(self):
        assert _canonical_uds_key("THC") == "thc"
        assert _canonical_uds_key("Cocaine Metabolites Urine") == "cocaine"
        assert _canonical_uds_key("Opiate Screen, Urine") == "opiates"
        assert _canonical_uds_key("Benzodiazepine Screen, Urine") == "benzodiazepines"
        assert _canonical_uds_key("Barbiturate Screen, Urine") == "barbiturates"
        assert _canonical_uds_key("Amphetamine/Methamph Screen, Urine") == "amphetamines"
        assert _canonical_uds_key("Phencyclidine Screen Urine") == "phencyclidine"
        assert _canonical_uds_key("Glucose") is None


# ── Tests: timestamp validation ─────────────────────────────────────

class TestTimestampValidation:
    def test_valid_timestamp(self):
        from datetime import datetime
        arrival = datetime(2025, 12, 18, 15, 54)
        status, warn = _validate_timestamp("2025-12-18T16:17:00", arrival, None)
        assert status == "VALID"
        assert warn is None

    def test_missing_timestamp(self):
        status, warn = _validate_timestamp(None, None, None)
        assert status == "MISSING_TS"
        assert warn is not None

    def test_unparseable_timestamp(self):
        from datetime import datetime
        arrival = datetime(2025, 12, 18, 15, 54)
        status, warn = _validate_timestamp("not-a-date", arrival, None)
        assert status == "MISSING_TS"
        assert "could not be parsed" in warn

    def test_before_arrival(self):
        from datetime import datetime
        arrival = datetime(2025, 12, 18, 15, 54)
        status, warn = _validate_timestamp("2025-12-17T10:00:00", arrival, None)
        assert status == "OUT_OF_WINDOW"
        assert "before arrival" in warn

    def test_after_discharge(self):
        from datetime import datetime
        arrival = datetime(2025, 12, 18, 15, 54)
        discharge = datetime(2025, 12, 25, 12, 0)
        status, warn = _validate_timestamp("2025-12-26T10:00:00", arrival, discharge)
        assert status == "OUT_OF_WINDOW"
        assert "after discharge" in warn

    def test_within_window(self):
        from datetime import datetime
        arrival = datetime(2025, 12, 18, 15, 54)
        discharge = datetime(2025, 12, 25, 12, 0)
        status, warn = _validate_timestamp("2025-12-20T08:00:00", arrival, discharge)
        assert status == "VALID"
        assert warn is None


# ── Tests: ETOH extraction from structured labs ─────────────────────

class TestEtohFromSeries:
    def test_etoh_found_in_series(self):
        pat_features = _make_pat_features({
            "2025-12-18": {
                "series": {
                    "Alcohol Serum": [{
                        "observed_dt": "2025-12-18T16:17:00",
                        "value_num": 10.0,
                        "value_raw": "<10",
                        "flags": [],
                        "source_line": 5,
                    }],
                },
                "daily": {},
            },
        })
        days_data = _make_days_data(
            arrival_datetime="2025-12-18 15:54:00",
        )

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] == 10.0
        assert result["etoh_value_raw"] == "<10"
        assert result["etoh_ts"] == "2025-12-18T16:17:00"
        assert result["etoh_ts_validation"] == "VALID"
        assert result["etoh_unit"] == "MG/DL"
        assert result["etoh_source_rule_id"] == "lab_series_alcohol_serum"
        assert result["etoh_raw_line_id"] is not None

    def test_etoh_not_found(self):
        pat_features = _make_pat_features({
            "2025-12-18": {
                "series": {"Glucose": []},
                "daily": {},
            },
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] is None
        assert result["etoh_ts"] is None
        assert result["etoh_ts_validation"] is None
        assert any("no ETOH" in n for n in result["notes"])

    def test_etoh_ts_out_of_window(self):
        pat_features = _make_pat_features({
            "2025-12-17": {
                "series": {
                    "Alcohol Serum": [{
                        "observed_dt": "2025-12-17T10:00:00",
                        "value_num": 50.0,
                        "value_raw": "50",
                        "flags": [],
                        "source_line": 1,
                    }],
                },
                "daily": {},
            },
        })
        days_data = _make_days_data(
            arrival_datetime="2025-12-18 15:54:00",
        )

        result = extract_etoh_uds(pat_features, days_data)

        # Value is still extracted but flagged
        assert result["etoh_value"] == 50.0
        assert result["etoh_ts_validation"] == "OUT_OF_WINDOW"
        assert any("etoh_ts" in w for w in result["warnings"])


# ── Tests: UDS extraction from structured labs ──────────────────────

class TestUdsFromSeries:
    def test_uds_panel_all_negative(self):
        series = {}
        for comp, key in [
            ("THC", "thc"),
            ("Cocaine Metabolites Urine", "cocaine"),
            ("Opiate Screen, Urine", "opiates"),
            ("Benzodiazepine Screen, Urine", "benzodiazepines"),
            ("Barbiturate Screen, Urine", "barbiturates"),
            ("Amphetamine/Methamph Screen, Urine", "amphetamines"),
            ("Phencyclidine Screen Urine", "phencyclidine"),
        ]:
            series[comp] = [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "NEGATIVE",
                "flags": [],
                "source_line": 10,
            }]

        pat_features = _make_pat_features({
            "2025-12-18": {"series": series, "daily": {}},
        })
        days_data = _make_days_data(arrival_datetime="2025-12-18 15:54:00")

        result = extract_etoh_uds(pat_features, days_data)

        assert result["uds_performed"] == "yes"
        assert result["uds_panel"] is not None
        for key in ("thc", "cocaine", "opiates", "benzodiazepines",
                     "barbiturates", "amphetamines", "phencyclidine"):
            assert result["uds_panel"][key] == "NEGATIVE"
        assert result["uds_ts_validation"] == "VALID"
        assert result["uds_raw_line_id"] is not None

    def test_uds_with_positive(self):
        series = {
            "THC": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "POSITIVE",
                "flags": [],
                "source_line": 10,
            }],
            "Cocaine Metabolites Urine": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "NEGATIVE",
                "flags": [],
                "source_line": 11,
            }],
        }
        pat_features = _make_pat_features({
            "2025-12-18": {"series": series, "daily": {}},
        })
        days_data = _make_days_data(arrival_datetime="2025-12-18 15:54:00")

        result = extract_etoh_uds(pat_features, days_data)

        assert result["uds_performed"] == "yes"
        assert result["uds_panel"]["thc"] == "POSITIVE"
        assert result["uds_panel"]["cocaine"] == "NEGATIVE"
        # Other analytes not found — should be None
        assert result["uds_panel"]["opiates"] is None

    def test_uds_not_found(self):
        pat_features = _make_pat_features({
            "2025-12-18": {"series": {"Glucose": []}, "daily": {}},
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        assert result["uds_performed"] == "DATA NOT AVAILABLE"
        assert result["uds_panel"] is None
        assert any("no UDS" in n for n in result["notes"])


# ── Tests: raw text fallback extraction ─────────────────────────────

class TestRawTextFallback:
    def test_etoh_from_raw_text(self):
        text = (
            "[LAB] 2025-12-18 16:17:00\n"
            "Labs:\n"
            "Component\tDate\tValue\tRef Range\tStatus\n"
            "\u2022\tAlcohol Serum\t12/18/2025\t<10\t<10 MG/DL\tFinal\n"
        )
        items = [{
            "type": "LAB",
            "dt": "2025-12-18T16:17:00",
            "payload": {"text": text},
        }]

        # Empty series so it falls through to raw text
        pat_features = _make_pat_features({
            "2025-12-18": {"series": {}, "daily": {}},
        })
        days_data = _make_days_data(
            items_by_day={"2025-12-18": items},
            arrival_datetime="2025-12-18 15:54:00",
        )

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] == 10.0
        assert result["etoh_source_rule_id"] == "raw_text_alcohol_serum"
        assert result["etoh_ts_validation"] == "VALID"
        assert result["etoh_raw_line_id"] is not None

    def test_uds_from_raw_text(self):
        text = (
            "DRUG SCREEN MEDICAL\n"
            "Collection Time: 12/18/25 4:30 PM\n"
            "THC              NEGATIVE\n"
            "Cocaine Metabolites Urine  NEGATIVE\n"
            "Opiate Screen, Urine       NEGATIVE\n"
            "Benzodiazepine Screen, Urine NEGATIVE\n"
            "Barbiturate Screen, Urine  NEGATIVE\n"
            "Amphetamine/Methamph Screen, Urine NEGATIVE\n"
            "Phencyclidine Screen Urine NEGATIVE\n"
        )
        items = [{
            "type": "ED_NOTE",
            "dt": "2025-12-18T16:30:00",
            "payload": {"text": text},
        }]

        pat_features = _make_pat_features({
            "2025-12-18": {"series": {}, "daily": {}},
        })
        days_data = _make_days_data(
            items_by_day={"2025-12-18": items},
            arrival_datetime="2025-12-18 15:54:00",
        )

        result = extract_etoh_uds(pat_features, days_data)

        assert result["uds_performed"] == "yes"
        assert result["uds_source_rule_id"] == "raw_text_drug_screen"
        assert result["uds_panel"]["thc"] == "NEGATIVE"
        assert result["uds_panel"]["cocaine"] == "NEGATIVE"
        assert result["uds_ts_validation"] == "VALID"
        assert result["uds_raw_line_id"] is not None

    def test_uds_from_raw_text_with_positive(self):
        text = (
            "DRUG SCREEN MEDICAL\n"
            "THC              POSITIVE\n"
            "Cocaine Metabolites Urine  NEGATIVE\n"
            "Opiate Screen, Urine       NEGATIVE\n"
            "Benzodiazepine Screen, Urine NEGATIVE\n"
            "Barbiturate Screen, Urine  NEGATIVE\n"
            "Amphetamine/Methamph Screen, Urine NEGATIVE\n"
            "Phencyclidine Screen Urine NEGATIVE\n"
        )
        items = [{
            "type": "LAB",
            "dt": "2025-12-18T16:30:00",
            "payload": {"text": text},
        }]

        pat_features = _make_pat_features({
            "2025-12-18": {"series": {}, "daily": {}},
        })
        days_data = _make_days_data(
            items_by_day={"2025-12-18": items},
            arrival_datetime="2025-12-18 15:54:00",
        )

        result = extract_etoh_uds(pat_features, days_data)

        assert result["uds_performed"] == "yes"
        assert result["uds_panel"]["thc"] == "POSITIVE"
        assert result["uds_panel"]["cocaine"] == "NEGATIVE"
        # Evidence snippet should mention positive
        ev = result["evidence"]
        uds_ev = [e for e in ev if "Drug Screen" in e.get("snippet", "")]
        assert len(uds_ev) == 1
        assert "thc" in uds_ev[0]["snippet"]


# ── Tests: fail-closed behavior ─────────────────────────────────────

class TestFailClosed:
    def test_empty_timeline(self):
        pat_features = _make_pat_features({})
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] is None
        assert result["etoh_ts"] is None
        assert result["etoh_ts_validation"] is None
        assert result["uds_performed"] == "DATA NOT AVAILABLE"
        assert result["uds_panel"] is None
        assert any("no ETOH" in n for n in result["notes"])
        assert any("no UDS" in n for n in result["notes"])

    def test_no_arrival_datetime(self):
        """When arrival_datetime is missing, timestamps can't be validated against it."""
        pat_features = _make_pat_features({
            "2025-12-18": {
                "series": {
                    "Alcohol Serum": [{
                        "observed_dt": "2025-12-18T16:17:00",
                        "value_num": 10.0,
                        "value_raw": "<10",
                        "flags": [],
                        "source_line": 5,
                    }],
                },
                "daily": {},
            },
        })
        days_data = _make_days_data(arrival_datetime=None)

        result = extract_etoh_uds(pat_features, days_data)

        # Should still extract the value, ts validated as VALID
        # (no bounds to violate)
        assert result["etoh_value"] == 10.0
        assert result["etoh_ts_validation"] == "VALID"


# ── Tests: evidence traceability ────────────────────────────────────

class TestEvidence:
    def test_etoh_evidence_has_raw_line_id(self):
        pat_features = _make_pat_features({
            "2025-12-18": {
                "series": {
                    "Alcohol Serum": [{
                        "observed_dt": "2025-12-18T16:17:00",
                        "value_num": 10.0,
                        "value_raw": "<10",
                        "flags": [],
                        "source_line": 5,
                    }],
                },
                "daily": {},
            },
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        # ETOH should have an evidence entry with raw_line_id
        etoh_ev = [e for e in result["evidence"]
                    if "Alcohol" in e.get("snippet", "")]
        assert len(etoh_ev) == 1
        assert etoh_ev[0]["raw_line_id"] is not None
        assert len(etoh_ev[0]["raw_line_id"]) > 0

    def test_all_evidence_has_required_fields(self):
        pat_features = _make_pat_features({
            "2025-12-18": {
                "series": {
                    "Alcohol Serum": [{
                        "observed_dt": "2025-12-18T16:17:00",
                        "value_num": 10.0,
                        "value_raw": "<10",
                        "flags": [],
                        "source_line": 5,
                    }],
                    "THC": [{
                        "observed_dt": "2025-12-18T16:17:00",
                        "value_num": None,
                        "value_raw": "NEGATIVE",
                        "flags": [],
                        "source_line": 10,
                    }],
                },
                "daily": {},
            },
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Missing raw_line_id in evidence: {ev}"
            assert "source" in ev, f"Missing source in evidence: {ev}"
            assert "ts" in ev, f"Missing ts in evidence: {ev}"
            assert "snippet" in ev, f"Missing snippet in evidence: {ev}"


# ── Tests: output schema contract ──────────────────────────────────

class TestOutputSchema:
    def test_all_required_keys_present(self):
        pat_features = _make_pat_features({})
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        required_keys = {
            "etoh_value", "etoh_value_raw", "etoh_ts",
            "etoh_ts_validation", "etoh_unit",
            "etoh_source_rule_id", "etoh_raw_line_id",
            "uds_performed", "uds_panel", "uds_ts",
            "uds_ts_validation", "uds_source_rule_id",
            "uds_raw_line_id",
            "evidence", "notes", "warnings",
        }
        assert set(result.keys()) == required_keys

    def test_uds_panel_keys_when_present(self):
        series = {
            "THC": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "NEGATIVE",
                "flags": [],
                "source_line": 10,
            }],
        }
        pat_features = _make_pat_features({
            "2025-12-18": {"series": series, "daily": {}},
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        panel = result["uds_panel"]
        assert panel is not None
        expected_analytes = {
            "thc", "cocaine", "opiates", "benzodiazepines",
            "barbiturates", "amphetamines", "phencyclidine",
        }
        assert set(panel.keys()) == expected_analytes


# ── Tests: mixed scenarios ──────────────────────────────────────────

class TestMixedScenarios:
    def test_etoh_present_uds_absent(self):
        pat_features = _make_pat_features({
            "2025-12-18": {
                "series": {
                    "Alcohol Serum": [{
                        "observed_dt": "2025-12-18T16:17:00",
                        "value_num": 10.0,
                        "value_raw": "<10",
                        "flags": [],
                        "source_line": 5,
                    }],
                },
                "daily": {},
            },
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] == 10.0
        assert result["uds_performed"] == "DATA NOT AVAILABLE"
        assert result["uds_panel"] is None

    def test_uds_present_etoh_absent(self):
        series = {
            "THC": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "NEGATIVE",
                "flags": [],
                "source_line": 10,
            }],
        }
        pat_features = _make_pat_features({
            "2025-12-18": {"series": series, "daily": {}},
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] is None
        assert result["uds_performed"] == "yes"
        assert result["uds_panel"]["thc"] == "NEGATIVE"

    def test_both_present(self):
        series = {
            "Alcohol Serum": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": 223.0,
                "value_raw": "223",
                "flags": [],
                "source_line": 5,
            }],
            "THC": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "POSITIVE",
                "flags": [],
                "source_line": 10,
            }],
            "Cocaine Metabolites Urine": [{
                "observed_dt": "2025-12-18T16:17:00",
                "value_num": None,
                "value_raw": "NEGATIVE",
                "flags": [],
                "source_line": 11,
            }],
        }
        pat_features = _make_pat_features({
            "2025-12-18": {"series": series, "daily": {}},
        })
        days_data = _make_days_data()

        result = extract_etoh_uds(pat_features, days_data)

        assert result["etoh_value"] == 223.0
        assert result["etoh_ts_validation"] == "VALID"
        assert result["uds_performed"] == "yes"
        assert result["uds_panel"]["thc"] == "POSITIVE"
        assert result["uds_panel"]["cocaine"] == "NEGATIVE"
        # Should have 2 evidence entries (one ETOH, one UDS)
        assert len(result["evidence"]) == 2
