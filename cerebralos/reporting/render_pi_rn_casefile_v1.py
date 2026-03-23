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

/* Day summary badge */
.day-badge { font-size: 0.72em; font-weight: 600; padding: 2px 8px; border-radius: 10px; margin-left: auto; }
.day-badge-data { background: var(--green-100); color: var(--green-700); }
.day-badge-empty { background: var(--slate-100); color: var(--slate-400); }

/* Plan notes */
.plan-note { margin-bottom: 8px; padding: 6px 0; border-bottom: 1px solid var(--slate-100); }
.plan-note:last-child { border-bottom: none; }
.plan-note-header { font-size: 0.78em; font-weight: 700; color: var(--slate-600); margin-bottom: 3px; }
.plan-note-meta { font-size: 0.72em; color: var(--slate-400); margin-bottom: 3px; }
.plan-lines { font-size: 0.86em; padding: 0; margin: 2px 0 0 16px; }
.plan-lines li { padding: 1px 0; }
.impression-lines { color: var(--slate-600); font-style: italic; }

/* Consultant plan items */
.consult-service { margin-bottom: 8px; }
.consult-service-name { font-size: 0.82em; font-weight: 700; color: var(--blue-700); margin-bottom: 3px; }
.consult-item { font-size: 0.86em; padding: 3px 0; border-bottom: 1px solid var(--slate-50); }
.consult-item:last-child { border-bottom: none; }
.consult-item-meta { font-size: 0.72em; color: var(--slate-400); }

/* GCS severity */
.gcs-ok { color: var(--green-700); font-weight: 700; }
.gcs-mod { color: var(--amber-600); font-weight: 700; }
.gcs-severe { color: var(--red-600); font-weight: 700; }

/* Lab flag highlighting */
.lab-flag { color: var(--red-600); font-weight: 600; font-size: 0.85em; }

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

/* Injury / Imaging / Procedure tables */
.clinical-tbl { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.clinical-tbl th {
    text-align: left; padding: 6px 10px; background: var(--slate-100);
    font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--slate-500); border-bottom: 2px solid var(--slate-200);
}
.clinical-tbl td { padding: 6px 10px; border-bottom: 1px solid var(--slate-100); vertical-align: top; }
.clinical-tbl tr:last-child td { border-bottom: none; }
.finding-label { font-weight: 600; color: var(--slate-700); }
.finding-detail { font-size: 0.88em; color: var(--slate-500); }
.proc-ts { font-size: 0.82em; color: var(--slate-500); white-space: nowrap; }
.proc-label { font-weight: 600; }
.proc-cat { font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.03em; padding: 2px 6px; border-radius: 3px;
    display: inline-block; }
.proc-cat-operative { background: var(--blue-100); color: var(--blue-700); }
.proc-cat-anesthesia { background: var(--amber-100); color: var(--amber-600); }
.proc-cat-pre-op { background: var(--slate-100); color: var(--slate-600); }
.proc-cat-significant { background: var(--red-100); color: var(--red-600); }

/* Device (LDA) table */
.dev-status { font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    padding: 2px 6px; border-radius: 3px; display: inline-block; letter-spacing: 0.03em; }
.dev-active { background: var(--green-100); color: var(--green-700); }
.dev-removed { background: var(--slate-100); color: var(--slate-500); }
.dev-cat { font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    padding: 2px 6px; border-radius: 3px; display: inline-block;
    letter-spacing: 0.03em; background: var(--blue-100); color: var(--blue-700); }

/* Prophylaxis table */
.proph-status { font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    padding: 2px 6px; border-radius: 3px; display: inline-block; letter-spacing: 0.03em; }
.proph-ok { background: var(--green-100); color: var(--green-700); }
.proph-delay { background: var(--amber-100); color: var(--amber-600); }
.proph-excluded { background: var(--slate-100); color: var(--slate-500); }
.proph-none { background: var(--red-50); color: var(--red-600); }
.proph-detected { background: var(--blue-100); color: var(--blue-700); }
.proph-not-detected { background: var(--slate-100); color: var(--slate-500); }

