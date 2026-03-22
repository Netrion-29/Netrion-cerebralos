"""
PI RN Casefile Hub v1 — Local patient index page.

Scans ``outputs/casefile/*/patient_bundle_v1.json`` and renders a single
self-contained HTML index page at ``outputs/casefile/hub_v1.html``.

Deterministic: output depends only on bundle data. Fail-closed: bundles
that cannot be read are skipped with a warning (never inferred).
"""

from __future__ import annotations

import json
import html as html_mod
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constants ──────────────────────────────────────────────────────

DEFAULT_CASEFILE_ROOT = Path("outputs/casefile")
HUB_FILENAME = "hub_v1.html"
BUNDLE_FILENAME = "patient_bundle_v1.json"
CASEFILE_FILENAME = "casefile_v1.html"


# ── Card extraction ───────────────────────────────────────────────

def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    """Walk nested dicts safely; return *default* on any miss."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _compute_los(arrival: Optional[str], discharge: Optional[str]) -> Optional[int]:
    """Return integer LOS in days, or None if either date is missing."""
    if not arrival or not discharge:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            a = datetime.strptime(arrival, fmt)
            d = datetime.strptime(discharge, fmt)
            delta = (d - a).days
            return max(delta, 0)
        except ValueError:
            continue
    return None


def _format_date(raw: Optional[str]) -> Optional[str]:
    """Format datetime string to 'YYYY-MM-DD HH:MM' display."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return raw  # pass through as-is if unparseable


def _count_ntds(compliance: Optional[Dict], outcome: str) -> int:
    """Count NTDS event outcomes matching *outcome*."""
    ntds = _safe_get(compliance, "ntds_event_outcomes")
    if not isinstance(ntds, dict):
        return 0
    return sum(1 for v in ntds.values()
               if isinstance(v, dict) and v.get("outcome") == outcome)


def _count_protocol_noncompliant(compliance: Optional[Dict]) -> int:
    """Count protocol results with outcome NON_COMPLIANT."""
    results = _safe_get(compliance, "protocol_results")
    if not isinstance(results, list):
        return 0
    return sum(1 for r in results
               if isinstance(r, dict) and r.get("outcome") == "NON_COMPLIANT")


def extract_card(bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a patient card dict from a bundle. Returns None if required fields missing."""
    patient = bundle.get("patient")
    if not isinstance(patient, dict):
        return None
    name = patient.get("patient_name")
    slug = patient.get("slug")
    if not name or not slug:
        return None

    arrival = patient.get("arrival_datetime")
    discharge = patient.get("discharge_datetime")
    trauma_cat = patient.get("trauma_category")
    if trauma_cat == "DATA_NOT_AVAILABLE":
        trauma_cat = None

    compliance = bundle.get("compliance")

    return {
        "name": name,
        "slug": slug,
        "age": _safe_get(bundle, "summary", "age", "age_years"),
        "sex": _safe_get(bundle, "summary", "demographics", "sex"),
        "arrival": arrival,
        "arrival_display": _format_date(arrival),
        "discharge": discharge,
        "discharge_display": _format_date(discharge),
        "los_days": _compute_los(arrival, discharge),
        "trauma_category": trauma_cat,
        "mechanism": _safe_get(bundle, "summary", "mechanism", "mechanism_primary"),
        "body_regions": _safe_get(bundle, "summary", "mechanism", "body_region_labels") or [],
        "ntds_yes": _count_ntds(compliance, "YES"),
        "ntds_utd": _count_ntds(compliance, "UNABLE_TO_DETERMINE"),
        "ntds_total": len(_safe_get(compliance, "ntds_event_outcomes") or {}),
        "protocol_noncompliant": _count_protocol_noncompliant(compliance),
        "casefile_link": f"./{slug}/{CASEFILE_FILENAME}",
        "is_discharged": discharge is not None,
    }


# ── Bundle scanning ───────────────────────────────────────────────

def scan_bundles(casefile_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Scan casefile_root for patient bundles. Returns (cards, warnings)."""
    cards: List[Dict[str, Any]] = []
    warnings: List[str] = []

    if not casefile_root.is_dir():
        warnings.append(f"Casefile root not found: {casefile_root}")
        return cards, warnings

    for bundle_path in sorted(casefile_root.glob(f"*/{BUNDLE_FILENAME}")):
        slug = bundle_path.parent.name
        try:
            with open(bundle_path, "r", encoding="utf-8") as f:
                bundle = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"Skipped {slug}: {exc}")
            continue

        card = extract_card(bundle)
        if card is None:
            warnings.append(f"Skipped {slug}: missing required fields (patient_name or slug)")
            continue
        cards.append(card)

    return cards, warnings


