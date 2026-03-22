"""Tests for the PI RN Casefile Hub v1 renderer."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict

import pytest

from cerebralos.reporting.render_casefile_hub_v1 import (
    _compute_los,
    _count_ntds,
    _count_protocol_noncompliant,
    _format_date,
    extract_card,
    generate_hub,
    render_hub,
    scan_bundles,
    sort_cards,
)

# ── Fixtures ──────────────────────────────────────────────────────

def _make_bundle(
    name: str = "Test Patient",
    slug: str = "Test_Patient",
    arrival: str = "2026-01-05 10:00:00",
    discharge: str | None = "2026-01-08 14:30:00",
    age: int | None = 55,
    sex: str | None = "Male",
    mechanism: str | None = "fall",
    body_regions: list | None = None,
    trauma_category: str | None = "Level II",
    ntds_outcomes: dict | None = None,
    protocol_results: list | None = None,
) -> Dict[str, Any]:
    """Build a minimal but valid patient bundle for testing."""
    if ntds_outcomes is None:
        ntds_outcomes = {
            "1": {"event_id": 1, "canonical_name": "AKI", "outcome": "NO"},
            "2": {"event_id": 2, "canonical_name": "ARDS", "outcome": "YES"},
            "3": {"event_id": 3, "canonical_name": "DVT", "outcome": "UNABLE_TO_DETERMINE"},
        }
    if protocol_results is None:
        protocol_results = [
            {"protocol_id": "TBI", "protocol_name": "TBI Mgmt", "outcome": "COMPLIANT"},
            {"protocol_id": "RIB", "protocol_name": "Rib Fx", "outcome": "NON_COMPLIANT"},
        ]
    return {
        "build": {"bundle_version": "1.0", "generated_at_utc": "2026-01-08T12:00:00Z",
                   "assembler": "build_patient_bundle_v1"},
        "patient": {
            "patient_id": "TP001",
            "patient_name": name,
            "dob": "1971-03-15",
            "slug": slug,
            "arrival_datetime": arrival,
            "discharge_datetime": discharge,
            "trauma_category": trauma_category,
        },
        "summary": {
            "mechanism": {
                "mechanism_primary": mechanism,
                "body_region_labels": body_regions or ["head", "chest"],
            } if mechanism else None,
            "age": {"age_years": age} if age is not None else None,
            "demographics": {"sex": sex} if sex else None,
            "pmh": None,
            "anticoagulants": None,
            "activation": None,
            "shock_trigger": None,
        },
        "compliance": {
            "ntds_summary": None,
            "ntds_event_outcomes": ntds_outcomes,
            "protocol_results": protocol_results,
        },
        "daily": {},
        "consultants": None,
        "artifacts": {},
        "warnings": [],
    }


def _write_bundle(tmp_path: Path, slug: str, bundle: dict) -> Path:
    """Write a bundle JSON to the expected directory structure."""
    patient_dir = tmp_path / slug
    patient_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = patient_dir / "patient_bundle_v1.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    # Also create a dummy casefile so links are valid
    (patient_dir / "casefile_v1.html").write_text("<html></html>", encoding="utf-8")
    return bundle_path


# ── extract_card tests ────────────────────────────────────────────

class TestExtractCard:
    def test_happy_path(self):
        bundle = _make_bundle()
        card = extract_card(bundle)
        assert card is not None
        assert card["name"] == "Test Patient"
        assert card["slug"] == "Test_Patient"
        assert card["age"] == 55
        assert card["sex"] == "Male"
        assert card["mechanism"] == "fall"
        assert card["ntds_yes"] == 1
        assert card["ntds_utd"] == 1
        assert card["ntds_total"] == 3
        assert card["protocol_noncompliant"] == 1
        assert card["los_days"] == 3
        assert card["is_discharged"] is True
        assert card["casefile_link"] == "./Test_Patient/casefile_v1.html"

    def test_missing_patient_name_returns_none(self):
        bundle = _make_bundle()
        bundle["patient"]["patient_name"] = None
        assert extract_card(bundle) is None

    def test_missing_slug_returns_none(self):
        bundle = _make_bundle()
        bundle["patient"]["slug"] = None
        assert extract_card(bundle) is None

    def test_missing_patient_section_returns_none(self):
        bundle = _make_bundle()
        del bundle["patient"]
        assert extract_card(bundle) is None

    def test_data_not_available_trauma_category(self):
        bundle = _make_bundle(trauma_category="DATA_NOT_AVAILABLE")
        card = extract_card(bundle)
        assert card is not None
        assert card["trauma_category"] is None

    def test_null_optional_fields(self):
        bundle = _make_bundle(
            age=None, sex=None, mechanism=None, discharge=None,
            trauma_category=None, ntds_outcomes={}, protocol_results=[],
        )
        card = extract_card(bundle)
        assert card is not None
        assert card["age"] is None
        assert card["sex"] is None
        assert card["mechanism"] is None
        assert card["discharge"] is None
        assert card["los_days"] is None
        assert card["is_discharged"] is False
        assert card["ntds_yes"] == 0
        assert card["ntds_utd"] == 0
        assert card["ntds_total"] == 0
        assert card["protocol_noncompliant"] == 0

    def test_null_compliance_section(self):
        bundle = _make_bundle()
        bundle["compliance"] = None
        card = extract_card(bundle)
        assert card is not None
        assert card["ntds_yes"] == 0
        assert card["protocol_noncompliant"] == 0

    def test_null_summary_section(self):
        bundle = _make_bundle()
        bundle["summary"] = None
        card = extract_card(bundle)
        assert card is not None
        assert card["age"] is None
        assert card["sex"] is None
        assert card["mechanism"] is None


# ── Helper function tests ─────────────────────────────────────────

class TestComputeLOS:
    def test_normal(self):
        assert _compute_los("2026-01-01 10:00:00", "2026-01-04 14:00:00") == 3

    def test_same_day(self):
        assert _compute_los("2026-01-01 10:00:00", "2026-01-01 22:00:00") == 0

    def test_null_arrival(self):
        assert _compute_los(None, "2026-01-04 14:00:00") is None

    def test_null_discharge(self):
        assert _compute_los("2026-01-01 10:00:00", None) is None

    def test_iso_format(self):
        assert _compute_los("2026-01-01T10:00:00", "2026-01-03T14:00:00") == 2


class TestFormatDate:
    def test_normal(self):
        assert _format_date("2026-01-05 10:30:00") == "2026-01-05 10:30"

    def test_iso(self):
        assert _format_date("2026-01-05T10:30:00") == "2026-01-05 10:30"

    def test_null(self):
        assert _format_date(None) is None

    def test_unparseable(self):
        assert _format_date("bad-date") == "bad-date"


class TestCountNTDS:
    def test_yes_count(self):
        comp = {"ntds_event_outcomes": {
            "1": {"outcome": "YES"}, "2": {"outcome": "NO"}, "3": {"outcome": "YES"},
        }}
        assert _count_ntds(comp, "YES") == 2

    def test_null_compliance(self):
        assert _count_ntds(None, "YES") == 0

    def test_null_outcomes(self):
        assert _count_ntds({"ntds_event_outcomes": None}, "YES") == 0


class TestCountProtocolNC:
    def test_normal(self):
        comp = {"protocol_results": [
            {"outcome": "NON_COMPLIANT"}, {"outcome": "COMPLIANT"}, {"outcome": "NON_COMPLIANT"},
        ]}
        assert _count_protocol_noncompliant(comp) == 2

    def test_null(self):
        assert _count_protocol_noncompliant(None) == 0

    def test_empty(self):
        assert _count_protocol_noncompliant({"protocol_results": []}) == 0


# ── scan_bundles tests ────────────────────────────────────────────

class TestScanBundles:
    def test_happy_path_multiple(self, tmp_path):
        b1 = _make_bundle(name="Alice A", slug="Alice_A", arrival="2026-01-10 08:00:00")
        b2 = _make_bundle(name="Bob B", slug="Bob_B", arrival="2026-01-05 12:00:00")
        _write_bundle(tmp_path, "Alice_A", b1)
        _write_bundle(tmp_path, "Bob_B", b2)

        cards, warnings = scan_bundles(tmp_path)
        assert len(cards) == 2
        assert len(warnings) == 0
        slugs = {c["slug"] for c in cards}
        assert slugs == {"Alice_A", "Bob_B"}

    def test_empty_directory(self, tmp_path):
        cards, warnings = scan_bundles(tmp_path)
        assert cards == []
        assert len(warnings) == 0

    def test_nonexistent_directory(self, tmp_path):
        cards, warnings = scan_bundles(tmp_path / "nonexistent")
        assert cards == []
        assert len(warnings) == 1
        assert "not found" in warnings[0]

    def test_invalid_json_skipped(self, tmp_path):
        patient_dir = tmp_path / "Bad_Patient"
        patient_dir.mkdir()
        (patient_dir / "patient_bundle_v1.json").write_text("not-json")
        b2 = _make_bundle(name="Good One", slug="Good_One")
        _write_bundle(tmp_path, "Good_One", b2)

        cards, warnings = scan_bundles(tmp_path)
        assert len(cards) == 1
        assert cards[0]["slug"] == "Good_One"
        assert len(warnings) == 1
        assert "Bad_Patient" in warnings[0]

    def test_missing_required_fields_skipped(self, tmp_path):
        b = _make_bundle()
        b["patient"]["patient_name"] = None
        _write_bundle(tmp_path, "Missing_Name", b)
        b2 = _make_bundle(name="Valid", slug="Valid")
        _write_bundle(tmp_path, "Valid", b2)

        cards, warnings = scan_bundles(tmp_path)
        assert len(cards) == 1
        assert len(warnings) == 1
        assert "Missing_Name" in warnings[0]


# ── sort_cards tests ──────────────────────────────────────────────

class TestSortCards:
    def _cards(self):
        return [
            extract_card(_make_bundle(name="Zara", slug="Zara", arrival="2026-01-01 10:00:00",
                                      discharge="2026-01-02 10:00:00")),
            extract_card(_make_bundle(name="Alice", slug="Alice", arrival="2026-01-10 10:00:00",
                                      discharge="2026-01-15 10:00:00")),
            extract_card(_make_bundle(name="Mira", slug="Mira", arrival="2026-01-05 10:00:00",
                                      discharge=None)),
        ]

    def test_sort_arrival_newest_first(self):
        cards = sort_cards(self._cards(), "arrival")
        assert [c["slug"] for c in cards] == ["Alice", "Mira", "Zara"]

    def test_sort_name(self):
        cards = sort_cards(self._cards(), "name")
        assert [c["slug"] for c in cards] == ["Alice", "Mira", "Zara"]

    def test_sort_los_longest_first(self):
        cards = sort_cards(self._cards(), "los")
        assert cards[0]["slug"] == "Alice"  # 5 days
        assert cards[1]["slug"] == "Zara"   # 1 day

    def test_sort_ntds(self):
        c1 = extract_card(_make_bundle(name="A", slug="A",
                                        ntds_outcomes={"1": {"outcome": "YES"}, "2": {"outcome": "YES"}}))
        c2 = extract_card(_make_bundle(name="B", slug="B",
                                        ntds_outcomes={"1": {"outcome": "NO"}}))
        cards = sort_cards([c2, c1], "ntds")
        assert cards[0]["slug"] == "A"


# ── Determinism test ──────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self, tmp_path):
        b1 = _make_bundle(name="Alice", slug="Alice")
        b2 = _make_bundle(name="Bob", slug="Bob")
        _write_bundle(tmp_path, "Alice", b1)
        _write_bundle(tmp_path, "Bob", b2)

        ts = "2026-01-15T12:00:00Z"
        out1 = tmp_path / "hub1.html"
        out2 = tmp_path / "hub2.html"
        generate_hub(tmp_path, out1, generated_at=ts)
        generate_hub(tmp_path, out2, generated_at=ts)
        assert out1.read_text() == out2.read_text()


# ── render_hub tests ──────────────────────────────────────────────

class TestRenderHub:
    def test_empty_cards_shows_empty_state(self):
        html = render_hub([], [])
        assert "No patient casefiles found" in html
        assert "run_casefile_v1.sh" in html

    def test_cards_render_names(self):
        card = extract_card(_make_bundle(name="Betty Roll", slug="Betty_Roll"))
        html = render_hub([card], [])
        assert "Betty Roll" in html
        assert "Betty_Roll" in html
        assert "./Betty_Roll/casefile_v1.html" in html

    def test_ntds_badges_render(self):
        card = extract_card(_make_bundle(ntds_outcomes={
            "1": {"outcome": "YES"}, "2": {"outcome": "YES"},
            "3": {"outcome": "UNABLE_TO_DETERMINE"},
        }))
        html = render_hub([card], [])
        assert "NTDS YES 2" in html
        assert "UTD 1" in html

    def test_ntds_clear_badge(self):
        card = extract_card(_make_bundle(ntds_outcomes={
            "1": {"outcome": "NO"}, "2": {"outcome": "NO"},
        }))
        html = render_hub([card], [])
        assert "NTDS clear" in html

    def test_protocol_nc_badge(self):
        card = extract_card(_make_bundle(protocol_results=[
            {"outcome": "NON_COMPLIANT"}, {"outcome": "NON_COMPLIANT"},
        ]))
        html = render_hub([card], [])
        assert "Protocol NC 2" in html

    def test_warnings_render(self):
        html = render_hub([], ["Some warning here"])
        assert "Some warning here" in html

    def test_search_input_present(self):
        card = extract_card(_make_bundle())
        html = render_hub([card], [])
        assert 'id="hub-search"' in html

    def test_sort_select_present(self):
        card = extract_card(_make_bundle())
        html = render_hub([card], [])
        assert 'id="hub-sort"' in html

    def test_filter_select_present(self):
        card = extract_card(_make_bundle())
        html = render_hub([card], [])
        assert 'id="hub-filter"' in html

    def test_html_escaping(self):
        card = extract_card(_make_bundle(name='<script>alert("x")</script>', slug="XSS_Test"))
        html = render_hub([card], [])
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_discharged_status(self):
        card = extract_card(_make_bundle(discharge="2026-01-08 14:00:00"))
        html = render_hub([card], [])
        assert "Discharged" in html

    def test_active_status(self):
        card = extract_card(_make_bundle(discharge=None))
        html = render_hub([card], [])
        assert "Active" in html

    def test_demographics_line(self):
        card = extract_card(_make_bundle(age=71, sex="Female", mechanism="fall"))
        html = render_hub([card], [])
        assert "71y" in html
        assert "Female" in html
        assert "Fall" in html

    def test_missing_demographics_graceful(self):
        card = extract_card(_make_bundle(age=None, sex=None, mechanism=None))
        html = render_hub([card], [])
        # Should not crash, and the card-demo div should be absent or empty
        assert card["name"] in html  # card still renders


# ── generate_hub (integration) ────────────────────────────────────

class TestGenerateHub:
    def test_writes_file(self, tmp_path):
        b = _make_bundle(name="Test", slug="Test")
        _write_bundle(tmp_path, "Test", b)
        out = generate_hub(tmp_path, generated_at="2026-01-15T00:00:00Z")
        assert out.exists()
        content = out.read_text()
        assert "Test" in content
        assert "PI RN Casefile Hub" in content

    def test_link_generation(self, tmp_path):
        b = _make_bundle(name="Betty Roll", slug="Betty_Roll")
        _write_bundle(tmp_path, "Betty_Roll", b)
        out = generate_hub(tmp_path, generated_at="2026-01-15T00:00:00Z")
        content = out.read_text()
        assert "./Betty_Roll/casefile_v1.html" in content

    def test_multiple_patients(self, tmp_path):
        for i, (name, slug) in enumerate([
            ("Alice Alpha", "Alice_Alpha"),
            ("Bob Beta", "Bob_Beta"),
            ("Carol Gamma", "Carol_Gamma"),
        ]):
            b = _make_bundle(name=name, slug=slug,
                             arrival=f"2026-01-0{i+1} 10:00:00")
            _write_bundle(tmp_path, slug, b)

        out = generate_hub(tmp_path, generated_at="2026-01-15T00:00:00Z")
        content = out.read_text()
        assert "3 patients" in content
        for slug in ["Alice_Alpha", "Bob_Beta", "Carol_Gamma"]:
            assert slug in content

    def test_empty_root(self, tmp_path):
        out = generate_hub(tmp_path, generated_at="2026-01-15T00:00:00Z")
        content = out.read_text()
        assert "No patient casefiles found" in content
        assert "0 patients" in content