/* Resuscitation / hemodynamic summary */
.resus-indicator { font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    padding: 2px 6px; border-radius: 3px; display: inline-block; letter-spacing: 0.03em; }
.resus-positive { background: var(--red-50); color: var(--red-600); }
.resus-negative { background: var(--green-100); color: var(--green-700); }
.resus-neutral { background: var(--slate-100); color: var(--slate-500); }
.resus-warn { background: var(--amber-100); color: var(--amber-600); }
.resus-sub { font-size: 0.82em; color: var(--slate-500); margin-top: 2px; }
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
    return f'<div class="status-bar">{"".join(chips)}</div>'


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
    utd_n = sum(1 for v in ntds.values() if isinstance(v, dict) and str(v.get("outcome", "")).upper() in ("UTD", "UNABLE_TO_DETERMINE"))
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
    _ay = age_data.get("age_years") if isinstance(age_data, dict) else None
    if _ay is None:
        _ay = age_data.get("age") if isinstance(age_data, dict) else None
    age = str(_ay) if _ay is not None else "\u2014"
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


def _render_primary_injuries(bundle: Dict[str, Any]) -> str:
    """Render structured injury findings from radiology_findings_v1.

    Groups findings by type (fractures, hemorrhage, organ injuries).
    Fail-closed: returns empty string when data absent.
    """
    injuries = bundle.get("summary", {}).get("injuries")
    if not injuries or not isinstance(injuries, dict):
        return ""
    if injuries.get("findings_present") != "yes":
        return ""

    rows = ""

    # ── Singular findings (object|null) ──
    _SINGULAR = [
        ("pelvic_fracture", "Pelvic Fracture"),
        ("spinal_fracture", "Spinal Fracture"),
        ("rib_fracture", "Rib Fracture"),
        ("flail_chest", "Flail Chest"),
        ("pneumothorax", "Pneumothorax"),
        ("hemothorax", "Hemothorax"),
    ]
    for key, display in _SINGULAR:
        obj = injuries.get(key)
        if not isinstance(obj, dict) or not obj.get("present"):
            continue
        details: List[str] = []
        if key == "spinal_fracture" and obj.get("level"):
            details.append(f"Level: {_e(str(obj['level']))}")
        if key == "rib_fracture":
            if obj.get("count"):
                details.append(f"Count: {_e(str(obj['count']))}")
            if obj.get("rib_numbers"):
                details.append(f"Ribs: {_e(', '.join(str(r) for r in obj['rib_numbers']))}")
        if key == "pneumothorax" and obj.get("subtype"):
            details.append(f"Subtype: {_e(str(obj['subtype']))}")
        if key == "hemothorax" and obj.get("qualifier"):
            details.append(f"Qualifier: {_e(str(obj['qualifier']))}")
        if obj.get("laterality"):
            details.append(f"Laterality: {_e(str(obj['laterality']))}")
        detail_str = f'<div class="finding-detail">{"; ".join(details)}</div>' if details else ""
        rows += f'<tr><td class="finding-label">{_e(display)}</td><td>{detail_str}</td></tr>'

    # ── List findings (list[object]) ──
    for ich in injuries.get("intracranial_hemorrhage", []):
        if isinstance(ich, dict) and ich.get("present"):
            subtype = ich.get("subtype", "unspecified")
            rows += f'<tr><td class="finding-label">Intracranial Hemorrhage</td><td><div class="finding-detail">Subtype: {_e(str(subtype).upper())}</div></td></tr>'

    for soi in injuries.get("solid_organ_injuries", []):
        if isinstance(soi, dict) and soi.get("present"):
            organ = soi.get("organ", "unknown")
            grade = soi.get("grade")
            detail = f"Organ: {_e(str(organ).title())}"
            if grade:
                detail += f"; AAST Grade {_e(str(grade))}"
            lat = soi.get("laterality")
            if lat:
                detail += f"; {_e(str(lat))}"
            rows += f'<tr><td class="finding-label">Solid Organ Injury</td><td><div class="finding-detail">{detail}</div></td></tr>'

    for ef in injuries.get("extremity_fracture", []):
        if isinstance(ef, dict) and ef.get("present"):
            bone = ef.get("bone", "unknown")
            parts: List[str] = []
            if ef.get("laterality"):
                parts.append(f"{_e(str(ef['laterality']))}")
            if ef.get("pathologic"):
                parts.append("pathologic")
            detail = _e(str(bone).title())
            if parts:
                detail += f' ({", ".join(parts)})'
            rows += f'<tr><td class="finding-label">Extremity Fracture</td><td><div class="finding-detail">{detail}</div></td></tr>'

    if not rows:
        return ""

    table = (
        '<table class="clinical-tbl">'
        "<thead><tr><th>Finding</th><th>Details</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return (
        '<div class="card">'
        '<div class="card-title">Primary Injuries</div>'
        f'<div class="card-body">{table}</div>'
        "</div>"
    )