# ── Sort helpers ──────────────────────────────────────────────────

def sort_cards(cards: list[dict[str, Any]], key: str = "arrival") -> list[dict[str, Any]]:
    """Sort cards by *key*. Default: arrival date newest first."""
    if key == "arrival":
        return sorted(cards, key=lambda c: c.get("arrival") or "", reverse=True)
    if key == "name":
        return sorted(cards, key=lambda c: c.get("name", "").lower())
    if key == "los":
        return sorted(cards, key=lambda c: c.get("los_days") or 0, reverse=True)
    if key == "ntds":
        return sorted(cards, key=lambda c: c.get("ntds_yes", 0), reverse=True)
    return cards


# ── HTML rendering ────────────────────────────────────────────────

def _e(text: Any) -> str:
    """HTML-escape a value, returning '—' for None."""
    if text is None:
        return "—"
    return html_mod.escape(str(text))


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
    margin: 0; padding: 24px; line-height: 1.55;
    -webkit-font-smoothing: antialiased; font-size: 14px;
}
h1,h2,h3 { margin: 0; font-weight: 700; }
.container { max-width: 1000px; margin: 0 auto; }

/* Header */
.hub-header {
    background: linear-gradient(135deg, var(--blue-700), var(--blue-800));
    color: white; padding: 24px 28px; border-radius: var(--card-radius);
    margin-bottom: 20px;
}
.hub-header h1 { font-size: 1.4em; margin-bottom: 2px; }
.hub-header .subtitle { opacity: 0.85; font-size: 0.85em; }

/* Toolbar */
.toolbar {
    display: flex; flex-wrap: wrap; gap: 10px;
    align-items: center; margin-bottom: 16px; padding: 0 2px;
}
.toolbar input[type=text] {
    flex: 1; min-width: 200px; padding: 8px 12px;
    border: 1px solid var(--slate-300); border-radius: 6px;
    font-size: 0.9em; outline: none;
}
.toolbar input[type=text]:focus {
    border-color: var(--blue-600); box-shadow: 0 0 0 2px var(--blue-100);
}
.toolbar select, .toolbar button {
    padding: 8px 12px; border: 1px solid var(--slate-300);
    border-radius: 6px; font-size: 0.85em; background: white;
    cursor: pointer;
}
.toolbar select:focus, .toolbar button:focus {
    border-color: var(--blue-600); outline: none;
}
.toolbar .count-badge {
    font-size: 0.82em; color: var(--slate-500); white-space: nowrap;
}

/* Patient cards */
.patient-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 12px;
}
.patient-card {
    background: white; border-radius: var(--card-radius);
    box-shadow: var(--card-shadow); border: 1px solid var(--slate-200);
    overflow: hidden; transition: box-shadow 0.15s, border-color 0.15s;
    display: flex; flex-direction: column;
}
.patient-card:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    border-color: var(--blue-200);
}
.patient-card a.card-link {
    text-decoration: none; color: inherit; display: flex;
    flex-direction: column; height: 100%; padding: 16px 18px;
}
.card-top { display: flex; justify-content: space-between; align-items: flex-start; }
.card-name { font-size: 1.05em; font-weight: 700; color: var(--slate-900); }
.card-slug { font-size: 0.78em; color: var(--slate-400); margin-top: 1px; }
.card-demo { font-size: 0.82em; color: var(--slate-500); margin-top: 6px; }

.card-meta {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 4px 12px; margin-top: 10px; font-size: 0.82em;
}
.card-meta dt { color: var(--slate-400); font-weight: 600; }
.card-meta dd { margin: 0; color: var(--slate-700); }

.card-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.badge {
    font-size: 0.75em; font-weight: 700; padding: 2px 8px;
    border-radius: 4px; white-space: nowrap;
}
.badge-red { background: var(--red-50); color: var(--red-700); border: 1px solid var(--red-100); }
.badge-amber { background: var(--amber-50); color: var(--amber-600); border: 1px solid var(--amber-100); }
.badge-green { background: var(--green-50); color: var(--green-700); border: 1px solid var(--green-100); }
.badge-slate { background: var(--slate-100); color: var(--slate-600); border: 1px solid var(--slate-200); }

.card-status {
    font-size: 0.72em; font-weight: 600; padding: 2px 6px;
    border-radius: 3px;
}
.status-discharged { background: var(--green-50); color: var(--green-700); }
.status-live { background: var(--amber-50); color: var(--amber-600); }

/* Warnings */
.hub-warnings {
    background: var(--amber-50); border: 1px solid var(--amber-100);
    border-radius: var(--card-radius); padding: 12px 16px;
    margin-bottom: 16px; font-size: 0.85em; color: var(--amber-600);
}
.hub-warnings p { margin: 0 0 4px; font-weight: 600; }
.hub-warnings ul { margin: 4px 0 0; padding-left: 20px; }

