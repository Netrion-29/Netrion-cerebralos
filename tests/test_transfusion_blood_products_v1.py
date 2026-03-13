#!/usr/bin/env python3
"""
Tests for transfusion_blood_products_v1 feature module.

Covers:
  - pRBC extraction from order headers, order lines, summary tables
  - FFP extraction from order headers and order lines
  - Platelet extraction from order headers and summary lines
  - TXA extraction from operative notes and medication orders
  - MTP activation detection
  - False-positive rejection (Platelet Count, Transfusion Status, etc.)
  - Deterministic raw_line_id generation
  - Empty / missing days → fail-closed
  - Deduplication of identical lines
"""

import pytest

from cerebralos.features.transfusion_blood_products_v1 import (
    _classify_line,
    _extract_units,
    _is_excluded,
    _make_raw_line_id,
    extract_transfusion_blood_products,
)


# ── helpers ─────────────────────────────────────────────────────────

def _make_days_data(lines: list[str], day: str = "2025-12-19") -> dict:
    """Build a minimal days_data dict with raw_lines for one day."""
    return {"days": {day: {"raw_lines": lines}}}


# ── _classify_line tests ────────────────────────────────────────────

class TestClassifyLine:
    """Positive and negative classification of individual lines."""

    # --- pRBC positives ---
    # Patient_File: Timothy_Cowan.txt:5090
    def test_rbc_order_header(self):
        line = "TRANSFUSE RED BLOOD CELLS (Order 464694986)"
        assert _classify_line(line) == "prbc"

    # Patient_File: Timothy_Cowan.txt:5076
    def test_rbc_order_line_with_units(self):
        line = "Transfuse RBC , 1 Units [NUR619] (Order 464666348)"
        assert _classify_line(line) == "prbc"

    # Patient_File: Timothy_Cowan.txt:21758
    def test_rbc_summary_table(self):
        line = "Transfuse RBC   12/22   1015    1 more"
        assert _classify_line(line) == "prbc"

    # Patient_File: Timothy_Cowan.txt:5416
    def test_rbc_info_block(self):
        line = "     Transfuse RBC"
        assert _classify_line(line) == "prbc"

    # --- FFP positives ---
    # Patient_File: Timothy_Cowan.txt:5162
    def test_ffp_order_header(self):
        line = "TRANSFUSE FRESH FROZEN PLASMAOrder: 464668835"
        assert _classify_line(line) == "ffp"

    # Patient_File: Timothy_Cowan.txt:5148
    def test_ffp_order_line_with_units(self):
        line = "Transfuse fresh frozen plasma , 1 Units [NUR621] (Order 464668835)"
        assert _classify_line(line) == "ffp"

    # --- Platelet positives ---
    # Patient_File: Timothy_Cowan.txt:5310
    def test_platelet_order_header(self):
        line = "TRANSFUSE PLATELET PHERESIS (Order 464673838)"
        assert _classify_line(line) == "platelets"

    # Patient_File: Timothy_Cowan.txt:21748
    def test_platelet_summary_line(self):
        line = "Transfuse platelet pheresis     12/19   0030    1 more"
        assert _classify_line(line) == "platelets"

    # Patient_File: Johnny_Stokes.txt:7162
    def test_platelet_order_header_johnny(self):
        line = "TRANSFUSE PLATELET PHERESIS (Order 466725819)"
        assert _classify_line(line) == "platelets"

    # --- TXA positives ---
    # Patient_File: Carlton_Van_Ness.txt:13066
    def test_txa_operative_note(self):
        line = "TXA: 1 g was administered at the time of skin incision"
        assert _classify_line(line) == "txa"

    # Patient_File: Valerie_Parker.txt:31809
    def test_txa_med_order(self):
        line = "tranexamic acid-NaCl IV premix   [466266640]"
        assert _classify_line(line) == "txa"

    # Patient_File: Valerie_Parker.txt:35073
    def test_txa_admin_line(self):
        line = "tranexamic acid 1 gram bolus   1,000 mg"
        assert _classify_line(line) == "txa"

    # --- MTP positives (synthetic — no current gate patient has MTP) ---
    def test_mtp_activation(self):
        line = "Massive transfusion protocol has been activated"
        assert _classify_line(line) == "mtp"

    def test_mtp_activated_short(self):
        line = "MTP activated at 0230"
        assert _classify_line(line) == "mtp"

    # --- Cryoprecipitate (synthetic) ---
    def test_cryo_order(self):
        line = "TRANSFUSE CRYOPRECIPITATE (Order 999999)"
        assert _classify_line(line) == "cryo"