def _render_imaging_studies(bundle: Dict[str, Any]) -> str:
    """Render imaging evidence trail from radiology_findings_v1.

    Shows study source, timestamp, and finding snippet from evidence items.
    Fail-closed: returns empty string when data absent.
    """
    imaging = bundle.get("summary", {}).get("imaging")
    if not imaging or not isinstance(imaging, dict):
        return ""
    evidence = imaging.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        return ""

    rows = ""
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        source = ev.get("source", "")
        ts = ev.get("ts", "")
        label = ev.get("label", "")
        snippet = ev.get("snippet", "")
        # Truncate long snippets for display
        if len(snippet) > 150:
            snippet = snippet[:147] + "..."
        rows += (
            f"<tr>"
            f'<td class="proc-ts">{_e(ts)}</td>'
            f"<td>{_e(source)}</td>"
            f'<td class="finding-label">{_e(str(label).replace("_", " ").title())}</td>'
            f"<td>{_e(snippet)}</td>"
            f"</tr>"
        )

    if not rows:
        return ""

    table = (
        '<table class="clinical-tbl">'
        "<thead><tr><th>Timestamp</th><th>Source</th><th>Finding</th><th>Excerpt</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return (
        '<div class="card">'
        '<div class="card-title">Imaging Studies</div>'
        f'<div class="card-body">{table}</div>'
        "</div>"
    )


def _render_procedures(bundle: Dict[str, Any]) -> str:
    """Render operative / procedural timeline from procedure_operatives_v1.

    Chronological list of procedure events with category badges.
    Fail-closed: returns empty string when data absent.
    """
    procs = bundle.get("summary", {}).get("procedures")
    if not procs or not isinstance(procs, dict):
        return ""
    events = procs.get("events", [])
    if not isinstance(events, list) or not events:
        return ""

    _CAT_CLS = {
        "operative": "proc-cat-operative",
        "anesthesia": "proc-cat-anesthesia",
        "pre-op": "proc-cat-pre-op",
        "significant_event": "proc-cat-significant",
    }

    rows = ""
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ts = ev.get("ts", "")
        category = ev.get("category", "")
        label = ev.get("label") or ""
        # Truncate very long auto-extracted labels
        if len(label) > 120:
            label = label[:117] + "..."
        preop_dx = ev.get("preop_dx", "")
        status = ev.get("status", "")

        cat_cls = _CAT_CLS.get(category, "proc-cat-operative")
        cat_badge = f'<span class="proc-cat {cat_cls}">{_e(category)}</span>' if category else ""

        detail_parts: List[str] = []
        if preop_dx:
            dx_display = preop_dx if len(preop_dx) <= 100 else preop_dx[:97] + "..."
            detail_parts.append(f"Dx: {_e(dx_display)}")
        if status:
            detail_parts.append(f"Status: {_e(status)}")
        cpt = ev.get("cpt_codes", [])
        if cpt:
            detail_parts.append(f"CPT: {_e(', '.join(str(c) for c in cpt))}")
        detail_str = f'<div class="finding-detail">{"; ".join(detail_parts)}</div>' if detail_parts else ""

        rows += (
            f"<tr>"
            f'<td class="proc-ts">{_e(ts)}</td>'
            f"<td>{cat_badge}</td>"
            f'<td class="proc-label">{_e(label)}{detail_str}</td>'
            f"</tr>"
        )

    if not rows:
        return ""

    # Summary counts
    proc_ct = procs.get("procedure_event_count", 0)
    op_ct = procs.get("operative_event_count", 0)
    anes_ct = procs.get("anesthesia_event_count", 0)
    total = len(events)
    summary_line = f"{total} event{'s' if total != 1 else ''}"
    if proc_ct or op_ct or anes_ct:
        parts = []
        if proc_ct:
            parts.append(f"{proc_ct} procedure{'s' if proc_ct != 1 else ''}")
        if op_ct:
            parts.append(f"{op_ct} operative{'s' if op_ct != 1 else ''}")
        if anes_ct:
            parts.append(f"{anes_ct} anesthesia")
        summary_line += f" ({', '.join(parts)})"
    summary_html = f'<div style="font-size:0.82em;color:var(--slate-500);margin-bottom:8px;">{_e(summary_line)}</div>'

    table = (
        '<table class="clinical-tbl">'
        "<thead><tr><th>Timestamp</th><th>Category</th><th>Procedure / Event</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return (
        '<div class="card">'
        '<div class="card-title">Operative / Procedural Timeline</div>'
        f'<div class="card-body">{summary_html}{table}</div>'
        "</div>"
    )


