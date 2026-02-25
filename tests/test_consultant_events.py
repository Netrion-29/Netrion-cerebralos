#!/usr/bin/env python3
"""
Tests for consultant_events_v1 feature extractor.

Covers:
  - Consultant entry detection (_is_consultant_entry)
  - Service exclusion rules
  - Per-service grouping and summary building
  - Fail-closed when no note_index
  - Fail-closed when no consultant entries
  - Real-world-like entry structures
  - Evidence traceability (raw_line_id)
  - Determinism
"""

import pytest

from cerebralos.features.consultant_events_v1 import (
    _is_consultant_entry,
    _build_consultant_services,
    extract_consultant_events,
)


# ── Fixtures ────────────────────────────────────────────────────────

def _make_entry(note_type, service=None, author_name="Dr Test",
                author_raw="Dr Test, MD", date_raw="01/01",
                time_raw="1020", raw_line_id="abc123"):
    return {
        "note_type": note_type,
        "service": service,
        "author_name": author_name,
        "author_raw": author_raw,
        "date_raw": date_raw,
        "time_raw": time_raw,
        "raw_line_id": raw_line_id,
        "author_credential": "MD",
    }


# ── _is_consultant_entry tests ─────────────────────────────────────

class TestIsConsultantEntry:
    def test_consults_with_specialty_service(self):
        e = _make_entry("Consults", "Otolaryngology")
        assert _is_consultant_entry(e) is True

    def test_consults_with_orthopedics(self):
        e = _make_entry("Consults", "Orthopedics")
        assert _is_consultant_entry(e) is True

    def test_consults_with_excluded_general_surgeon(self):
        e = _make_entry("Consults", "General Surgeon")
        assert _is_consultant_entry(e) is False

    def test_consults_with_excluded_hospitalist(self):
        e = _make_entry("Consults", "Hospitalist")
        assert _is_consultant_entry(e) is False

    def test_consults_with_no_service(self):
        e = _make_entry("Consults", None)
        assert _is_consultant_entry(e) is False

    def test_consults_with_empty_service(self):
        e = _make_entry("Consults", "")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_with_physical_therapy(self):
        e = _make_entry("Progress Notes", "Physical Therapy")
        assert _is_consultant_entry(e) is True

    def test_progress_notes_with_occupational_therapy(self):
        e = _make_entry("Progress Notes", "Occupational Therapy")
        assert _is_consultant_entry(e) is True

    def test_progress_notes_with_excluded_general_surgeon(self):
        e = _make_entry("Progress Notes", "General Surgeon")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_with_excluded_nurse_to_nurse(self):
        e = _make_entry("Progress Notes", "Nurse to Nurse")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_with_excluded_case_manager(self):
        e = _make_entry("Progress Notes", "Case Manager")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_with_excluded_emergency(self):
        e = _make_entry("Progress Notes", "Emergency")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_with_excluded_physician_to_physician(self):
        e = _make_entry("Progress Notes", "Physician to Physician")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_with_excluded_surgery(self):
        e = _make_entry("Progress Notes", "Surgery")
        assert _is_consultant_entry(e) is False

    def test_progress_notes_no_service(self):
        e = _make_entry("Progress Notes", None)
        assert _is_consultant_entry(e) is False

    def test_ed_notes_excluded(self):
        e = _make_entry("ED Notes", "Emergency")
        assert _is_consultant_entry(e) is False

    def test_ed_provider_notes_excluded(self):
        e = _make_entry("ED Provider Notes", "Emergency")
        assert _is_consultant_entry(e) is False

    def test_hp_excluded(self):
        e = _make_entry("H&P", "General Surgeon")
        assert _is_consultant_entry(e) is False

    def test_triage_excluded(self):
        e = _make_entry("Triage Assessment", "Nurse to Nurse")
        assert _is_consultant_entry(e) is False

    def test_discharge_summary_excluded(self):
        e = _make_entry("Discharge Summary", "General Surgeon")
        assert _is_consultant_entry(e) is False

    def test_plan_of_care_excluded(self):
        e = _make_entry("Plan of Care", "Nursing")
        assert _is_consultant_entry(e) is False

    def test_case_insensitive_exclusion(self):
        e = _make_entry("Consults", "GENERAL SURGEON")
        assert _is_consultant_entry(e) is False

    def test_neurosurgery_included(self):
        e = _make_entry("Consults", "Neurosurgery")
        assert _is_consultant_entry(e) is True

    def test_wound_ostomy_included(self):
        e = _make_entry("Consults", "Wound/Ostomy")
        assert _is_consultant_entry(e) is True

    def test_internal_medicine_included(self):
        e = _make_entry("Consults", "Internal Medicine")
        assert _is_consultant_entry(e) is True


# ── _build_consultant_services tests ───────────────────────────────

