#!/usr/bin/env python3
"""
PI RN Casefile v1 — Single-patient HTML renderer.

Reads patient_bundle_v1.json and produces a self-contained HTML casefile
suitable for direct browser viewing. No CDN, no framework, no server.

Usage:
    python3 cerebralos/reporting/render_pi_rn_casefile_v1.py \
        --bundle outputs/casefile/Betty_Roll/patient_bundle_v1.json \
        --out outputs/casefile/Betty_Roll/casefile_v1.html

Exit codes:
    0 — casefile written
    1 — bundle missing or render error
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Helpers ────────────────────────────────────────────────────────

def _e(text: Any) -> str:
    """HTML-escape text, coercing to string."""
    if text is None:
        return ""
    return html.escape(str(text))


def _na(val: Any, fallback: str = "—") -> str:
    """Return escaped val or the fallback if None/empty."""
    if val is None or val == "" or val == "DATA_NOT_AVAILABLE":
        return fallback
    return _e(val)


def _load_bundle(path: Path) -> Dict[str, Any]:
    """Load and return the bundle JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_los(arrival: Optional[str], discharge: Optional[str]) -> Optional[int]:
    """Compute length of stay in days.  Returns None on failure."""
    if not arrival or not discharge:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            a = datetime.strptime(arrival, fmt)
            d = datetime.strptime(discharge, fmt)
            delta = (d - a).days
            return max(delta, 0)
        except ValueError:
            continue
    return None


# ── CSS ────────────────────────────────────────────────────────────