def _render_devices(bundle: Dict[str, Any]) -> str:
    """Render LDA device inventory from lda_events_v1.

    Shows device table with category, type, placement/removal, duration, status.
    Fail-closed: returns empty string when data absent.
    """
    devs = bundle.get("summary", {}).get("devices")
    if not devs or not isinstance(devs, dict):
        return ""
    devices = devs.get("devices", [])
    if not isinstance(devices, list) or not devices:
        return ""

    rows = ""
    for d in devices:
        if not isinstance(d, dict):
            continue
        category = d.get("category", "")
        dtype = d.get("device_type", "")
        placed = d.get("placed_ts", "")
        removed = d.get("removed_ts", "")
        duration = d.get("duration_text", "")
        site = d.get("site", "")

        is_active = bool(placed and not removed)
        status_cls = "dev-active" if is_active else "dev-removed"
        status_text = "Active" if is_active else ("Removed" if removed else "\u2014")
        status_badge = f'<span class="dev-status {status_cls}">{status_text}</span>'
        cat_badge = f'<span class="dev-cat">{_e(category)}</span>' if category else ""

        rows += (
            "<tr>"
            f"<td>{cat_badge}</td>"
            f"<td>{_e(dtype)}</td>"
            f'<td class="proc-ts">{_na(placed)}</td>'
            f'<td class="proc-ts">{_na(removed)}</td>'
            f"<td>{_na(duration)}</td>"
            f"<td>{_na(site)}</td>"
            f"<td>{status_badge}</td>"
            "</tr>"
        )

    if not rows:
        return ""

    total = devs.get("lda_device_count", len(devices))
    active = devs.get("active_devices_count", 0)
    cats = devs.get("categories_present", [])
    summary_parts = [f"{total} device{'s' if total != 1 else ''}"]
    if active:
        summary_parts.append(f"{active} active")
    if cats:
        summary_parts.append(", ".join(str(c) for c in cats))
    summary_line = " \u2014 ".join(summary_parts)
    summary_html = f'<div style="font-size:0.82em;color:var(--slate-500);margin-bottom:8px;">{_e(summary_line)}</div>'

    table = (
        '<table class="clinical-tbl">'
        "<thead><tr>"
        "<th>Category</th><th>Device</th><th>Placed</th><th>Removed</th>"
        "<th>Duration</th><th>Site</th><th>Status</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return (
        '<div class="card">'
        '<div class="card-title">Lines / Drains / Airways</div>'
        f'<div class="card-body">{summary_html}{table}</div>'
        "</div>"
    )


