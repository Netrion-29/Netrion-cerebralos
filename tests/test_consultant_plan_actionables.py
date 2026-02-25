#!/usr/bin/env python3
"""
Tests for consultant_plan_actionables_v1 feature extractor.

Covers:
  - Category mapping (direct item_type and keyword promotion)
  - Action text normalization
  - Deduplication
  - Evidence traceability
  - Fail-closed behaviour
  - Determinism
"""

import unittest

from cerebralos.features.consultant_plan_actionables_v1 import (
    _map_category,
    _normalize_action_text,
    extract_consultant_plan_actionables,
)


# ═══════════════════════════════════════════════════════════════════
#  Category mapping
# ═══════════════════════════════════════════════════════════════════


class TestMapCategory(unittest.TestCase):
    """Test _map_category deterministic category assignment."""

    # ── Direct item_type mapping ────────────────────────────────────

    def test_imaging_passthrough(self):
        self.assertEqual(_map_category("imaging", "Order TTE"), "imaging")

    def test_procedure_passthrough(self):
        self.assertEqual(_map_category("procedure", "ORIF right clavicle"), "procedure")

    def test_medication_passthrough(self):
        self.assertEqual(_map_category("medication", "Start Nimodipine"), "medication")

    def test_follow_up_passthrough(self):
        self.assertEqual(_map_category("follow-up", "Follow up in 2 weeks"), "follow_up")

    def test_activity_passthrough(self):
        self.assertEqual(_map_category("activity", "NWB on RUE"), "activity")

    def test_discharge_passthrough(self):
        self.assertEqual(_map_category("discharge", "Ok to d/c"), "discharge")

    # ── Keyword promotion from recommendation ──────────────────────

    def test_reco_to_brace(self):
        self.assertEqual(
            _map_category("recommendation", "Will plan to treat in a Jewett brace"),
            "brace_immobilization",
        )

    def test_reco_to_brace_sling(self):
        self.assertEqual(
            _map_category("recommendation", "Use sling for 6 weeks"),
            "brace_immobilization",
        )

    def test_reco_to_monitoring_labs(self):
        self.assertEqual(
            _map_category("recommendation", "Labs ordered: A1c, vitamin-D, TSH"),
            "monitoring_labs",
        )

    def test_reco_to_monitoring_telemetry(self):
        self.assertEqual(
            _map_category("recommendation", "Telemetry monitoring"),
            "monitoring_labs",
        )

    def test_reco_to_follow_up(self):
        self.assertEqual(
            _map_category("recommendation", "Does not require neurosurgical follow-up."),
            "follow_up",
        )

    def test_reco_to_medication(self):
        self.assertEqual(
            _map_category("recommendation", "Resume Wellbutrin"),
            "medication",
        )

    def test_reco_to_medication_continue(self):
        self.assertEqual(
            _map_category("recommendation", "on memantine, donepezil."),
            "medication",
        )

    def test_reco_to_imaging(self):
        self.assertEqual(
            _map_category("recommendation", "Repeat CT head in 6 hours"),
            "imaging",
        )

    def test_reco_to_procedure(self):
        self.assertEqual(
            _map_category("recommendation", "May need surgical repair"),
            "procedure",
        )

    def test_reco_to_activity(self):
        self.assertEqual(
            _map_category("recommendation", "Okay for activity, mobilize as tolerated"),
            "activity",
        )

    def test_reco_to_discharge(self):
        self.assertEqual(
            _map_category("recommendation", "Ok for disposition home"),
            "discharge",
        )

    def test_reco_stays_recommendation(self):
        self.assertEqual(
            _map_category("recommendation", "Subarachnoid hemorrhage management"),
            "recommendation",
        )

    def test_reco_stays_recommendation_generic(self):
        self.assertEqual(
            _map_category("recommendation", "Okay for diet."),
            "recommendation",
        )


# ═══════════════════════════════════════════════════════════════════
#  Action text normalization
# ═══════════════════════════════════════════════════════════════════


class TestNormalizeActionText(unittest.TestCase):
    """Test _normalize_action_text whitespace and length handling."""

    def test_basic_trim(self):
        self.assertEqual(
            _normalize_action_text("  Start medication  "),
            "Start medication",
        )

    def test_collapse_whitespace(self):
        self.assertEqual(
            _normalize_action_text("ICU   admission   for    monitoring"),
            "ICU admission for monitoring",
        )

    def test_truncation(self):
        long_text = "A" * 300
        result = _normalize_action_text(long_text)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 210)  # 200 + "..."

    def test_empty(self):
        self.assertEqual(_normalize_action_text(""), "")

    def test_normal_length(self):
        text = "Leave foam dressing in place for 5 days."
        self.assertEqual(_normalize_action_text(text), text)


