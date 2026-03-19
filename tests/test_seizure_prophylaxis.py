#!/usr/bin/env python3
"""
Tests for Seizure Prophylaxis Extraction v1.

Covers:
  - Levetiracetam (Keppra) detection from MAR, physician notes, med list
  - Phenytoin (Dilantin) detection
  - Home medication vs inpatient-initiated distinction
  - Administration confirmation (Given signal)
  - Discontinuation detection
  - Dose / route / frequency extraction
  - Negative control (no seizure prophylaxis agents)
  - Evidence traceability (raw_line_id on every evidence item)
  - Deduplication across repeated timeline items
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.seizure_prophylaxis_v1 import (
    extract_seizure_prophylaxis,
    _match_agent,
    _has_admin_signal,
    _has_discontinue_signal,
    _is_outpatient_section,
    _extract_dose_info,
    _normalize_route,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days_data(
    items_by_day: dict | None = None,
    arrival_datetime: str | None = "2025-01-15T14:30:00",
) -> dict:
    """Build a minimal patient_days_v1 structure."""
    days = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}
    return {
        "meta": {
            "arrival_datetime": arrival_datetime,
            "patient_id": "Test_Patient",
        },
        "days": days,
    }


def _make_item(text: str, item_type: str = "PHYSICIAN_NOTE",
               item_id: str = "item_001",
               dt: str = "2025-01-15T14:30:00") -> dict:
    """Build a minimal timeline item."""
    return {
        "type": item_type,
        "id": item_id,
        "dt": dt,
        "payload": {"text": text},
    }


def _pat_features() -> dict:
    return {"days": {}}


# ── Unit tests: agent matching ──────────────────────────────────────

def test_match_levetiracetam_lowercase():
    assert _match_agent("levetiracetam 1000 mg oral BID") == "levetiracetam"


def test_match_keppra():
    assert _match_agent("Continue Keppra 750mg BID") == "levetiracetam"


def test_match_epic_mixed_case():
    """Epic displays as 'levETIRAcetam' — must match."""
    assert _match_agent("levETIRAcetam") == "levetiracetam"


def test_match_phenytoin():
    assert _match_agent("phenytoin 100 mg IV") == "phenytoin"


def test_match_dilantin():
    assert _match_agent("Dilantin loading dose") == "phenytoin"


def test_match_fosphenytoin():
    assert _match_agent("fosphenytoin 150 mg PE IV") == "phenytoin"


def test_match_depakote():
    assert _match_agent("consider a change from Keppra to Depakote") == "levetiracetam"
    # Depakote alone triggers valproate
    assert _match_agent("Depakote 500 mg BID") == "valproate"


def test_match_no_agent():
    assert _match_agent("acetaminophen 650 mg PO") is None


def test_match_no_agent_generic_seizure():
    """'seizure' alone without an agent name must NOT match."""
    assert _match_agent("seizure precautions") is None


# ── Unit tests: admin signal ────────────────────────────────────────

def test_admin_signal_given():
    assert _has_admin_signal("Given 01/03/2026 0814")


def test_admin_signal_administered():
    assert _has_admin_signal("Medication administered by RN")


def test_admin_signal_absent():
    assert not _has_admin_signal("Continue Keppra 750mg BID")


# ── Unit tests: discontinue signal ──────────────────────────────────

def test_discontinue_signal_bracket():
    assert _has_discontinue_signal("[DISCONTINUED] levETIRAcetam (KEPPRA) injection 500 mg")


def test_discontinue_signal_stop_keppra():
    assert _has_discontinue_signal("Stop keppra as we have alternative cause")


def test_discontinue_signal_was_discontinued():
    assert _has_discontinue_signal("Keppra was discontinued")


def test_discontinue_signal_absent():
    assert not _has_discontinue_signal("Continue Keppra 750mg BID")


# ── Unit tests: outpatient section ──────────────────────────────────

def test_outpatient_section_standard():
    assert _is_outpatient_section(
        "Current Outpatient Medications on File Prior to Encounter"
    )


def test_outpatient_section_home():
    assert _is_outpatient_section("Home Medications")


def test_outpatient_section_absent():
    assert not _is_outpatient_section("Assessment and Plan:")


# ── Unit tests: dose extraction ─────────────────────────────────────

def test_dose_extraction_full():
    result = _extract_dose_info("levETIRAcetam 1,000 mg Intravenous Q12H", "levetiracetam")
    assert result is not None
    assert result["dose_text"] == "1,000 mg"
    assert result["route"] == "IV"
    assert result["frequency"] == "Q12H"


def test_dose_extraction_oral_bid():
    result = _extract_dose_info("Keppra 750mg BID", "levetiracetam")
    assert result is not None
    assert result["dose_text"] == "750mg"
    assert result["frequency"] == "BID"


def test_dose_extraction_no_dose():
    result = _extract_dose_info("Continue Keppra", "levetiracetam")
    assert result is None


# ── Unit tests: route normalization ─────────────────────────────────

def test_normalize_route_oral():
    assert _normalize_route("Oral") == "PO"
    assert _normalize_route("PO") == "PO"


def test_normalize_route_iv():
    assert _normalize_route("IV") == "IV"
    assert _normalize_route("Intravenous") == "IV"


# ── Integration: Keppra started and continued (Larry_Corne pattern) ─

KEPPRA_HOME_MED_AND_CONTINUED = """\
Current Outpatient Medications on File Prior to Encounter
Medication\tSig\tDispense\tRefill
•    levETIRAcetam (KEPPRA) 500 MG tablet    Take 1 tablet (500 mg) by mouth 2 times daily   60 tablet       5
•    metformin (GLUCOPHAGE) 500 MG tablet    Take 1 tablet by mouth twice daily