def _render_prophylaxis(bundle: Dict[str, Any]) -> str:
    """Render prophylaxis summary (DVT, GI, seizure).

    Shows status, timing, delay flags, and exclusion reasons.
    Fail-closed: returns empty string when all prophylaxis data absent.
    """
    summary = bundle.get("summary", {})
    dvt = summary.get("dvt_prophylaxis")
    gi = summary.get("gi_prophylaxis")
    szr = summary.get("seizure_prophylaxis")
    if not any(isinstance(x, dict) for x in (dvt, gi, szr)):
        return ""

    # Sentinel values that mean "no evidence found" — not a real clinical exclusion
    _NO_EVIDENCE_SENTINELS = frozenset({
        "NO_CHEMICAL_PROPHYLAXIS_EVIDENCE",
        "NO_GI_PROPHYLAXIS_EVIDENCE",
    })

    rows = ""

    # DVT prophylaxis
    if isinstance(dvt, dict):
        excluded = dvt.get("excluded_reason")
        pharm_ts = dvt.get("pharm_first_ts")
        mech_ts = dvt.get("mech_first_ts")
        delay_h = dvt.get("delay_hours")
        delay_flag = dvt.get("delay_flag_24h")

        if excluded and excluded not in _NO_EVIDENCE_SENTINELS:
            status_cls = "proph-excluded"
            status_text = f"Excluded: {excluded}"
        elif pharm_ts:
            if delay_flag:
                status_cls = "proph-delay"
                status_text = "Pharmacologic started (delayed >24h)"
            else:
                status_cls = "proph-ok"
                status_text = "Pharmacologic started"
        elif mech_ts:
            status_cls = "proph-ok"
            status_text = "Mechanical only"
        else:
            status_cls = "proph-none"
            status_text = "No evidence"

        detail_parts: List[str] = []
        if pharm_ts:
            detail_parts.append(f"Pharm: {_e(str(pharm_ts))}")
        if mech_ts:
            detail_parts.append(f"Mech: {_e(str(mech_ts))}")
        if delay_h is not None:
            detail_parts.append(f"Delay: {delay_h:.1f}h")
        detail = f'<div class="finding-detail">{"; ".join(detail_parts)}</div>' if detail_parts else ""

        rows += (
            "<tr>"
            '<td class="finding-label">DVT Prophylaxis</td>'
            f'<td><span class="proph-status {status_cls}">{_e(status_text)}</span>{detail}</td>'
            "</tr>"
        )

    # GI prophylaxis
    if isinstance(gi, dict):
        excluded = gi.get("excluded_reason")
        pharm_ts = gi.get("pharm_first_ts")
        delay_h = gi.get("delay_hours")
        delay_flag = gi.get("delay_flag_48h")

        if excluded and excluded not in _NO_EVIDENCE_SENTINELS:
            status_cls = "proph-excluded"
            status_text = f"Excluded: {excluded}"
        elif pharm_ts:
            if delay_flag:
                status_cls = "proph-delay"
                status_text = "Started (delayed >48h)"
            else:
                status_cls = "proph-ok"
                status_text = "Started"
        else:
            status_cls = "proph-none"
            status_text = "No evidence"

        detail_parts_gi: List[str] = []
        if pharm_ts:
            detail_parts_gi.append(f"First: {_e(str(pharm_ts))}")
        if delay_h is not None:
            detail_parts_gi.append(f"Delay: {delay_h:.1f}h")
        detail = f'<div class="finding-detail">{"; ".join(detail_parts_gi)}</div>' if detail_parts_gi else ""

        rows += (
            "<tr>"
            '<td class="finding-label">GI Prophylaxis</td>'
            f'<td><span class="proph-status {status_cls}">{_e(status_text)}</span>{detail}</td>'
            "</tr>"
        )

    # Seizure prophylaxis
    if isinstance(szr, dict):
        detected = szr.get("detected", False)
        agents = szr.get("agents", [])
        admin_ts = szr.get("first_admin_ts")
        discontinued = szr.get("discontinued", False)

        if detected:
            status_cls = "proph-detected"
            agent_str = ", ".join(str(a) for a in agents) if agents else "detected"
            status_text = agent_str
        else:
            status_cls = "proph-not-detected"
            status_text = "Not detected"

        detail_parts_szr: List[str] = []
        if admin_ts:
            detail_parts_szr.append(f"First admin: {_e(str(admin_ts))}")
        if discontinued:
            disc_ts = szr.get("discontinued_ts")
            if disc_ts:
                detail_parts_szr.append(f"D/C: {_e(str(disc_ts))}")
            else:
                detail_parts_szr.append("Discontinued")
        detail = f'<div class="finding-detail">{"; ".join(detail_parts_szr)}</div>' if detail_parts_szr else ""

        rows += (
            "<tr>"
            '<td class="finding-label">Seizure Prophylaxis</td>'
            f'<td><span class="proph-status {status_cls}">{_e(status_text)}</span>{detail}</td>'
            "</tr>"
        )

    if not rows:
        return ""

    table = (
        '<table class="clinical-tbl">'
        "<thead><tr><th>Measure</th><th>Status / Detail</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return (
        '<div class="card">'
        '<div class="card-title">Prophylaxis Summary</div>'
        f'<div class="card-body">{table}</div>'
        "</div>"
    )