# ═══════════════════════════════════════════════════════════════════
#  Full extraction (extract_consultant_plan_actionables)
# ═══════════════════════════════════════════════════════════════════


class TestExtractConsultantPlanActionables(unittest.TestCase):
    """Test the public extract_consultant_plan_actionables API."""

    def _make_plan_items(self, items=None, item_count=None,
                         source_rule_id="consultant_plan_from_note_text"):
        """Helper to build a mock consultant_plan_items_v1 dict."""
        if items is None:
            items = []
        if item_count is None:
            item_count = len(items)
        return {
            "items": items,
            "item_count": item_count,
            "services_with_plan_items": sorted(set(
                i.get("service", "") for i in items
            )),
            "source_rule_id": source_rule_id,
            "warnings": [],
            "notes": [],
        }

    def _make_item(self, service="Internal Medicine", ts="2026-01-01T05:53:00",
                    author_name="Duran, Adriano M", item_text="ICU admission",
                    item_type="recommendation", raw_line_id="abc123"):
        return {
            "service": service,
            "ts": ts,
            "author_name": author_name,
            "item_text": item_text,
            "item_type": item_type,
            "evidence": [
                {
                    "role": "consultant_plan_item",
                    "snippet": f"[{service}] {item_type}:: {item_text[:40]}",
                    "raw_line_id": raw_line_id,
                }
            ],
        }

    def test_no_plan_items_feature(self):
        """Missing consultant_plan_items_v1 → fail closed."""
        result = extract_consultant_plan_actionables({})
        self.assertEqual(result["actionable_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_plan_items")
        self.assertEqual(result["actionables"], [])

    def test_empty_plan_items(self):
        """consultant_plan_items_v1 with 0 items → fail closed."""
        features = {
            "consultant_plan_items_v1": self._make_plan_items(
                items=[], source_rule_id="no_plan_sections_found"
            ),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_plan_items")

    def test_single_medication_item(self):
        """Single medication plan item → one medication actionable."""
        items = [self._make_item(
            item_text="Start Nimodipine",
            item_type="medication",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 1)
        self.assertEqual(result["source_rule_id"],
                         "consultant_actionables_from_plan_items")
        act = result["actionables"][0]
        self.assertEqual(act["category"], "medication")
        self.assertEqual(act["action_text"], "Start Nimodipine")
        self.assertEqual(act["source_item_type"], "medication")
        self.assertEqual(act["service"], "Internal Medicine")

    def test_recommendation_promoted_to_monitoring(self):
        """Recommendation with labs keywords → monitoring_labs."""
        items = [self._make_item(
            item_text="Labs ordered: A1c, vitamin-D, lipid profile",
            item_type="recommendation",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 1)
        self.assertEqual(result["actionables"][0]["category"], "monitoring_labs")
        self.assertEqual(result["actionables"][0]["source_item_type"],
                         "recommendation")

    def test_recommendation_stays_recommendation(self):
        """Recommendation without specific keywords stays as-is."""
        items = [self._make_item(
            item_text="Subarachnoid hemorrhage",
            item_type="recommendation",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 1)
        self.assertEqual(result["actionables"][0]["category"], "recommendation")

    def test_brace_immobilization(self):
        """Recommendation with brace/sling → brace_immobilization."""
        items = [self._make_item(
            item_text="Will plan to treat in a Jewett brace",
            item_type="recommendation",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionables"][0]["category"],
                         "brace_immobilization")

    def test_multiple_services(self):
        """Items from multiple services."""
        items = [
            self._make_item(
                service="Orthopedics",
                item_text="NWB on RUE",
                item_type="activity",
                raw_line_id="aaa",
            ),
            self._make_item(
                service="Wound/Ostomy",
                item_text="Leave foam dressing in place for 5 days.",
                item_type="recommendation",
                raw_line_id="bbb",
            ),
        ]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 2)
        self.assertIn("Orthopedics", result["services_with_actionables"])
        self.assertIn("Wound/Ostomy", result["services_with_actionables"])

    def test_category_counts(self):
        """Category counts are correctly computed."""
        items = [
            self._make_item(item_text="Start Nimodipine", item_type="medication", raw_line_id="a1"),
            self._make_item(item_text="Order TTE", item_type="imaging", raw_line_id="a2"),
            self._make_item(item_text="Resume Wellbutrin", item_type="medication", raw_line_id="a3"),
        ]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["category_counts"]["medication"], 2)
        self.assertEqual(result["category_counts"]["imaging"], 1)

    def test_deduplication(self):
        """Duplicate (service, category, action_text) are deduplicated."""
        items = [
            self._make_item(
                item_text="ICU admission",
                item_type="recommendation",
                raw_line_id="a1",
                ts="2026-01-01T05:53:00",
            ),
            self._make_item(
                item_text="ICU admission",
                item_type="recommendation",
                raw_line_id="a2",
                ts="2026-01-02T05:53:00",
            ),
        ]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 1)
        self.assertTrue(len(result["warnings"]) > 0)

    def test_evidence_passthrough(self):
        """Evidence raw_line_id is passed through from source items."""
        items = [self._make_item(
            item_text="Start Nimodipine",
            item_type="medication",
            raw_line_id="my_original_id_123",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        act = result["actionables"][0]
        self.assertEqual(len(act["evidence"]), 1)
        self.assertEqual(act["evidence"][0]["role"],
                         "consultant_plan_actionable")
        self.assertEqual(act["evidence"][0]["raw_line_id"],
                         "my_original_id_123")

    def test_determinism(self):
        """Same input produces identical output on repeated runs."""
        items = [
            self._make_item(item_text="Start Nimodipine", item_type="medication", raw_line_id="a1"),
            self._make_item(item_text="Order TTE", item_type="imaging", raw_line_id="a2"),
            self._make_item(item_text="Follow up in 2 weeks", item_type="follow-up", raw_line_id="a3"),
        ]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        r1 = extract_consultant_plan_actionables(features)
        r2 = extract_consultant_plan_actionables(features)
        self.assertEqual(r1, r2)

    def test_follow_up_underscore(self):
        """follow-up item_type becomes follow_up category (hyphen → underscore)."""
        items = [self._make_item(
            item_text="Follow up in 2 weeks",
            item_type="follow-up",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionables"][0]["category"], "follow_up")

    def test_author_name_preserved(self):
        """author_name is passed through to actionables."""
        items = [self._make_item(
            author_name="Chacko, Chris E",
            item_text="Nasal fracture management",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionables"][0]["author_name"], "Chacko, Chris E")

    def test_ts_preserved(self):
        """ts is passed through to actionables."""
        items = [self._make_item(
            ts="2026-01-03T14:26:00",
            item_text="ICU admission",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionables"][0]["ts"], "2026-01-03T14:26:00")

    def test_source_item_type_preserved(self):
        """source_item_type reflects the original plan item type."""
        items = [self._make_item(
            item_text="Start Nimodipine",
            item_type="medication",
        )]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionables"][0]["source_item_type"], "medication")

    def test_empty_item_text_skipped(self):
        """Items with empty item_text are skipped."""
        items = [self._make_item(item_text="", item_type="recommendation")]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items, item_count=1),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 0)
        self.assertEqual(result["source_rule_id"], "no_actionables_extracted")

    def test_mixed_categories_full(self):
        """Full mix of categories from a realistic consultant plan."""
        items = [
            self._make_item(item_text="ICU admission", item_type="recommendation", raw_line_id="r1"),
            self._make_item(item_text="Start Nimodipine", item_type="medication", raw_line_id="r2"),
            self._make_item(item_text="Order TTE", item_type="imaging", raw_line_id="r3"),
            self._make_item(item_text="ENT consult per primary", item_type="recommendation", raw_line_id="r4"),
            self._make_item(item_text="Labs ordered: A1c, vitamin-D", item_type="recommendation", raw_line_id="r5"),
            self._make_item(item_text="Telemetry monitoring", item_type="recommendation", raw_line_id="r6"),
            self._make_item(item_text="May be WBAT on LLE with walker", item_type="activity", raw_line_id="r7"),
            self._make_item(
                service="Neurosurgery",
                item_text="Ok to d/c from a neurosurgery standpoint",
                item_type="discharge",
                raw_line_id="r8",
            ),
        ]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(result["actionable_count"], 8)
        cats = [a["category"] for a in result["actionables"]]
        self.assertIn("medication", cats)
        self.assertIn("imaging", cats)
        self.assertIn("monitoring_labs", cats)
        self.assertIn("activity", cats)
        self.assertIn("discharge", cats)
        self.assertIn("recommendation", cats)

    def test_services_with_actionables_sorted(self):
        """services_with_actionables is sorted alphabetically."""
        items = [
            self._make_item(service="Wound/Ostomy", item_text="Leave dressing", raw_line_id="a1"),
            self._make_item(service="Orthopedics", item_text="NWB on RUE", item_type="activity", raw_line_id="a2"),
            self._make_item(service="Internal Medicine", item_text="ICU admission", raw_line_id="a3"),
        ]
        features = {
            "consultant_plan_items_v1": self._make_plan_items(items=items),
        }
        result = extract_consultant_plan_actionables(features)
        self.assertEqual(
            result["services_with_actionables"],
            ["Internal Medicine", "Orthopedics", "Wound/Ostomy"],
        )


if __name__ == "__main__":
    unittest.main()
