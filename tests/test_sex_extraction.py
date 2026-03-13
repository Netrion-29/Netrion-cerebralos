"""
Tests for sex/gender extraction from raw patient files.

Covers:
  - Line 2 direct "NN year old male/female" (DOS format header)
  - HPI fallback: "NN y.o. male/female", "NN yo male/female",
    "NN-year-old male/female"
  - False-positive guard: Partner lines, sexual activity fields
  - Normalization to "Male"/"Female"

Raw-file citation evidence (Slice A plan §2A / §2B):
  Ronald_Bittner:2        -> "72 year old male"          (line 2 header)
  Anna_Dennis:23          -> "65 y.o. female"             (HPI fallback)
  Timothy_Cowan:16        -> "60 yo male"                 (HPI fallback)
  Timothy_Nachtwey:20     -> "56-year-old male"           (HPI fallback)
  William_Simmons:43      -> "86 y.o. male"               (HPI fallback)
  Ronald_Bittner:108      -> "Partners:       Female"     (NEGATIVE)
  Anna_Dennis:2062        -> "Substance and Sexual ..."   (NEGATIVE)
"""

import pytest

from cerebralos.ingest.parse_patient_txt import (
    _extract_header_dos,
    _extract_sex_hpi_fallback,
)


class TestLine2HeaderSex:
    """DOS-format line 2: 'NN year old male/female'."""

    @pytest.mark.parametrize(
        "line2, expected_sex",
        [
            ("72 year old male", "Male"),
            ("88 year old female", "Female"),
            ("71 year old female", "Female"),
            ("84 year old male", "Male"),
            ("49 year old male", "Male"),
            ("73 year old male", "Male"),
        ],
        ids=[
            "Ronald_Bittner",
            "Margaret_Rudd",
            "Betty_Roll",
            "Lee_Woodard",
            "Robert_Altmeyer",
            "Johnny_Stokes",
        ],
    )
    def test_dos_header_sex(self, line2, expected_sex):
        lines = ["Patient Name", line2, "01/01/2000"]
        header = _extract_header_dos(lines)
        assert header.get("SEX") == expected_sex


class TestHPIFallbackSex:
    """HPI-style age/sex patterns in body text."""

    @pytest.mark.parametrize(
        "line, expected_sex",
        [
            ("Anna Dennis is a 65 y.o. female Pt arrives via EMS", "Female"),
            ("HPI: 60 yo male with unknown PMH", "Male"),
            ("HPI: 56-year-old male with PMH hemorrhagic stroke", "Male"),
            ("William H Simmons is a 86 y.o. male with PMH of Afib", "Male"),
            ("65-year-old female with dementia and epilepsy", "Female"),
            ("General: 60 year old male who is anxious", "Male"),
            ("55 year old female", "Female"),
            ("Patient is a 56-year-old male with a past medical history", "Male"),
        ],
        ids=[
            "Anna_Dennis_yo",
            "Timothy_Cowan_yo",
            "Timothy_Nachtwey_year_old",
            "William_Simmons_yo",
            "Anna_Dennis_year_old",
            "Timothy_Cowan_year_old",
            "Arnetta_Henry_year_old",
            "Timothy_Nachtwey_year_old_v2",
        ],
    )
    def test_hpi_fallback_matches(self, line, expected_sex):
        lines = ["PATIENT_ID: 12345", "ARRIVAL_TIME: 2025-01-01 00:00:00", ""] + [line]
        sex, line_num = _extract_sex_hpi_fallback(lines)
        assert sex == expected_sex
        assert line_num == 3  # 0-indexed, the 4th line

    def test_hpi_fallback_first_match_wins(self):
        """Should return the first valid match."""
        lines = [
            "PATIENT_ID: 12345",
            "",
            "HPI: 60 yo male with unknown PMH",
            "General: 60 year old male who is anxious",
        ]
        sex, line_num = _extract_sex_hpi_fallback(lines)
        assert sex == "Male"
        assert line_num == 2


class TestSexNegatives:
    """Lines that contain sex-related words but are NOT patient sex."""

    @pytest.mark.parametrize(
        "line",
        [
            "Partners:       Female",
            "Partners:       Male",
            "Sexual activity:        Yes",
            "Sexual activity:        Never",
            "Sexual activity:        Defer",
            "Sexual activity:        Not on file",
            "Sexually Abused: No",
        ],
        ids=[
            "partners_female",
            "partners_male",
            "sexual_activity_yes",
            "sexual_activity_never",
            "sexual_activity_defer",
            "sexual_activity_notfile",
            "sexually_abused",
        ],
    )
    def test_noise_lines_excluded(self, line):
        lines = [line]
        sex, line_num = _extract_sex_hpi_fallback(lines)
        assert sex is None
        assert line_num is None

    def test_noise_before_valid_is_skipped(self):
        """Noise lines should be skipped, valid match found after them."""
        lines = [
            "Partners:       Female",
            "HPI: 72 yo male with PMH of CAD",
        ]
        sex, line_num = _extract_sex_hpi_fallback(lines)
        assert sex == "Male"
        assert line_num == 1

    def test_no_match_returns_none(self):
        lines = [
            "PATIENT_ID: 12345",
            "ARRIVAL_TIME: 2025-01-01 00:00:00",
            "PATIENT_NAME: John Doe",
        ]
        sex, line_num = _extract_sex_hpi_fallback(lines)
        assert sex is None
        assert line_num is None


class TestSexScanLimit:
    """HPI fallback should only scan first N lines."""

    def test_beyond_scan_limit_not_matched(self):
        lines = [""] * 70 + ["HPI: 60 yo male with PMH"]
        sex, line_num = _extract_sex_hpi_fallback(lines, scan_limit=60)
        assert sex is None

    def test_within_scan_limit_matched(self):
        lines = [""] * 50 + ["HPI: 60 yo male with PMH"]
        sex, line_num = _extract_sex_hpi_fallback(lines, scan_limit=60)
        assert sex == "Male"
        assert line_num == 50
