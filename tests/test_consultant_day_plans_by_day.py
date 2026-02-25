#!/usr/bin/env python3
"""
Tests for consultant_day_plans_by_day_v1 extractor and v5 integration.

Covers:
  - Per-day grouping from consultant_plan_items_v1
  - Per-service sub-grouping within days
  - Determinism (same input → same output)
  - Fail-closed behaviour (missing upstream features)
  - Evidence traceability
  - v5 rendering integration
"""

import unittest

from cerebralos.features.consultant_day_plans_by_day_v1 import (
    extract_consultant_day_plans_by_day,
)
from cerebralos.reporting.render_trauma_daily_notes_v5 import (
    _render_consultant_day_plans,
)


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def _make_plan_item(service, ts, author, text, item_type="recommendation"):
    """Helper to create a consultant_plan_items_v1-style item."""
    return {
        "service": service,
        "ts": ts,
        "author_name": author,
        "item_text": text,
        "item_type": item_type,
        "evidence": [
            {
                "role": "consultant_plan_item",
                "snippet": f"[{service}] {text[:40]}",
                "raw_line_id": "abc123",
            }
        ],
    }


def _features_with_consultants(items, services=None):
    """Build a features dict with consultant_events_v1 and consultant_plan_items_v1."""
    if services is None:
        # Derive from items
        seen = set()
        svcs = []
        for it in items:
            s = it.get("service", "")
            if s and s not in seen:
                seen.add(s)
                svcs.append({
                    "service": s,
                    "first_ts": it.get("ts", ""),
                    "last_ts": it.get("ts", ""),
                    "note_count": 1,
                    "authors": [it.get("author_name", "")],
                    "note_types": ["Consults"],
                    "evidence": [],
                })
        services = svcs
    return {
        "consultant_events_v1": {
            "consultant_present": "yes",
            "consultant_services_count": len(services),
            "consultant_services": services,
            "source_rule_id": "consultant_events_from_note_index",
            "warnings": [],
            "notes": [],
        },
        "consultant_plan_items_v1": {
            "items": items,
            "item_count": len(items),
            "services_with_plan_items": sorted({i["service"] for i in items}),
            "source_rule_id": "consultant_plan_from_note_text",
            "warnings": [],
            "notes": [],
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  Extractor tests
# ═══════════════════════════════════════════════════════════════════

class TestConsultantDayPlanExtractor(unittest.TestCase):
    """Core extractor tests."""

    # ── Happy path: single day, single service ─────────────────────

    def test_single_day_single_service(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "NWB on RUE", "activity"),
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "Repeat CT in 2 weeks", "imaging"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        self.assertEqual(result["source_rule_id"], "consultant_day_plans_from_plan_items")
        self.assertEqual(result["total_days"], 1)
        self.assertEqual(result["total_items"], 2)
        self.assertEqual(result["total_services"], 1)
        self.assertIn("Orthopedics", result["services_seen"])
        self.assertIn("2026-01-01", result["days"])
        day = result["days"]["2026-01-01"]
        self.assertEqual(day["service_count"], 1)
        self.assertEqual(day["item_count"], 2)
        svc = day["services"]["Orthopedics"]
        self.assertEqual(svc["item_count"], 2)
        self.assertEqual(svc["authors"], ["Smith, John"])
        self.assertEqual(svc["items"][0]["item_text"], "NWB on RUE")
        self.assertEqual(svc["items"][1]["item_text"], "Repeat CT in 2 weeks")

    # ── Multi-day, multi-service ───────────────────────────────────

    def test_multi_day_multi_service(self):
        items = [
            _make_plan_item("Pulmonology", "2026-01-01T04:14:00", "Moore, Branden",
                            "Continue vent support", "recommendation"),
            _make_plan_item("Palliative Care", "2026-01-01T12:30:00", "Jones, Alice",
                            "Goals of care discussed", "recommendation"),
            _make_plan_item("Pulmonology", "2026-01-02T06:00:00", "Moore, Branden",
                            "Wean FiO2", "recommendation"),
            _make_plan_item("Neurosurgery", "2026-01-02T10:00:00", "Lee, David",
                            "Repeat CT head", "imaging"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        self.assertEqual(result["total_days"], 2)
        self.assertEqual(result["total_items"], 4)
        self.assertEqual(result["total_services"], 3)

        # Day 1
        d1 = result["days"]["2026-01-01"]
        self.assertEqual(d1["service_count"], 2)
        self.assertEqual(d1["item_count"], 2)
        self.assertIn("Pulmonology", d1["services"])
        self.assertIn("Palliative Care", d1["services"])

        # Day 2
        d2 = result["days"]["2026-01-02"]
        self.assertEqual(d2["service_count"], 2)
        self.assertEqual(d2["item_count"], 2)
        self.assertIn("Pulmonology", d2["services"])
        self.assertIn("Neurosurgery", d2["services"])

    # ── Items sorted by ts within service ──────────────────────────

    def test_items_sorted_by_ts(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T14:00:00", "Smith, John",
                            "Second item", "recommendation"),
            _make_plan_item("Orthopedics", "2026-01-01T08:00:00", "Smith, John",
                            "First item", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        svc = result["days"]["2026-01-01"]["services"]["Orthopedics"]
        self.assertEqual(svc["items"][0]["item_text"], "First item")
        self.assertEqual(svc["items"][1]["item_text"], "Second item")

    # ── Multiple authors per service ───────────────────────────────

    def test_multiple_authors_preserved(self):
        items = [
            _make_plan_item("Neurosurgery", "2026-01-01T08:00:00", "Lee, David",
                            "Item A", "recommendation"),
            _make_plan_item("Neurosurgery", "2026-01-01T10:00:00", "Park, Sarah",
                            "Item B", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        svc = result["days"]["2026-01-01"]["services"]["Neurosurgery"]
        self.assertEqual(svc["authors"], ["Lee, David", "Park, Sarah"])

    # ── Evidence preserved ─────────────────────────────────────────

    def test_evidence_passthrough(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "NWB on RUE", "activity"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        svc = result["days"]["2026-01-01"]["services"]["Orthopedics"]
        self.assertEqual(len(svc["items"][0]["evidence"]), 1)
        self.assertEqual(svc["items"][0]["evidence"][0]["role"], "consultant_plan_item")

    # ── item_type preserved ────────────────────────────────────────

    def test_item_type_preserved(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "NWB on RUE", "activity"),
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "Repeat CT in 2 weeks", "imaging"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        svc = result["days"]["2026-01-01"]["services"]["Orthopedics"]
        self.assertEqual(svc["items"][0]["item_type"], "activity")
        self.assertEqual(svc["items"][1]["item_type"], "imaging")


# ═══════════════════════════════════════════════════════════════════
#  Fail-closed tests
# ═══════════════════════════════════════════════════════════════════

class TestConsultantDayPlanFailClosed(unittest.TestCase):
    """Fail-closed paths."""

    def test_no_consultant_events(self):
        """No consultant_events_v1 at all."""
        result = extract_consultant_day_plans_by_day({})
        self.assertEqual(result["source_rule_id"], "no_consultant_events")
        self.assertEqual(result["total_days"], 0)
        self.assertEqual(result["total_items"], 0)
        self.assertEqual(result["days"], {})

    def test_consultant_present_no(self):
        """consultant_present == 'no'."""
        feats = {
            "consultant_events_v1": {
                "consultant_present": "no",
                "consultant_services_count": 0,
                "consultant_services": [],
                "source_rule_id": "no_consultant_entries",
                "warnings": [],
                "notes": [],
            },
            "consultant_plan_items_v1": {
                "items": [],
                "item_count": 0,
                "services_with_plan_items": [],
                "source_rule_id": "no_consultant_events",
                "warnings": [],
                "notes": [],
            },
        }
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(result["source_rule_id"], "no_consultant_events")
        self.assertEqual(result["total_days"], 0)

    def test_consultant_present_dna(self):
        """consultant_present == 'DATA NOT AVAILABLE'."""
        feats = {
            "consultant_events_v1": {
                "consultant_present": "DATA NOT AVAILABLE",
                "consultant_services_count": 0,
                "consultant_services": [],
                "source_rule_id": "no_note_index_available",
                "warnings": [],
                "notes": [],
            },
        }
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(result["source_rule_id"], "no_consultant_events")

    def test_consultants_present_but_no_plan_items(self):
        """Consultant events exist but plan_items is empty."""
        feats = {
            "consultant_events_v1": {
                "consultant_present": "yes",
                "consultant_services_count": 1,
                "consultant_services": [
                    {"service": "ENT", "first_ts": "01/01 1000",
                     "last_ts": "01/01 1000", "note_count": 1,
                     "authors": ["Doc, A"], "note_types": ["Consults"],
                     "evidence": []}
                ],
                "source_rule_id": "consultant_events_from_note_index",
                "warnings": [],
                "notes": [],
            },
            "consultant_plan_items_v1": {
                "items": [],
                "item_count": 0,
                "services_with_plan_items": [],
                "source_rule_id": "no_plan_sections_found",
                "warnings": [],
                "notes": [],
            },
        }
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(result["source_rule_id"], "no_plan_items")
        self.assertEqual(result["total_days"], 0)

    def test_item_with_missing_ts_warns(self):
        """Items without valid ts should emit warning and be skipped."""
        items = [
            _make_plan_item("Orthopedics", "", "Smith, John",
                            "Bad item", "recommendation"),
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "Good item", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)

        self.assertEqual(result["total_items"], 1)
        self.assertTrue(len(result["warnings"]) > 0)
        self.assertIn("missing valid ts", result["warnings"][0])


# ═══════════════════════════════════════════════════════════════════
#  Determinism tests
# ═══════════════════════════════════════════════════════════════════

class TestConsultantDayPlanDeterminism(unittest.TestCase):
    """Verify same input → identical output."""

    def test_deterministic_output(self):
        items = [
            _make_plan_item("Pulmonology", "2026-01-01T04:14:00", "Moore, B",
                            "Continue vent", "recommendation"),
            _make_plan_item("Palliative Care", "2026-01-01T12:30:00", "Jones, A",
                            "Goals discussed", "recommendation"),
            _make_plan_item("Neurosurgery", "2026-01-02T10:00:00", "Lee, D",
                            "Repeat CT head", "imaging"),
        ]
        feats = _features_with_consultants(items)
        r1 = extract_consultant_day_plans_by_day(feats)
        r2 = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(r1, r2)

    def test_services_sorted_alphabetically(self):
        """services_seen list is sorted."""
        items = [
            _make_plan_item("Neurosurgery", "2026-01-01T10:00:00", "Lee, D",
                            "Item A", "recommendation"),
            _make_plan_item("ENT", "2026-01-01T11:00:00", "Doc, B",
                            "Item B", "recommendation"),
            _make_plan_item("Orthopedics", "2026-01-01T12:00:00", "Smith, J",
                            "Item C", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(result["services_seen"],
                         ["ENT", "Neurosurgery", "Orthopedics"])

    def test_days_sorted_chronologically(self):
        """days keys are sorted by date."""
        items = [
            _make_plan_item("Orthopedics", "2026-01-03T09:00:00", "Smith, J",
                            "Day 3 item", "recommendation"),
            _make_plan_item("Orthopedics", "2026-01-01T09:00:00", "Smith, J",
                            "Day 1 item", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(list(result["days"].keys()),
                         ["2026-01-01", "2026-01-03"])


# ═══════════════════════════════════════════════════════════════════
#  v5 Rendering tests
# ═══════════════════════════════════════════════════════════════════

class TestConsultantDayPlanV5Render(unittest.TestCase):
    """Test the v5 _render_consultant_day_plans function."""

    def test_renders_single_service(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "NWB on RUE", "activity"),
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "Repeat CT in 2 weeks", "imaging"),
        ]
        feats = _features_with_consultants(items)
        feats["consultant_day_plans_by_day_v1"] = extract_consultant_day_plans_by_day(feats)

        lines = _render_consultant_day_plans(feats, "2026-01-01")
        text = "\n".join(lines)

        self.assertIn("Consultant Day Plans:", text)
        self.assertIn("[Orthopedics]", text)
        self.assertIn("Smith, John", text)
        self.assertIn("(activity) NWB on RUE", text)
        self.assertIn("(imaging) Repeat CT in 2 weeks", text)

    def test_renders_multi_service(self):
        items = [
            _make_plan_item("Pulmonology", "2026-01-01T04:14:00", "Moore, B",
                            "Continue vent support", "recommendation"),
            _make_plan_item("Palliative Care", "2026-01-01T12:30:00", "Jones, A",
                            "Goals discussed", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        feats["consultant_day_plans_by_day_v1"] = extract_consultant_day_plans_by_day(feats)

        lines = _render_consultant_day_plans(feats, "2026-01-01")
        text = "\n".join(lines)

        self.assertIn("[Palliative Care]", text)
        self.assertIn("[Pulmonology]", text)

    def test_renders_empty_for_no_data_day(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            "NWB on RUE", "activity"),
        ]
        feats = _features_with_consultants(items)
        feats["consultant_day_plans_by_day_v1"] = extract_consultant_day_plans_by_day(feats)

        # Render for a day that has no data
        lines = _render_consultant_day_plans(feats, "2026-01-05")
        self.assertEqual(lines, [])

    def test_renders_empty_for_missing_feature(self):
        lines = _render_consultant_day_plans({}, "2026-01-01")
        self.assertEqual(lines, [])

    def test_renders_empty_for_no_consultant_events(self):
        feats = {"consultant_day_plans_by_day_v1": {
            "days": {},
            "source_rule_id": "no_consultant_events",
        }}
        lines = _render_consultant_day_plans(feats, "2026-01-01")
        self.assertEqual(lines, [])

    def test_item_count_shown(self):
        items = [
            _make_plan_item("Orthopedics", "2026-01-01T09:30:00", "Smith, John",
                            f"Item {i}", "recommendation")
            for i in range(5)
        ]
        feats = _features_with_consultants(items)
        feats["consultant_day_plans_by_day_v1"] = extract_consultant_day_plans_by_day(feats)

        lines = _render_consultant_day_plans(feats, "2026-01-01")
        text = "\n".join(lines)
        self.assertIn("(5 items)", text)


# ═══════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestConsultantDayPlanEdgeCases(unittest.TestCase):
    """Edge cases and boundary tests."""

    def test_unknown_service_name(self):
        """Items with service='UNKNOWN' are still grouped."""
        items = [
            _make_plan_item("UNKNOWN", "2026-01-01T09:30:00", "Smith, John",
                            "Some item", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)
        self.assertIn("UNKNOWN", result["days"]["2026-01-01"]["services"])

    def test_single_item_single_day(self):
        """Minimal case: one item, one day."""
        items = [
            _make_plan_item("ENT", "2026-01-05T14:00:00", "Chacko, Chris",
                            "No surgical intervention needed", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(result["total_days"], 1)
        self.assertEqual(result["total_items"], 1)
        self.assertEqual(result["total_services"], 1)

    def test_many_items_per_service(self):
        """Many items from one service on one day."""
        items = [
            _make_plan_item("Pulmonology", f"2026-01-01T{h:02d}:00:00", "Moore, B",
                            f"Item {i}", "recommendation")
            for i, h in enumerate(range(4, 20))
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)
        svc = result["days"]["2026-01-01"]["services"]["Pulmonology"]
        self.assertEqual(svc["item_count"], 16)

    def test_dna_author_not_in_authors_list(self):
        """DATA NOT AVAILABLE author is excluded from authors list."""
        items = [
            _make_plan_item("ENT", "2026-01-01T09:00:00",
                            "DATA NOT AVAILABLE", "Some item", "recommendation"),
        ]
        feats = _features_with_consultants(items)
        result = extract_consultant_day_plans_by_day(feats)
        svc = result["days"]["2026-01-01"]["services"]["ENT"]
        self.assertEqual(svc["authors"], [])

    def test_empty_items_list_with_consultant_present(self):
        """consultant_present=yes but items=[] should return no_plan_items."""
        feats = {
            "consultant_events_v1": {
                "consultant_present": "yes",
                "consultant_services_count": 1,
                "consultant_services": [],
                "source_rule_id": "consultant_events_from_note_index",
                "warnings": [],
                "notes": [],
            },
            "consultant_plan_items_v1": {
                "items": [],
                "item_count": 0,
                "services_with_plan_items": [],
                "source_rule_id": "no_plan_sections_found",
                "warnings": [],
                "notes": [],
            },
        }
        result = extract_consultant_day_plans_by_day(feats)
        self.assertEqual(result["source_rule_id"], "no_plan_items")


if __name__ == "__main__":
    unittest.main()
