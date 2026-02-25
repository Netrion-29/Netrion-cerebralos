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
    _extract_service_from_consult_note,
    _is_primary_service_note,
    _scan_timeline_for_consult_notes,
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


# ── _extract_service_from_consult_note tests ───────────────────────

class TestExtractServiceFromConsultNote:
    """Tests for CONSULT_NOTE text → service extraction (fallback path)."""

    def test_consult_to_pulmonology(self):
        text = "Consult to Pulmonology [order 12345]\nOrdered by Dr. Smith"
        assert _extract_service_from_consult_note(text) == "Pulmonology"

    def test_consult_to_orthopedic_surgery(self):
        text = "Consult to Orthopedic Surgery [ord 99]\nSome text follows."
        assert _extract_service_from_consult_note(text) == "Orthopedic Surgery"

    def test_consult_to_ent(self):
        text = "Consult to ENT [order 555]\nordered by someone"
        assert _extract_service_from_consult_note(text) == "ENT"

    def test_consult_to_palliative_care(self):
        text = "Consult to Palliative Care [order 777]\nOrdered by Dr. Jones"
        assert _extract_service_from_consult_note(text) == "Palliative Care"

    def test_heading_neurosurgery_consult_note(self):
        text = "Neurosurgery Consult Note\n\nPatient seen and evaluated."
        assert _extract_service_from_consult_note(text) == "Neurosurgery"

    def test_heading_vascular_surgery_consult(self):
        text = "Vascular Surgery Consult\n\nHistory of..."
        assert _extract_service_from_consult_note(text) == "Vascular Surgery"

    def test_no_service_in_random_text(self):
        text = "This is just some random medical note text.\nNo consult header."
        assert _extract_service_from_consult_note(text) is None

    def test_consult_to_ordered_by(self):
        text = "Consult to Infectious Disease ordered by Dr. Lee"
        assert _extract_service_from_consult_note(text) == "Infectious Disease"

    def test_picks_longest_candidate(self):
        """When multiple 'consult to' matches exist, picks the longest."""
        text = (
            "Consult to Orthopedic Surgery [order 1]\n"
            "Consult to Ortho [order 2]\n"
        )
        result = _extract_service_from_consult_note(text)
        assert result == "Orthopedic Surgery"

    def test_alias_normalization_orthopedics(self):
        text = "Consult to Orthopedics [order 99]\n"
        assert _extract_service_from_consult_note(text) == "Orthopedic Surgery"


# ── _is_primary_service_note tests ─────────────────────────────────

class TestIsPrimaryServiceNote:
    """Tests for primary-service note detection (CONSULT_NOTE mislabel)."""

    def test_trauma_h_and_p(self):
        text = "Trauma H & P\n\nHistory:\nPatient presents with..."
        assert _is_primary_service_note(text) is True

    def test_trauma_hp(self):
        text = "Trauma HP\n\nThis is a 45 year old male..."
        assert _is_primary_service_note(text) is True

    def test_trauma_hp_ampersand(self):
        text = "Trauma H&P\n\nChief Complaint: Fall from height."
        assert _is_primary_service_note(text) is True

    def test_normal_consult_note(self):
        text = "Pulmonology Consult Note\n\nConsult to Pulmonology [order 1]\n"
        assert _is_primary_service_note(text) is False

    def test_empty_text(self):
        assert _is_primary_service_note("") is False

    def test_trauma_in_body_not_heading(self):
        """Trauma mentioned deep in note body doesn't trigger."""
        text = "A" * 600 + "\nTrauma H & P"
        assert _is_primary_service_note(text) is False


# ── _scan_timeline_for_consult_notes tests ─────────────────────────

class TestScanTimelineForConsultNotes:
    """Tests for timeline CONSULT_NOTE fallback scanner."""

    @staticmethod
    def _make_days_data(items_by_date):
        days = {}
        for date_key, items in items_by_date.items():
            days[date_key] = {"items": items}
        return {"days": days, "meta": {}}

    def test_single_consult_note(self):
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T08:30:00",
                "source_id": "42",
                "payload": {
                    "text": "Consult to Pulmonology [order 123]\nPatient seen."
                },
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 1
        assert entries[0]["service"] == "Pulmonology"
        assert entries[0]["date_raw"] == "01/01"
        assert entries[0]["time_raw"] == "0830"
        assert entries[0]["note_type"] == "Consults"
        assert len(entries[0]["raw_line_id"]) > 0

    def test_multiple_services_across_days(self):
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T06:00:00",
                "source_id": "10",
                "payload": {
                    "text": "Consult to Palliative Care [order 1]\nSeen."
                },
            }],
            "2026-01-02": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-02T14:30:00",
                "source_id": "20",
                "payload": {
                    "text": "Consult to Pulmonology [order 2]\nEvaluated."
                },
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 2
        services = {e["service"] for e in entries}
        assert "Palliative Care" in services
        assert "Pulmonology" in services

    def test_skips_primary_service_note(self):
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T10:00:00",
                "source_id": "99",
                "payload": {
                    "text": "Trauma H & P\n\nChief Complaint: MVC.\nPatient..."
                },
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 0

    def test_skips_excluded_service(self):
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T10:00:00",
                "source_id": "50",
                "payload": {
                    "text": "Consult to Hospitalist [order 5]\nAdmission."
                },
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 0

    def test_skips_non_consult_note_types(self):
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "PHYSICIAN_NOTE",
                "dt": "2026-01-01T10:00:00",
                "source_id": "60",
                "payload": {
                    "text": "Consult to Neurosurgery [order 8]\nSeen."
                },
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 0

    def test_empty_days(self):
        dd = {"days": {}, "meta": {}}
        entries = _scan_timeline_for_consult_notes(dd)
        assert entries == []

    def test_no_text_in_payload(self):
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T10:00:00",
                "source_id": "70",
                "payload": {"text": ""},
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 0

    def test_unextractable_service(self):
        """CONSULT_NOTE with no recognisable service pattern → skipped."""
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T10:00:00",
                "source_id": "80",
                "payload": {
                    "text": "Random clinical text without consult header."
                },
            }],
        })
        entries = _scan_timeline_for_consult_notes(dd)
        assert len(entries) == 0