_CSS = r"""
:root {
    --blue-50: #eff6ff; --blue-100: #dbeafe; --blue-200: #bfdbfe;
    --blue-600: #2563eb; --blue-700: #1d4ed8; --blue-800: #1e40af;
    --slate-50: #f8fafc; --slate-100: #f1f5f9; --slate-200: #e2e8f0;
    --slate-300: #cbd5e1; --slate-400: #94a3b8; --slate-500: #64748b;
    --slate-600: #475569; --slate-700: #334155; --slate-800: #1e293b;
    --slate-900: #0f172a;
    --red-50: #fef2f2; --red-100: #fee2e2; --red-500: #ef4444; --red-600: #dc2626; --red-700: #b91c1c;
    --green-50: #f0fdf4; --green-100: #dcfce7; --green-500: #22c55e; --green-600: #16a34a; --green-700: #15803d;
    --amber-50: #fffbeb; --amber-100: #fef3c7; --amber-500: #f59e0b; --amber-600: #d97706;
    --card-radius: 8px;
    --card-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
}
*, *::before, *::after { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--slate-50); color: var(--slate-800);
    margin: 0; padding: 16px; line-height: 1.55;
    -webkit-font-smoothing: antialiased; font-size: 14px;
}
h1,h2,h3,h4 { margin: 0; font-weight: 700; }
.container { max-width: 900px; margin: 0 auto; }

/* Header */
.cf-header {
    background: linear-gradient(135deg, var(--blue-700), var(--blue-800));
    color: white; padding: 24px 28px; border-radius: var(--card-radius);
    margin-bottom: 16px;
}
.cf-header h1 { font-size: 1.5em; margin-bottom: 2px; }
.cf-header .subtitle { opacity: 0.85; font-size: 0.88em; }

/* Cards */
.card {
    background: white; border-radius: var(--card-radius);
    box-shadow: var(--card-shadow); margin-bottom: 12px;
    border: 1px solid var(--slate-200); overflow: hidden;
}
.card-title {
    font-size: 0.82em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--slate-500); padding: 14px 18px 8px;
}
.card-body { padding: 0 18px 14px; }

/* Meta grid (patient info) */
.meta-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 10px 20px;
}
.meta-item .label {
    font-size: 0.72em; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--slate-400); margin-bottom: 1px;
}
.meta-item .value { font-weight: 600; font-size: 0.92em; }

/* Summary list */
.summary-list { list-style: none; padding: 0; margin: 0; }
.summary-list li {
    padding: 6px 0; font-size: 0.9em;
    border-bottom: 1px solid var(--slate-100);
}
.summary-list li:last-child { border-bottom: none; }
.summary-list .sl-label {
    font-weight: 600; color: var(--slate-600); min-width: 100px;
    display: inline-block;
}

/* Badges */
.badge {
    display: inline-block; padding: 2px 7px; border-radius: 4px;
    font-size: 0.7em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.03em; color: white; vertical-align: middle;
}
.badge-yes, .badge-non-compliant { background: var(--red-600); }
.badge-no, .badge-compliant { background: var(--green-600); }
.badge-utd, .badge-unable, .badge-indeterminate { background: var(--amber-500); color: var(--slate-800); }
.badge-excluded, .badge-not-triggered { background: var(--slate-400); }
.badge-error { background: var(--red-700); }

/* Compliance stat row */
.stat-row {
    display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;
}
.stat-box {
    flex: 1; min-width: 80px; text-align: center; padding: 10px 8px;
    border-radius: var(--card-radius); border: 1px solid var(--slate-200);
    background: white;
}
.stat-box .num { font-size: 1.6em; font-weight: 800; line-height: 1.1; }
.stat-box .lbl { font-size: 0.68em; text-transform: uppercase; letter-spacing: 0.05em; color: var(--slate-500); }
.stat-yes .num { color: var(--red-600); }
.stat-no .num { color: var(--green-600); }
.stat-utd .num { color: var(--amber-600); }
.stat-exc .num { color: var(--slate-400); }

/* Compliance table */
.compliance-tbl { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.compliance-tbl th {
    text-align: left; padding: 6px 10px; background: var(--slate-100);
    font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--slate-500); border-bottom: 2px solid var(--slate-200);
}
.compliance-tbl td { padding: 6px 10px; border-bottom: 1px solid var(--slate-100); }
.compliance-tbl tr:last-child td { border-bottom: none; }
.compliance-tbl tr.row-yes { background: var(--red-50); }
.compliance-tbl tr.row-utd { background: var(--amber-50); }

/* Day accordion */
details.day-card {
    background: white; border-radius: var(--card-radius);
    margin-bottom: 8px; box-shadow: var(--card-shadow);
    border: 1px solid var(--slate-200); overflow: hidden;
}
summary.day-summary {
    padding: 12px 18px; cursor: pointer; font-weight: 700;
    font-size: 0.92em; color: var(--blue-700); list-style: none;
    display: flex; align-items: center; gap: 8px;
    user-select: none;
}
summary.day-summary::-webkit-details-marker { display: none; }
summary.day-summary::before {
    content: "\25B6"; font-size: 0.65em; transition: transform 0.15s; color: var(--slate-400);
}
details.day-card[open] > summary.day-summary::before { transform: rotate(90deg); }
.day-body { padding: 0 18px 14px; }

/* Day sub-sections */
.day-section { margin-bottom: 10px; }
.day-section-title {
    font-size: 0.76em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--slate-400); margin-bottom: 4px;
    padding-bottom: 3px; border-bottom: 1px solid var(--slate-100);
}
.day-kv { font-size: 0.88em; padding: 2px 0; }
.day-kv .dk { font-weight: 600; color: var(--slate-600); }

/* Vitals mini-grid */
.vitals-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 6px;
}
.vital-chip {
    background: var(--slate-50); border: 1px solid var(--slate-200);
    border-radius: 6px; padding: 6px 8px; text-align: center;
}
.vital-chip .vl { font-size: 0.68em; text-transform: uppercase; color: var(--slate-400); }
.vital-chip .vv { font-size: 1em; font-weight: 700; }

/* Warnings */
.warning-list { list-style: none; padding: 0; margin: 0; }
.warning-list li {
    padding: 6px 10px; font-size: 0.85em;
    background: var(--amber-50); border-left: 3px solid var(--amber-500);
    margin-bottom: 4px; border-radius: 0 4px 4px 0;
}

/* Footer */
.cf-footer {
    text-align: center; padding: 16px 0 4px; color: var(--slate-400);
    font-size: 0.72em; border-top: 1px solid var(--slate-200); margin-top: 24px;
}

/* Toggle-all button */
.toggle-btn {
    background: var(--blue-50); color: var(--blue-700);
    border: 1px solid var(--blue-200); padding: 5px 12px;
    border-radius: 6px; font-size: 0.78em; font-weight: 600;
    cursor: pointer; margin-bottom: 10px;
}
.toggle-btn:hover { background: var(--blue-100); }

/* Status bar */
.status-bar {
    display: flex; gap: 8px; flex-wrap: wrap;
    margin-bottom: 12px;
}
.status-chip {
    flex: 1 1 0; min-width: 140px;
    border-radius: var(--card-radius); padding: 10px 14px;
    border: 1px solid var(--slate-200); background: white;
    box-shadow: var(--card-shadow);
}
.status-chip .sc-label {
    font-size: 0.68em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--slate-400); margin-bottom: 2px;
}
.status-chip .sc-value {
    font-size: 0.95em; font-weight: 700;
}
.sc-alert { border-left: 4px solid var(--red-600); }
.sc-alert .sc-value { color: var(--red-700); }
.sc-ok { border-left: 4px solid var(--green-600); }
.sc-ok .sc-value { color: var(--green-700); }
.sc-warn { border-left: 4px solid var(--amber-500); }
.sc-warn .sc-value { color: var(--amber-600); }
.sc-na { border-left: 4px solid var(--slate-300); }
.sc-na .sc-value { color: var(--slate-400); }

/* Compliance snapshot */
.compliance-snap {
    display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;
}
.csnap-box {
    flex: 1 1 0; min-width: 100px; text-align: center; padding: 10px 8px;
    border-radius: var(--card-radius); border: 1px solid var(--slate-200);
    background: white; box-shadow: var(--card-shadow);
}
.csnap-box .cn { font-size: 1.5em; font-weight: 800; line-height: 1.1; }
.csnap-box .cl {
    font-size: 0.66em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--slate-500); margin-top: 2px;
}
.csnap-yes .cn { color: var(--red-600); }
.csnap-utd .cn { color: var(--amber-600); }
.csnap-nc .cn { color: var(--red-700); }
.csnap-clear .cn { color: var(--green-600); }

/* Admission snapshot */
.admit-snap {
    background: white; border-radius: var(--card-radius);
    box-shadow: var(--card-shadow); margin-bottom: 12px;
    border: 1px solid var(--slate-200); overflow: hidden;
}
.admit-snap .as-title {
    font-size: 0.78em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--slate-500); padding: 12px 18px 6px;
}
.admit-snap .as-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 8px 18px; padding: 0 18px 14px;
}
.admit-snap .as-item .al {
    font-size: 0.68em; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--slate-400); margin-bottom: 1px;
}
.admit-snap .as-item .av { font-weight: 600; font-size: 0.88em; }

/* First-day snapshot */
.day1-snap {
    background: white; border-radius: var(--card-radius);
    box-shadow: var(--card-shadow); margin-bottom: 12px;
    border: 1px solid var(--slate-200); overflow: hidden;
}
.day1-snap .d1-title {
    font-size: 0.78em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--slate-500); padding: 12px 18px 6px;
}
.day1-snap .d1-body { padding: 0 18px 14px; }

/* Print */
@media print {
    body { padding: 0; font-size: 11px; }
    .cf-header { padding: 12px 16px; }
    details.day-card { break-inside: avoid; }
    details.day-card[open] { break-inside: auto; }
    .toggle-btn { display: none; }
}
"""