def _render_resuscitation(bundle: Dict[str, Any]) -> str:
    """Render Resuscitation / Hemodynamic Summary card.

    Covers hemodynamic instability patterns, blood product administration,
    and base deficit monitoring. Fail-closed: returns empty string when
    all three upstream modules are absent/null.
    """
    summary = bundle.get("summary", {})
    hemo = summary.get("hemodynamic_instability")
    tx = summary.get("transfusions")
    bd = summary.get("base_deficit")

    # Fail-closed: skip entire section when no data
    if not any(isinstance(x, dict) for x in (hemo, tx, bd)):
        return ""

    sections: List[str] = []

    # ── Hemodynamic instability ──────────────────────────────
    if isinstance(hemo, dict):
        present = hemo.get("pattern_present", "no")
        patterns = hemo.get("patterns_detected", [])
        abnormal = hemo.get("total_abnormal_readings", 0)
        total_vit = hemo.get("total_vitals_readings", 0)

        if present == "yes" and patterns:
            badge_cls = "resus-positive"
            badge_text = "Instability detected"
        else:
            badge_cls = "resus-negative"
            badge_text = "No instability detected"

        detail_parts: List[str] = []
        for pname in ("hypotension_pattern", "map_low_pattern",
                      "tachycardia_pattern"):
            pdata = hemo.get(pname)
            if isinstance(pdata, dict) and pdata.get("detected"):
                threshold = pdata.get("threshold", "")
                rc = pdata.get("reading_count", 0)
                da = pdata.get("days_affected", 0)
                label = pname.replace("_pattern", "").replace("_", " ").title()
                detail_parts.append(
                    f"{_e(label)}: {rc} reading{'s' if rc != 1 else ''}"
                    f" over {da} day{'s' if da != 1 else ''}"
                    f" ({_e(threshold)})"
                )

        if total_vit:
            detail_parts.append(
                f"Abnormal: {abnormal}/{total_vit} vitals readings"
            )

        detail = ""
        if detail_parts:
            detail = '<div class="resus-sub">' + "<br>".join(detail_parts) + "</div>"

        sections.append(
            "<tr>"
            '<td class="finding-label">Hemodynamic Instability</td>'
            f'<td><span class="resus-indicator {badge_cls}">{_e(badge_text)}</span>'
            f"{detail}</td></tr>"
        )

    # ── Blood products / transfusion ─────────────────────────
    if isinstance(tx, dict):
        status = tx.get("status", "DATA NOT AVAILABLE")
        total_ev = tx.get("total_events", 0)
        products = tx.get("products_detected", [])
        mtp = tx.get("mtp_activated", False)
        txa = tx.get("txa_administered", False)

        if status == "DATA NOT AVAILABLE" and total_ev == 0 and not mtp and not txa:
            badge_cls = "resus-neutral"
            badge_text = "No blood products documented"
        elif total_ev > 0 or products:
            badge_cls = "resus-positive"
            badge_text = f"{total_ev} transfusion event{'s' if total_ev != 1 else ''}"
        else:
            badge_cls = "resus-neutral"
            badge_text = "No transfusion events"

        detail_parts_tx: List[str] = []
        for prod_key, label in [
            ("prbc_events", "pRBC"), ("ffp_events", "FFP"),
            ("platelet_events", "Platelets"), ("cryo_events", "Cryo"),
        ]:
            count = tx.get(prod_key, 0)
            if count:
                detail_parts_tx.append(f"{label}: {count}")
        if mtp:
            detail_parts_tx.append("MTP activated")
        if txa:
            detail_parts_tx.append("TXA administered")
        if products and not detail_parts_tx:
            detail_parts_tx.append("Products: " + ", ".join(str(p) for p in products))

        detail_tx = ""
        if detail_parts_tx:
            detail_tx = '<div class="resus-sub">' + "; ".join(detail_parts_tx) + "</div>"

        sections.append(
            "<tr>"
            '<td class="finding-label">Blood Products</td>'
            f'<td><span class="resus-indicator {badge_cls}">{_e(badge_text)}</span>'
            f"{detail_tx}</td></tr>"
        )

    # ── Base deficit monitoring ───────────────────────────────
    if isinstance(bd, dict):
        initial_val = bd.get("initial_bd_value")
        trigger = bd.get("trigger_bd_gt4")
        series = bd.get("bd_series", [])
        compliant = bd.get("overall_compliant")
        nc_reasons = bd.get("noncompliance_reasons", [])
        notes = bd.get("notes", [])
        initial_ts = bd.get("initial_bd_ts")

        has_data = initial_val is not None or (isinstance(series, list) and len(series) > 0)

        if not has_data:
            badge_cls = "resus-neutral"
            badge_text = "No base deficit data"
        elif trigger:
            if compliant is False:
                badge_cls = "resus-warn"
                badge_text = "BD trigger — non-compliant monitoring"
            else:
                badge_cls = "resus-positive"
                badge_text = "BD trigger present"
        else:
            badge_cls = "resus-negative"
            badge_text = "BD within range"

        detail_parts_bd: List[str] = []
        if initial_val is not None:
            ts_str = f" at {_e(str(initial_ts))}" if initial_ts else ""
            detail_parts_bd.append(f"Initial BD: {initial_val}{ts_str}")
        if isinstance(series, list) and len(series) > 1:
            detail_parts_bd.append(f"{len(series)} BD measurements")
        if compliant is False and nc_reasons:
            for r in nc_reasons[:3]:
                detail_parts_bd.append(f"Non-compliant: {_e(str(r))}")

        detail_bd = ""
        if detail_parts_bd:
            detail_bd = '<div class="resus-sub">' + "<br>".join(detail_parts_bd) + "</div>"

        sections.append(
            "<tr>"
            '<td class="finding-label">Base Deficit</td>'
            f'<td><span class="resus-indicator {badge_cls}">{_e(badge_text)}</span>'
            f"{detail_bd}</td></tr>"
        )

    if not sections:
        return ""

    table = (
        '<table class="clinical-tbl">'
        "<thead><tr><th>Indicator</th><th>Status</th></tr></thead>"
        f'<tbody>{"".join(sections)}</tbody></table>'
    )
    return (
        '<div class="card">'
        '<div class="card-title">Resuscitation / Hemodynamic Summary</div>'
        f'<div class="card-body">{table}</div>'
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
    """Render GCS for a single day.

    Real bundle shape:
      gcs.arrival_gcs_value: int
      gcs.best_gcs: {value, intubated, source, dt}
      gcs.worst_gcs: {value, intubated, source, dt}
      gcs.all_readings: [{value, intubated, source}]
    Also supports legacy shape: {best, eye, verbal, motor}.
    """
    if not gcs or not isinstance(gcs, dict):
        return ""
    parts = []
    # ── Real nested shape ──
    total = gcs.get("arrival_gcs_value")
    best_obj = gcs.get("best_gcs")
    worst_obj = gcs.get("worst_gcs")
    if total is not None or best_obj or worst_obj:
        score = total
        if score is None and isinstance(best_obj, dict):
            score = best_obj.get("value")
        if score is not None:
            sev_cls = "gcs-ok" if int(score) >= 13 else ("gcs-mod" if int(score) >= 9 else "gcs-severe")
            parts.append(f'<span class="{sev_cls}">GCS {_e(str(score))}</span>')
        if isinstance(best_obj, dict) and isinstance(worst_obj, dict):
            b_val = best_obj.get("value")
            w_val = worst_obj.get("value")
            if b_val is not None and w_val is not None and b_val != w_val:
                parts.append(f"Best {_e(str(b_val))} / Worst {_e(str(w_val))}")
    else:
        # ── Legacy flat shape ──
        best = gcs.get("best")
        e = gcs.get("eye")
        v = gcs.get("verbal")
        m = gcs.get("motor")
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
    """Render structured labs for a single day.

    Real bundle shape:
      labs.latest: {component_name: {value_raw, value_num, flags, unit}}
      labs.daily: dict
      labs.series: dict
    Also supports legacy shape: {panel_name: {analyte: value}}.
    """
    if not labs or not isinstance(labs, dict):
        return ""
    items = ""
    # ── Detect canonical shape by presence of known top-level keys ──
    _CANONICAL_KEYS = {"latest", "daily", "series"}
    is_canonical = bool(_CANONICAL_KEYS & labs.keys())

    if is_canonical:
        # ── Real nested shape: {"latest": {comp: {value_raw, flags, ...}}} ──
        latest = labs.get("latest")
        if isinstance(latest, dict) and latest:
            for comp_name in sorted(latest.keys()):
                comp = latest[comp_name]
                if not isinstance(comp, dict):
                    continue
                val = comp.get("value_raw", comp.get("value_num", ""))
                if val is None or val == "":
                    continue
                unit = comp.get("unit", "")
                flags = comp.get("flags", []) or []
                flag_str = ""
                if flags:
                    flag_str = f' <span class="lab-flag">({" ".join(_e(str(f)) for f in flags)})</span>'
                unit_str = f" {_e(unit)}" if unit else ""
                items += (
                    f'<div class="day-kv">'
                    f'<span class="dk">{_e(comp_name)}:</span> '
                    f'{_e(str(val))}{unit_str}{flag_str}'
                    "</div>"
                )
        # canonical shape with empty latest → return empty (fail-closed)
    else:
        # ── Legacy flat shape: {panel: {analyte: value}} ──
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
    """Render trauma daily plan / changes in course for a single day.

    Real bundle shape:
      plans.notes: [{note_type, author, dt, impression_lines, plan_lines, raw_line_id}]
    Also supports legacy shapes: plain string, flat dict, or list.
    """
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
        # ── Real nested shape: {"notes": [...]} ──
        notes = plans.get("notes")
        if isinstance(notes, list):
            if not notes:
                return ""
            parts = ""
            for note in notes:
                if not isinstance(note, dict):
                    continue
                note_type = note.get("note_type", "")
                author = note.get("author", "")
                dt = note.get("dt", "")
                header = _e(note_type) if note_type else "Note"
                meta_parts = [p for p in [_e(author), _e(dt)] if p]
                meta = f'<div class="plan-note-meta">{", ".join(meta_parts)}</div>' if meta_parts else ""

                impression = note.get("impression_lines", []) or []
                plan_lines = note.get("plan_lines", []) or []

                imp_html = ""
                if impression:
                    imp_items = "".join(f"<li>{_e(str(ln))}</li>" for ln in impression if ln)
                    if imp_items:
                        imp_html = f'<ul class="plan-lines impression-lines">{imp_items}</ul>'

                plan_html = ""
                if plan_lines:
                    plan_items = "".join(f"<li>{_e(str(ln))}</li>" for ln in plan_lines if ln)
                    if plan_items:
                        plan_html = f'<ul class="plan-lines">{plan_items}</ul>'

                if imp_html or plan_html:
                    parts += (
                        f'<div class="plan-note">'
                        f'<div class="plan-note-header">{header}</div>'
                        f'{meta}{imp_html}{plan_html}'
                        '</div>'
                    )
            if parts:
                return (
                    '<div class="day-section">'
                    '<div class="day-section-title">Course / Plan</div>'
                    f'{parts}</div>'
                )
            return ""
        # ── Legacy flat dict shape ──
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
    """Render consultant plans for a single day.

    Real bundle shape:
      cp.services: {service_name: {items: [{item_text, item_type, author_name, ts, evidence}]}}
      cp.service_count: int
      cp.item_count: int
    Also supports legacy shapes: flat {service: plan_text} dict or list.
    """
    if not cp:
        return ""
    if isinstance(cp, dict):
        # ── Real nested shape: {"services": {...}} ──
        services = cp.get("services")
        if isinstance(services, dict) and services:
            parts = ""
            for svc_name in sorted(services.keys()):
                svc_data = services[svc_name]
                if not isinstance(svc_data, dict):
                    continue
                items_list = svc_data.get("items", [])
                if not isinstance(items_list, list) or not items_list:
                    continue
                item_html = ""
                for item in items_list:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("item_text", "")
                    if not text:
                        continue
                    author = item.get("author_name", "")
                    ts = item.get("ts", "")
                    meta_parts = [p for p in [_e(author), _e(ts)] if p]
                    meta = f' <span class="consult-item-meta">{", ".join(meta_parts)}</span>' if meta_parts else ""
                    item_html += f'<div class="consult-item">{_e(text)}{meta}</div>'
                if item_html:
                    parts += (
                        f'<div class="consult-service">'
                        f'<div class="consult-service-name">{_e(svc_name)}</div>'
                        f'{item_html}'
                        '</div>'
                    )
            if parts:
                return (
                    '<div class="day-section">'
                    '<div class="day-section-title">Consultant Plans</div>'
                    f'{parts}</div>'
                )
            return ""
        # ── Legacy flat dict shape: {service_name: plan_text} ──
        items = ""
        for service, plan in sorted(cp.items()):
            if plan is not None and not isinstance(plan, dict):
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
        _render_primary_injuries(bundle),
        _render_imaging_studies(bundle),
        _render_procedures(bundle),
        _render_devices(bundle),
        _render_prophylaxis(bundle),
        _render_resuscitation(bundle),
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