/* Empty state */
.hub-empty {
    text-align: center; padding: 48px 24px; color: var(--slate-400);
}
.hub-empty h2 { font-size: 1.1em; margin-bottom: 8px; }

/* Footer */
.hub-footer {
    text-align: center; margin-top: 24px; padding: 12px;
    font-size: 0.78em; color: var(--slate-400);
}

@media print {
    body { padding: 0; }
    .toolbar { display: none; }
    .patient-card { break-inside: avoid; }
}
"""

_JS = r"""
(function() {
    var searchInput = document.getElementById('hub-search');
    var sortSelect = document.getElementById('hub-sort');
    var filterSelect = document.getElementById('hub-filter');
    var grid = document.getElementById('hub-grid');
    var countEl = document.getElementById('hub-count');
    var cards = Array.from(grid.querySelectorAll('.patient-card'));

    function applyFilters() {
        var query = (searchInput.value || '').toLowerCase();
        var filter = filterSelect.value;
        var visible = 0;
        cards.forEach(function(card) {
            var name = (card.dataset.name || '').toLowerCase();
            var slug = (card.dataset.slug || '').toLowerCase();
            var status = card.dataset.status || '';
            var matchSearch = !query || name.indexOf(query) >= 0 || slug.indexOf(query) >= 0;
            var matchFilter = filter === 'all' ||
                (filter === 'discharged' && status === 'discharged') ||
                (filter === 'live' && status === 'live');
            if (matchSearch && matchFilter) { card.style.display = ''; visible++; }
            else { card.style.display = 'none'; }
        });
        countEl.textContent = visible + ' of ' + cards.length + ' patients';
    }

    function applySort() {
        var key = sortSelect.value;
        cards.sort(function(a, b) {
            if (key === 'name') return (a.dataset.name || '').localeCompare(b.dataset.name || '');
            if (key === 'arrival') {
                var aa = a.dataset.arrival || '', bb = b.dataset.arrival || '';
                return bb.localeCompare(aa);
            }
            if (key === 'los') return (parseFloat(b.dataset.los) || 0) - (parseFloat(a.dataset.los) || 0);
            if (key === 'ntds') return (parseInt(b.dataset.ntdsYes) || 0) - (parseInt(a.dataset.ntdsYes) || 0);
            return 0;
        });
        cards.forEach(function(card) { grid.appendChild(card); });
        applyFilters();
    }

    searchInput.addEventListener('input', applyFilters);
    filterSelect.addEventListener('change', applyFilters);
    sortSelect.addEventListener('change', applySort);
})();
"""


def _render_card_html(card: Dict[str, Any]) -> str:
    """Render a single patient card to HTML."""
    lines: list[str] = []
    status = "discharged" if card["is_discharged"] else "live"
    status_cls = "status-discharged" if card["is_discharged"] else "status-live"
    status_label = "Discharged" if card["is_discharged"] else "Active"

    lines.append(
        f'<div class="patient-card" '
        f'data-name="{_e(card["name"])}" '
        f'data-slug="{_e(card["slug"])}" '
        f'data-status="{status}" '
        f'data-arrival="{_e(card["arrival"] or "")}" '
        f'data-los="{card["los_days"] if card["los_days"] is not None else ""}" '
        f'data-ntds-yes="{card["ntds_yes"]}">'
    )
    lines.append(f'<a class="card-link" href="{_e(card["casefile_link"])}">')

    # Top row: name + status badge
    lines.append('<div class="card-top">')
    lines.append(f'<div><div class="card-name">{_e(card["name"])}</div>')
    lines.append(f'<div class="card-slug">{_e(card["slug"])}</div></div>')
    lines.append(f'<span class="card-status {status_cls}">{status_label}</span>')
    lines.append('</div>')

    # Demographics line
    demo_parts = []
    if card["age"] is not None:
        demo_parts.append(f'{_e(card["age"])}y')
    if card["sex"]:
        demo_parts.append(_e(card["sex"]))
    if card["mechanism"]:
        demo_parts.append(_e(card["mechanism"]).title())
    if demo_parts:
        lines.append(f'<div class="card-demo">{" · ".join(demo_parts)}</div>')

    # Meta grid
    lines.append('<dl class="card-meta">')
    lines.append(f'<dt>Arrival</dt><dd>{_e(card["arrival_display"])}</dd>')
    if card["is_discharged"]:
        lines.append(f'<dt>Discharge</dt><dd>{_e(card["discharge_display"])}</dd>')
    if card["los_days"] is not None:
        lines.append(f'<dt>LOS</dt><dd>{card["los_days"]}d</dd>')
    if card["trauma_category"]:
        lines.append(f'<dt>Trauma</dt><dd>{_e(card["trauma_category"])}</dd>')
    lines.append('</dl>')

    # Badges: NTDS + protocols
    lines.append('<div class="card-badges">')
    yes = card["ntds_yes"]
    utd = card["ntds_utd"]
    total = card["ntds_total"]
    if yes > 0:
        cls = "badge-red"
        lines.append(f'<span class="badge {cls}">NTDS YES {yes}</span>')
    if utd > 0:
        lines.append(f'<span class="badge badge-amber">UTD {utd}</span>')
    if yes == 0 and utd == 0 and total > 0:
        lines.append('<span class="badge badge-green">NTDS clear</span>')
    nc = card["protocol_noncompliant"]
    if nc > 0:
        lines.append(f'<span class="badge badge-red">Protocol NC {nc}</span>')
    lines.append('</div>')

    lines.append('</a></div>')
    return "\n".join(lines)


def render_hub(cards: list[dict[str, Any]], warnings: list[str],
               generated_at: Optional[str] = None) -> str:
    """Render the full hub HTML page. *cards* should already be sorted."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append("<title>PI RN Casefile Hub</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head><body>")
    parts.append('<div class="container">')

    # Header
    parts.append('<div class="hub-header">')
    parts.append("<h1>PI RN Casefile Hub</h1>")
    parts.append(f'<div class="subtitle">{len(cards)} patients · Generated {_e(generated_at)}</div>')
    parts.append("</div>")

    # Warnings
    if warnings:
        parts.append('<div class="hub-warnings">')
        parts.append("<p>Warnings</p><ul>")
        for w in warnings:
            parts.append(f"<li>{_e(w)}</li>")
        parts.append("</ul></div>")

    if not cards:
        parts.append('<div class="hub-empty">')
        parts.append("<h2>No patient casefiles found</h2>")
        parts.append("<p>Run the pipeline for a patient first:</p>")
        parts.append('<p><code>./scripts/run_casefile_v1.sh &quot;Betty Roll&quot;</code></p>')
        parts.append("</div>")
    else:
        # Toolbar
        parts.append('<div class="toolbar">')
        parts.append('<input type="text" id="hub-search" placeholder="Search by name…" autocomplete="off">')
        parts.append('<select id="hub-filter">')
        parts.append('<option value="all">All patients</option>')
        parts.append('<option value="discharged">Discharged</option>')
        parts.append('<option value="live">Active / in-house</option>')
        parts.append("</select>")
        parts.append('<select id="hub-sort">')
        parts.append('<option value="arrival">Newest arrival</option>')
        parts.append('<option value="name">Name A–Z</option>')
        parts.append('<option value="los">Longest LOS</option>')
        parts.append('<option value="ntds">Most NTDS YES</option>')
        parts.append("</select>")
        parts.append(f'<span class="count-badge" id="hub-count">{len(cards)} of {len(cards)} patients</span>')
        parts.append("</div>")

        # Grid
        parts.append('<div class="patient-grid" id="hub-grid">')
        for card in cards:
            parts.append(_render_card_html(card))
        parts.append("</div>")

    # Footer
    parts.append('<div class="hub-footer">')
    parts.append(f"CerebralOS · PI RN Casefile Hub v1 · {_e(generated_at)}")
    parts.append("</div>")

    parts.append("</div>")  # container

    if cards:
        parts.append(f"<script>{_JS}</script>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ── Public API ────────────────────────────────────────────────────

def generate_hub(casefile_root: Optional[Path] = None,
                 output_path: Optional[Path] = None,
                 generated_at: Optional[str] = None) -> Path:
    """
    Scan bundles, render hub HTML, write to disk.

    Returns the path of the written hub file.
    """
    if casefile_root is None:
        casefile_root = DEFAULT_CASEFILE_ROOT
    if output_path is None:
        output_path = casefile_root / HUB_FILENAME

    cards, warnings = scan_bundles(casefile_root)
    cards = sort_cards(cards, key="arrival")
    html = render_hub(cards, warnings, generated_at=generated_at)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


# ── CLI ───────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point: generate the hub and print the output path."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate PI RN Casefile Hub")
    parser.add_argument("--root", type=Path, default=DEFAULT_CASEFILE_ROOT,
                        help="Casefile root directory (default: outputs/casefile)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output HTML path (default: ROOT/hub_v1.html)")
    args = parser.parse_args()

    out = generate_hub(casefile_root=args.root, output_path=args.out)
    print(f"Hub written: {out}")


if __name__ == "__main__":
    main()