# ── JS ─────────────────────────────────────────────────────────────

_JS = r"""
function toggleAll() {
    var cards = document.querySelectorAll('details.day-card');
    var anyOpen = false;
    for (var i = 0; i < cards.length; i++) { if (cards[i].open) { anyOpen = true; break; } }
    for (var i = 0; i < cards.length; i++) { cards[i].open = !anyOpen; }
}
"""


# ── Section renderers ──────────────────────────────────────────────

def _render_header(bundle: Dict[str, Any]) -> str:
    p = bundle.get("patient", {})
    name = _na(p.get("patient_name"), "Unknown Patient")
    arrival = p.get("arrival_datetime") or ""
    discharge = p.get("discharge_datetime") or ""
    los = _compute_los(arrival, discharge)
    los_str = f"{los} day{'s' if los != 1 else ''}" if los is not None else "—"
    return (
        '<div class="cf-header">'
        f'<h1>{name}</h1>'
        f'<div class="subtitle">PI RN Casefile v1 &middot; LOS: {_e(los_str)}</div>'
        "</div>"
    )


def _render_status_bar(bundle: Dict[str, Any]) -> str:
    """Render the above-the-fold clinical status summary bar.

    Shows compact badges for activation level, shock status,
    anticoagulation, and penetrating mechanism.  Fail-closed:
    any missing field renders as '\u2014' with neutral styling.
    """
    summary = bundle.get("summary") or {}
    chips: List[str] = []

    # ── Activation ────────────────────────────────────────────
    activation = summary.get("activation")
    if isinstance(activation, dict):
        detected = activation.get("detected")
        cat = activation.get("category")
        if detected is True or (cat and detected is not False):
            if isinstance(cat, str) and cat.strip():
                norm = cat.strip()
                # Category might be "Level II" already or just "II"
                if norm.startswith("Level"):
                    label = norm
                else:
                    label = f"Level {norm}"
                cls = "sc-alert" if norm in ("I", "Level I") else "sc-warn"
                chips.append(_status_chip("Activation", _e(label), cls))
            else:
                chips.append(_status_chip("Activation", "Detected", "sc-warn"))
        elif detected is False:
            chips.append(_status_chip("Activation", "Not Detected", "sc-ok"))
        else:
            chips.append(_status_chip("Activation", "\u2014", "sc-na"))
    else:
        chips.append(_status_chip("Activation", "\u2014", "sc-na"))

    # ── Shock Triggered ───────────────────────────────────────
    shock = summary.get("shock_trigger")
    if isinstance(shock, dict):
        triggered = shock.get("shock_triggered")
        if triggered is True or (isinstance(triggered, str) and triggered.lower() == "yes"):
            chips.append(_status_chip("Shock", "Triggered", "sc-alert"))
        elif triggered is False or (isinstance(triggered, str) and triggered.lower() == "no"):
            chips.append(_status_chip("Shock", "Not Triggered", "sc-ok"))
        else:
            chips.append(_status_chip("Shock", "\u2014", "sc-na"))
    else:
        chips.append(_status_chip("Shock", "\u2014", "sc-na"))

    # ── Anticoagulation ───────────────────────────────────────
    anticoag = summary.get("anticoagulants")
    if isinstance(anticoag, dict):
        ac_present = anticoag.get("anticoag_present", "")
        ap_present = anticoag.get("antiplatelet_present", "")
        # Fallback for simplified test-fixture shape
        on_ac = anticoag.get("on_anticoagulant")

        drug_count = len(anticoag.get("home_anticoagulants", []))
        ap_count = len(anticoag.get("home_antiplatelets", []))
        agents = anticoag.get("agents", [])

        has_anticoag = (
            (isinstance(ac_present, str) and ac_present.lower() == "yes")
            or on_ac is True
        )
        has_antiplatelet = (
            isinstance(ap_present, str) and ap_present.lower() == "yes"
        )

        if has_anticoag or has_antiplatelet:
            label_parts: List[str] = []
            if has_anticoag:
                label_parts.append(f"Anticoag ({drug_count or len(agents)})")
            if has_antiplatelet:
                label_parts.append(f"Antiplatelet ({ap_count})")
            chips.append(_status_chip("Anticoagulation", "Yes \u2014 " + ", ".join(label_parts), "sc-alert"))
        elif (
            (isinstance(ac_present, str) and ac_present.lower() == "no")
            or on_ac is False
        ):
            chips.append(_status_chip("Anticoagulation", "No", "sc-ok"))
        else:
            chips.append(_status_chip("Anticoagulation", "\u2014", "sc-na"))
    else:
        chips.append(_status_chip("Anticoagulation", "\u2014", "sc-na"))

    # ── Penetrating Mechanism ─────────────────────────────────
    mechanism = summary.get("mechanism")
    if isinstance(mechanism, dict):
        pen = mechanism.get("penetrating_mechanism")
        if pen is True:
            chips.append(_status_chip("Penetrating", "Yes", "sc-alert"))
        elif pen is False:
            chips.append(_status_chip("Penetrating", "No", "sc-ok"))
        else:
            chips.append(_status_chip("Penetrating", "\u2014", "sc-na"))
    else:
        chips.append(_status_chip("Penetrating", "\u2014", "sc-na"))

    # ── Discharge Status ──────────────────────────────────────
    p = bundle.get("patient") or {}
    discharge_dt = p.get("discharge_datetime")
    if discharge_dt and discharge_dt != "DATA_NOT_AVAILABLE":
        chips.append(_status_chip("Status", "Discharged", "sc-ok"))
    elif p.get("arrival_datetime"):
        chips.append(_status_chip("Status", "Active", "sc-warn"))
    else:
        chips.append(_status_chip("Status", "\u2014", "sc-na"))

    if not chips:
        return ""
    return f'<div class="status-bar">{"" .join(chips)}</div>'


