#!/usr/bin/env python3
"""
Tests for PMH / Social / Allergies Extraction v1.

Covers:
  - PMH extraction from bullet-format sections (tabbed + sub-comments)
  - Allergy extraction: NKA detection, allergen+reaction pairs
  - Social history: smoking, alcohol, drug use, marital status
  - Deduplication (PMH by label, allergies by allergen)
  - Evidence traceability (raw_line_id on every entry)
  - Fail-closed: empty/missing data → DATA NOT AVAILABLE or empty lists
  - Contract shape: required output keys present
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.pmh_social_allergies_v1 import (
    extract_pmh_social_allergies,
    _extract_pmh_from_section,
    _extract_allergies_from_section,
    _extract_social_from_section,
    _normalize_pmh_label,
    _dedup_pmh,
    _dedup_allergies,
    _dedup_evidence,
    _scan_item,
    _DNA,
)


# ── Helper: build minimal days_data ────────────────────────────────

def _make_days_data(
    items_by_day: dict | None = None,
) -> dict:
    """Build a minimal patient_days_v1 structure."""
    days = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}
    return {
        "meta": {
            "patient_id": "Test_Patient",
        },
        "days": days,
    }


def _make_item(text: str, source_type: str = "TRAUMA_HP",
               item_id: str = "item_001", dt: str = "2025-01-15 08:00:00") -> dict:
    """Build a minimal timeline item."""
    return {
        "type": source_type,
        "id": item_id,
        "dt": dt,
        "payload": {"text": text},
    }


# ── Required output keys ───────────────────────────────────────────

REQUIRED_KEYS = {
    "pmh_items", "pmh_count", "allergies", "allergy_count",
    "allergy_status", "social_history", "source_rule_id",
    "evidence", "notes", "warnings",
}


# ── PMH extraction tests ──────────────────────────────────────────

class TestPMHExtraction:
    """PMH: bullet-based extraction from Past Medical History sections."""

    def test_basic_bullet_items(self):
        section = (
            "\nPast Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tHypertension\t3/16/2018\n"
            "•\tDiabetes mellitus\t\n"
        )
        items, evidence = _extract_pmh_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert len(items) == 2
        assert items[0]["label"] == "Hypertension"
        assert items[0]["date"] == "3/16/2018"
        assert items[1]["label"] == "Diabetes mellitus"
        assert all("raw_line_id" in it for it in items)
        assert len(evidence) == 2

    def test_sub_comment_capture(self):
        section = (
            "\nPast Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tOther chronic pain\t03/16/2018\n"
            " \trheumatoid arthritis\n"
            "•\tGERD\t\n"
        )
        items, _ = _extract_pmh_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert len(items) == 2
        assert items[0]["label"] == "Other chronic pain"
        assert items[0].get("sub_comment") == "rheumatoid arthritis"
        assert items[1]["label"] == "GERD"

    def test_no_bullet_no_capture(self):
        """Lines without bullets should NOT be captured (fail-closed)."""
        section = (
            "\nPast Medical History:\n"
            "Hypertension\n"
            "Diabetes\n"
        )
        items, _ = _extract_pmh_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert len(items) == 0

    def test_empty_section(self):
        items, evidence = _extract_pmh_from_section(
            "", "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert items == []
        assert evidence == []


# ── Allergy extraction tests ──────────────────────────────────────

class TestAllergyExtraction:
    """Allergy extraction from Allergies sections."""

    def test_nka_detection(self):
        section = "\nAllergies\nNo Known Allergies\n"
        items, evidence, status = _extract_allergies_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert status == "NKA"
        assert items == []
        assert len(evidence) == 1
        assert evidence[0]["role"] == "allergy_nka"
        assert "raw_line_id" in evidence[0]

    def test_nkda_detection(self):
        section = "\nAllergies\nNKDA\n"
        _, _, status = _extract_allergies_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert status == "NKA"

    def test_allergen_with_reaction(self):
        section = (
            "\nAllergies\nAllergies\n"
            "Allergen\tReactions\n"
            "•\tCiprofloxacin\t \n"
            " \t \tYEAST INFECTION\n"
            "•\tNsaids\t \n"
            " \t \tBLISTERS IN MOUTH\n"
        )
        items, evidence, status = _extract_allergies_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert status == "present"
        assert len(items) == 2
        assert items[0]["allergen"] == "Ciprofloxacin"
        assert items[0]["reaction"] == "YEAST INFECTION"
        assert items[1]["allergen"] == "Nsaids"
        assert items[1]["reaction"] == "BLISTERS IN MOUTH"
        assert all("raw_line_id" in it for it in items)
        assert len(evidence) == 2

    def test_allergen_no_reaction(self):
        section = (
            "\nAllergies\n"
            "Allergen\tReactions\n"
            "•\tPenicillin\t \n"
        )
        items, _, status = _extract_allergies_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert status == "present"
        assert len(items) == 1
        assert items[0]["allergen"] == "Penicillin"
        # reaction may or may not be present, just should not crash

    def test_empty_section(self):
        items, evidence, status = _extract_allergies_from_section(
            "", "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert items == []
        assert status is None


# ── Social history tests ──────────────────────────────────────────

class TestSocialExtraction:
    """Social history field extraction."""

    def test_basic_social_fields(self):
        section = (
            "\nSocial History\n"
            "Tobacco Use\n"
            "•\tSmoking status:\tNever\n"
            "•\tSmokeless tobacco:\tNever\n"
            "Vaping Use\n"
            "•\tVaping status:\tNever Used\n"
            "Substance and Sexual Activity\n"
            "•\tAlcohol use:\tNo\n"
            "•\tDrug use:\tNo\n"
        )
        social, evidence = _extract_social_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert social["smoking_status"] == "Never"
        assert social["smokeless_tobacco"] == "Never"
        assert social["vaping_status"] == "Never Used"
        assert social["alcohol_use"] == "No"
        assert social["drug_use"]["status"] == "No"
        assert len(evidence) >= 5

    def test_drug_use_with_types_and_comment(self):
        section = (
            "\n•\tDrug use:\tYes\n"
            " \t \tTypes:\tMarijuana\n"
            " \t \tComment: 5x monthly 06/2022\n"
        )
        social, evidence = _extract_social_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        drug = social["drug_use"]
        assert drug["status"] == "Yes"
        assert drug["types"] == "Marijuana"
        assert "5x monthly" in drug["comment"]

    def test_marital_status(self):
        section = (
            "\nSocioeconomic History\n"
            "•\tMarital status:\tMarried\n"
        )
        social, evidence = _extract_social_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert social["marital_status"] == "Married"
        assert any(e["role"] == "social_marital" for e in evidence)

    def test_empty_section(self):
        social, evidence = _extract_social_from_section(
            "", "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert social == {}
        assert evidence == []

    def test_first_seen_wins(self):
        """When a field appears twice, first value wins."""
        section = (
            "\n•\tSmoking status:\tNever\n"
            "•\tSmoking status:\tFormer\n"
        )
        social, _ = _extract_social_from_section(
            section, "TRAUMA_HP", "src1", "2025-01-15",
        )
        assert social["smoking_status"] == "Never"


# ── Deduplication tests ───────────────────────────────────────────

class TestDeduplication:
    """Deduplication helpers."""

    def test_dedup_pmh_by_label(self):
        items = [
            {"label": "Hypertension", "raw_line_id": "a"},
            {"label": "hypertension", "raw_line_id": "b"},
            {"label": "Diabetes", "raw_line_id": "c"},
        ]
        result = _dedup_pmh(items)
        labels = [it["label"] for it in result]
        assert len(result) == 2
        assert "Hypertension" in labels
        assert "Diabetes" in labels

    def test_dedup_pmh_strips_hcc(self):
        items = [
            {"label": "GERD (HCC)", "raw_line_id": "a"},
            {"label": "GERD", "raw_line_id": "b"},
        ]
        result = _dedup_pmh(items)
        assert len(result) == 1

    def test_dedup_allergies_by_name(self):
        items = [
            {"allergen": "Penicillin", "raw_line_id": "a"},
            {"allergen": "penicillin", "raw_line_id": "b"},
            {"allergen": "Sulfa", "raw_line_id": "c"},
        ]
        result = _dedup_allergies(items)
        assert len(result) == 2

    def test_dedup_evidence_by_raw_line_id(self):
        evidence = [
            {"raw_line_id": "abc123", "role": "pmh_item"},
            {"raw_line_id": "abc123", "role": "pmh_item"},
            {"raw_line_id": "def456", "role": "allergy"},
        ]
        result = _dedup_evidence(evidence)
        assert len(result) == 2

    def test_normalize_pmh_label(self):
        assert _normalize_pmh_label("Hypertension") == "hypertension"
        assert _normalize_pmh_label("GERD (HCC)") == "gerd"
        assert _normalize_pmh_label("Stroke 1/15/2020") == "stroke"
        assert _normalize_pmh_label("  DM,  ") == "dm"


# ── Full extractor (integration) ─────────────────────────────────

class TestFullExtraction:
    """Integration tests for extract_pmh_social_allergies."""

    def test_output_shape(self):
        """Output dict must contain all contract keys."""
        days_data = _make_days_data()
        result = extract_pmh_social_allergies({}, days_data)
        assert REQUIRED_KEYS.issubset(set(result.keys()))
        assert result["source_rule_id"] == "pmh_social_allergies_v1"

    def test_empty_days_data(self):
        """No days → fail-closed with defaults."""
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert result["pmh_count"] == 0
        assert result["allergy_count"] == 0
        assert result["allergy_status"] == _DNA
        assert result["social_history"] == {}
        assert result["pmh_items"] == []
        assert result["allergies"] == []

    def test_no_days_key(self):
        """Missing days key → fail-closed."""
        result = extract_pmh_social_allergies({}, {})
        assert result["pmh_count"] == 0

    def test_pmh_from_trauma_hp(self):
        """Extract PMH from TRAUMA_HP note."""
        text = (
            "HPI:\nFall from height\n"
            "PMH: PAST MEDICAL HISTORY\n\n"
            "Past Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tHypertension\t3/16/2018\n"
            "•\tDiabetes\t\n"
            "\n"
            "Allergies:\n\nAllergies\nNo Known Allergies\n"
            "\n"
            "Social Hx:\n\nSocial History\n"
            "Tobacco Use\n"
            "•\tSmoking status:\tNever\n"
            "Substance and Sexual Activity\n"
            "•\tAlcohol use:\tNo\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)],
        })
        result = extract_pmh_social_allergies({}, days_data)

        # PMH
        assert result["pmh_count"] == 2
        labels = [it["label"] for it in result["pmh_items"]]
        assert "Hypertension" in labels
        assert "Diabetes" in labels
        assert all("raw_line_id" in it for it in result["pmh_items"])

        # Allergies
        assert result["allergy_status"] == "NKA"
        assert result["allergy_count"] == 0

        # Social
        assert result["social_history"]["smoking_status"] == "Never"
        assert result["social_history"]["alcohol_use"] == "No"

        # Evidence
        assert len(result["evidence"]) >= 4
        assert all("raw_line_id" in e for e in result["evidence"])

    def test_allergies_present(self):
        """Detect real allergens with reactions."""
        text = (
            "Allergies:\n\nAllergies\nAllergies\n"
            "Allergen\tReactions\n"
            "•\tPenicillin\t \n"
            " \t \tRASH\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)],
        })
        result = extract_pmh_social_allergies({}, days_data)
        assert result["allergy_status"] == "present"
        assert result["allergy_count"] == 1
        assert result["allergies"][0]["allergen"] == "Penicillin"
        assert result["allergies"][0]["reaction"] == "RASH"

    def test_dedup_across_notes(self):
        """Same PMH across two TRAUMA_HP notes → deduplicated."""
        text1 = (
            "PMH: PAST MEDICAL HISTORY\n"
            "Past Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tHypertension\t\n"
        )
        text2 = (
            "PMH: PAST MEDICAL HISTORY\n"
            "Past Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tHypertension\t3/1/2020\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [
                _make_item(text1, item_id="item_001"),
                _make_item(text2, item_id="item_002"),
            ],
        })
        result = extract_pmh_social_allergies({}, days_data)
        assert result["pmh_count"] == 1

    def test_ignores_non_source_types(self):
        """Non-scanned source types should be skipped."""
        text = (
            "PMH: PAST MEDICAL HISTORY\n"
            "Past Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tHypertension\t\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text, source_type="LAB_RESULT")],
        })
        result = extract_pmh_social_allergies({}, days_data)
        assert result["pmh_count"] == 0

    def test_drug_use_rich(self):
        """Drug use with types and comment."""
        text = (
            "Social Hx:\n\nSocial History\n"
            "Substance and Sexual Activity\n"
            "•\tDrug use:\tYes\n"
            " \t \tTypes:\tMarijuana\n"
            " \t \tComment: 5x monthly 06/2022\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)],
        })
        result = extract_pmh_social_allergies({}, days_data)
        drug = result["social_history"]["drug_use"]
        assert drug["status"] == "Yes"
        assert drug["types"] == "Marijuana"
        assert "5x monthly" in drug["comment"]


# ── Contract compliance ───────────────────────────────────────────

class TestContractCompliance:
    """Validate output matches contract doc requirements."""

    def test_all_keys_present(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        for key in REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_source_rule_id_value(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert result["source_rule_id"] == "pmh_social_allergies_v1"

    def test_pmh_items_is_list(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert isinstance(result["pmh_items"], list)

    def test_allergies_is_list(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert isinstance(result["allergies"], list)

    def test_evidence_is_list(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert isinstance(result["evidence"], list)

    def test_social_history_is_dict(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert isinstance(result["social_history"], dict)

    def test_warnings_is_list(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert isinstance(result["warnings"], list)

    def test_notes_is_list(self):
        result = extract_pmh_social_allergies({}, {"days": {}})
        assert isinstance(result["notes"], list)