Assessment and Plan:
Will increase Keppra to 750mg bid. Continue seizure precautions.
Therapeutic Interventions: seizure precautions. Continue increased dose of Keppra 750mg bid.
"""


def test_keppra_home_med_and_continued():
    """Larry_Corne pattern: home med Keppra 500mg, escalated to 750mg in-house."""
    days = _make_days_data(items_by_day={
        "2025-12-27": [_make_item(KEPPRA_HOME_MED_AND_CONTINUED, dt="2025-12-27T10:00:00")],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    assert "levetiracetam" in result["agents"]
    assert result["home_med_present"] is True
    assert result["discontinued"] is False
    assert result["mention_evidence_count"] > 0
    # Must have dose entries
    assert len(result["dose_entries"]) >= 1
    # Check evidence traceability
    all_evidence = (
        result["evidence"]["admin"]
        + result["evidence"]["mention"]
        + result["evidence"]["discontinued"]
    )
    for e in all_evidence:
        assert "raw_line_id" in e
        assert len(e["raw_line_id"]) == 16


# ── Integration: Keppra started and then discontinued (David_Gross) ─

KEPPRA_STARTED_THEN_STOPPED = """\
•    [COMPLETED] levETIRAcetam (KEPPRA) injection 1,000 mg    1,000 mg      Intravenous      Q12H    Aliker, Denis O, MD             1,000 mg at 12/17/25 1805
•    [DISCONTINUED] levETIRAcetam (KEPPRA) injection 500 mg   500 mg Intravenous     Q12H    Aliker, Denis O, MD