def _status_chip(label: str, value: str, cls: str) -> str:
    """Return a single status chip HTML fragment."""
    return (
        f'<div class="status-chip {cls}">'
        f'<div class="sc-label">{_e(label)}</div>'
        f'<div class="sc-value">{value}</div>'
        "</div>"
    )


def _render_compliance_snapshot(bundle: Dict[str, Any]) -> str:
    """Render above-the-fold NTDS YES / UTD / Protocol NC counts."""
    compliance = bundle.get("compliance")
    if not compliance or not isinstance(compliance, dict):
        return ""

    ntds = compliance.get("ntds_event_outcomes") or {}
    protocols = compliance.get("protocol_results") or []

    if not ntds and not protocols:
        return ""

    yes_n = sum(1 for v in ntds.values() if isinstance(v, dict) and str(v.get("outcome", "")).upper() == "YES")
    utd_n = sum(1 for v in ntds.values() if isinstance(v, dict) and str(v.get("outcome", "")).upper() == "UTD")
    nc_n = sum(1 for r in protocols if isinstance(r, dict) and str(r.get("outcome", "")).upper() == "NON_COMPLIANT")

    if yes_n == 0 and utd_n == 0 and nc_n == 0:
        # All clear
        def _box(n: int, lbl: str) -> str:
            return (
                f'<div class="csnap-box csnap-clear">'
                f'<div class="cn">{n}</div>'
                f'<div class="cl">{_e(lbl)}</div>'
                "</div>"
            )
        return (
            '<div class="compliance-snap">'
            + _box(0, "NTDS YES") + _box(0, "NTDS UTD") + _box(0, "Protocol NC")
            + "</div>"
        )

    parts: List[str] = []
    for n, lbl, cls in [(yes_n, "NTDS YES", "csnap-yes"), (utd_n, "NTDS UTD", "csnap-utd"), (nc_n, "Protocol NC", "csnap-nc")]:
        c = cls if n > 0 else "csnap-clear"
        parts.append(
            f'<div class="csnap-box {c}">'
            f'<div class="cn">{n}</div>'
            f'<div class="cl">{_e(lbl)}</div>'
            "</div>"
        )
    return '<div class="compliance-snap">' + "".join(parts) + "</div>"


def _render_admission_snapshot(bundle: Dict[str, Any]) -> str:
    """Render a dense 9-field admission summary grid."""
    p = bundle.get("patient") or {}
    summary = bundle.get("summary") or {}

    arrival = _na(p.get("arrival_datetime"))
    discharge = _na(p.get("discharge_datetime"))
    los_val = _compute_los(p.get("arrival_datetime"), p.get("discharge_datetime"))
    los = f"{los_val} day{'s' if los_val != 1 else ''}" if los_val is not None else "\u2014"

    age_data = summary.get("age")
    age = str(age_data.get("age", "\u2014")) if isinstance(age_data, dict) and age_data.get("age") is not None else "\u2014"
    demo = summary.get("demographics")
    sex = str(demo.get("sex", "\u2014")) if isinstance(demo, dict) and demo.get("sex") else "\u2014"
    age_sex = f"{age} / {sex}"

    mech = summary.get("mechanism")
    mechanism_str = _na(mech.get("mechanism_primary", "").title() if isinstance(mech, dict) and mech.get("mechanism_primary") else None)

    mech_data = summary.get("mechanism") or {}
    regions_raw = mech_data.get("body_region_labels", []) if isinstance(mech_data, dict) else []
    if isinstance(regions_raw, list) and regions_raw:
        regions = ", ".join(_e(str(r).title()) for r in regions_raw if r) or "\u2014"
    else:
        regions = "\u2014"

    consult_raw = bundle.get("consultants") or {}
    if isinstance(consult_raw, dict):
        services = consult_raw.get("consultant_services", []) or []
        consults = ", ".join(_e(str(s)) for s in services if s) or "\u2014"
    else:
        consults = "\u2014"

    pmh_data = summary.get("pmh")
    pmh_items = pmh_data.get("pmh_items", []) or [] if isinstance(pmh_data, dict) else []
    pmh = "; ".join(_e(str(i.get("text", ""))) for i in pmh_items if isinstance(i, dict) and i.get("text")) or "\u2014"

    anticoag = summary.get("anticoagulants") or {}
    agent_list: List[str] = []
    if isinstance(anticoag, dict):
        for a in anticoag.get("agents", []):
            if a:
                agent_list.append(str(a))
        for a in anticoag.get("home_anticoagulants", []):
            if isinstance(a, dict) and a.get("agent"):
                agent_list.append(str(a["agent"]))
            elif isinstance(a, str) and a:
                agent_list.append(a)
        for a in anticoag.get("home_antiplatelets", []):
            if isinstance(a, dict) and a.get("agent"):
                agent_list.append(str(a["agent"]))
            elif isinstance(a, str) and a:
                agent_list.append(a)
    agents_str = ", ".join(_e(a) for a in agent_list) or "\u2014"

    fields = [
        ("Arrival", arrival), ("Discharge", discharge), ("LOS", los),
        ("Age / Sex", age_sex), ("Mechanism", mechanism_str),
        ("Body Regions", regions), ("Consultants", consults),
        ("PMH", pmh), ("Anticoag / Antiplatelet", agents_str),
    ]
    grid = ""
    for label, val in fields:
        grid += (
            f'<div class="as-item">'
            f'<div class="al">{_e(label)}</div>'
            f'<div class="av">{val}</div>'
            "</div>"
        )
    return (
        '<div class="admit-snap">'
        '<div class="as-title">Admission Snapshot</div>'
        f'<div class="as-grid">{grid}</div>'
        "</div>"
    )


