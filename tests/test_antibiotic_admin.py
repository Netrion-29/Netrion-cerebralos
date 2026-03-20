#!/usr/bin/env python3
"""
Tests for Antibiotic Administration Extraction v1.

Covers:
  - Agent matching (cephalosporins, glycopeptides, beta-lactam combos, etc.)
  - Epic mixed-case drug names (ceFAZolin, cefTRIAXone, ceFEPIme)
  - Brand-name recognition (Ancef, Rocephin, Zosyn, Unasyn, etc.)
  - Allergy section exclusion (drug + reaction tab-separated lines)
  - Outpatient / home medication section exclusion
  - Discharge instruction section exclusion
  - Administration confirmation (Given signal)
  - Discontinuation detection ([DISCONTINUED], completed course, can stop)
  - Negative MAR status (Not Given, Patient Refused, Held)
  - Dose / route / frequency extraction
  - Negative control (no antibiotic agents)
  - Evidence traceability (raw_line_id on every evidence item)
  - Deduplication across repeated timeline items
  - False-positive defense (allergy-only patients, generic "antibiotics" text)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.antibiotic_admin_v1 import (
    extract_antibiotic_admin,
    _match_agent,
    _has_admin_signal,
    _has_discontinue_signal,
    _has_negative_status,
    _is_allergy_section,
    _is_allergy_line,
    _is_outpatient_section,
    _is_discharge_instruction_section,
    _extract_dose_info,
    _normalize_route,
    _normalize_frequency,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days_data(
    items_by_day: dict | None = None,
    arrival_datetime: str | None = "2025-01-15T14:30:00",
) -> dict:
    """Build a minimal patient_days_v1 structure."""
    days = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}
    return {
        "meta": {
            "arrival_datetime": arrival_datetime,
            "patient_id": "Test_Patient",
        },
        "days": days,
    }


def _make_item(text: str, item_type: str = "MEDICATION_ADMIN",
               item_id: str = "item_001",
               dt: str = "2025-01-15T14:30:00") -> dict:
    """Build a minimal timeline item."""
    return {
        "type": item_type,
        "id": item_id,
        "dt": dt,
        "payload": {"text": text},
    }


def _pat_features() -> dict:
    return {"days": {}}


# ═══════════════════════════════════════════════════════════════════
# Unit tests: agent matching
# ═══════════════════════════════════════════════════════════════════

class TestAgentMatching:
    # ── Cephalosporins ──
    def test_cefazolin_lowercase(self):
        assert _match_agent("cefazolin 2 g IV") == "cefazolin"

    def test_cefazolin_epic_mixed(self):
        assert _match_agent("ceFAZolin 2 g in sodium chloride 0.9% 50mL IVPB") == "cefazolin"

    def test_ancef(self):
        assert _match_agent("Ancef administered") == "cefazolin"

    def test_ceftriaxone_lowercase(self):
        assert _match_agent("ceftriaxone 1 g IV") == "ceftriaxone"

    def test_ceftriaxone_epic_mixed(self):
        assert _match_agent("cefTRIAXone (ROCEPHIN) IV") == "ceftriaxone"

    def test_rocephin(self):
        assert _match_agent("ABX - Rocephin.") == "ceftriaxone"

    def test_cefepime_epic_mixed(self):
        assert _match_agent("ceFEPIme 2 g NS 100mL Mini-Bag (MAXIPIME) IVPB") == "cefepime"

    def test_maxipime(self):
        assert _match_agent("Maxipime 2g Q8H") == "cefepime"

    def test_ceftazidime(self):
        assert _match_agent("ceftazidime 2 g IV Q8H") == "ceftazidime"

    # ── Glycopeptides ──
    def test_vancomycin(self):
        assert _match_agent("vancomycin 1750 mg IV") == "vancomycin"

    def test_vancocin(self):
        assert _match_agent("vancocin trough level") == "vancomycin"

    # ── Beta-lactam combos ──
    def test_pip_tazo(self):
        assert _match_agent("piperacillin-tazobactam 3.375 g IV") == "piperacillin-tazobactam"

    def test_zosyn(self):
        assert _match_agent("Zosyn 2.25 g IV Q6H") == "piperacillin-tazobactam"

    def test_ampicillin_sulbactam(self):
        assert _match_agent("ampicillin-sulbactam 3 g IV") == "ampicillin-sulbactam"

    def test_unasyn(self):
        assert _match_agent("Start Unasyn for aspiration pneumonia") == "ampicillin-sulbactam"

    # ── Carbapenems ──
    def test_meropenem(self):
        assert _match_agent("meropenem 1 g IV Q8H") == "meropenem"

    # ── Nitroimidazoles ──
    def test_metronidazole(self):
        assert _match_agent("metronidazole 500 mg IV") == "metronidazole"

    def test_flagyl(self):
        assert _match_agent("Flagyl 500 mg PO TID") == "metronidazole"

    # ── Fluoroquinolones ──
    def test_levofloxacin(self):
        assert _match_agent("levofloxacin 750 mg PO daily") == "levofloxacin"

    def test_ciprofloxacin(self):
        assert _match_agent("ciprofloxacin 500 mg PO BID") == "ciprofloxacin"

    # ── Others ──
    def test_clindamycin(self):
        assert _match_agent("clindamycin 600 mg IV Q8H") == "clindamycin"

    def test_gentamicin(self):
        assert _match_agent("gentamicin 80 mg IV") == "gentamicin"

    def test_azithromycin(self):
        assert _match_agent("azithromycin 500 mg IV") == "azithromycin"

    def test_zpack(self):
        assert _match_agent("Z-pack prescribed") == "azithromycin"

    def test_doxycycline(self):
        assert _match_agent("doxycycline 100 mg PO BID") == "doxycycline"

    def test_linezolid(self):
        assert _match_agent("linezolid 600 mg IV BID") == "linezolid"

    def test_ampicillin_standalone(self):
        """Standalone ampicillin must NOT match ampicillin-sulbactam."""
        assert _match_agent("ampicillin 2 g IV Q4H") == "ampicillin"

    def test_nafcillin(self):
        assert _match_agent("nafcillin 2 g IV Q4H") == "nafcillin"

    # ── Negative ──
    def test_no_match_acetaminophen(self):
        assert _match_agent("acetaminophen 650 mg PO") is None

    def test_no_match_generic_antibiotic(self):
        """'antibiotic' or 'abx' alone must NOT match any specific agent."""
        assert _match_agent("antibiotic therapy") is None

    def test_no_match_abx_alone(self):
        assert _match_agent("ABX - none") is None

    def test_no_match_empty(self):
        assert _match_agent("") is None

    def test_no_match_heparin(self):
        """Heparin is not an antibiotic."""
        assert _match_agent("heparin 5000 units subQ") is None


# ═══════════════════════════════════════════════════════════════════
# Unit tests: admin signals
# ═══════════════════════════════════════════════════════════════════

class TestAdminSignals:
    def test_given(self):
        assert _has_admin_signal("Given 01/15/2025 0814")

    def test_administered(self):
        assert _has_admin_signal("cefazolin administered at 0800")

    def test_medication_administration(self):
        assert _has_admin_signal("Medication Administration")

    def test_dose_given(self):
        assert _has_admin_signal("dose given at bedside")

    def test_last_dose(self):
        assert _has_admin_signal("last dose 01/14/2025")

    def test_no_signal(self):
        assert not _has_admin_signal("ordered cefazolin 2 g")


# ═══════════════════════════════════════════════════════════════════
# Unit tests: discontinuation signals
# ═══════════════════════════════════════════════════════════════════

class TestDiscontinueSignals:
    def test_discontinued(self):
        assert _has_discontinue_signal("vancomycin DISCONTINUED")

    def test_completed_course(self):
        assert _has_discontinue_signal("completed course of cefazolin")

    def test_bracket_discontinued(self):
        assert _has_discontinue_signal("[DISCONTINUED] vancomycin 1750 mg IV")

    def test_bracket_completed(self):
        assert _has_discontinue_signal("[COMPLETED] cefazolin 2 g IV")

    def test_can_stop(self):
        assert _has_discontinue_signal("MRSA screen negative, can stop vancomycin")

    def test_abx_completed(self):
        assert _has_discontinue_signal("abx completed per ID")

    def test_no_discontinue(self):
        assert not _has_discontinue_signal("continue cefazolin 2 g IV Q8H")


# ═══════════════════════════════════════════════════════════════════
# Unit tests: negative MAR status
# ═══════════════════════════════════════════════════════════════════

class TestNegativeStatus:
    def test_not_given(self):
        assert _has_negative_status("Not Given")

    def test_patient_refused(self):
        assert _has_negative_status("Patient Refused - cefazolin")

    def test_held(self):
        assert _has_negative_status("Held")

    def test_no_negative(self):
        assert not _has_negative_status("Given 01/15/2025 0814")


# ═══════════════════════════════════════════════════════════════════
# Unit tests: allergy section detection
# ═══════════════════════════════════════════════════════════════════

class TestAllergySection:
    def test_allergies_header(self):
        assert _is_allergy_section("Allergies")

    def test_allergy_list_header(self):
        assert _is_allergy_section("Allergy List")

    def test_allergen_reactions_header(self):
        assert _is_allergy_section("Allergen Reactions")

    def test_allergy_line_tab_separated(self):
        assert _is_allergy_line("•\tCiprofloxacin\tOther/Unknown (See Comments)")

    def test_allergy_line_with_hives(self):
        assert _is_allergy_line("•\tPenicillins\tHives")

    def test_allergy_line_with_anaphylaxis(self):
        assert _is_allergy_line("•\tPenicillins\tAnaphylaxis")

    def test_non_allergy_line(self):
        assert not _is_allergy_line("cefazolin 2 g IV Q8H")


# ═══════════════════════════════════════════════════════════════════
# Unit tests: outpatient section detection
# ═══════════════════════════════════════════════════════════════════

class TestOutpatientSection:
    def test_current_outpatient(self):
        assert _is_outpatient_section("Current Outpatient Medications on File")

    def test_home_medications(self):
        assert _is_outpatient_section("Home Medications")

    def test_medications_prior_to_admission(self):
        assert _is_outpatient_section("Medications Prior to Admission")

    def test_not_outpatient(self):
        assert not _is_outpatient_section("Active Inpatient Medications")


# ═══════════════════════════════════════════════════════════════════
# Unit tests: discharge instruction section detection
# ═══════════════════════════════════════════════════════════════════

class TestDischargeInstructionSection:
    def test_discharge_instructions(self):
        assert _is_discharge_instruction_section("Discharge Instructions")

    def test_instructions_upon_discharge(self):
        assert _is_discharge_instruction_section("Instructions Upon Discharge")

    def test_patient_instructions(self):
        assert _is_discharge_instruction_section("Patient Instructions")

    def test_not_discharge(self):
        assert not _is_discharge_instruction_section("Progress Note")


# ═══════════════════════════════════════════════════════════════════
# Unit tests: dose extraction
# ═══════════════════════════════════════════════════════════════════

class TestDoseExtraction:
    def test_mg_dose(self):
        d = _extract_dose_info("vancomycin 1750 mg IV", "vancomycin")
        assert d is not None
        assert d["dose_text"] == "1750 mg"
        assert d["agent"] == "vancomycin"

    def test_g_dose(self):
        d = _extract_dose_info("cefazolin 2 g IV Q8H", "cefazolin")
        assert d is not None
        assert d["dose_text"] == "2 g"

    def test_route_iv(self):
        d = _extract_dose_info("cefazolin 2 g IV", "cefazolin")
        assert d is not None
        assert d["route"] == "IV"

    def test_route_po(self):
        d = _extract_dose_info("levofloxacin 750 mg oral daily", "levofloxacin")
        assert d is not None
        assert d["route"] == "PO"

    def test_no_dose(self):
        d = _extract_dose_info("continue cefazolin", "cefazolin")
        assert d is None


# ═══════════════════════════════════════════════════════════════════
# Unit tests: frequency normalization
# ═══════════════════════════════════════════════════════════════════

class TestFrequencyNormalization:
    def test_every_8_hours(self):
        assert _normalize_frequency("EVERY 8 HOURS") == "Q8H"

    def test_three_times_per_day(self):
        assert _normalize_frequency("3 times per day") == "Q8H"

    def test_once_daily(self):
        assert _normalize_frequency("once daily") == "DAILY"

    def test_bid(self):
        assert _normalize_frequency("BID") == "BID"

    def test_twice_daily(self):
        assert _normalize_frequency("twice daily") == "BID"


# ═══════════════════════════════════════════════════════════════════
# Unit tests: route normalization
# ═══════════════════════════════════════════════════════════════════

class TestRouteNormalization:
    def test_oral(self):
        assert _normalize_route("oral") == "PO"

    def test_iv(self):
        assert _normalize_route("IV") == "IV"

    def test_intravenous(self):
        assert _normalize_route("intravenous") == "IV"

    def test_ivpb(self):
        assert _normalize_route("IVPB") == "IV"

    def test_intramuscular(self):
        assert _normalize_route("intramuscular") == "IM"


# ═══════════════════════════════════════════════════════════════════
# Integration tests: full extractor
# ═══════════════════════════════════════════════════════════════════

class TestExtractorBasic:
    def test_empty_days(self):
        """No items → detected=False, empty evidence."""
        days_data = _make_days_data()
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False
        assert result["agents"] == []
        assert result["admin_evidence_count"] == 0
        assert result["mention_evidence_count"] == 0

    def test_no_antibiotics_in_text(self):
        """Text with no antibiotic names → detected=False."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item("Vitals stable. Continue monitoring.")]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_cefazolin_admin(self):
        """MAR entry with Given signal → admin evidence."""
        text = "ceFAZolin 2 g in sodium chloride 0.9% 50mL IVPB\nGiven 01/15/2025 0814"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text, item_type="MEDICATION_ADMIN")]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert "cefazolin" in result["agents"]
        assert result["admin_evidence_count"] >= 1

    def test_cefazolin_mention_without_given(self):
        """Antibiotic name without Given signal → mention, not admin."""
        text = "ceFAZolin 2 g IV Q8H ordered"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert "cefazolin" in result["agents"]
        assert result["admin_evidence_count"] == 0
        assert result["mention_evidence_count"] >= 1