Initial concern for seizure given "stiffening" before crash seen on vehicle camera.  This seems unlikely to be seizure.  EEG normal.  CT head negative.  Stop keppra as we have alternative cause.
"""


def test_keppra_started_then_discontinued():
    """David_Gross pattern: started for possible seizure, discontinued after EEG normal."""
    days = _make_days_data(items_by_day={
        "2025-12-17": [_make_item(KEPPRA_STARTED_THEN_STOPPED, dt="2025-12-17T18:00:00")],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    assert "levetiracetam" in result["agents"]
    assert result["home_med_present"] is False
    assert result["discontinued"] is True
    assert result["discontinued_ts"] is not None
    assert len(result["evidence"]["discontinued"]) >= 1


# ── Integration: MAR admin confirmation ─────────────────────────────

KEPPRA_MAR_ADMIN = """\
levETIRAcetam
Given  01/15/2025 0800
1,000 mg  Intravenous  Scheduled  Q12H
"""


def test_keppra_mar_admin():
    """MAR line with 'Given' must produce admin evidence."""
    days = _make_days_data(items_by_day={
        "2025-01-15": [_make_item(KEPPRA_MAR_ADMIN, item_type="MAR",
                                   dt="2025-01-15T08:00:00")],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    assert result["admin_evidence_count"] >= 1
    assert result["first_admin_ts"] is not None


# ── Integration: negative control ───────────────────────────────────

NO_SEIZURE_MEDS = """\
Assessment and Plan:
1. Rib fractures: Pain management with acetaminophen and tramadol.
2. DVT prophylaxis: Start enoxaparin 40mg SQ daily.
3. GI prophylaxis: famotidine 20mg BID.
"""


def test_negative_control():
    """Patient with no seizure prophylaxis agents."""
    days = _make_days_data(items_by_day={
        "2025-01-15": [_make_item(NO_SEIZURE_MEDS)],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is False
    assert result["agents"] == []
    assert result["home_med_present"] is False
    assert result["first_mention_ts"] is None
    assert result["first_admin_ts"] is None
    assert result["discontinued"] is False
    assert result["admin_evidence_count"] == 0
    assert result["mention_evidence_count"] == 0


# ── Integration: empty timeline ─────────────────────────────────────

def test_empty_timeline():
    """Empty days_data produces fail-closed output."""
    days = _make_days_data()
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is False
    assert result["agents"] == []


# ── Integration: phenytoin detection ────────────────────────────────

PHENYTOIN_LOADING = """\
Neurosurgery recommendations:
1. Load phenytoin 1000 mg IV x1 then 100 mg IV Q8H
2. Seizure precautions
"""


def test_phenytoin_detection():
    days = _make_days_data(items_by_day={
        "2025-01-15": [_make_item(PHENYTOIN_LOADING)],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    assert "phenytoin" in result["agents"]
    assert len(result["dose_entries"]) >= 1


# ── Integration: multiple agents (Keppra + Depakote switch) ────────

MULTI_AGENT = """\
On Keppra 500 mg BID for seizure prophylaxis.
If agitation becomes an issue could consider a change from Keppra to Depakote.
Depakote 500 mg BID started.
"""


def test_multiple_agents():
    """When patient transitions between agents, both should be captured."""
    days = _make_days_data(items_by_day={
        "2025-01-15": [_make_item(MULTI_AGENT)],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    assert "levetiracetam" in result["agents"]
    assert "valproate" in result["agents"]
    assert len(result["agents"]) >= 2


# ── Integration: deduplication across repeated items ────────────────

def test_deduplication():
    """Same text repeated in two items should deduplicate evidence."""
    text = "Continue Keppra 750mg BID"
    days = _make_days_data(items_by_day={
        "2025-01-15": [
            _make_item(text, item_id="item_001", dt="2025-01-15T08:00:00"),
            _make_item(text, item_id="item_001", dt="2025-01-15T08:00:00"),
        ],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    # Should deduplicate identical evidence
    assert result["mention_evidence_count"] == 1


# ── Integration: Ronald_Bittner pattern ─────────────────────────────

BITTNER_SEIZURE_ACTIVITY = """\
Seizure-like activity noted started on Keppra seen by Neurology 1/18
levETIRAcetam, 1,000 mg, BID
Started on Keppra for him some twitching
"""


def test_bittner_pattern():
    """Ronald_Bittner: seizure-like activity → started on Keppra."""
    days = _make_days_data(items_by_day={
        "2025-01-18": [_make_item(BITTNER_SEIZURE_ACTIVITY, dt="2025-01-18T10:00:00")],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    assert result["detected"] is True
    assert "levetiracetam" in result["agents"]
    assert result["home_med_present"] is False
    assert result["discontinued"] is False
    assert len(result["dose_entries"]) >= 1
    # 1000 mg dose should be captured
    doses = [d["dose_text"] for d in result["dose_entries"]]
    assert any("1,000" in d or "1000" in d for d in doses)


# ── Integration: evidence has required fields ───────────────────────

def test_evidence_fields():
    """Every evidence item must have ts, raw_line_id, snippet, agent."""
    days = _make_days_data(items_by_day={
        "2025-01-15": [_make_item("Keppra 500mg BID given", dt="2025-01-15T08:00:00")],
    })
    result = extract_seizure_prophylaxis(_pat_features(), days)
    for category in ("admin", "mention", "discontinued"):
        for e in result["evidence"][category]:
            assert "ts" in e
            assert "raw_line_id" in e
            assert "snippet" in e
            assert "agent" in e
            assert len(e["raw_line_id"]) == 16