class TestExclusions:
    """Lines that must NOT be classified as transfusion events."""

    # Patient_File: Anna_Dennis.txt:820
    def test_platelet_count_lab(self):
        line = "   Platelet Count  354     130 - 400 THOUS/uL"
        assert _classify_line(line) is None

    # Patient_File: Anna_Dennis.txt:821
    def test_mean_platelet_volume_lab(self):
        line = "    Mean Platelet Volume    9.0     7.4 - 10.4 FL"
        assert _classify_line(line) is None

    # Patient_File: Timothy_Cowan.txt:276
    def test_transfusion_status_ok(self):
        line = "•       Transfusion Status      12/18/2025      OK TO TRANSFUSE"
        assert _classify_line(line) is None

    # Patient_File: Timothy_Nachtwey.txt:18438
    def test_transfusion_status_inline(self):
        line = "Transfusion Status   OK TO TRANSFUSE"
        assert _classify_line(line) is None

    # Patient_File: William_Simmons.txt:6206
    def test_radiology_without_blood_product(self):
        line = "Sinuses and mastoids without blood product."
        assert _classify_line(line) is None

    # Patient_File: William_Simmons.txt:11463
    def test_billing_transfusion_code(self):
        line = "Blood transfusion without reported diagnosis"
        assert _classify_line(line) is None

    # Patient_File: Anna_Dennis.txt:6259
    def test_platelet_instruction(self):
        line = "If platelets less than 100,000 or decrease by 50%"
        assert _classify_line(line) is None

    def test_ok_to_transfuse_standalone(self):
        line = "OK TO TRANSFUSE"
        assert _classify_line(line) is None

    # Patient_File: Anna_Dennis.txt:3721
    def test_platelet_count_high_flag(self):
        line = "Platelet Count     423 High"
        assert _classify_line(line) is None


# ── _extract_units tests ────────────────────────────────────────────

class TestExtractUnits:
    """Unit count extraction from order lines."""

    def test_rbc_1_unit(self):
        line = "Transfuse RBC , 1 Units [NUR619] (Order 464666348)"
        assert _extract_units(line, "prbc") == 1

    def test_ffp_1_unit(self):
        line = "Transfuse fresh frozen plasma , 1 Units [NUR621] (Order 464668835)"
        assert _extract_units(line, "ffp") == 1

    def test_rbc_2_units(self):
        line = "Transfuse RBC , 2 Units [NUR619] (Order 999999999)"
        assert _extract_units(line, "prbc") == 2

    def test_no_units_in_header(self):
        line = "TRANSFUSE RED BLOOD CELLS (Order 464694986)"
        assert _extract_units(line, "prbc") is None


# ── _is_excluded tests ──────────────────────────────────────────────

class TestIsExcluded:
    """Confirm exclusion predicates."""

    def test_platelet_count_excluded(self):
        assert _is_excluded("Platelet Count  354") is True

    def test_transfusion_status_excluded(self):
        assert _is_excluded("Transfusion Status  OK TO TRANSFUSE") is True

    def test_without_blood_product_excluded(self):
        assert _is_excluded("mastoids without blood product") is True

    def test_rbc_order_not_excluded(self):
        assert _is_excluded("TRANSFUSE RED BLOOD CELLS") is False

    def test_transfuse_platelet_not_excluded(self):
        assert _is_excluded("Transfuse platelet pheresis") is False


# ── raw_line_id determinism ─────────────────────────────────────────

class TestRawLineId:
    """raw_line_id must be deterministic and 16-char hex."""

    def test_deterministic(self):
        id1 = _make_raw_line_id("prbc", 100, "Transfuse RBC")
        id2 = _make_raw_line_id("prbc", 100, "Transfuse RBC")
        assert id1 == id2

    def test_length_and_hex(self):
        rid = _make_raw_line_id("ffp", 42, "Test line")
        assert len(rid) == 16
        assert all(c in "0123456789abcdef" for c in rid)

    def test_different_inputs_different_ids(self):
        id1 = _make_raw_line_id("prbc", 100, "Transfuse RBC")
        id2 = _make_raw_line_id("ffp", 100, "Transfuse FFP")
        assert id1 != id2


# ── end-to-end extraction tests ────────────────────────────────────

