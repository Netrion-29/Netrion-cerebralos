#!/usr/bin/env python3
"""
Tests for NURSING_ORDER spine clearance supplemental ingest handler.

Validates that the ingest parser correctly detects and emits evidence items
for spine clearance order detail pages in the supplemental zone of DoS-format
patient files.
"""

import textwrap
import unittest

from cerebralos.ingest.parse_patient_txt import _parse_supplemental_dos


def _make_lines(text: str) -> list:
    """Convert indented text block to list of lines."""
    return textwrap.dedent(text).strip().split("\n")


class TestSpineClearanceOrderIngest(unittest.TestCase):
    """Test NURSING_ORDER evidence item emission for spine clearance orders."""

    def _run_supp(self, raw_text: str, arrival_dt_str=None):
        lines = _make_lines(raw_text)
        return _parse_supplemental_dos(
            lines, last_dos_idx=-1, arrival_dt_str=arrival_dt_str,
        )

    def test_inline_spine_clearance_captured(self):
        """Inline 'Spine Clearance Cervical Spine Clearance: Yes; ...' emits NURSING_ORDER."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: Yes [NUR1015] (Order 467162498)
        Nursing
        Discontinued
        Date: 1/5/2026\tDepartment: Surgical Trauma Cardiovascular ICU
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 1)
        item = nursing_orders[0]
        self.assertIn("Cervical Spine Clearance: Yes", item.text)
        self.assertIn("Thoracic/Spine Lumbar Clearance: Yes", item.text)

    def test_inline_spine_clearance_mixed_answers(self):
        """Inline with mixed answers (C=Yes, TL=No) captured correctly."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: No [NUR1015] (Order 466671395)
        Nursing
        Discontinued
        Date: 1/1/2026\tDepartment: Surgical Trauma Cardiovascular ICU
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 1)
        self.assertIn("Clearance: No", nursing_orders[0].text)

    def test_timestamp_from_ordered_on(self):
        """Timestamp extracted from 'Ordered On' line (military HHMM)."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: Yes [NUR1015] (Order 467162498)
        Nursing
        Discontinued
        Date: 1/5/2026\tDepartment: Surgical Trauma Cardiovascular ICU

        Patient Demographics

        Patient Name
        Bittner, Ronald E

        Original Order

        Ordered On\tOrdered By
        1/5/2026 0835\tChavez, Adriana E, RN

        Order Questions

        Question\tAnswer
        Cervical Spine Clearance\tYes
        Thoracic/Spine Lumbar Clearance\tYes

        Requisition

        Print Order Requisition
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 1)
        item = nursing_orders[0]
        # Should extract "1/5/2026 0835" → "2026-01-05 08:35:00"
        self.assertIsNotNone(item.datetime)
        self.assertIn("2026-01-05", item.datetime)
        self.assertIn("08:35", item.datetime)

    def test_timestamp_fallback_to_date_field(self):
        """When no 'Ordered On', timestamp falls back to Date: field."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: No [NUR1015] (Order 466671395)
        Nursing
        Discontinued
        Date: 1/1/2026\tDepartment: Surgical Trauma Cardiovascular ICU
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 1)
        item = nursing_orders[0]
        self.assertIsNotNone(item.datetime)
        self.assertIn("2026-01-01", item.datetime)

    def test_two_spine_clearance_orders(self):
        """Two inline spine clearance lines produce two NURSING_ORDER items."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: No [NUR1015] (Order 466671395)
        Nursing
        Discontinued
        Date: 1/1/2026\tDepartment: Surgical Trauma Cardiovascular ICU

        Original Order

        Ordered On\tOrdered By
        1/1/2026 0237\tMeehan, Sarah M, NP

        Order Questions

        Question\tAnswer
        Cervical Spine Clearance\tYes
        Thoracic/Spine Lumbar Clearance\tNo

        Requisition

        Print Order Requisition

        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: Yes [NUR1015] (Order 467162498)
        Nursing
        Discontinued
        Date: 1/5/2026\tDepartment: Surgical Trauma Cardiovascular ICU

        Original Order

        Ordered On\tOrdered By
        1/5/2026 0835\tChavez, Adriana E, RN

        Order Questions

        Question\tAnswer
        Cervical Spine Clearance\tYes
        Thoracic/Spine Lumbar Clearance\tYes

        Requisition

        Print Order Requisition
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 2)
        # First order: C=Yes, TL=No
        self.assertIn("Clearance: No", nursing_orders[0].text)
        # Second order: C=Yes, TL=Yes
        self.assertIn("Thoracic/Spine Lumbar Clearance: Yes", nursing_orders[1].text)

    def test_no_spine_clearance_no_nursing_order(self):
        """Non-spine-clearance order detail pages don't emit NURSING_ORDER."""
        raw = """\
        IP Consult To Case Management/Social Work Eval and Discharge Needs [CON101] (Order 466671396)
        Consult
        Date: 1/1/2026\tDepartment: Surgical Trauma Cardiovascular ICU

        Order Questions

        Question\tAnswer
        Some Other Question\tYes
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 0)

    def test_order_questions_block_included_in_text(self):
        """The emitted text includes the Order Questions block for downstream parsing."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: Yes [NUR1015] (Order 467162498)
        Nursing
        Discontinued
        Date: 1/5/2026\tDepartment: Surgical Trauma Cardiovascular ICU

        Original Order

        Ordered On\tOrdered By
        1/5/2026 0835\tChavez, Adriana E, RN

        Order Questions

        Question\tAnswer
        Cervical Spine Clearance\tYes
        Thoracic/Spine Lumbar Clearance\tYes

        Requisition

        Print Order Requisition
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 1)
        text = nursing_orders[0].text
        # Must contain Order Questions block for structured parsing
        self.assertIn("Order Questions", text)
        self.assertIn("Cervical Spine Clearance", text)

    def test_ts_missing_warning_when_no_timestamp(self):
        """If no timestamp can be extracted, ts_missing warning is set."""
        raw = """\
        Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: Yes [NUR1015] (Order 467162498)
        Some unrelated text follows
        No date or ordered-on info here
        """
        items = self._run_supp(raw)
        nursing_orders = [it for it in items if it.kind == "NURSING_ORDER"]
        self.assertEqual(len(nursing_orders), 1)
        self.assertIn("ts_missing", nursing_orders[0].warnings)


if __name__ == "__main__":
    unittest.main()