class TestAllergyExclusion:
    def test_allergy_section_cipro_excluded(self):
        """Betty Roll pattern: ciprofloxacin in allergy section must NOT produce detected=True."""
        text = (
            "Allergies\n"
            "Allergen\tReactions\n"
            "•\tPenicillins\tHives\n"
            "•\tCiprofloxacin\tOther/Unknown (See Comments)\n"
            "\n"
            "Social Hx:\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False
        assert result["agents"] == []

    def test_allergy_section_flagyl_excluded(self):
        """Roscella pattern: Flagyl in allergy section must NOT produce detected=True."""
        text = (
            "Allergies\n"
            "Allergen\tReactions\n"
            "•\tFlagyl [Metronidazole]\tOther/Unknown (See Comments)\n"
            "•\tLatex\tHives\n"
            "•\tPenicillins\tAnaphylaxis\n"
            "\n"
            "Social Hx:\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_allergy_line_outside_section(self):
        """Tab-separated allergy-format line even without header → excluded."""
        text = "•\tGentamicin\tAnaphylaxis"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_allergy_section_followed_by_real_admin(self):
        """Allergy section with ciprofloxacin, then real cefazolin admin later."""
        text = (
            "Allergies\n"
            "Allergen\tReactions\n"
            "•\tCiprofloxacin\tOther/Unknown\n"
            "\n"
            "Medication Administration:\n"
            "ceFAZolin 2 g IV Given 01/15/2025 0814\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert "cefazolin" in result["agents"]
        # Ciprofloxacin must NOT appear (allergy only)
        assert "ciprofloxacin" not in result["agents"]


class TestOutpatientExclusion:
    def test_home_medication_excluded(self):
        """Antibiotics listed under Home Medications should not count as inpatient admin."""
        text = (
            "Home Medications\n"
            "azithromycin 250 mg PO daily\n"
            "lisinopril 10 mg PO daily\n"
            "\n"
            "Assessment:\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_outpatient_medications_excluded(self):
        """Current Outpatient Medications on File section excluded."""
        text = (
            "Current Outpatient Medications on File\n"
            "doxycycline 100 mg PO BID\n"
            "\n"
            "Assessment:\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False


class TestDischargeInstructionExclusion:
    def test_discharge_instruction_excluded(self):
        """Antibiotics mentioned in discharge instructions should not count."""
        text = (
            "Discharge Instructions\n"
            "If an antibiotic prescription is provided, please take until completely finished.\n"
            "Complete your cefazolin course as directed.\n"
            "\n"
            "Follow Up:\n"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False


class TestDiscontinuation:
    def test_discontinued_signal(self):
        """Line with discontinue signal → discontinue evidence."""
        text = "vancomycin DISCONTINUED per ID recommendation"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert result["discontinued"] is True
        assert len(result["evidence"]["discontinued"]) >= 1

    def test_bracket_discontinued(self):
        """[DISCONTINUED] bracket marker on medication line."""
        text = "[DISCONTINUED] vancomycin 1750 mg IV"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["discontinued"] is True

    def test_bracket_completed(self):
        """[COMPLETED] bracket marker on medication line."""
        text = "[COMPLETED] cefazolin 2 g IV Q8H"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["discontinued"] is True

    def test_can_stop(self):
        """'can stop vancomycin' → discontinue signal."""
        text = "MRSA screen negative, can stop vancomycin"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["discontinued"] is True

    def test_completed_course(self):
        """'completed course' → discontinue signal."""
        text = "transitioned to cefazolin completed course"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["discontinued"] is True

    def test_no_discontinuation(self):
        """No discontinue signal → discontinued=False."""
        text = "continue cefazolin 2 g IV Q8H"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["discontinued"] is False


class TestNegativeMAR:
    def test_not_given_is_mention_only(self):
        """Not Given status → classified as mention, not admin."""
        text = "ceFAZolin 2 g IV\nNot Given"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text, item_type="MEDICATION_ADMIN")]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert result["admin_evidence_count"] == 0
        assert result["mention_evidence_count"] >= 1

    def test_patient_refused(self):
        """Patient Refused → classified as mention."""
        text = "cefazolin 2 g IV - Patient Refused"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["admin_evidence_count"] == 0
        assert result["mention_evidence_count"] >= 1


class TestMultiAgent:
    def test_two_agents_detected(self):
        """Multiple antibiotic agents on separate items."""
        text1 = "ceFAZolin 2 g IV Given 01/15/2025 0814"
        text2 = "vancomycin 1750 mg IV Given 01/15/2025 0900"
        days_data = _make_days_data({
            "2025-01-15": [
                _make_item(text1, item_id="item_001"),
                _make_item(text2, item_id="item_002"),
            ]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert "cefazolin" in result["agents"]
        assert "vancomycin" in result["agents"]
        assert result["admin_evidence_count"] >= 2


class TestEvidenceTraceability:
    def test_raw_line_id_present_on_all_evidence(self):
        """Every evidence entry must have raw_line_id."""
        text = (
            "ceFAZolin 2 g IV Given 01/15/2025 0814\n"
            "vancomycin DISCONTINUED"
        )
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        for cat in ("admin", "mention", "discontinued"):
            for ev in result["evidence"][cat]:
                assert "raw_line_id" in ev, f"Missing raw_line_id in {cat} evidence"
                assert len(ev["raw_line_id"]) == 16

    def test_deduplication(self):
        """Repeated identical items should be deduplicated."""
        text = "ceFAZolin 2 g IV Given 01/15/2025 0814"
        item1 = _make_item(text, item_id="item_001", dt="2025-01-15T08:14:00")
        item2 = _make_item(text, item_id="item_001", dt="2025-01-15T08:14:00")
        days_data = _make_days_data({
            "2025-01-15": [item1, item2]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        # Same item_id + dt + text → same raw_line_id → deduplicated
        assert result["admin_evidence_count"] == 1


class TestDoseEntries:
    def test_dose_extracted(self):
        """Dose info should be extracted from admin line."""
        text = "ceFAZolin 2 g IV Q8H\nGiven 01/15/2025 0814"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert len(result["dose_entries"]) >= 1
        dose = result["dose_entries"][0]
        assert dose["agent"] == "cefazolin"
        assert dose["dose_text"] == "2 g"

    def test_dose_deduplication(self):
        """Identical dose entries across items should be deduplicated."""
        text = "ceFAZolin 2 g IV Q8H\nGiven 01/15/2025 0814"
        days_data = _make_days_data({
            "2025-01-15": [
                _make_item(text, item_id="item_001"),
                _make_item(text, item_id="item_002"),
            ]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        # Same (agent, dose_text, route, frequency) → deduplicated
        cef_doses = [d for d in result["dose_entries"] if d["agent"] == "cefazolin"]
        assert len(cef_doses) == 1


class TestFalsePositiveDefense:
    def test_generic_antibiotics_no_match(self):
        """Generic 'Antibiotics: no' must not trigger detection."""
        text = "Antibiotics: no"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_abx_none_not_match(self):
        """'ABX - none' must not trigger detection."""
        text = "ABX - none"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_antibiotic_prescription_instruction(self):
        """Discharge instruction about antibiotics without agent → no detection."""
        text = "If an antibiotic prescription is provided, please take until completely finished."
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False

    def test_antibiotic_initiation_template(self):
        """Institutional template text about antibiotics without specific agent → no detection."""
        text = "Antibiotic INITIATION should not be withheld if highly suspicious for sepsis."
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text)]
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is False


class TestOutputContract:
    def test_output_keys(self):
        """Output must contain required keys."""
        days_data = _make_days_data()
        result = extract_antibiotic_admin(_pat_features(), days_data)
        required_keys = {
            "detected", "agents", "first_mention_ts", "first_admin_ts",
            "discontinued", "dose_entries", "admin_evidence_count",
            "mention_evidence_count", "evidence",
        }
        assert required_keys.issubset(result.keys())

    def test_evidence_structure(self):
        """Evidence dict must have admin, mention, discontinued keys."""
        days_data = _make_days_data()
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert "admin" in result["evidence"]
        assert "mention" in result["evidence"]
        assert "discontinued" in result["evidence"]

    def test_first_ts_null_when_not_detected(self):
        """When not detected, first_mention_ts and first_admin_ts must be None."""
        days_data = _make_days_data()
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["first_mention_ts"] is None
        assert result["first_admin_ts"] is None


class TestMultiDayTimeline:
    def test_multi_day_first_admin_ts(self):
        """First admin timestamp should be from earliest day."""
        text_d1 = "vancomycin 1750 mg IV\nGiven 01/15/2025 0900"
        text_d2 = "ceFAZolin 2 g IV\nGiven 01/16/2025 0800"
        days_data = _make_days_data({
            "2025-01-15": [_make_item(text_d1, dt="2025-01-15T09:00:00", item_id="id1")],
            "2025-01-16": [_make_item(text_d2, dt="2025-01-16T08:00:00", item_id="id2")],
        })
        result = extract_antibiotic_admin(_pat_features(), days_data)
        assert result["detected"] is True
        assert "vancomycin" in result["agents"]
        assert "cefazolin" in result["agents"]
        # First admin should be from day 1
        assert result["first_admin_ts"] is not None
        assert "2025-01-15" in result["first_admin_ts"]
