#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# PI RN Casefile Hub v1 — Generate and open the patient index
#
# Usage:
#   ./scripts/run_casefile_hub_v1.sh
#
# Scans existing patient bundles under outputs/casefile/*/
# and produces outputs/casefile/hub_v1.html.
#
# Environment:
#   CEREBRAL_NO_OPEN=1  — skip auto-open (for CI / sandbox)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  PI RN Casefile Hub v1 — Patient Index                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Generate hub ──────────────────────────────────────────────────

python3 -m cerebralos.reporting.render_casefile_hub_v1

HUB="outputs/casefile/hub_v1.html"

if [[ ! -f "$HUB" ]]; then
  echo "Error: Hub page was not produced at: $HUB" >&2
  exit 1
fi

echo ""
echo "────────────────────────────────────────────────────────────"
echo "  Hub ready: $HUB"
echo "────────────────────────────────────────────────────────────"

# ── Auto-open in browser ─────────────────────────────────────────

if [[ "${CEREBRAL_NO_OPEN:-0}" != "1" ]]; then
  echo "  Opening in browser..."
  if command -v open &>/dev/null; then
    open "$HUB"
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$HUB"
  else
    echo "  (Could not auto-open — open manually: $HUB)"
  fi
fi

echo ""
echo "Done."
