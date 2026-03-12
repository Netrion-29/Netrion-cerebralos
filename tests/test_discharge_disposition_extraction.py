"""
Tests for discharge disposition extraction and normalization.

Covers:
  - Normalization map (canonical values)
  - Raw-file fallback scan: Discharge Disposition, Discharge Plan,
    9. Disposition: Discharged to ...
  - False-positive guard: eye "discharge", planning notes, interim values
  - Exclusion of uncertain/deferred values

Raw-file citation evidence (Slice A plan §2C / §2D):
  Anna_Dennis:1729        -> "Discharge Disposition: Skilled Nursing Facility" (SNF)
  Ronald_Bittner:3677     -> "Discharge Disposition: Long Term Hospital"       (LTAC)
  Arnetta_Henry:1256      -> "9. Disposition: Discharged to home."             (Home)
  Jamie_Hunter:3999       -> "Discharge Disposition: Swing Bed"                (Swing Bed)
  Linda_Hufford:3064      -> "Discharge Disposition: Home Health"              (Home Health)
  Anna_Dennis:3458        -> "Eyes: ... No discharge."                         (NEGATIVE)
  Arnetta_Henry:356       -> "SW/CM for disposition needs."                    (NEGATIVE)
  Lee_Woodard:371         -> "Barriers to discharge: ..."                     (NEGATIVE)
"""

import os
import tempfile

import pytest

from cerebralos.features.patient_movement_v1 import (
    _normalize_disposition,
    _scan_raw_disposition_fallback,
)


class TestNormalizeDisposition:
    """Normalization of raw disposition values to canonical set."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Home", "Home"),
            ("home", "Home"),
            ("Skilled Nursing Facility", "SNF"),
            ("SNF", "SNF"),
            ("snf", "SNF"),
            ("Rehab-Inpt", "Rehab"),
            ("Rehab", "Rehab"),
            ("Acute Rehab", "Rehab"),
            ("Long Term Hospital", "LTAC"),
            ("LTAC", "LTAC"),
            ("Swing Bed", "Swing Bed"),
            ("Home Health", "Home Health"),
            ("Home Health Care", "Home Health"),
            ("Expired", "Expired"),
            ("Deceased", "Expired"),
        ],
        ids=[
            "home_cap",
            "home_lower",
            "snf_full",
            "snf_abbrev",
            "snf_lower",
            "rehab_inpt",
            "rehab",
            "acute_rehab",
            "ltac_full",
            "ltac_abbrev",
            "swing_bed",
            "home_health",
            "home_health_care",
            "expired",
            "deceased",
        ],
    )
    def test_normalization(self, raw, expected):
        assert _normalize_disposition(raw) == expected

    def test_none_input(self):
        assert _normalize_disposition(None) is None

    def test_empty_input(self):
        assert _normalize_disposition("") is None
        assert _normalize_disposition("   ") is None

    def test_unknown_value_passthrough(self):
        assert _normalize_disposition("Against Medical Advice") == "Against Medical Advice"


class TestRawFileFallback:
    """Fallback scan of raw patient files for disposition data."""

    def _write_temp(self, content):
        """Write content to a temp file and return its path."""
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        return path

    def test_discharge_disposition_field(self):
        path = self._write_temp(
            "Some header\n"
            "Discharge Disposition: Skilled Nursing Facility\n"
            "Discharge Plan: SNF\n"
        )
        try:
            result = _scan_raw_disposition_fallback(path)
            assert result == "SNF"
        finally:
            os.unlink(path)

    def test_numbered_disposition(self):
        path = self._write_temp(
            "Some notes\n"
            "9. Disposition: Discharged to home.\n"
            "10. Follow-up: As needed.\n"
        )
        try:
            result = _scan_raw_disposition_fallback(path)
            assert result == "Home"
        finally:
            os.unlink(path)

    def test_discharge_plan_field(self):
        path = self._write_temp(
            "Some notes\n"
            "Discharge Plan: LTAC\n"
        )
        try:
            result = _scan_raw_disposition_fallback(path)
            assert result == "LTAC"
        finally:
            os.unlink(path)

    def test_last_value_wins(self):
        """Multiple disposition entries should prefer the last one."""
        path = self._write_temp(
            "Discharge Disposition: Rehab-Inpt\n"
            "Discharge Plan: Acute Rehab\n"
            "---\n"
            "Discharge Disposition: Long Term Hospital\n"
            "Discharge Plan: LTAC\n"
        )
        try:
            result = _scan_raw_disposition_fallback(path)
            assert result == "LTAC"
        finally:
            os.unlink(path)

    def test_swing_bed(self):
        path = self._write_temp("Discharge Disposition: Swing Bed\n")
        try:
            assert _scan_raw_disposition_fallback(path) == "Swing Bed"
        finally:
            os.unlink(path)

    def test_home_health(self):
        path = self._write_temp("Discharge Disposition: Home Health\n")
        try:
            assert _scan_raw_disposition_fallback(path) == "Home Health"
        finally:
            os.unlink(path)

    def test_no_match(self):
        path = self._write_temp("Patient arrived via EMS.\nNo disposition data.\n")
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_none_source(self):
        assert _scan_raw_disposition_fallback(None) is None

    def test_missing_file(self):
        assert _scan_raw_disposition_fallback("/nonexistent/path.txt") is None


class TestDispositionNegatives:
    """Lines that mention 'discharge' or 'disposition' but are NOT patient disposition."""

    def _write_temp(self, content):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        return path

    def test_eye_discharge_excluded(self):
        """'No discharge' in eye exam should not match."""
        path = self._write_temp(
            "Eyes: PERRLA, EOMI, Conjunctiva normal, No discharge.\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_barriers_to_discharge_excluded(self):
        """'Barriers to discharge' should not match."""
        path = self._write_temp(
            "Barriers to discharge: Unable to complete basic hygiene\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_defer_excluded(self):
        """Deferred disposition values should be skipped."""
        path = self._write_temp(
            "Discharge Disposition: Defer to primary team\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_pending_excluded(self):
        path = self._write_temp(
            "Discharge Disposition: Pending patient progress\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_likely_excluded(self):
        """Uncertain disposition ('likely') should be skipped."""
        path = self._write_temp(
            "Discharge Disposition: SNF likely tomorrow\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_planning_note_excluded(self):
        """'SW/CM for disposition needs' should not match."""
        path = self._write_temp(
            "- SW/CM for disposition needs.\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) is None
        finally:
            os.unlink(path)

    def test_valid_after_negatives(self):
        """Valid disposition found after negative lines should work."""
        path = self._write_temp(
            "Barriers to discharge: Unable to walk\n"
            "Eyes: No discharge.\n"
            "Discharge Disposition: Home\n"
        )
        try:
            assert _scan_raw_disposition_fallback(path) == "Home"
        finally:
            os.unlink(path)
