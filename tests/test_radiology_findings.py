#!/usr/bin/env python3
"""
Tests for Radiology Findings Extraction v1.

Covers:
  - Pneumothorax: positive, negated, with subtype
  - Hemothorax: positive, negated, with qualifier
  - Rib fracture: positive, with count, with rib numbers, negated
  - Flail chest: positive, negated
  - Solid organ injury: liver/spleen/kidney, with grade, negated
  - Intracranial hemorrhage subtypes: EDH, SDH, SAH, ICH, IVH, negated
  - Pelvic fracture: positive, hip fracture alias, negated
  - Spinal fracture: positive, with level, negated
  - Chronic/stable exclusion
  - Fail-closed: no qualifying source → DNA
  - Fail-closed: source present but no findings → "no"
  - Evidence traceability (raw_line_id on every evidence entry)
  - IMPRESSION section preference over FINDINGS/full text
  - Multiple findings across multiple items (merge dedup)
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is on import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.radiology_findings_v1 import (
    _extract_findings_from_text,
    _is_negated,
    _is_chronic,
    _parse_rib_numbers,
    _parse_rib_laterality,
    _grade_to_string,
    extract_radiology_findings,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days_data(items_by_day):
    """Build a minimal days_data dict from {day_iso: [items]}."""
    days = {}
    for day_iso, items in items_by_day.items():
        days[day_iso] = {"items": items}
    return {"days": days, "meta": {}}


def _make_radiology_item(text, dt="2025-12-18T16:17:00", source_id="rad_0"):
    """Build a minimal RADIOLOGY timeline item."""
    return {
        "type": "RADIOLOGY",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _make_trauma_hp_item(text, dt="2025-12-18T16:00:00", source_id="hp_0"):
    """Build a minimal TRAUMA_HP timeline item."""
    return {
        "type": "TRAUMA_HP",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _make_ed_note_item(text, dt="2025-12-18T17:00:00", source_id="ed_0"):
    """Build a minimal ED_NOTE timeline item."""
    return {
        "type": "ED_NOTE",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _run_single_radiology(text):
    """Run extract_radiology_findings with a single RADIOLOGY item."""
    days_data = _make_days_data({"2025-12-18": [_make_radiology_item(text)]})
    return extract_radiology_findings({"days": {}}, days_data)


# ── Test: No qualifying source → DNA ───────────────────────────────

class TestFailClosed:
    def test_no_items(self):
        days_data = _make_days_data({})
        result = extract_radiology_findings({"days": {}}, days_data)
        assert result["findings_present"] == "DATA NOT AVAILABLE"
        assert result["findings_labels"] == []
        assert result["source_rule_id"] == "no_qualifying_source"

    def test_no_qualifying_type(self):
        days_data = _make_days_data({
            "2025-12-18": [{
                "type": "LAB",
                "dt": "2025-12-18T16:00:00",
                "source_id": "0",
                "payload": {"text": "pneumothorax noted"},
            }]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        assert result["findings_present"] == "DATA NOT AVAILABLE"

    def test_no_findings_matched(self):
        result = _run_single_radiology(
            "IMPRESSION: Normal chest radiograph. No acute findings."
        )
        assert result["findings_present"] == "no"
        assert result["findings_labels"] == []
        assert result["pneumothorax"] is None


# ── Test: Pneumothorax ──────────────────────────────────────────────

class TestPneumothorax:
    def test_positive_pneumothorax(self):
        result = _run_single_radiology(
            "FINDINGS: Small left-sided pneumothorax. "
            "IMPRESSION: Left pneumothorax."
        )
        assert result["findings_present"] == "yes"
        assert "pneumothorax" in result["findings_labels"]
        assert result["pneumothorax"]["present"] is True

    def test_negated_pneumothorax(self):
        result = _run_single_radiology(
            "IMPRESSION: No pneumothorax or pleural effusion."
        )
        assert result["findings_present"] == "no"
        assert result["pneumothorax"] is None

    def test_no_evidence_of_pneumothorax(self):
        result = _run_single_radiology(
            "IMPRESSION: No evidence of pneumothorax."
        )
        assert result["pneumothorax"] is None

    def test_without_pneumothorax(self):
        result = _run_single_radiology(
            "FINDINGS: No pleural effusion or pneumothorax. No suspicious nodules."
        )
        assert result["pneumothorax"] is None

    def test_pneumothorax_with_subtype(self):
        result = _run_single_radiology(
            "IMPRESSION: Tension pneumothorax on right."
        )
        assert result["pneumothorax"]["present"] is True
        assert result["pneumothorax"]["subtype"] == "tension"

    def test_pneumothorax_simple_subtype(self):
        result = _run_single_radiology(
            "IMPRESSION: Small simple pneumothorax."
        )
        assert result["pneumothorax"]["present"] is True
        # "small" is captured by PNEUMOTHORAX_TYPE pattern
        assert result["pneumothorax"]["subtype"] in ("small", "simple")


# ── Test: Hemothorax ────────────────────────────────────────────────

class TestHemothorax:
    def test_positive_hemothorax(self):
        result = _run_single_radiology(
            "IMPRESSION: Right-sided hemothorax."
        )
        assert "hemothorax" in result["findings_labels"]
        assert result["hemothorax"]["present"] is True

    def test_negated_hemothorax(self):
        result = _run_single_radiology(
            "IMPRESSION: No hemothorax."
        )
        assert result["hemothorax"] is None

    def test_hemothorax_with_qualifier(self):
        result = _run_single_radiology(
            "IMPRESSION: Massive hemothorax on the left."
        )
        assert result["hemothorax"]["qualifier"] == "massive"

    def test_hemopneumothorax(self):
        result = _run_single_radiology(
            "IMPRESSION: Left hemopneumothorax."
        )
        assert "hemothorax" in result["findings_labels"]
        assert "pneumothorax" in result["findings_labels"]


# ── Test: Rib Fracture ──────────────────────────────────────────────

class TestRibFracture:
    def test_positive_rib_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: Right-sided rib fractures."
        )
        assert "rib_fracture" in result["findings_labels"]
        assert result["rib_fracture"]["present"] is True

    def test_negated_rib_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: No rib fractures."
        )
        assert result["rib_fracture"] is None

    def test_rib_fracture_with_numbers(self):
        result = _run_single_radiology(
            "IMPRESSION: Right-sided rib fractures including the first, "
            "third, fourth, sixth, and seventh ribs."
        )
        assert result["rib_fracture"]["present"] is True
        assert result["rib_fracture"]["rib_numbers"] is not None
        nums = result["rib_fracture"]["rib_numbers"]
        assert "1" in nums
        assert "3" in nums
        assert "4" in nums

    def test_rib_fracture_range(self):
        result = _run_single_radiology(
            "IMPRESSION: Left rib fractures 4-7."
        )
        assert result["rib_fracture"]["present"] is True
        nums = result["rib_fracture"]["rib_numbers"]
        assert nums is not None
        assert "4" in nums
        assert "7" in nums
        assert result["rib_fracture"]["count"] == 4  # 4, 5, 6, 7

    def test_rib_fracture_alt_pattern(self):
        result = _run_single_radiology(
            "IMPRESSION: Right 1, 3, 4, 6, 7 rib fractures."
        )
        assert result["rib_fracture"]["present"] is True

    def test_chronic_rib_fracture_excluded(self):
        result = _run_single_radiology(
            "IMPRESSION: Chronic rib fracture on the left."
        )
        assert result["rib_fracture"] is None

    def test_acute_rib_fracture_not_chronic(self):
        result = _run_single_radiology(
            "IMPRESSION: Acute fracture of the posterior right ribs."
        )
        assert result["rib_fracture"]["present"] is True


# ── Test: Flail Chest ──────────────────────────────────────────────

class TestFlailChest:
    def test_positive_flail_chest(self):
        result = _run_single_radiology(
            "IMPRESSION: Flail chest on the left."
        )
        assert "flail_chest" in result["findings_labels"]
        assert result["flail_chest"]["present"] is True

    def test_negated_flail_chest(self):
        result = _run_single_radiology(
            "IMPRESSION: No flail chest."
        )
        assert result["flail_chest"] is None


# ── Test: Solid Organ Injuries ──────────────────────────────────────

class TestSolidOrganInjuries:
    def test_liver_laceration(self):
        result = _run_single_radiology(
            "IMPRESSION: Liver laceration."
        )
        assert "liver_injury" in result["findings_labels"]
        assert len(result["solid_organ_injuries"]) == 1
        assert result["solid_organ_injuries"][0]["organ"] == "liver"

    def test_splenic_laceration_with_grade(self):
        result = _run_single_radiology(
            "IMPRESSION: Grade III splenic laceration."
        )
        assert "spleen_injury" in result["findings_labels"]
        soi = result["solid_organ_injuries"]
        assert len(soi) == 1
        assert soi[0]["organ"] == "spleen"
        assert soi[0]["grade"] == "3"

    def test_kidney_injury(self):
        result = _run_single_radiology(
            "IMPRESSION: Right renal laceration."
        )
        assert "kidney_injury" in result["findings_labels"]

    def test_negated_liver(self):
        result = _run_single_radiology(
            "IMPRESSION: No liver laceration."
        )
        assert len(result["solid_organ_injuries"]) == 0

    def test_normal_organs(self):
        """Normal organ mentions should not match injury patterns."""
        result = _run_single_radiology(
            "FINDINGS: The liver, gallbladder, spleen, pancreas, and adrenal "
            "glands are normal. IMPRESSION: No acute findings."
        )
        assert len(result["solid_organ_injuries"]) == 0


# ── Test: Intracranial Hemorrhage ───────────────────────────────────

class TestIntracranialHemorrhage:
    def test_sdh(self):
        result = _run_single_radiology(
            "IMPRESSION: Acute subdural hemorrhage."
        )
        assert "sdh" in result["findings_labels"]
        assert len(result["intracranial_hemorrhage"]) == 1
        assert result["intracranial_hemorrhage"][0]["subtype"] == "sdh"

    def test_sah(self):
        result = _run_single_radiology(
            "IMPRESSION: Subarachnoid hemorrhage in the left sylvian fissure."
        )
        assert "sah" in result["findings_labels"]

    def test_edh(self):
        result = _run_single_radiology(
            "IMPRESSION: Right epidural hematoma."
        )
        assert "edh" in result["findings_labels"]

    def test_ivh(self):
        result = _run_single_radiology(
            "IMPRESSION: Intraventricular hemorrhage."
        )
        assert "ivh" in result["findings_labels"]

    def test_ich(self):
        result = _run_single_radiology(
            "IMPRESSION: Intracerebral hemorrhage in the right frontal lobe."
        )
        assert "ich" in result["findings_labels"]

    def test_negated_intracranial_hemorrhage(self):
        result = _run_single_radiology(
            "IMPRESSION: No acute intracranial hemorrhage."
        )
        assert len(result["intracranial_hemorrhage"]) == 0

    def test_no_evidence_of_hemorrhage(self):
        result = _run_single_radiology(
            "FINDINGS: No evidence of acute intracranial hemorrhage, mass "
            "effect or midline shift."
        )
        assert len(result["intracranial_hemorrhage"]) == 0

    def test_chronic_sdh_excluded(self):
        result = _run_single_radiology(
            "IMPRESSION: Chronic subdural hematoma."
        )
        assert len(result["intracranial_hemorrhage"]) == 0

    def test_abbreviation_sdh(self):
        result = _run_single_radiology(
            "IMPRESSION: Acute SDH over the right convexity."
        )
        assert "sdh" in result["findings_labels"]


# ── Test: Pelvic Fracture ──────────────────────────────────────────

class TestPelvicFracture:
    def test_pelvic_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: Left pelvic fracture."
        )
        assert "pelvic_fracture" in result["findings_labels"]
        assert result["pelvic_fracture"]["present"] is True

    def test_hip_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: Left hip fracture."
        )
        assert "pelvic_fracture" in result["findings_labels"]

    def test_negated_pelvic(self):
        result = _run_single_radiology(
            "IMPRESSION: No pelvic fracture."
        )
        assert result["pelvic_fracture"] is None

    def test_acetabular_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: Acetabular fracture on the left."
        )
        assert "pelvic_fracture" in result["findings_labels"]


# ── Test: Spinal Fracture ──────────────────────────────────────────

class TestSpinalFracture:
    def test_spinal_fracture_with_level(self):
        result = _run_single_radiology(
            "IMPRESSION: S4 vertebral body fracture."
        )
        assert "spinal_fracture" in result["findings_labels"]
        assert result["spinal_fracture"]["present"] is True
        assert result["spinal_fracture"]["level"] is not None
        assert "S4" in result["spinal_fracture"]["level"]

    def test_compression_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: L1 compression fracture."
        )
        assert result["spinal_fracture"]["present"] is True

    def test_negated_spinal_fracture(self):
        result = _run_single_radiology(
            "IMPRESSION: No acute thoracic or lumbar spine fracture."
        )
        assert result["spinal_fracture"] is None

    def test_chronic_compression_excluded(self):
        result = _run_single_radiology(
            "IMPRESSION: Stable chronic T5 and T6 compression fractures."
        )
        assert result["spinal_fracture"] is None


# ── Test: Evidence Traceability ─────────────────────────────────────

class TestEvidence:
    def test_raw_line_id_on_all_evidence(self):
        result = _run_single_radiology(
            "IMPRESSION: Right pneumothorax. Left hemothorax. "
            "Rib fractures 4-7. Liver laceration."
        )
        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Evidence missing raw_line_id: {ev}"
            assert len(ev["raw_line_id"]) == 16

    def test_evidence_has_source_and_ts(self):
        result = _run_single_radiology(
            "IMPRESSION: Left pneumothorax."
        )
        assert len(result["evidence"]) >= 1
        ev = result["evidence"][0]
        assert ev["source"] == "RADIOLOGY"
        assert ev["ts"] == "2025-12-18T16:17:00"
        assert ev["role"] == "finding"


# ── Test: Multiple Findings Merge ───────────────────────────────────

class TestMerge:
    def test_multiple_items_merge(self):
        """Findings from multiple RADIOLOGY items should merge."""
        days_data = _make_days_data({
            "2025-12-18": [
                _make_radiology_item(
                    "IMPRESSION: Right pneumothorax.",
                    source_id="rad_1",
                ),
                _make_radiology_item(
                    "IMPRESSION: S4 vertebral body fracture.",
                    source_id="rad_2",
                ),
            ]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        assert "pneumothorax" in result["findings_labels"]
        assert "spinal_fracture" in result["findings_labels"]

    def test_dedup_same_category(self):
        """Same category from multiple items should not duplicate."""
        days_data = _make_days_data({
            "2025-12-18": [
                _make_radiology_item(
                    "IMPRESSION: Left pneumothorax.",
                    source_id="rad_1",
                ),
                _make_radiology_item(
                    "IMPRESSION: Left pneumothorax.",
                    source_id="rad_2",
                ),
            ]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        assert result["findings_labels"].count("pneumothorax") == 1

    def test_multiple_organ_injuries_merge(self):
        days_data = _make_days_data({
            "2025-12-18": [
                _make_radiology_item(
                    "IMPRESSION: Liver laceration.",
                    source_id="rad_1",
                ),
                _make_radiology_item(
                    "IMPRESSION: Splenic laceration.",
                    source_id="rad_2",
                ),
            ]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        organs = [e["organ"] for e in result["solid_organ_injuries"]]
        assert "liver" in organs
        assert "spleen" in organs


# ── Test: IMPRESSION preference ─────────────────────────────────────

class TestSectionPreference:
    def test_impression_preferred(self):
        """IMPRESSION section is preferred over FINDINGS."""
        text = (
            "FINDINGS: Small right-sided pneumothorax seen. "
            "The liver appears normal. "
            "IMPRESSION: No acute findings."
        )
        result = _run_single_radiology(text)
        # IMPRESSION says no acute findings — so pneumothorax from FINDINGS
        # should still NOT be excluded since we fall back to FINDINGS when
        # IMPRESSION has no match
        # Actually: IMPRESSION is extracted first; "No acute findings" has
        # no specific finding mentions, so no positives from IMPRESSION.
        # Then we don't re-scan FINDINGS (impression takes precedence).
        assert result["findings_present"] == "no"


# ── Test: Real-world patterns ───────────────────────────────────────

class TestRealWorld:
    def test_timothy_cowan_rib_fractures(self):
        """Timothy Cowan has documented rib fractures 4-7."""
        text = (
            "IMPRESSION: 60 yo male s/p auger accident with "
            "- Left rib fractures 4-7"
        )
        # This is clinical note text, not a RADIOLOGY item;
        # use a TRAUMA_HP item
        days_data = _make_days_data({
            "2025-12-18": [_make_trauma_hp_item(text)]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        assert result["findings_present"] == "yes"
        assert "rib_fracture" in result["findings_labels"]
        nums = result["rib_fracture"]["rib_numbers"]
        assert nums is not None
        assert "4" in nums
        assert "7" in nums

    def test_barbara_burgdorf_rib_fractures_and_spinal(self):
        """Barbara Burgdorf has rib fractures + S4 vertebral body fracture."""
        text = (
            "IMPRESSION: 1. Right-sided rib fractures without significant "
            "displacement is including the first, third, fourth, sixth, "
            "and seventh ribs. "
            "2. Increased densities in lung bases bilaterally probable "
            "atelectasis. No pleural effusion or pneumothorax. "
            "3. Moderate size hiatal hernia."
        )
        result = _run_single_radiology(text)
        assert "rib_fracture" in result["findings_labels"]
        assert result["pneumothorax"] is None  # negated

        # Also test the spinal fracture from separate report
        text2 = (
            "IMPRESSION: 1. No fracture in the thoracic or lumbar spine. "
            "2. S4 vertebral body fracture "
            "3. Rib fractures described on chest CT"
        )
        result2 = _run_single_radiology(text2)
        assert "spinal_fracture" in result2["findings_labels"]
        assert result2["spinal_fracture"]["level"] is not None

    def test_no_acute_intracranial_process(self):
        """Timothy Cowan: 'No acute intracranial process' → no ICH."""
        result = _run_single_radiology(
            "IMPRESSION: No acute intracranial process."
        )
        assert len(result["intracranial_hemorrhage"]) == 0

    def test_william_simmons_hip_fracture(self):
        """William Simmons has left hip fracture."""
        text = (
            "CT imaging of pelvis shows left hip fracture. "
            "IMPRESSION: Left hip fracture."
        )
        days_data = _make_days_data({
            "2025-12-18": [_make_ed_note_item(text)]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        assert "pelvic_fracture" in result["findings_labels"]


# ── Test: Negation helper ───────────────────────────────────────────

class TestNegationHelper:
    def test_no_prefix(self):
        text = "No pneumothorax is seen."
        m = next(iter(
            __import__("re").finditer(r"\bpneumothorax\b", text, __import__("re").IGNORECASE)
        ))
        assert _is_negated(text, m.start(), m.end()) is True

    def test_positive_no_negation(self):
        text = "Large pneumothorax on the right."
        m = next(iter(
            __import__("re").finditer(r"\bpneumothorax\b", text, __import__("re").IGNORECASE)
        ))
        assert _is_negated(text, m.start(), m.end()) is False

    def test_without_negation(self):
        text = "without evidence of pneumothorax."
        m = next(iter(
            __import__("re").finditer(r"\bpneumothorax\b", text, __import__("re").IGNORECASE)
        ))
        assert _is_negated(text, m.start(), m.end()) is True


# ── Test: Chronic helper ────────────────────────────────────────────

class TestChronicHelper:
    def test_chronic_prefix(self):
        text = "Chronic subdural hematoma."
        m = next(iter(
            __import__("re").finditer(r"\bsubdural hematoma\b", text, __import__("re").IGNORECASE)
        ))
        assert _is_chronic(text, m.start(), m.end()) is True

    def test_stable_prefix(self):
        text = "Stable rib fracture."
        m = next(iter(
            __import__("re").finditer(r"\brib fracture\b", text, __import__("re").IGNORECASE)
        ))
        assert _is_chronic(text, m.start(), m.end()) is True

    def test_acute_not_chronic(self):
        text = "Acute rib fracture."
        m = next(iter(
            __import__("re").finditer(r"\brib fracture\b", text, __import__("re").IGNORECASE)
        ))
        assert _is_chronic(text, m.start(), m.end()) is False


# ── Test: Grade parsing ─────────────────────────────────────────────

class TestGradeParsing:
    def test_roman_numerals(self):
        assert _grade_to_string("III") == "3"
        assert _grade_to_string("IV") == "4"
        assert _grade_to_string("I") == "1"
        assert _grade_to_string("V") == "5"

    def test_arabic_numerals(self):
        assert _grade_to_string("1") == "1"
        assert _grade_to_string("3") == "3"
        assert _grade_to_string("5") == "5"

    def test_invalid_grade(self):
        assert _grade_to_string("VI") is None
        assert _grade_to_string("0") is None
        assert _grade_to_string("hello") is None


# ── Test: Rib number parsing ───────────────────────────────────────

class TestRibNumberParsing:
    def test_range(self):
        nums = _parse_rib_numbers("ribs 4-7")
        assert nums is not None
        assert "4" in nums and "5" in nums and "6" in nums and "7" in nums

    def test_comma_list(self):
        nums = _parse_rib_numbers("right 1, 3, 4, 6, 7 rib")
        assert nums is not None
        assert "1" in nums and "3" in nums

    def test_ordinal_words(self):
        nums = _parse_rib_numbers("first, third, fourth ribs")
        assert nums is not None
        assert "1" in nums and "3" in nums and "4" in nums

    def test_no_numbers(self):
        nums = _parse_rib_numbers("several rib fractures")
        assert nums is None

    # ── Ordinal-suffix range tests (v2) ────────────────────────
    def test_ordinal_suffix_range(self):
        """'5th-7th' should expand to 5, 6, 7."""
        nums = _parse_rib_numbers("right 5th-7th ribs")
        assert nums is not None
        assert nums == ["5", "6", "7"]

    def test_ordinal_suffix_range_ninth_tenth(self):
        """'9th-10th' should expand to 9, 10."""
        nums = _parse_rib_numbers("posterior right 9th-10th ribs")
        assert nums is not None
        assert "9" in nums and "10" in nums

    def test_partial_suffix_range(self):
        """'5-7th' (partial suffix) should expand to 5, 6, 7."""
        nums = _parse_rib_numbers("right 5-7th rib fxs")
        assert nums is not None
        assert nums == ["5", "6", "7"]

    def test_to_range_separator(self):
        """'5th to 7th' should expand to 5, 6, 7."""
        nums = _parse_rib_numbers("right 5th to 7th ribs")
        assert nums is not None
        assert nums == ["5", "6", "7"]

    def test_through_range_separator(self):
        """'5th through 7th' should expand to 5, 6, 7."""
        nums = _parse_rib_numbers("right 5th through 7th ribs")
        assert nums is not None
        assert nums == ["5", "6", "7"]

    def test_comma_separated_ordinal_ranges(self):
        """'5th-7th, 9th-10th' should expand to 5,6,7,9,10."""
        nums = _parse_rib_numbers("rib fractures, 5th-7th, 9th-10th")
        assert nums is not None
        assert nums == ["5", "6", "7", "9", "10"]

    def test_mixed_ordinal_word_and_numeric(self):
        """'ninth and 10th' should produce 9, 10."""
        nums = _parse_rib_numbers("posterior right ninth and 10th ribs")
        assert nums is not None
        assert "9" in nums and "10" in nums

    def test_ronald_bittner_impression(self):
        """Real-world IMPRESSION from Ronald Bittner:
        'right 5th-7th and ninth and 10th ribs' → 5,6,7,9,10"""
        text = "right 5th-7th and ninth and 10th ribs"
        nums = _parse_rib_numbers(text)
        assert nums is not None
        assert nums == ["5", "6", "7", "9", "10"]


# ── Test: Rib laterality parsing ───────────────────────────────────

class TestRibLateralityParsing:
    def test_right(self):
        assert _parse_rib_laterality("right 5th-7th ribs") == "right"

    def test_left(self):
        assert _parse_rib_laterality("left rib fractures 4-7") == "left"

    def test_bilateral(self):
        assert _parse_rib_laterality("bilateral rib fractures") == "bilateral"

    def test_no_laterality(self):
        assert _parse_rib_laterality("rib fractures 4-7") is None


# ── Test: Laterality in full pipeline ──────────────────────────────

class TestRibFractureLaterality:
    def test_laterality_in_output(self):
        result = _run_single_radiology(
            "IMPRESSION: Right-sided rib fractures."
        )
        assert result["rib_fracture"]["present"] is True
        assert result["rib_fracture"]["laterality"] == "right"

    def test_left_laterality(self):
        result = _run_single_radiology(
            "IMPRESSION: Left rib fractures 4-7."
        )
        assert result["rib_fracture"]["laterality"] == "left"


# ── Test: Solid organ grade-after-injury patterns ──────────────────

class TestSolidOrganGradePatterns:
    def test_grade_before_organ(self):
        result = _run_single_radiology(
            "IMPRESSION: Grade III splenic laceration."
        )
        assert result["solid_organ_injuries"][0]["grade"] == "3"

    def test_grade_after_injury(self):
        result = _run_single_radiology(
            "IMPRESSION: Splenic laceration, grade 3."
        )
        assert "spleen_injury" in result["findings_labels"]
        assert result["solid_organ_injuries"][0]["grade"] == "3"

    def test_aast_grade(self):
        result = _run_single_radiology(
            "IMPRESSION: Liver laceration, AAST grade II."
        )
        assert "liver_injury" in result["findings_labels"]
        assert result["solid_organ_injuries"][0]["grade"] == "2"

    def test_grade_before_injury_arabic(self):
        result = _run_single_radiology(
            "IMPRESSION: Grade 4 liver laceration."
        )
        assert result["solid_organ_injuries"][0]["grade"] == "4"


# ── Test: Ronald Bittner real-world (v2) ───────────────────────────

class TestRonaldBittner:
    def test_impression_ordinal_ranges(self):
        """Ronald Bittner IMPRESSION: 'Acute, minimally displaced fractures
        in the right 5th-7th and ninth and 10th ribs.'"""
        text = (
            "IMPRESSION: 1. Diffuse idiopathic skeletal hyperostosis with "
            "extension distraction fracture through the T8 vertebral body, "
            "possible mechanical instability. "
            "2. Acute, minimally displaced fractures in the right 5th-7th "
            "and ninth and 10th ribs."
        )
        result = _run_single_radiology(text)
        assert result["findings_present"] == "yes"
        assert "rib_fracture" in result["findings_labels"]
        assert "spinal_fracture" in result["findings_labels"]
        rf = result["rib_fracture"]
        assert rf["present"] is True
        nums = rf["rib_numbers"]
        assert nums is not None
        assert nums == ["5", "6", "7", "9", "10"]
        assert rf["count"] == 5
        assert rf["laterality"] == "right"

    def test_findings_section_ribs(self):
        """Ronald Bittner FINDINGS with ordinal-suffix ranges."""
        text = (
            "FINDINGS: CHEST: Bones: There are acute, minimally displaced "
            "fractures in the right 5th-7th ribs. There are also acute, "
            "minimally displaced fractures in the posterior right ninth and "
            "10th ribs."
        )
        result = _run_single_radiology(text)
        assert "rib_fracture" in result["findings_labels"]
        rf = result["rib_fracture"]
        nums = rf["rib_numbers"]
        assert nums is not None
        # Should get at least 5,6,7 from the first mention
        assert "5" in nums and "6" in nums and "7" in nums

    def test_summary_line_comma_ranges(self):
        """'Right sided rib fractures, 5th-7th, 9th-10th'"""
        text = "Right sided rib fractures, 5th-7th, 9th-10th"
        days_data = _make_days_data({
            "2025-12-18": [_make_trauma_hp_item(text)]
        })
        result = extract_radiology_findings({"days": {}}, days_data)
        assert result["findings_present"] == "yes"
        rf = result["rib_fracture"]
        assert rf is not None
        nums = rf["rib_numbers"]
        assert nums is not None
        assert nums == ["5", "6", "7", "9", "10"]
        assert rf["count"] == 5
        assert rf["laterality"] == "right"
