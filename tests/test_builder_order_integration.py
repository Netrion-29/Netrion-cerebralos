"""
Builder-level integration test: order-dependent feature assembly.

Exercises the order-sensitive dependency edges in build_patient_features_v1
with a single synthetic patient to catch ordering regressions:

  vitals_canonical_v1 ──┬──► shock_trigger_v1
  base_deficit_monitoring_v1 ──┘
  vitals_canonical_v1 ──────► hemodynamic_instability_pattern_v1
  note_index_events_v1 ──► consultant_events_v1
                              ──► consultant_plan_items_v1
                                   ──► consultant_plan_actionables_v1

If any of these edges are reordered (e.g. shock_trigger computed before
base_deficit_monitoring is in the features dict), the downstream module
receives empty/missing data and the assertions below will fail.
"""

import pytest

from cerebralos.features.build_patient_features_v1 import build_patient_features


# ── Synthetic patient fixture ────────────────────────────────────────

# Arrival day with:
#   - TRAUMA_HP: SBP 82 (< 90 → shock), HR 128 (> 120 → tachycardia)
#   - LAB: base deficit 8.2 (> 6 → BD shock trigger)
#   - CONSULT_NOTE: Orthopedic Surgery with plan section
_ARRIVAL_DAY = "2026-01-15"
_ARRIVAL_TS = "2026-01-15 14:30:00"

_TRAUMA_HP_ITEM = {
    "type": "TRAUMA_HP",
    "dt": f"{_ARRIVAL_DAY}T14:40:00",
    "source_id": "SRC_INTEG_001",
    "time_missing": False,
    "payload": {
        "text": (
            "Vitals: Blood pressure 82/54, pulse 128, "
            "temperature 98.6 °F (37.0 °C), "
            "resp. rate 22, SpO2 94%."
        ),
    },
}

_LAB_ITEM = {
    "type": "LAB",
    "dt": f"{_ARRIVAL_DAY}T14:45:00",
    "source_id": "SRC_INTEG_002",
    "time_missing": False,
    "payload": {
        "text": (
            "ABG (Arterial)\n"
            "  Base Deficit        8.2        mEq/L     (-2.0 - 2.0)  01/15/2026 14:45\n"
        ),
    },
}

_CONSULT_NOTE_ITEM = {
    "type": "CONSULT_NOTE",
    "dt": f"{_ARRIVAL_DAY}T16:20:00",
    "source_id": "SRC_INTEG_003",
    "time_missing": False,
    "payload": {
        "text": (
            "Orthopedic Surgery Consult Note\n"
            "\n"
            "Consult To Orthopedic Surgery [ORD-12345]\n"
            "\n"
            "Reason for Consult: Right tibial plateau fracture\n"
            "\n"
            "Assessment and Plan:\n"
            "- ORIF right tibial plateau fracture when hemodynamically stable\n"
            "- NWB right lower extremity\n"
            "- Follow up in orthopedic clinic in 2 weeks\n"
            "- Continue DVT prophylaxis per trauma protocol\n"
        ),
    },
}

_DAYS_DATA = {
    "meta": {
        "arrival_datetime": _ARRIVAL_TS,
        "patient_id": "TEST_BUILDER_ORDER",
    },
    "days": {
        _ARRIVAL_DAY: {
            "items": [_TRAUMA_HP_ITEM, _LAB_ITEM, _CONSULT_NOTE_ITEM],
        },
    },
}


# ── The integration test ─────────────────────────────────────────────

