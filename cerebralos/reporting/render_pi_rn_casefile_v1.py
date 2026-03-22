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
        f'<h1>{_e(name)}</h1>'
        f'<div class="subtitle">PI RN Casefile v1 &middot; LOS: {_e(los_str)}</div>'
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
    }
    cls = cls_map.get(o, "badge-excluded")
    return f'<span class="badge {cls}">{_e(o)}</span>'


def _render_ntds_summary(bundle: Dict[str, Any]) -> str:
    outcomes = bundle.get("compliance", {}).get("ntds_event_outcomes")
    if not outcomes or not isinstance(outcomes, dict):
        return ""

    # Count outcomes
    counts: Dict[str, int] = {}
    for ev in outcomes.values():
        o = ev.get("outcome", "")
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
        row_cls = ""
        if outcome == "YES":
            row_cls = ' class="row-yes"'
        elif outcome == "UNABLE_TO_DETERMINE":
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
    # vitals can be a list of readings or a dict
    readings = vitals if isinstance(vitals, list) else [vitals]
    if not readings:
        return ""
    # Use the first reading for a quick snapshot
    v = readings[0] if isinstance(readings[0], dict) else {}
    if not v:
        return ""
    chips = ""
    for key, label in [
        ("hr", "HR"), ("sbp", "SBP"), ("dbp", "DBP"), ("map", "MAP"),
        ("resp", "RR"), ("spo2", "SpO2"), ("temp", "Temp"),
    ]:
        val = v.get(key)
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
        _render_header(bundle),
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
    render_casefile_to_file(bundle_path, out_path)
    print(f"OK  Casefile written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