class TestBuildConsultantServices:
    def test_empty(self):
        result = _build_consultant_services([])
        assert result == []

    def test_single_service_single_entry(self):
        entries = [
            _make_entry("Consults", "Otolaryngology",
                        author_name="Chacko, Chris E",
                        date_raw="01/01", time_raw="1020",
                        raw_line_id="hash1"),
        ]
        result = _build_consultant_services(entries)
        assert len(result) == 1
        svc = result[0]
        assert svc["service"] == "Otolaryngology"
        assert svc["note_count"] == 1
        assert svc["first_ts"] == "01/01 1020"
        assert svc["last_ts"] == "01/01 1020"
        assert svc["authors"] == ["Chacko, Chris E"]
        assert "Consults" in svc["note_types"]
        assert len(svc["evidence"]) == 1
        assert svc["evidence"][0]["raw_line_id"] == "hash1"

    def test_multiple_services(self):
        entries = [
            _make_entry("Consults", "Orthopedics", author_name="Doc A",
                        date_raw="01/01", time_raw="0930"),
            _make_entry("Progress Notes", "Physical Therapy", author_name="PT B",
                        date_raw="01/02", time_raw="1400"),
        ]
        result = _build_consultant_services(entries)
        assert len(result) == 2
        svc_names = [s["service"] for s in result]
        assert "Orthopedics" in svc_names
        assert "Physical Therapy" in svc_names

    def test_same_service_multiple_entries(self):
        entries = [
            _make_entry("Consults", "Neurosurgery", author_name="NS A",
                        date_raw="01/01", time_raw="0800", raw_line_id="h1"),
            _make_entry("Progress Notes", "Neurosurgery", author_name="NS A",
                        date_raw="01/02", time_raw="1000", raw_line_id="h2"),
            _make_entry("Progress Notes", "Neurosurgery", author_name="NS B",
                        date_raw="01/03", time_raw="0900", raw_line_id="h3"),
        ]
        result = _build_consultant_services(entries)
        assert len(result) == 1
        svc = result[0]
        assert svc["note_count"] == 3
        assert svc["first_ts"] == "01/01 0800"
        assert svc["last_ts"] == "01/03 0900"
        assert len(svc["authors"]) == 2
        assert "NS A" in svc["authors"]
        assert "NS B" in svc["authors"]
        assert set(svc["note_types"]) == {"Consults", "Progress Notes"}
        assert len(svc["evidence"]) == 3


# ── extract_consultant_events tests ────────────────────────────────

class TestExtractConsultantEvents:
    def test_no_note_index(self):
        result = extract_consultant_events({}, {})
        assert result["consultant_present"] == "DATA NOT AVAILABLE"
        assert result["source_rule_id"] == "no_note_index_available"
        assert result["consultant_services_count"] == 0
        assert result["consultant_services"] == []

    def test_note_index_no_notes_section(self):
        features = {
            "note_index_events_v1": {
                "entries": [],
                "source_rule_id": "no_notes_section",
            }
        }
        result = extract_consultant_events(features, {})
        assert result["consultant_present"] == "DATA NOT AVAILABLE"
        assert result["source_rule_id"] == "no_note_index_available"

    def test_note_index_present_no_consultants(self):
        features = {
            "note_index_events_v1": {
                "entries": [
                    _make_entry("ED Notes", "Emergency"),
                    _make_entry("H&P", "General Surgeon"),
                    _make_entry("Progress Notes", "General Surgeon"),
                ],
                "source_rule_id": "note_index_raw_file",
            }
        }
        result = extract_consultant_events(features, {})
        assert result["consultant_present"] == "no"
        assert result["source_rule_id"] == "no_consultant_entries"
        assert result["consultant_services_count"] == 0

    def test_with_consultant_entries(self):
        features = {
            "note_index_events_v1": {
                "entries": [
                    _make_entry("Consults", "Otolaryngology",
                                author_name="Chacko, Chris E",
                                date_raw="01/01", time_raw="1020",
                                raw_line_id="h1"),
                    _make_entry("Consults", "Internal Medicine",
                                author_name="Duran, Adriano M",
                                date_raw="01/01", time_raw="0553",
                                raw_line_id="h2"),
                    _make_entry("Progress Notes", "Physical Therapy",
                                author_name="Sharp, Kelsey",
                                date_raw="01/01", time_raw="1514",
                                raw_line_id="h3"),
                    # Excluded entries
                    _make_entry("Progress Notes", "General Surgeon"),
                    _make_entry("ED Notes", "Emergency"),
                    _make_entry("Progress Notes", "Hospitalist"),
                ],
                "source_rule_id": "note_index_raw_file",
            }
        }
        result = extract_consultant_events(features, {})
        assert result["consultant_present"] == "yes"
        assert result["source_rule_id"] == "consultant_events_from_note_index"
        assert result["consultant_services_count"] == 3
        svc_names = [s["service"] for s in result["consultant_services"]]
        assert "Otolaryngology" in svc_names
        assert "Internal Medicine" in svc_names
        assert "Physical Therapy" in svc_names

        # Evidence traceability
        for svc in result["consultant_services"]:
            for ev in svc["evidence"]:
                assert "raw_line_id" in ev
                assert ev["role"] == "consultant_event"
                assert len(ev["raw_line_id"]) > 0

    def test_determinism(self):
        features = {
            "note_index_events_v1": {
                "entries": [
                    _make_entry("Consults", "Orthopedics", author_name="Doc A",
                                date_raw="01/01", time_raw="0930", raw_line_id="x1"),
                    _make_entry("Progress Notes", "Physical Therapy", author_name="PT B",
                                date_raw="01/02", time_raw="1400", raw_line_id="x2"),
                ],
                "source_rule_id": "note_index_raw_file",
            }
        }
        r1 = extract_consultant_events(features, {})
        r2 = extract_consultant_events(features, {})
        assert r1["consultant_services"] == r2["consultant_services"]
        assert r1["consultant_present"] == r2["consultant_present"]
        assert r1["consultant_services_count"] == r2["consultant_services_count"]

    def test_hospitalist_excluded_even_in_consults(self):
        """Hospitalist consults are excluded per classification rules."""
        features = {
            "note_index_events_v1": {
                "entries": [
                    _make_entry("Consults", "Hospitalist", author_name="Hosp A"),
                ],
                "source_rule_id": "note_index_raw_file",
            }
        }
        result = extract_consultant_events(features, {})
        assert result["consultant_present"] == "no"
        assert result["consultant_services_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