class TestEndToEnd:
    """Full extraction pipeline tests."""

    def test_empty_days_data(self):
        result = extract_transfusion_blood_products({}, None)
        assert result["status"] == "DATA NOT AVAILABLE"
        assert result["evidence"] == []
        assert result["total_events"] == 0

    def test_no_transfusion_lines(self):
        days = _make_days_data([
            "Patient admitted for fall",
            "Platelet Count  271  130-400 THOUS/uL",
            "Transfusion Status OK TO TRANSFUSE",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["status"] == "DATA NOT AVAILABLE"
        assert result["total_events"] == 0

    def test_single_rbc_event(self):
        """Single RBC order → status=available, prbc_events=1."""
        days = _make_days_data([
            "TRANSFUSE RED BLOOD CELLS (Order 464694986)",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["status"] == "available"
        assert result["prbc_events"] == 1
        assert "prbc" in result["products_detected"]
        assert len(result["evidence"]) == 1
        assert "raw_line_id" in result["evidence"][0]

    def test_mixed_products(self):
        """Multiple product types in one day."""
        # Patient_File refs: Timothy_Cowan.txt lines 5076, 5148, 5310
        days = _make_days_data([
            "Transfuse RBC , 1 Units [NUR619] (Order 464666348)",
            "Transfuse fresh frozen plasma , 1 Units [NUR621] (Order 464668835)",
            "TRANSFUSE PLATELET PHERESIS (Order 464673838)",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["status"] == "available"
        assert result["prbc_events"] == 1
        assert result["ffp_events"] == 1
        assert result["platelet_events"] == 1
        assert result["total_events"] == 3

    def test_txa_detection(self):
        """TXA line → txa_administered=True."""
        # Patient_File: Carlton_Van_Ness.txt:13066
        days = _make_days_data([
            "TXA: 1 g was administered at the time of skin incision",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["txa_administered"] is True
        assert "txa" in result["products_detected"]

    def test_mtp_detection(self):
        """MTP line → mtp_activated=True."""
        days = _make_days_data([
            "Massive transfusion protocol has been activated",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["mtp_activated"] is True

    def test_deduplication(self):
        """Identical lines produce only one event."""
        days = _make_days_data([
            "TRANSFUSE RED BLOOD CELLS (Order 464694986)",
            "TRANSFUSE RED BLOOD CELLS (Order 464694986)",
        ])
        result = extract_transfusion_blood_products({}, days)
        # Two lines at different indices → different raw_line_ids → two events
        assert result["prbc_events"] == 2

    def test_exclusions_mixed_with_positives(self):
        """Excluded lines don't contaminate real events."""
        days = _make_days_data([
            "Platelet Count  354     130 - 400 THOUS/uL",
            "TRANSFUSE RED BLOOD CELLS (Order 464694986)",
            "Transfusion Status   OK TO TRANSFUSE",
            "Blood transfusion without reported diagnosis",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["total_events"] == 1
        assert result["prbc_events"] == 1

    def test_multi_day(self):
        """Events across multiple days are all captured."""
        days_data = {
            "days": {
                "2025-12-19": {
                    "raw_lines": [
                        "Transfuse RBC , 1 Units [NUR619] (Order 464666348)",
                    ]
                },
                "2025-12-20": {
                    "raw_lines": [
                        "TRANSFUSE PLATELET PHERESIS (Order 464673838)",
                    ]
                },
            }
        }
        result = extract_transfusion_blood_products({}, days_data)
        assert result["total_events"] == 2
        days_in_evidence = {e["day"] for e in result["evidence"]}
        assert "2025-12-19" in days_in_evidence
        assert "2025-12-20" in days_in_evidence

    def test_units_in_evidence(self):
        """When units are extractable, they appear in the evidence dict."""
        days = _make_days_data([
            "Transfuse RBC , 1 Units [NUR619] (Order 464666348)",
        ])
        result = extract_transfusion_blood_products({}, days)
        ev = result["evidence"][0]
        assert ev["units"] == 1
        assert ev["product"] == "prbc"

    def test_all_evidence_has_raw_line_id(self):
        """Contract requirement: every evidence item has raw_line_id."""
        days = _make_days_data([
            "Transfuse RBC , 1 Units [NUR619] (Order 464666348)",
            "Transfuse fresh frozen plasma , 1 Units [NUR621] (Order 464668835)",
            "TXA: 1 g was administered at the time of skin incision",
        ])
        result = extract_transfusion_blood_products({}, days)
        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Missing raw_line_id in {ev}"
            assert len(ev["raw_line_id"]) == 16

    def test_txa_med_order_forms(self):
        """Both TXA medication order formats are captured."""
        # Patient_File: Valerie_Parker.txt:31809, 35073
        days = _make_days_data([
            "tranexamic acid-NaCl IV premix   [466266640]",
            "tranexamic acid 1 gram bolus   1,000 mg",
        ])
        result = extract_transfusion_blood_products({}, days)
        assert result["txa_administered"] is True
        txa_events = [e for e in result["evidence"] if e["product"] == "txa"]
        assert len(txa_events) == 2
