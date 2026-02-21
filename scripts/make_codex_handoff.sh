#!/usr/bin/env bash
# scripts/make_codex_handoff.sh — generate outputs/audit/codex_handoff.md
# Usage: scripts/make_codex_handoff.sh <gate_output_file> [pass|fail]
set -euo pipefail

cd "$(dirname "$0")/.."

GATE_FILE="${1:?Usage: make_codex_handoff.sh <gate_output_file> [pass|fail]}"
GATE_STATUS="${2:-pass}"

OUTDIR="outputs/audit"
OUTFILE="$OUTDIR/codex_handoff.md"
mkdir -p "$OUTDIR"

# ── Gather data ─────────────────────────────────────────────
GIT_STATUS="$(git status 2>&1)"
FILES_TRACKED="$(git diff --name-status HEAD 2>/dev/null || echo '(unable to diff against HEAD)')"
FILES_UNTRACKED="$(git ls-files --others --exclude-standard 2>/dev/null || true)"
FILES_CHANGED="${FILES_TRACKED}"
if [ -n "$FILES_UNTRACKED" ]; then
  # Label untracked files with '?' prefix (like git status --short)
  UNTRACKED_LABELED="$(echo "$FILES_UNTRACKED" | sed 's/^/?\t/')"
  FILES_CHANGED="${FILES_CHANGED}
${UNTRACKED_LABELED}"
fi
BRANCH="$(git branch --show-current 2>/dev/null || echo 'unknown')"

# Gate output: tail for summary section
if [ -f "$GATE_FILE" ]; then
  GATE_TAIL="$(tail -60 "$GATE_FILE")"
else
  GATE_TAIL="(gate output file not found: $GATE_FILE)"
fi

# Extract baseline drift check block (from "Baseline drift check" through
# "No v4 drift" or "Updated baseline" or next section separator)
BASELINE_BLOCK="$(sed -n '/---- Baseline drift check/,/---- Running regression/{ /---- Running regression/!p; }' "$GATE_FILE" 2>/dev/null || true)"
if [ -z "$BASELINE_BLOCK" ]; then
  # Fallback: grab lines containing MATCH/MISMATCH/MISSING/drift/Updated
  BASELINE_BLOCK="$(grep -E '(MATCH|MISMATCH|MISSING|No v4 drift|Updated baseline|Baseline drift)' "$GATE_FILE" 2>/dev/null || echo '(baseline drift check not found in gate output)')"
fi

# Banner
if [ "$GATE_STATUS" = "pass" ]; then
  BANNER="Gate: PASSED"
else
  BANNER="Gate: FAILED — review output below"
fi

# ── No-go zones check ──────────────────────────────────────
NOGO_FILES=(
  "cerebralos/reporting/render_trauma_daily_notes_v3.py"
  "cerebralos/reporting/render_trauma_daily_notes_v4.py"
  "cerebralos/ntds_logic/engine.py"
  "cerebralos/protocol_engine/engine.py"
)
NOGO_SECTION=""
for f in "${NOGO_FILES[@]}"; do
  if echo "$FILES_CHANGED" | grep -qF "$f"; then
    NOGO_SECTION="${NOGO_SECTION}  - ${f}: **YES — CHANGED** (review required)\n"
  else
    NOGO_SECTION="${NOGO_SECTION}  - ${f}: NO (unchanged)\n"
  fi
done

# ── Write handoff markdown ──────────────────────────────────
cat > "$OUTFILE" <<EOF
# Codex Handoff — $(date '+%Y-%m-%d %H:%M:%S')

**${BANNER}**
**Branch**: ${BRANCH}

---

## Files changed (git diff --name-status HEAD)

\`\`\`
${FILES_CHANGED}
\`\`\`

---

## Baseline drift check

\`\`\`
${BASELINE_BLOCK}
\`\`\`

---

## No-go zones confirmation

$(printf '%b' "$NOGO_SECTION")

---

## Terminal output (gate tail)

\`\`\`
--- BEGIN TERMINAL OUTPUT ---
${GATE_TAIL}
--- END TERMINAL OUTPUT ---
\`\`\`

---

## git status

\`\`\`
${GIT_STATUS}
\`\`\`

---

## Request

Please audit the diff and provide:
1. \`git add\` / \`git commit\` / \`git push\` commands
2. Any corrections or follow-ups before merge
EOF

echo "Handoff written: $OUTFILE"