# ── Fallback integration (extract_consultant_events) ───────────────

class TestExtractConsultantEventsFallback:
    """
    Full fallback path: note_index has no_notes_section,
    but timeline has CONSULT_NOTE items.
    """

    @staticmethod
    def _make_days_data(items_by_date):
        days = {}
        for date_key, items in items_by_date.items():
            days[date_key] = {"items": items}
        return {"days": days, "meta": {}}

    def test_fallback_discovers_services(self):
        features = {
            "note_index_events_v1": {
                "entries": [],
                "source_rule_id": "no_notes_section",
            }
        }
        dd = self._make_days_data({
            "2026-01-01": [
                {
                    "type": "CONSULT_NOTE",
                    "dt": "2026-01-01T06:00:00",
                    "source_id": "10",
                    "payload": {
                        "text": "Consult to Palliative Care [order 1]\nSeen."
                    },
                },
                {
                    "type": "CONSULT_NOTE",
                    "dt": "2026-01-01T14:00:00",
                    "source_id": "20",
                    "payload": {
                        "text": "Consult to Pulmonology [order 2]\nEval."
                    },
                },
            ],
        })
        result = extract_consultant_events(features, dd)
        assert result["consultant_present"] == "yes"
        assert result["source_rule_id"] == "consultant_events_from_timeline_items"
        assert result["consultant_services_count"] == 2
        svc_names = [s["service"] for s in result["consultant_services"]]
        assert "Palliative Care" in svc_names
        assert "Pulmonology" in svc_names

    def test_fallback_no_consult_notes_returns_dna(self):
        features = {
            "note_index_events_v1": {
                "entries": [],
                "source_rule_id": "no_notes_section",
            }
        }
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "PHYSICIAN_NOTE",
                "dt": "2026-01-01T08:00:00",
                "source_id": "30",
                "payload": {"text": "Radiology report."},
            }],
        })
        result = extract_consultant_events(features, dd)
        assert result["consultant_present"] == "DATA NOT AVAILABLE"
        assert result["source_rule_id"] == "no_note_index_available"

    def test_fallback_excludes_primary_note(self):
        features = {
            "note_index_events_v1": {
                "entries": [],
                "source_rule_id": "no_notes_section",
            }
        }
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T10:00:00",
                "source_id": "40",
                "payload": {
                    "text": "Trauma H & P\n\nChief Complaint: MVC.\nPatient..."
                },
            }],
        })
        result = extract_consultant_events(features, dd)
        assert result["consultant_present"] == "DATA NOT AVAILABLE"

    def test_fallback_evidence_has_raw_line_id(self):
        features = {
            "note_index_events_v1": {
                "entries": [],
                "source_rule_id": "no_notes_section",
            }
        }
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T08:30:00",
                "source_id": "50",
                "payload": {
                    "text": "Consult to Neurosurgery [order 9]\nSeen."
                },
            }],
        })
        result = extract_consultant_events(features, dd)
        assert result["consultant_present"] == "yes"
        for svc in result["consultant_services"]:
            for ev in svc["evidence"]:
                assert "raw_line_id" in ev
                assert len(ev["raw_line_id"]) > 0
                assert ev["role"] == "consultant_event"

    def test_fallback_determinism(self):
        features = {
            "note_index_events_v1": {
                "entries": [],
                "source_rule_id": "no_notes_section",
            }
        }
        dd = self._make_days_data({
            "2026-01-01": [
                {
                    "type": "CONSULT_NOTE",
                    "dt": "2026-01-01T06:00:00",
                    "source_id": "10",
                    "payload": {
                        "text": "Consult to Palliative Care [order 1]\nSeen."
                    },
                },
                {
                    "type": "CONSULT_NOTE",
                    "dt": "2026-01-01T14:00:00",
                    "source_id": "20",
                    "payload": {
                        "text": "Consult to Pulmonology [order 2]\nEval."
                    },
                },
            ],
        })
        r1 = extract_consultant_events(features, dd)
        r2 = extract_consultant_events(features, dd)
        assert r1 == r2

    def test_primary_path_unaffected(self):
        """When note_index has entries, fallback is NOT triggered."""
        features = {
            "note_index_events_v1": {
                "entries": [
                    _make_entry("Consults", "Orthopedics",
                                author_name="Doc A",
                                date_raw="01/01", time_raw="0930",
                                raw_line_id="x1"),
                ],
                "source_rule_id": "note_index_raw_file",
            }
        }
        dd = self._make_days_data({
            "2026-01-01": [{
                "type": "CONSULT_NOTE",
                "dt": "2026-01-01T09:30:00",
                "source_id": "1",
                "payload": {
                    "text": "Consult to Neurosurgery [order 9]\n"
                },
            }],
        })
        result = extract_consultant_events(features, dd)
        assert result["source_rule_id"] == "consultant_events_from_note_index"
        assert result["consultant_services_count"] == 1
        assert result["consultant_services"][0]["service"] == "Orthopedics"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])