def _render_first_day_snapshot(bundle: Dict[str, Any]) -> str:
    """Render vitals/GCS/labs/vent from the earliest daily block."""
    daily = bundle.get("daily") or {}
    if not daily:
        return ""
    first_key = sorted(daily.keys())[0]
    day = daily[first_key]
    if not isinstance(day, dict):
        return ""

    sections: List[str] = []
    vitals = day.get("vitals")
    if vitals:
        sections.append(_render_vitals(vitals))
    gcs = day.get("gcs")
    if gcs:
        sections.append(_render_gcs(gcs))
    labs = day.get("labs")
    if labs:
        sections.append(_render_labs(labs))
    vent = day.get("ventilator")
    if vent:
        sections.append(_render_ventilator(vent))

    if not sections:
        return ""
    body = "".join(sections)
    return (
        '<div class="day1-snap">'
        f'<div class="d1-title">Day 1 Clinical Snapshot \u2014 {_e(first_key)}</div>'
        f'<div class="d1-body">{body}</div>'
        "</div>"
    )


def _render_patient_card(bundle: Dict[str, Any]) -> str:
    p = bundle.get("patient", {})
    summary = bundle.get("summary", {})
    age_data = summary.get("age")
    age_str = "—"
    if isinstance(age_data, dict):
        age_val = age_data.get("age")
        if age_val is not None:
            age_str = str(age_val)

    demo = summary.get("demographics")
    sex_str = "—"
    if isinstance(demo, dict):
        sex_val = demo.get("sex")
        if sex_val:
            sex_str = str(sex_val)

    arrival = _na(p.get("arrival_datetime"))
    discharge = _na(p.get("discharge_datetime"))
    category = _na(p.get("trauma_category"))

    items = [
        ("Patient ID", _na(p.get("patient_id"))),
        ("DOB", _na(p.get("dob"))),
        ("Age", age_str),
        ("Sex", sex_str),
        ("Arrival", arrival),
        ("Discharge", discharge),
        ("Trauma Category", category),
    ]
    grid = ""
    for label, val in items:
        grid += (
            f'<div class="meta-item">'
            f'<div class="label">{_e(label)}</div>'
            f'<div class="value">{val}</div>'
            f"</div>"
        )
    return (
        '<div class="card">'
        '<div class="card-title">Patient Information</div>'
        f'<div class="card-body"><div class="meta-grid">{grid}</div></div>'
        "</div>"
    )


def _render_moi(bundle: Dict[str, Any]) -> str:
    mech = bundle.get("summary", {}).get("mechanism")
    if not mech or not isinstance(mech, dict):
        return ""
    primary = mech.get("mechanism_primary", "—")
    labels = mech.get("mechanism_labels", [])
    regions = mech.get("body_region_labels", [])
    penetrating = mech.get("penetrating_mechanism", False)
    items = f'<li><span class="sl-label">Primary:</span> {_e(primary)}</li>'
    if labels:
        items += f'<li><span class="sl-label">All:</span> {_e(", ".join(labels))}</li>'
    if regions:
        items += f'<li><span class="sl-label">Body Regions:</span> {_e(", ".join(regions))}</li>'
    if penetrating:
        items += '<li><span class="sl-label">Penetrating:</span> Yes</li>'
    return (
        '<div class="card">'
        '<div class="card-title">Mechanism of Injury</div>'
        f'<div class="card-body"><ul class="summary-list">{items}</ul></div>'
        "</div>"
    )


