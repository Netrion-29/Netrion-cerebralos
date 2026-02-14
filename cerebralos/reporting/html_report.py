#!/usr/bin/env python3
"""
CerebralOS HTML Report Generator — Elle Woods on a Trauma Committee.

Generates self-contained HTML patient reports with:
- Pink/gold/sparkle Elle Woods theme
- Protocol compliance results with evidence snippets
- NTDS hospital event results with gate traces
- Trauma summary (narrative fact-only)
- Trauma daily notes (per-calendar-day clinical snapshots)
- CSS-only donut chart, expand/collapse sections
- Mobile-responsive (iOS Safari 320px+)

No external dependencies. No CDN. No server required.
Open the .html file directly in any browser.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _e(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text)) if text else ""


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _build_css(is_live: bool = False) -> str:
    """Build complete inline CSS for Elle Woods theme."""
    return """
:root {
    --pink-50: #fdf2f8;
    --pink-100: #fce7f3;
    --pink-200: #fbcfe8;
    --pink-300: #f9a8d4;
    --pink-400: #f472b6;
    --pink-500: #ec4899;
    --pink-600: #db2777;
    --pink-700: #be185d;
    --pink-800: #9d174d;
    --gold-light: #fbbf24;
    --gold: #d4a843;
    --gold-dark: #b8860b;
    --gold-shimmer: #f59e0b;
    --emerald: #059669;
    --emerald-light: #d1fae5;
    --amber: #d97706;
    --amber-light: #fef3c7;
    --gray: #9ca3af;
    --gray-light: #f3f4f6;
    --text-primary: #1e1b4b;
    --text-secondary: #4c1d95;
    --bg: var(--pink-50);
    --card-bg: #ffffff;
    --card-shadow: rgba(236, 72, 153, 0.08);
    --card-radius: 12px;
}

*, *::before, *::after { box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text-primary);
    margin: 0;
    padding: 16px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
}

