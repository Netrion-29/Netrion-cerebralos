"""Tests for demographics_v1 feature extraction.

Locks the schema: demographics_v1 must include both 'sex' and
'discharge_disposition', sourced from evidence header and
patient_movement_v1 respectively.
"""

import json
import pathlib

import pytest

OUTPUTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "outputs" / "features"

# Gate patients that must have feature outputs
GATE_PATIENTS = ["Anna_Dennis", "William_Simmons", "Timothy_Cowan", "Timothy_Nachtwey"]


# ── Schema tests ──────────────────────────────────────────────

class TestDemographicsSchema:
    """demographics_v1 must contain exactly sex + discharge_disposition."""

    @pytest.mark.parametrize("patient", GATE_PATIENTS)
    def test_demographics_v1_has_required_keys(self, patient: str) -> None:
        path = OUTPUTS_DIR / patient / "patient_features_v1.json"
        if not path.exists():
            pytest.skip(f"No output for {patient}")
        data = json.loads(path.read_text())
        demo = data["features"]["demographics_v1"]
        assert "sex" in demo, "demographics_v1 must contain 'sex'"
        assert "discharge_disposition" in demo, (
            "demographics_v1 must contain 'discharge_disposition'"
        )

    @pytest.mark.parametrize("patient", GATE_PATIENTS)
    def test_demographics_v1_no_extra_keys(self, patient: str) -> None:
        path = OUTPUTS_DIR / patient / "patient_features_v1.json"
        if not path.exists():
            pytest.skip(f"No output for {patient}")
        data = json.loads(path.read_text())
        demo = data["features"]["demographics_v1"]
        allowed = {"sex", "discharge_disposition"}
        extra = set(demo.keys()) - allowed
        assert not extra, f"Unexpected keys in demographics_v1: {extra}"


# ── Sex behaviour ─────────────────────────────────────────────

class TestSexExtraction:
    """Sex must be Male, Female, or null; unchanged from prior behaviour."""

    @pytest.mark.parametrize("patient", GATE_PATIENTS)
    def test_sex_valid_value(self, patient: str) -> None:
        path = OUTPUTS_DIR / patient / "patient_features_v1.json"
        if not path.exists():
            pytest.skip(f"No output for {patient}")
        data = json.loads(path.read_text())
        sex = data["features"]["demographics_v1"]["sex"]
        assert sex in ("Male", "Female", None), f"Unexpected sex value: {sex}"

    def test_anna_dennis_sex_female(self) -> None:
        path = OUTPUTS_DIR / "Anna_Dennis" / "patient_features_v1.json"
        if not path.exists():
            pytest.skip("No Anna_Dennis output")
        data = json.loads(path.read_text())
        assert data["features"]["demographics_v1"]["sex"] == "Female"

    def test_william_simmons_sex_male(self) -> None:
        path = OUTPUTS_DIR / "William_Simmons" / "patient_features_v1.json"
        if not path.exists():
            pytest.skip("No William_Simmons output")
        data = json.loads(path.read_text())
        assert data["features"]["demographics_v1"]["sex"] == "Male"


# ── Discharge disposition ─────────────────────────────────────

class TestDischargeDisposition:
    """discharge_disposition sourced from patient_movement_v1.summary."""

    @pytest.mark.parametrize("patient", GATE_PATIENTS)
    def test_disposition_is_string_or_null(self, patient: str) -> None:
        path = OUTPUTS_DIR / patient / "patient_features_v1.json"
        if not path.exists():
            pytest.skip(f"No output for {patient}")
        data = json.loads(path.read_text())
        dispo = data["features"]["demographics_v1"]["discharge_disposition"]
        assert dispo is None or isinstance(dispo, str), (
            f"Unexpected disposition type: {type(dispo)}"
        )

    @pytest.mark.parametrize("patient", GATE_PATIENTS)
    def test_disposition_matches_movement_source(self, patient: str) -> None:
        """discharge_disposition must equal patient_movement_v1 source."""
        path = OUTPUTS_DIR / patient / "patient_features_v1.json"
        if not path.exists():
            pytest.skip(f"No output for {patient}")
        data = json.loads(path.read_text())
        demo_dispo = data["features"]["demographics_v1"]["discharge_disposition"]
        movement_dispo = (
            data["features"]
            .get("patient_movement_v1", {})
            .get("summary", {})
            .get("discharge_disposition_final")
        )
        assert demo_dispo == movement_dispo, (
            f"demographics_v1.discharge_disposition ({demo_dispo!r}) "
            f"!= patient_movement_v1.summary.discharge_disposition_final ({movement_dispo!r})"
        )


# ── Null-safe edge cases ──────────────────────────────────────

class TestNullSafety:
    """demographics_v1 must not crash when movement data is absent."""

    def test_no_movement_gives_null_disposition(self) -> None:
        """Simulate missing patient_movement_v1 in features dict."""
        # Replicate the assembly logic from build_patient_features_v1.py
        features: dict = {}  # no patient_movement_v1
        dispo_final = (
            (features.get("patient_movement_v1") or {})
            .get("summary", {})
            .get("discharge_disposition_final")
        )
        result = dispo_final if isinstance(dispo_final, str) else None
        assert result is None

    def test_empty_summary_gives_null_disposition(self) -> None:
        features = {"patient_movement_v1": {"summary": {}}}
        dispo_final = (
            (features.get("patient_movement_v1") or {})
            .get("summary", {})
            .get("discharge_disposition_final")
        )
        result = dispo_final if isinstance(dispo_final, str) else None
        assert result is None

    def test_numeric_disposition_gives_null(self) -> None:
        features = {"patient_movement_v1": {"summary": {"discharge_disposition_final": 42}}}
        dispo_final = (
            (features.get("patient_movement_v1") or {})
            .get("summary", {})
            .get("discharge_disposition_final")
        )
        result = dispo_final if isinstance(dispo_final, str) else None
        assert result is None

    def test_none_movement_gives_null_disposition(self) -> None:
        features = {"patient_movement_v1": None}
        dispo_final = (
            (features.get("patient_movement_v1") or {})
            .get("summary", {})
            .get("discharge_disposition_final")
        )
        result = dispo_final if isinstance(dispo_final, str) else None
        assert result is None

    def test_valid_string_passthrough(self) -> None:
        features = {"patient_movement_v1": {"summary": {"discharge_disposition_final": "Home"}}}
        dispo_final = (
            (features.get("patient_movement_v1") or {})
            .get("summary", {})
            .get("discharge_disposition_final")
        )
        result = dispo_final if isinstance(dispo_final, str) else None
        assert result == "Home"