def _render_pmh(bundle: Dict[str, Any]) -> str:
    pmh = bundle.get("summary", {}).get("pmh")
    anticoag = bundle.get("summary", {}).get("anticoagulants")
    if not pmh and not anticoag:
        return ""
    parts: List[str] = []
    if isinstance(pmh, dict):
        for key in ("pmh_items", "social_items", "allergy_items"):
            items = pmh.get(key)
            if isinstance(items, list) and items:
                label = key.replace("_items", "").replace("_", " ").upper()
                strs = []
                for item in items:
                    if isinstance(item, dict):
                        strs.append(item.get("text", str(item)))
                    else:
                        strs.append(str(item))
                parts.append(
                    f'<li><span class="sl-label">{_e(label)}:</span> '
                    f'{_e("; ".join(strs))}</li>'
                )
    if isinstance(anticoag, dict):
        on_anticoag = anticoag.get("on_anticoagulant")
        agents = anticoag.get("agents", [])
        if on_anticoag:
            agent_str = ", ".join(str(a) for a in agents) if agents else "not specified"
            parts.append(
                f'<li><span class="sl-label">Anticoagulants:</span> '
                f'Yes ({_e(agent_str)})</li>'
            )
        elif on_anticoag is False:
            parts.append(
                '<li><span class="sl-label">Anticoagulants:</span> No</li>'
            )
    if not parts:
        return ""
    return (
        '<div class="card">'
        '<div class="card-title">PMH / Anticoagulants</div>'
        f'<div class="card-body"><ul class="summary-list">{"".join(parts)}</ul></div>'
        "</div>"
    )


def _render_consultants(bundle: Dict[str, Any]) -> str:
    cons = bundle.get("consultants")
    if not cons or not isinstance(cons, dict):
        return ""
    services = cons.get("consultant_services", [])
    if not services:
        return ""
    items = "".join(f"<li>{_e(s)}</li>" for s in services)
    return (
        '<div class="card">'
        '<div class="card-title">Consultants</div>'
        f'<div class="card-body"><ul class="summary-list">{items}</ul></div>'
        "</div>"
    )


def _outcome_badge(outcome: str) -> str:
    """Return a colored badge for an NTDS/protocol outcome."""
    o = outcome.upper().strip()
    cls_map = {
        "YES": "badge-yes", "NO": "badge-no",
        "UNABLE_TO_DETERMINE": "badge-utd", "UTD": "badge-utd",
        "EXCLUDED": "badge-excluded",
        "COMPLIANT": "badge-compliant", "NON_COMPLIANT": "badge-non-compliant",
        "NOT_TRIGGERED": "badge-not-triggered",
        "INDETERMINATE": "badge-indeterminate",
        "ERROR": "badge-error",
    }
    cls = cls_map.get(o, "badge-excluded")
    return f'<span class="badge {cls}">{_e(o)}</span>'