class TestBuilderOrderDependentAssembly:
    """
    Single end-to-end build from synthetic input, asserting all seven
    order-dependent feature outputs across the dependency graph.
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the full builder once for the class."""
        return build_patient_features(_DAYS_DATA)

    @pytest.fixture(scope="class")
    def features(self, result):
        return result["features"]

    # ── Edge 1: vitals_canonical_v1 must be populated ────────────

    def test_vitals_canonical_present(self, features):
        vc = features.get("vitals_canonical_v1")
        assert vc is not None, "vitals_canonical_v1 missing from features"
        assert "arrival_vitals" in vc
        assert "days" in vc

    def test_arrival_vitals_sbp_captured(self, features):
        av = features["vitals_canonical_v1"]["arrival_vitals"]
        assert av["status"] == "selected", (
            f"arrival_vitals status={av.get('status')}; expected 'selected'"
        )
        assert av["sbp"] == 82.0, f"SBP={av.get('sbp')}; expected 82.0"

    # ── Edge 2: base_deficit_monitoring_v1 must be populated ─────

    def test_base_deficit_monitoring_present(self, features):
        bd = features.get("base_deficit_monitoring_v1")
        assert bd is not None, "base_deficit_monitoring_v1 missing from features"

    # ── Edge 3: shock_trigger_v1 depends on edges 1+2 ───────────

    def test_shock_trigger_present(self, features):
        st = features.get("shock_trigger_v1")
        assert st is not None, "shock_trigger_v1 missing from features"

    def test_shock_triggered_yes(self, features):
        st = features["shock_trigger_v1"]
        assert st["shock_triggered"] == "yes", (
            f"shock_triggered={st.get('shock_triggered')}; "
            "expected 'yes' (SBP 82 < 90 threshold)"
        )

    def test_shock_trigger_vitals_sbp(self, features):
        """shock_trigger must have consumed arrival vitals SBP."""
        tv = features["shock_trigger_v1"].get("trigger_vitals") or {}
        assert tv.get("sbp") == 82.0, (
            f"trigger_vitals.sbp={tv.get('sbp')}; expected 82.0 from arrival vitals"
        )

    def test_shock_trigger_consumed_bd(self, features):
        """shock_trigger must have consumed BD from base_deficit_monitoring_v1."""
        st = features["shock_trigger_v1"]
        tv = st.get("trigger_vitals") or {}
        assert tv.get("bd_value") == 8.2, (
            f"trigger_vitals.bd_value={tv.get('bd_value')}; expected 8.2 "
            "proving BD was consumed from base_deficit_monitoring_v1"
        )
        rule = st.get("trigger_rule_id") or ""
        assert "bd_gt6" in rule, (
            f"trigger_rule_id={rule!r}; expected 'bd_gt6' substring "
            "proving BD > 6 contributed to shock trigger"
        )

    def test_shock_trigger_has_evidence(self, features):
        st = features["shock_trigger_v1"]
        evidence = st.get("evidence") or []
        assert len(evidence) > 0, "shock_trigger evidence list is empty"

    # ── Edge 4: hemodynamic_instability_pattern_v1 depends on edge 1 ─

    def test_hemodynamic_instability_present(self, features):
        hi = features.get("hemodynamic_instability_pattern_v1")
        assert hi is not None, (
            "hemodynamic_instability_pattern_v1 missing from features"
        )

    def test_hemodynamic_instability_detected(self, features):
        hi = features["hemodynamic_instability_pattern_v1"]
        assert hi["pattern_present"] == "yes", (
            f"pattern_present={hi.get('pattern_present')}; "
            "expected 'yes' (SBP 82 < 90 and/or HR 128 > 120)"
        )

    def test_hemodynamic_hypotension_detected(self, features):
        """SBP 82 should trigger the hypotension sub-pattern."""
        hi = features["hemodynamic_instability_pattern_v1"]
        hp = hi.get("hypotension_pattern", {})
        assert hp.get("detected") is True, (
            "hypotension_pattern.detected should be True for SBP=82"
        )

    def test_hemodynamic_tachycardia_detected(self, features):
        """HR 128 should trigger the tachycardia sub-pattern."""
        hi = features["hemodynamic_instability_pattern_v1"]
        tp = hi.get("tachycardia_pattern", {})
        assert tp.get("detected") is True, (
            "tachycardia_pattern.detected should be True for HR=128"
        )

    # ── Edge 5: consultant chain (events → plan items → actionables) ─

    def test_consultant_events_present(self, features):
        ce = features.get("consultant_events_v1")
        assert ce is not None, "consultant_events_v1 missing from features"

    def test_consultant_events_found(self, features):
        ce = features["consultant_events_v1"]
        assert ce["consultant_present"] == "yes", (
            f"consultant_present={ce.get('consultant_present')}; "
            "expected 'yes' from Orthopedic Surgery consult note"
        )

    def test_consultant_plan_items_present(self, features):
        cpi = features.get("consultant_plan_items_v1")
        assert cpi is not None, "consultant_plan_items_v1 missing from features"

    def test_consultant_plan_items_extracted(self, features):
        cpi = features["consultant_plan_items_v1"]
        assert cpi["item_count"] > 0, (
            f"item_count={cpi.get('item_count')}; expected > 0 from "
            "'Assessment and Plan' section in consult note"
        )

    def test_consultant_plan_actionables_present(self, features):
        cpa = features.get("consultant_plan_actionables_v1")
        assert cpa is not None, (
            "consultant_plan_actionables_v1 missing from features"
        )

    def test_consultant_plan_actionables_extracted(self, features):
        cpa = features["consultant_plan_actionables_v1"]
        assert cpa["actionable_count"] > 0, (
            f"actionable_count={cpa.get('actionable_count')}; expected > 0 "
            "from plan items (ORIF → procedure, NWB → activity, follow up)"
        )

    # ── Cross-chain consistency ──────────────────────────────────

    def test_all_order_dependent_keys_exist_in_features(self, features):
        """Guard: all seven order-dependent keys must be present."""
        required = [
            "vitals_canonical_v1",
            "base_deficit_monitoring_v1",
            "shock_trigger_v1",
            "hemodynamic_instability_pattern_v1",
            "consultant_events_v1",
            "consultant_plan_items_v1",
            "consultant_plan_actionables_v1",
        ]
        missing = [k for k in required if k not in features]
        assert not missing, f"Missing order-dependent feature keys: {missing}"

    def test_top_level_contract_keys(self, result):
        """Output must honour the patient_features_v1 contract."""
        required_top = {
            "build", "patient_id", "days", "evidence_gaps",
            "features", "warnings", "warnings_summary",
        }
        actual = set(result.keys())
        assert required_top.issubset(actual), (
            f"Missing contract keys: {required_top - actual}"
        )