h1, h2, h3 {
    font-family: Georgia, "Times New Roman", Times, serif;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.container { max-width: 960px; margin: 0 auto; }

/* Shimmer header */
.header {
    background: linear-gradient(135deg, var(--pink-600), var(--gold), var(--pink-500), var(--gold-shimmer), var(--pink-600));
    background-size: 300% 300%;
    animation: shimmer 8s ease infinite;
    color: white;
    padding: 28px 32px;
    border-radius: var(--card-radius);
    margin-bottom: 20px;
    text-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
.header h1 { margin: 0 0 4px 0; font-size: 1.6em; }
.header .subtitle { opacity: 0.92; font-size: 0.95em; }
@keyframes shimmer {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

/* Live banner */
.live-banner {
    background: var(--pink-700);
    color: white;
    text-align: center;
    padding: 10px 16px;
    border-radius: var(--card-radius);
    margin-bottom: 16px;
    font-weight: 700;
    font-size: 0.95em;
    animation: pulse-live 2s ease-in-out infinite;
    letter-spacing: 0.05em;
}
@keyframes pulse-live {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

/* Patient info card */
.patient-card {
    background: var(--card-bg);
    border-radius: var(--card-radius);
    padding: 20px 24px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px var(--card-shadow);
    border-left: 4px solid var(--gold);
}
.patient-card .meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 8px 24px;
}
.meta-label { font-size: 0.78em; text-transform: uppercase; color: var(--gray); letter-spacing: 0.05em; }
.meta-value { font-weight: 600; font-size: 0.95em; }

/* Stat cards */
.stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
.stat-card {
    background: var(--card-bg);
    border-radius: var(--card-radius);
    padding: 16px;
    text-align: center;
    box-shadow: 0 2px 8px var(--card-shadow);
}
.stat-card .stat-num { font-size: 2em; font-weight: 800; line-height: 1.1; }
.stat-card .stat-label { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-top: 4px; }
.stat-nc { border-top: 4px solid var(--pink-500); }
.stat-nc .stat-num { color: var(--pink-600); }
.stat-ind { border-top: 4px solid var(--gold); }
.stat-ind .stat-num { color: var(--amber); }
.stat-comp { border-top: 4px solid var(--emerald); }
.stat-comp .stat-num { color: var(--emerald); }
.stat-nt { border-top: 4px solid var(--gray); }
.stat-nt .stat-num { color: var(--gray); }
.stat-yes { border-top: 4px solid var(--pink-500); }
.stat-yes .stat-num { color: var(--pink-600); }
.stat-unable { border-top: 4px solid var(--gold); }
.stat-unable .stat-num { color: var(--amber); }

/* Donut chart */
.donut-wrapper { text-align: center; margin-bottom: 20px; }
.donut {
    width: 160px; height: 160px;
    border-radius: 50%;
    margin: 0 auto 8px;
    position: relative;
}
.donut-label {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font-size: 0.82em; font-weight: 700;
    color: var(--text-primary);
    background: var(--bg);
    width: 90px; height: 90px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    text-align: center; line-height: 1.2;
}

/* Section headings */
.section-heading {
    font-size: 1.15em;
    margin: 24px 0 12px;
    padding-bottom: 6px;
    border-bottom: 2px solid var(--gold);
    color: var(--text-secondary);
}

/* Protocol / NTDS cards */
details.outcome-card {
    background: var(--card-bg);
    border-radius: var(--card-radius);
    margin-bottom: 10px;
    box-shadow: 0 1px 4px var(--card-shadow);
    border-left: 4px solid var(--gray);
    overflow: hidden;
}
details.outcome-card[data-outcome="NON_COMPLIANT"],
details.outcome-card[data-outcome="YES"] { border-left-color: var(--pink-500); }
details.outcome-card[data-outcome="INDETERMINATE"],
details.outcome-card[data-outcome="UNABLE_TO_DETERMINE"] { border-left-color: var(--gold); }
details.outcome-card[data-outcome="COMPLIANT"],
details.outcome-card[data-outcome="NO"] { border-left-color: var(--emerald); }
details.outcome-card[data-outcome="NOT_TRIGGERED"],
details.outcome-card[data-outcome="EXCLUDED"] { border-left-color: var(--gray); }

summary.card-summary {
    padding: 12px 16px;
    cursor: pointer;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    font-size: 0.92em;
}
summary.card-summary::-webkit-details-marker { display: none; }
summary.card-summary::before {
    content: "\\25B6";
    font-size: 0.7em;
    transition: transform 0.2s;
    color: var(--gray);
}
details.outcome-card[open] > summary.card-summary::before { transform: rotate(90deg); }

.outcome-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: white;
}
.badge-nc, .badge-yes { background: var(--pink-500); }
.badge-ind, .badge-unable { background: var(--gold); color: var(--text-primary); }
.badge-comp, .badge-no { background: var(--emerald); }
.badge-nt, .badge-excluded { background: var(--gray); }
.badge-error { background: #ef4444; }

.card-body { padding: 0 16px 16px; }

/* Evidence snippet */
.evidence-block {
    background: #fff1f2;
    border-left: 3px solid var(--gold);
    padding: 8px 12px;
    margin: 6px 0;
    border-radius: 0 6px 6px 0;
    font-family: "SF Mono", SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.78em;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 150px;
    overflow-y: auto;
}
.evidence-source {
    font-weight: 700;
    color: var(--text-secondary);
    font-size: 0.85em;
    margin-bottom: 2px;
}

/* Step / gate rows */
.step-row {
    padding: 6px 0;
    border-bottom: 1px solid var(--pink-100);
    font-size: 0.88em;
}
.step-row:last-child { border-bottom: none; }
.step-pass { color: var(--emerald); font-weight: 700; }
.step-fail { color: var(--pink-600); font-weight: 700; }
.step-reason { color: #64748b; font-size: 0.9em; margin-left: 12px; }
.missing-data { color: var(--amber); font-style: italic; font-size: 0.85em; margin-left: 12px; }

/* Contract sections */
.contract-section {
    background: var(--card-bg);
    border-radius: var(--card-radius);
    padding: 20px 24px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px var(--card-shadow);
    border-left: 4px solid var(--gold);
}
.contract-section h2 {
    margin-top: 0; font-size: 1.1em; color: var(--gold-dark);
    border-bottom: 2px solid var(--gold-light);
    padding-bottom: 8px;
    margin-bottom: 12px;
}
.contract-field {
    display: grid;
    grid-template-columns: minmax(180px, 240px) 1fr;
    gap: 4px 16px;
    padding: 6px 0;
    border-bottom: 1px solid var(--pink-50);
    font-size: 0.88em;
}
.contract-field:last-child { border-bottom: none; }
.field-label {
    font-weight: 700;
    font-size: 0.82em;
    text-transform: uppercase;
    color: var(--gold-dark);
    letter-spacing: 0.03em;
    padding-top: 2px;
}
.field-value {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 0.92em;
    line-height: 1.5;
    word-break: break-word;
}
.field-value.not-documented {
    color: var(--amber);
    font-style: italic;
}
.field-value.positive { color: var(--pink-600); font-weight: 600; }
.field-value.negative { color: var(--emerald); }

/* Green card — special styling */
.green-card {
    border-left: 4px solid var(--emerald);
    border-right: 4px solid var(--emerald);
}
.green-card h2 { color: var(--emerald); border-bottom-color: var(--emerald-light); }

/* Daily notes */
details.day-card {
    background: var(--card-bg);
    border-radius: var(--card-radius);
    margin-bottom: 8px;
    box-shadow: 0 1px 4px var(--card-shadow);
    border-left: 4px solid var(--gold-light);
    overflow: hidden;
}
summary.day-summary {
    padding: 10px 16px;
    cursor: pointer;
    font-weight: 600;
    font-size: 0.9em;
    color: var(--gold-dark);
    list-style: none;
}
summary.day-summary::-webkit-details-marker { display: none; }
summary.day-summary::before {
    content: "\\25B6";
    font-size: 0.65em;
    margin-right: 8px;
    transition: transform 0.2s;
    color: var(--gold);
}
details.day-card[open] > summary.day-summary::before { transform: rotate(90deg); }
.day-body { padding: 0 16px 12px; }

/* Compact lists */
.compact-list { list-style: none; padding: 0; margin: 0; }
.compact-list li {
    padding: 6px 12px;
    font-size: 0.88em;
    border-bottom: 1px solid var(--pink-50);
}
.compact-list li:last-child { border-bottom: none; }

/* Footer */
.footer {
    text-align: center;
    padding: 20px 0 8px;
    color: var(--gray);
    font-size: 0.78em;
    border-top: 2px solid var(--gold);
    margin-top: 32px;
}

/* Toggle all button */
.toggle-all {
    display: inline-block;
    background: var(--pink-100);
    color: var(--pink-700);
    border: 1px solid var(--pink-300);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 0.8em;
    font-weight: 600;
    cursor: pointer;
    margin-bottom: 12px;
}
.toggle-all:hover { background: var(--pink-200); }

/* Responsive */
@media (max-width: 600px) {
    body { padding: 8px; }
    .header { padding: 18px 16px; }
    .header h1 { font-size: 1.25em; }
    .stats-row { grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .patient-card .meta-grid { grid-template-columns: 1fr; }
    .contract-field { grid-template-columns: 1fr; gap: 2px; }
    .field-label { margin-bottom: 0; }
}
"""


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_live_banner(is_live: bool) -> str:
    if not is_live:
        return ""
    return '<div class="live-banner">LIVE — PATIENT IN HOSPITAL — PROVISIONAL RESULTS</div>\n'


def _build_patient_header(ev: Dict) -> str:
    name = _e(ev.get("patient_name") or "Unknown")
    pid = _e(ev.get("patient_id") or "Unknown")
    dob = _e(ev.get("dob") or "Unknown")
    arrival = _e(ev.get("arrival_time") or "Unknown")
    trauma_cat = _e(ev.get("trauma_category") or "N/A")
    blocks = ev.get("evidence_blocks", 0)
    status = "IN HOSPITAL" if ev.get("is_live") else "Discharged"
    source = _e(Path(ev.get("source_file", "")).name)

    return f"""<div class="patient-card">
<div class="meta-grid">
  <div><div class="meta-label">Patient</div><div class="meta-value">{name}</div></div>
  <div><div class="meta-label">MRN / ID</div><div class="meta-value">{pid}</div></div>
  <div><div class="meta-label">DOB</div><div class="meta-value">{dob}</div></div>
  <div><div class="meta-label">Arrival</div><div class="meta-value">{arrival}</div></div>
  <div><div class="meta-label">Trauma Category</div><div class="meta-value">{trauma_cat}</div></div>
  <div><div class="meta-label">Status</div><div class="meta-value">{status}</div></div>
  <div><div class="meta-label">Evidence Blocks</div><div class="meta-value">{blocks}</div></div>
  <div><div class="meta-label">Source</div><div class="meta-value">{source}</div></div>
</div>
</div>\n"""


def _build_trauma_summary(ev: Dict) -> str:
    """Build === TRAUMA SUMMARY === section per contract."""
    from cerebralos.reporting.trauma_doc_extractor import extract_trauma_summary

    fields = extract_trauma_summary(ev)
    if not fields:
        return ""

    parts = ['<div class="contract-section">']
    parts.append('<h2>TRAUMA SUMMARY</h2>')

    for label, value in fields.items():
        value_str = _e(str(value))
        # Determine CSS class based on content
        css_class = "field-value"
        if value_str in ("NOT DOCUMENTED IN SOURCE", "NONE DOCUMENTED"):
            css_class = "field-value not-documented"
        elif label == "NTDS complications present?" and value_str == "YES":
            css_class = "field-value positive"
        elif label == "NTDS complications present?" and value_str == "NO":
            css_class = "field-value negative"

        parts.append(f'<div class="contract-field">')
        parts.append(f'<div class="field-label">{_e(label)}</div>')
        parts.append(f'<div class="{css_class}">{value_str}</div>')
        parts.append('</div>')

    parts.append('</div>\n')
    return "\n".join(parts)


def _build_outcome_summary(ev: Dict) -> str:
    """Build stat cards + donut chart for protocol outcomes."""
    results = ev.get("results", [])
    ntds = ev.get("ntds_results", [])

    # Protocol counts
    nc = sum(1 for r in results if r["outcome"] == "NON_COMPLIANT")
    ind = sum(1 for r in results if r["outcome"] == "INDETERMINATE")
    comp = sum(1 for r in results if r["outcome"] == "COMPLIANT")
    nt = sum(1 for r in results if r["outcome"] == "NOT_TRIGGERED")
    triggered = nc + ind + comp

    # NTDS counts
    ntds_yes = sum(1 for r in ntds if r["outcome"] == "YES")
    ntds_unable = sum(1 for r in ntds if r["outcome"] == "UNABLE_TO_DETERMINE")

    # Donut chart
    total = max(nc + ind + comp + nt, 1)
    pct_nc = (nc / total) * 100
    pct_ind = (ind / total) * 100
    pct_comp = (comp / total) * 100
    pct_nt = (nt / total) * 100

    # Build conic-gradient stops
    stops = []
    cur = 0
    if nc > 0:
        stops.append(f"var(--pink-500) {cur}% {cur + pct_nc}%")
        cur += pct_nc
    if ind > 0:
        stops.append(f"var(--gold) {cur}% {cur + pct_ind}%")
        cur += pct_ind
    if comp > 0:
        stops.append(f"var(--emerald) {cur}% {cur + pct_comp}%")
        cur += pct_comp
    if nt > 0:
        stops.append(f"var(--gray-light) {cur}% {cur + pct_nt}%")
        cur += pct_nt

    gradient = ", ".join(stops) if stops else "var(--gray-light) 0% 100%"

    html_parts = []
    html_parts.append('<div class="donut-wrapper">')
    html_parts.append(f'<div class="donut" style="background: conic-gradient({gradient});">')
    html_parts.append(f'<div class="donut-label">{triggered} triggered<br>of {total}</div>')
    html_parts.append('</div></div>')

    # Stat cards
    html_parts.append('<div class="stats-row">')
    html_parts.append(f'<div class="stat-card stat-nc"><div class="stat-num">{nc}</div><div class="stat-label">Non-Compliant</div></div>')
    html_parts.append(f'<div class="stat-card stat-ind"><div class="stat-num">{ind}</div><div class="stat-label">Indeterminate</div></div>')
    html_parts.append(f'<div class="stat-card stat-comp"><div class="stat-num">{comp}</div><div class="stat-label">Compliant</div></div>')
    html_parts.append(f'<div class="stat-card stat-nt"><div class="stat-num">{nt}</div><div class="stat-label">Not Triggered</div></div>')
    html_parts.append(f'<div class="stat-card stat-yes"><div class="stat-num">{ntds_yes}</div><div class="stat-label">NTDS Yes</div></div>')
    html_parts.append(f'<div class="stat-card stat-unable"><div class="stat-num">{ntds_unable}</div><div class="stat-label">NTDS Unable</div></div>')
    html_parts.append('</div>\n')

    return "\n".join(html_parts)


def _build_evidence_snippets_html(snippets: List[Dict]) -> str:
    """Render evidence snippet blocks."""
    if not snippets:
        return ""
    parts = []
    for s in snippets:
        src = _e(s.get("source_type", ""))
        ts = _e(s.get("timestamp") or "")
        text = _e(s.get("text") or "").strip()
        if not text:
            continue
        # Truncate display
        display_text = text[:300]
        if len(text) > 300:
            display_text += "..."
        parts.append(f'<div class="evidence-block">')
        parts.append(f'<div class="evidence-source">[{src}] {ts}</div>')
        parts.append(f'{display_text}')
        parts.append(f'</div>')
    return "\n".join(parts)


def _badge_class(outcome: str) -> str:
    """Map outcome to badge CSS class."""
    mapping = {
        "NON_COMPLIANT": "badge-nc",
        "INDETERMINATE": "badge-ind",
        "COMPLIANT": "badge-comp",
        "NOT_TRIGGERED": "badge-nt",
        "YES": "badge-yes",
        "NO": "badge-no",
        "UNABLE_TO_DETERMINE": "badge-unable",
        "EXCLUDED": "badge-excluded",
        "ERROR": "badge-error",
    }
    return mapping.get(outcome, "badge-nt")


def _build_protocol_card(r: Dict, open_default: bool = False) -> str:
    """Build a single protocol result card."""
    outcome = r.get("outcome", "")
    name = _e(r.get("protocol_name", "Unknown"))
    badge = _badge_class(outcome)
    open_attr = " open" if open_default else ""

    parts = [f'<details class="outcome-card" data-outcome="{_e(outcome)}"{open_attr}>']
    parts.append(f'<summary class="card-summary">')
    parts.append(f'<span class="outcome-badge {badge}">{_e(outcome)}</span>')
    parts.append(f'<span>{name}</span>')
    parts.append(f'</summary>')
    parts.append(f'<div class="card-body">')

    for step in r.get("step_trace", []):
        from cerebralos.reporting.protocol_explainer import explain_requirement, explain_pattern_key

        req_id = step.get("requirement_id", "")
        req_name = explain_requirement(req_id)  # Plain language
        passed = step.get("passed", False)
        reason = _e(step.get("reason", ""))
        status_cls = "step-pass" if passed else "step-fail"
        status_txt = "PASS" if passed else "FAIL"

        parts.append(f'<div class="step-row">')
        parts.append(f'<span class="{status_cls}">{status_txt}</span> {_e(req_name)}')
        parts.append(f'<div class="step-reason">{reason}</div>')

        if step.get("missing_data"):
            # Plain language for missing items
            missing_explained = [explain_pattern_key(key) for key in step["missing_data"]]
            missing_html = "<br>".join(f"&nbsp;&nbsp;• {_e(m)}" for m in missing_explained)
            parts.append(f'<div class="missing-data">Missing:<br>{missing_html}</div>')

        # Evidence snippets
        snippets_html = _build_evidence_snippets_html(step.get("evidence_snippets", []))
        if snippets_html:
            parts.append(snippets_html)

        parts.append(f'</div>')

    if r.get("warnings"):
        for w in r["warnings"]:
            parts.append(f'<div class="missing-data">Warning: {_e(w)}</div>')

    parts.append('</div></details>')
    return "\n".join(parts)


def _build_protocol_sections(ev: Dict) -> str:
    """Build all protocol result sections grouped by outcome."""
    results = ev.get("results", [])
    if not results:
        return ""

    nc = [r for r in results if r["outcome"] == "NON_COMPLIANT"]
    ind = [r for r in results if r["outcome"] == "INDETERMINATE"]
    comp = [r for r in results if r["outcome"] == "COMPLIANT"]
    nt = [r for r in results if r["outcome"] == "NOT_TRIGGERED"]
    errors = [r for r in results if r["outcome"] == "ERROR"]

    parts = ['<h2 class="section-heading">Protocol Compliance</h2>']
    parts.append('<button class="toggle-all" onclick="toggleAll(\'protocol-section\')">Expand / Collapse All</button>')
    parts.append('<div id="protocol-section">')

    # NON_COMPLIANT — always open
    if nc:
        parts.append(f'<h3 style="color:var(--pink-600);margin:12px 0 8px;">Non-Compliant ({len(nc)})</h3>')
        for r in nc:
            parts.append(_build_protocol_card(r, open_default=True))

    # INDETERMINATE — always open
    if ind:
        parts.append(f'<h3 style="color:var(--amber);margin:12px 0 8px;">Indeterminate ({len(ind)})</h3>')
        for r in ind:
            parts.append(_build_protocol_card(r, open_default=True))

    # COMPLIANT — collapsed by default
    if comp:
        parts.append(f'<h3 style="color:var(--emerald);margin:12px 0 8px;">Compliant ({len(comp)})</h3>')
        for r in comp:
            parts.append(_build_protocol_card(r, open_default=False))

    # NOT_TRIGGERED — compact list
    if nt:
        parts.append(f'<h3 style="color:var(--gray);margin:12px 0 8px;">Not Triggered ({len(nt)})</h3>')
        parts.append('<ul class="compact-list">')
        for r in nt:
            parts.append(f'<li><span class="outcome-badge badge-nt">NOT TRIGGERED</span> {_e(r.get("protocol_name", ""))}</li>')
        parts.append('</ul>')

    # ERRORS
    if errors:
        parts.append(f'<h3 style="color:#ef4444;margin:12px 0 8px;">Errors ({len(errors)})</h3>')
        for r in errors:
            parts.append(f'<div class="step-row"><span class="step-fail">ERROR</span> {_e(r.get("protocol_name", ""))}: {_e(r.get("error", ""))}</div>')

    parts.append('</div>\n')
    return "\n".join(parts)


def _build_ntds_card(r: Dict, open_default: bool = False) -> str:
    """Build a single NTDS event result card."""
    outcome = r.get("outcome", "")
    eid = r.get("event_id", 0)
    name = _e(r.get("canonical_name", "Unknown"))
    badge = _badge_class(outcome)
    open_attr = " open" if open_default else ""

    parts = [f'<details class="outcome-card" data-outcome="{_e(outcome)}"{open_attr}>']
    parts.append(f'<summary class="card-summary">')
    parts.append(f'<span class="outcome-badge {badge}">{_e(outcome)}</span>')
    parts.append(f'<span>#{eid:02d} {name}</span>')
    parts.append(f'</summary>')
    parts.append(f'<div class="card-body">')

    for g in r.get("gate_trace", []):
        gate = _e(g.get("gate", ""))
        passed = g.get("passed", False)
        reason = _e(g.get("reason", ""))
        status_cls = "step-pass" if passed else "step-fail"
        status_txt = "PASS" if passed else "FAIL"

        parts.append(f'<div class="step-row">')
        parts.append(f'<span class="{status_cls}">{status_txt}</span> {gate}')
        parts.append(f'<div class="step-reason">{reason}</div>')

        snippets_html = _build_evidence_snippets_html(g.get("evidence_snippets", []))
        if snippets_html:
            parts.append(snippets_html)

        parts.append(f'</div>')

    parts.append('</div></details>')
    return "\n".join(parts)


def _build_ntds_section(ev: Dict) -> str:
    """Build NTDS hospital events section."""
    ntds = ev.get("ntds_results", [])
    if not ntds:
        return ""

    yes = [r for r in ntds if r["outcome"] == "YES"]
    unable = [r for r in ntds if r["outcome"] == "UNABLE_TO_DETERMINE"]
    no = [r for r in ntds if r["outcome"] == "NO"]
    excluded = [r for r in ntds if r["outcome"] == "EXCLUDED"]
    errors = [r for r in ntds if r["outcome"] == "ERROR"]

    parts = ['<h2 class="section-heading">NTDS Hospital Events (2026)</h2>']
    parts.append('<button class="toggle-all" onclick="toggleAll(\'ntds-section\')">Expand / Collapse All</button>')
    parts.append('<div id="ntds-section">')

    if yes:
        parts.append(f'<h3 style="color:var(--pink-600);margin:12px 0 8px;">Events Detected — YES ({len(yes)})</h3>')
        for r in yes:
            parts.append(_build_ntds_card(r, open_default=True))

    if unable:
        parts.append(f'<h3 style="color:var(--amber);margin:12px 0 8px;">Unable to Determine ({len(unable)})</h3>')
        for r in unable:
            parts.append(_build_ntds_card(r, open_default=True))

    if no:
        parts.append(f'<h3 style="color:var(--emerald);margin:12px 0 8px;">No Event ({len(no)})</h3>')
        parts.append('<ul class="compact-list">')
        for r in no:
            parts.append(f'<li><span class="outcome-badge badge-no">NO</span> #{r.get("event_id", 0):02d} {_e(r.get("canonical_name", ""))}</li>')
        parts.append('</ul>')

    if excluded:
        parts.append(f'<h3 style="color:var(--gray);margin:12px 0 8px;">Excluded ({len(excluded)})</h3>')
        parts.append('<ul class="compact-list">')
        for r in excluded:
            parts.append(f'<li><span class="outcome-badge badge-excluded">EXCLUDED</span> #{r.get("event_id", 0):02d} {_e(r.get("canonical_name", ""))}</li>')
        parts.append('</ul>')

    if errors:
        parts.append(f'<h3 style="color:#ef4444;margin:12px 0 8px;">Errors ({len(errors)})</h3>')
        for r in errors:
            parts.append(f'<div class="step-row"><span class="step-fail">ERROR</span> #{r.get("event_id", 0):02d}: {_e(r.get("error", ""))}</div>')

    parts.append('</div>\n')
    return "\n".join(parts)


def _build_daily_notes(ev: Dict) -> str:
    """Build === TRAUMA DAILY NOTES === section per contract."""
    from cerebralos.reporting.trauma_doc_extractor import extract_daily_notes

    daily = extract_daily_notes(ev)
    if not daily:
        return ""

    parts = ['<h2 class="section-heading">TRAUMA DAILY NOTES</h2>']

    for i, day in enumerate(daily):
        date = _e(day["date"])
        open_attr = " open" if i == 0 else ""  # First day (admission) open by default

        parts.append(f'<details class="day-card"{open_attr}>')
        parts.append(f'<summary class="day-summary">[{date}]</summary>')
        parts.append('<div class="day-body">')

        for label, value in day["fields"].items():
            value_str = _e(str(value))
            css_class = "field-value"
            if value_str in ("NOT DOCUMENTED IN SOURCE", "NONE DOCUMENTED"):
                css_class = "field-value not-documented"

            parts.append(f'<div class="contract-field">')
            parts.append(f'<div class="field-label">{_e(label)}</div>')
            parts.append(f'<div class="{css_class}">{value_str}</div>')
            parts.append('</div>')

        parts.append('</div></details>')

    parts.append("")
    return "\n".join(parts)


def _build_green_card(ev: Dict) -> str:
    """Build === GREEN CARD === section per contract."""
    from cerebralos.reporting.trauma_doc_extractor import extract_green_card

    fields = extract_green_card(ev)
    if not fields:
        return ""

    parts = ['<div class="contract-section green-card">']
    parts.append('<h2>GREEN CARD</h2>')

    for label, value in fields.items():
        value_str = _e(str(value))
        css_class = "field-value"
        if value_str in ("NOT DOCUMENTED IN SOURCE", "NONE DOCUMENTED"):
            css_class = "field-value not-documented"
        elif label == "Mortality (YES/NO)" and value_str == "YES":
            css_class = "field-value positive"
        elif label == "Mortality (YES/NO)" and value_str == "NO":
            css_class = "field-value negative"

        parts.append(f'<div class="contract-field">')
        parts.append(f'<div class="field-label">{_e(label)}</div>')
        parts.append(f'<div class="{css_class}">{value_str}</div>')
        parts.append('</div>')

    parts.append('</div>\n')
    return "\n".join(parts)


def _build_js() -> str:
    """Build minimal JS for expand/collapse all."""
    return """
<script>
function toggleAll(sectionId) {
    var section = document.getElementById(sectionId);
    if (!section) return;
    var details = section.querySelectorAll('details');
    var anyOpen = false;
    for (var i = 0; i < details.length; i++) {
        if (details[i].open) { anyOpen = true; break; }
    }
    for (var i = 0; i < details.length; i++) {
        details[i].open = !anyOpen;
    }
}
</script>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_patient_html(
    evaluation: Dict[str, Any],
    output_path: Optional[Path] = None,
) -> str:
    """
    Generate a self-contained HTML patient report.

    Args:
        evaluation: Patient evaluation dict from batch_eval.evaluate_patient()
        output_path: Optional path to write HTML file

    Returns:
        Complete HTML string.
    """
    name = evaluation.get("patient_name") or evaluation.get("patient_id") or "Unknown"
    is_live = evaluation.get("is_live", False)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_parts = []

    # DOCTYPE + head
    html_parts.append('<!DOCTYPE html>')
    html_parts.append('<html lang="en">')
    html_parts.append('<head>')
    html_parts.append('<meta charset="UTF-8">')
    html_parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_parts.append(f'<title>CerebralOS &mdash; {_e(name)}</title>')
    html_parts.append(f'<style>{_build_css(is_live)}</style>')
    html_parts.append('</head>')
    html_parts.append('<body>')
    html_parts.append('<div class="container">')

    # Header
    html_parts.append('<div class="header">')
    html_parts.append('<h1>CerebralOS</h1>')
    html_parts.append('<div class="subtitle">Governance Engine &mdash; Protocol Compliance &amp; NTDS Report</div>')
    html_parts.append('</div>')

    # Live banner
    html_parts.append(_build_live_banner(is_live))

    # Patient info
    html_parts.append(_build_patient_header(evaluation))

    # === TRAUMA SUMMARY === (contract section 1)
    html_parts.append(_build_trauma_summary(evaluation))

    # === TRAUMA DAILY NOTES === (contract section 2)
    html_parts.append(_build_daily_notes(evaluation))

    # === GREEN CARD === (contract section 3)
    html_parts.append(_build_green_card(evaluation))

    # Outcome summary (donut + stat cards)
    html_parts.append(_build_outcome_summary(evaluation))

    # Protocol sections
    html_parts.append(_build_protocol_sections(evaluation))

    # NTDS section
    html_parts.append(_build_ntds_section(evaluation))

    # Footer
    html_parts.append(f'<div class="footer">')
    html_parts.append(f'Report generated: {_e(now)}<br>')
    html_parts.append(f'CerebralOS Governance Engine v2026.01')
    html_parts.append(f'</div>')

    html_parts.append('</div>')  # container
    html_parts.append(_build_js())
    html_parts.append('</body>')
    html_parts.append('</html>')

    result = "\n".join(html_parts)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result, encoding="utf-8")

    return result