def _render_ntds_summary(bundle: Dict[str, Any]) -> str:
    outcomes = bundle.get("compliance", {}).get("ntds_event_outcomes")
    if not outcomes or not isinstance(outcomes, dict):
        return ""

    # Count outcomes (normalize case/whitespace)
    counts: Dict[str, int] = {}
    for ev in outcomes.values():
        o = ev.get("outcome", "").upper().strip()
        counts[o] = counts.get(o, 0) + 1

    yes_ct = counts.get("YES", 0)
    no_ct = counts.get("NO", 0)
    utd_ct = counts.get("UNABLE_TO_DETERMINE", 0)
    exc_ct = counts.get("EXCLUDED", 0)

    stat_html = (
        '<div class="stat-row">'
        f'<div class="stat-box stat-yes"><div class="num">{yes_ct}</div><div class="lbl">YES</div></div>'
        f'<div class="stat-box stat-no"><div class="num">{no_ct}</div><div class="lbl">NO</div></div>'
        f'<div class="stat-box stat-utd"><div class="num">{utd_ct}</div><div class="lbl">UTD</div></div>'
        f'<div class="stat-box stat-exc"><div class="num">{exc_ct}</div><div class="lbl">Excluded</div></div>'
        "</div>"
    )

    rows = ""
    for eid, ev in sorted(outcomes.items(), key=lambda x: int(x[0])):
        outcome = ev.get("outcome", "")
        outcome_norm = outcome.upper().strip()
        row_cls = ""
        if outcome_norm == "YES":
            row_cls = ' class="row-yes"'
        elif outcome_norm == "UNABLE_TO_DETERMINE":
            row_cls = ' class="row-utd"'
        rows += (
            f"<tr{row_cls}>"
            f'<td>E{_e(str(ev.get("event_id", eid)))}</td>'
            f"<td>{_e(ev.get('canonical_name', ''))}</td>"
            f"<td>{_outcome_badge(outcome)}</td>"
            "</tr>"
        )

    table = (
        '<table class="compliance-tbl">'
        "<thead><tr><th>ID</th><th>Event</th><th>Outcome</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )

    return (
        '<div class="card">'
        '<div class="card-title">NTDS Hospital Event Outcomes</div>'
        f'<div class="card-body">{stat_html}{table}</div>'
        "</div>"
    )


def _render_protocol_summary(bundle: Dict[str, Any]) -> str:
    results = bundle.get("compliance", {}).get("protocol_results")
    if not results:
        return ""
    if isinstance(results, list):
        rows = ""
        for r in results:
            if not isinstance(r, dict):
                continue
            name = r.get("protocol", r.get("protocol_id", ""))
            outcome = r.get("outcome", "")
            rows += (
                f"<tr><td>{_e(name)}</td>"
                f"<td>{_outcome_badge(outcome)}</td></tr>"
            )
        if not rows:
            return ""
        table = (
            '<table class="compliance-tbl">'
            "<thead><tr><th>Protocol</th><th>Outcome</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        return (
            '<div class="card">'
            '<div class="card-title">Protocol Compliance</div>'
            f'<div class="card-body">{table}</div>'
            "</div>"
        )
    return ""


def _render_vitals(vitals: Any) -> str:
    """Render a vitals snapshot for a single day."""
    if not vitals:
        return ""
    # Canonical shape: {"records": [...]}; also accept flat list or single dict
    if isinstance(vitals, dict):
        readings = vitals.get("records", [])
        if not readings:
            readings = [vitals]
    elif isinstance(vitals, list):
        readings = vitals
    else:
        return ""
    if not readings:
        return ""
    # Use the first reading for a quick snapshot
    v = readings[0] if isinstance(readings[0], dict) else {}
    if not v:
        return ""
    chips = ""
    for keys, label in [
        (("hr",), "HR"),
        (("sbp",), "SBP"),
        (("dbp",), "DBP"),
        (("map",), "MAP"),
        (("rr", "resp"), "RR"),
        (("spo2",), "SpO2"),
        (("temp_f", "temp_c", "temp"), "Temp"),
    ]:
        val = None
        for k in keys:
            val = v.get(k)
            if val is not None:
                break
        if val is not None:
            chips += (
                f'<div class="vital-chip">'
                f'<div class="vl">{_e(label)}</div>'
                f'<div class="vv">{_e(str(val))}</div>'
                "</div>"
            )
    if not chips:
        return ""
    return (
        '<div class="day-section">'
        '<div class="day-section-title">Vitals</div>'
        f'<div class="vitals-grid">{chips}</div>'
        "</div>"
    )


def _render_gcs(gcs: Any) -> str:
    """Render GCS for a single day."""
    if not gcs or not isinstance(gcs, dict):
        return ""
    best = gcs.get("best")
    e = gcs.get("eye")
    v = gcs.get("verbal")
    m = gcs.get("motor")
    parts = []
    if best is not None:
        parts.append(f"GCS Total: {_e(str(best))}")
    if e is not None or v is not None or m is not None:
        parts.append(
            f"E{_e(str(e or '?'))} "
            f"V{_e(str(v or '?'))} "
            f"M{_e(str(m or '?'))}"
        )
    if not parts:
        return ""
    return (
        '<div class="day-section">'
        '<div class="day-section-title">GCS</div>'
        f'<div class="day-kv">{" &middot; ".join(parts)}</div>'
        "</div>"
    )


def _render_labs(labs: Any) -> str:
    """Render structured labs for a single day."""
    if not labs or not isinstance(labs, dict):
        return ""
    items = ""
    for panel_name, panel_data in sorted(labs.items()):
        if isinstance(panel_data, dict):
            vals = []
            for k, v in sorted(panel_data.items()):
                if v is not None:
                    vals.append(f"{_e(k)}: {_e(str(v))}")
            if vals:
                items += (
                    f'<div class="day-kv">'
                    f'<span class="dk">{_e(panel_name)}:</span> '
                    f'{", ".join(vals)}'
                    "</div>"
                )
        elif isinstance(panel_data, list):
            for entry in panel_data:
                if isinstance(entry, dict):
                    vals = []
                    for k, v in sorted(entry.items()):
                        if v is not None:
                            vals.append(f"{_e(k)}: {_e(str(v))}")
                    if vals:
                        items += (
                            f'<div class="day-kv">'
                            f'<span class="dk">{_e(panel_name)}:</span> '
                            f'{", ".join(vals)}'
                            "</div>"
                        )
    if not items:
        return ""
    return (
        '<div class="day-section">'
        '<div class="day-section-title">Labs</div>'
        f"{items}</div>"
    )


def _render_ventilator(vent: Any) -> str:
    """Render ventilator settings for a single day."""
    if not vent:
        return ""
    if isinstance(vent, list):
        if not vent:
            return ""
        vent = vent[0] if isinstance(vent[0], dict) else {}
    if not isinstance(vent, dict):
        return ""
    parts = []
    for key, label in [
        ("mode", "Mode"), ("fio2", "FiO2"), ("peep", "PEEP"),
        ("tidal_volume", "Vt"), ("resp_rate", "RR"),
        ("status", "Status"),
    ]:
        val = vent.get(key)
        if val is not None:
            parts.append(f"{_e(label)}: {_e(str(val))}")
    if not parts:
        return ""
    return (
        '<div class="day-section">'
        '<div class="day-section-title">Ventilator</div>'
        f'<div class="day-kv">{" &middot; ".join(parts)}</div>'
        "</div>"
    )


def _render_plans(plans: Any) -> str:
    """Render trauma daily plan / changes in course for a single day."""
    if not plans:
        return ""
    if isinstance(plans, str):
        return (
            '<div class="day-section">'
            '<div class="day-section-title">Course / Plan</div>'
            f'<div class="day-kv">{_e(plans)}</div>'
            "</div>"
        )
    if isinstance(plans, dict):
        items = ""
        for k, v in plans.items():
            if v is not None:
                items += f'<div class="day-kv"><span class="dk">{_e(k)}:</span> {_e(str(v))}</div>'
        if items:
            return (
                '<div class="day-section">'
                '<div class="day-section-title">Course / Plan</div>'
                f"{items}</div>"
            )
    if isinstance(plans, list):
        items = "".join(f'<div class="day-kv">{_e(str(p))}</div>' for p in plans if p)
        if items:
            return (
                '<div class="day-section">'
                '<div class="day-section-title">Course / Plan</div>'
                f"{items}</div>"
            )
    return ""


def _render_consultant_plans(cp: Any) -> str:
    """Render consultant plans for a single day."""
    if not cp:
        return ""
    if isinstance(cp, dict):
        items = ""
        for service, plan in sorted(cp.items()):
            if plan is not None:
                items += (
                    f'<div class="day-kv">'
                    f'<span class="dk">{_e(service)}:</span> {_e(str(plan))}'
                    "</div>"
                )
        if items:
            return (
                '<div class="day-section">'
                '<div class="day-section-title">Consultant Plans</div>'
                f"{items}</div>"
            )
    if isinstance(cp, list):
        items = "".join(f'<div class="day-kv">{_e(str(p))}</div>' for p in cp if p)
        if items:
            return (
                '<div class="day-section">'
                '<div class="day-section-title">Consultant Plans</div>'
                f"{items}</div>"
            )
    return ""


def _render_daily(bundle: Dict[str, Any]) -> str:
    daily = bundle.get("daily", {})
    if not daily:
        return ""

    days_sorted = sorted(daily.keys())
    day_count = len(days_sorted)

    toggle = '<button class="toggle-btn" onclick="toggleAll()">Expand / Collapse All Days</button>'
    cards = ""
    for idx, day_key in enumerate(days_sorted):
        day_data = daily[day_key]
        if not isinstance(day_data, dict):
            continue
        day_num = idx + 1
        # Open first day by default
        open_attr = " open" if idx == 0 else ""

        body_parts = []
        body_parts.append(_render_vitals(day_data.get("vitals")))
        body_parts.append(_render_gcs(day_data.get("gcs")))
        body_parts.append(_render_labs(day_data.get("labs")))
        body_parts.append(_render_ventilator(day_data.get("ventilator")))
        body_parts.append(_render_plans(day_data.get("plans")))
        body_parts.append(_render_consultant_plans(day_data.get("consultant_plans")))

        body_html = "".join(p for p in body_parts if p)
        if not body_html:
            body_html = '<div class="day-kv" style="color:var(--slate-400);font-style:italic;">No data documented for this day.</div>'

        cards += (
            f'<details class="day-card"{open_attr}>'
            f'<summary class="day-summary">'
            f"Hospital Day {day_num} &mdash; {_e(day_key)}"
            f"</summary>"
            f'<div class="day-body">{body_html}</div>'
            f"</details>"
        )

    section_title = (
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">'
        f'<h3 style="font-size:1.05em;color:var(--slate-700);">Day-by-Day Admission ({day_count} day{"s" if day_count != 1 else ""})</h3>'
        f"{toggle}</div>"
    )
    return f"{section_title}{cards}"


def _render_warnings(bundle: Dict[str, Any]) -> str:
    warnings = bundle.get("warnings", [])
    if not warnings:
        return ""
    items = "".join(f"<li>{_e(str(w))}</li>" for w in warnings)
    return (
        '<div class="card">'
        '<div class="card-title">Warnings</div>'
        f'<div class="card-body"><ul class="warning-list">{items}</ul></div>'
        "</div>"
    )


def _render_footer(bundle: Dict[str, Any]) -> str:
    build = bundle.get("build", {})
    version = build.get("bundle_version", "?")
    ts = build.get("generated_at_utc", "?")
    assembler = build.get("assembler", "?")
    return (
        '<div class="cf-footer">'
        f"CerebralOS &middot; bundle v{_e(version)} &middot; "
        f"{_e(assembler)} &middot; {_e(ts)}"
        "</div>"
    )


# ── Main render ────────────────────────────────────────────────────

def render_casefile(bundle: Dict[str, Any]) -> str:
    """Render a complete self-contained HTML casefile from a bundle dict."""
    parts = [
        # ── Above the fold ────────────────────────────
        _render_header(bundle),
        _render_status_bar(bundle),
        _render_compliance_snapshot(bundle),
        _render_admission_snapshot(bundle),
        _render_first_day_snapshot(bundle),
        # ── Detail sections ───────────────────────────
        _render_patient_card(bundle),
        _render_moi(bundle),
        _render_pmh(bundle),
        _render_consultants(bundle),
        _render_ntds_summary(bundle),
        _render_protocol_summary(bundle),
        _render_daily(bundle),
        _render_warnings(bundle),
        _render_footer(bundle),
    ]
    body = "".join(p for p in parts if p)

    patient_name = _e(
        bundle.get("patient", {}).get("patient_name", "Casefile")
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{patient_name} — PI RN Casefile v1</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        f'<div class="container">{body}</div>\n'
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )


def render_casefile_to_file(bundle_path: Path, out_path: Path) -> None:
    """Load a bundle JSON and write the rendered HTML casefile."""
    bundle = _load_bundle(bundle_path)
    html_content = render_casefile(bundle)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content, encoding="utf-8")


# ── CLI ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render PI RN Casefile v1 HTML from patient_bundle_v1.json."
    )
    parser.add_argument(
        "--bundle", required=True,
        help="Path to patient_bundle_v1.json",
    )
    parser.add_argument(
        "--out", required=True,
        help="Output path for casefile_v1.html",
    )
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    if not bundle_path.is_file():
        print(f"Error: Bundle not found: {bundle_path}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    try:
        render_casefile_to_file(bundle_path, out_path)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"Error: Failed to render casefile: {exc}", file=sys.stderr)
        return 1
    print(f"OK  Casefile written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
