#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# PI RN Casefile v1 — One-step patient casefile workflow
#
# Usage:
#   ./scripts/run_casefile_v1.sh "Betty Roll"
#   ./scripts/run_casefile_v1.sh Betty_Roll
#   ./scripts/run_casefile_v1.sh          # (prompts interactively)
#
# Runs the full canonical pipeline (evidence → timeline → features →
# NTDS → protocols → v3/v4/v5 → bundle → casefile HTML) and opens
# the resulting casefile in the default browser.
#
# Environment:
#   CEREBRAL_NO_OPEN=1  — skip auto-open (for CI / sandbox)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Patient input ──────────────────────────────────────────────────

PAT="${1:-}"

if [[ -z "$PAT" ]]; then
  echo "PI RN Casefile v1 — Patient Runner"
  echo "──────────────────────────────────"
  echo ""
  echo "Available patients in data_raw/:"
  echo ""
  for f in data_raw/*.txt; do
    [[ -e "$f" ]] || continue
    basename "$f" .txt
  done | sort | column
  echo ""
  read -rp "Enter patient name: " PAT
  if [[ -z "$PAT" ]]; then
    echo "Error: No patient name provided." >&2
    exit 1
  fi
fi

# ── Validate raw file exists ──────────────────────────────────────

# Strip .txt if provided
PAT="${PAT%.txt}"

RAW_FILE="data_raw/${PAT}.txt"
if [[ ! -f "$RAW_FILE" ]]; then
  # Try underscore variant (user may type "Betty Roll" or "Betty_Roll")
  PAT_UNDER="${PAT// /_}"
  RAW_FILE="data_raw/${PAT_UNDER}.txt"
  if [[ ! -f "$RAW_FILE" ]]; then
    # Try space variant (user may type "Betty_Roll" but file is "Betty Roll.txt")
    PAT_SPACE="${PAT//_/ }"
    RAW_FILE="data_raw/${PAT_SPACE}.txt"
    if [[ ! -f "$RAW_FILE" ]]; then
      echo "Error: Patient raw file not found." >&2
      echo "  Tried: data_raw/${PAT}.txt" >&2
      echo "         data_raw/${PAT_UNDER}.txt" >&2
      echo "         data_raw/${PAT_SPACE}.txt" >&2
      echo "" >&2
      echo "Available patients:" >&2
      ls data_raw/*.txt 2>/dev/null | xargs -I{} basename {} .txt | sort >&2
      exit 1
    fi
    # Use the original name from the filename for run_patient.sh
    PAT="$PAT_SPACE"
  else
    PAT="$PAT_UNDER"
  fi
fi

SLUG="${PAT// /_}"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  PI RN Casefile v1                                      ║"
echo "║  Patient: $(printf '%-45s' "$PAT")║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Run canonical pipeline ────────────────────────────────────────

export CEREBRAL_NTDS=1
export CEREBRAL_PROTOCOLS=1
export CEREBRAL_NO_OPEN=1

echo "Running canonical pipeline (run_patient.sh)..."
echo ""
./run_patient.sh "$PAT"

# ── Verify casefile was produced ──────────────────────────────────

CASEFILE="outputs/casefile/${SLUG}/casefile_v1.html"

if [[ ! -f "$CASEFILE" ]]; then
  echo "" >&2
  echo "Error: Casefile was not produced at: $CASEFILE" >&2
  echo "Check pipeline output above for errors." >&2
  exit 1
fi

echo ""
echo "────────────────────────────────────────────────────────────"
echo "  Casefile ready: $CASEFILE"
echo "────────────────────────────────────────────────────────────"

# ── Auto-open in browser ─────────────────────────────────────────

if [[ "${CEREBRAL_NO_OPEN:-0}" != "1" ]]; then
  echo "  Opening in browser..."
  if command -v open &>/dev/null; then
    open "$CASEFILE"
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$CASEFILE"
  else
    echo "  (Could not auto-open — open manually: $CASEFILE)"
  fi
fi

echo ""
echo "Done."
