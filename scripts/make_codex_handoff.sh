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
BRANCH="$(git branch --show-current 2>/dev/null || echo 'unknown')"

# Branch diff vs origin/main — the authoritative changeset for PR review.
# Falls back to HEAD-only diff if origin/main is unavailable (e.g. shallow clone).
if git rev-parse --verify origin/main >/dev/null 2>&1; then
  FILES_BRANCH="$(git diff --name-status origin/main...HEAD 2>/dev/null || true)"
  DIFF_BASIS="origin/main...HEAD"
else
  FILES_BRANCH="$(git diff --name-status HEAD 2>/dev/null || true)"
  DIFF_BASIS="HEAD (fallback — origin/main not available)"
fi

# Uncommitted working-tree changes (staged + unstaged vs HEAD)
FILES_WIP="$(git diff --name-status HEAD 2>/dev/null || true)"

# Untracked files
FILES_UNTRACKED="$(git ls-files --others --exclude-standard 2>/dev/null || true)"

# Combine branch diff + WIP + untracked for the full picture.
# Branch diff is the primary section; WIP/untracked are appended if non-empty.
FILES_CHANGED="${FILES_BRANCH}"
if [ -n "$FILES_WIP" ]; then
  FILES_CHANGED="${FILES_CHANGED}
# uncommitted (working tree vs HEAD):
${FILES_WIP}"
fi
if [ -n "$FILES_UNTRACKED" ]; then
  UNTRACKED_LABELED="$(echo "$FILES_UNTRACKED" | sed 's/^/?\t/')"
  FILES_CHANGED="${FILES_CHANGED}
# untracked:
${UNTRACKED_LABELED}"
fi

# For no-go zone checks, use the branch diff as the primary source
# (catches committed changes that the old HEAD-only diff missed).
NOGO_CHECK_LIST="${FILES_BRANCH}"
if [ -n "$FILES_WIP" ]; then
  NOGO_CHECK_LIST="${NOGO_CHECK_LIST}
${FILES_WIP}"
fi

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
  if echo "$NOGO_CHECK_LIST" | grep -qF "$f"; then
    NOGO_SECTION="${NOGO_SECTION}  - ${f}: **YES — CHANGED** (review required)\n"
  else
    NOGO_SECTION="${NOGO_SECTION}  - ${f}: NO (unchanged)\n"
  fi
done

# ── Cohort invariant summary ────────────────────────────────
COHORT_SUMMARY="$(python3 scripts/audit_cohort_counts.py --markdown 2>/dev/null || echo '(cohort invariant summary unavailable)')"

# ── Write handoff markdown ──────────────────────────────────
cat > "$OUTFILE" <<EOF
# Codex Handoff — $(date '+%Y-%m-%d %H:%M:%S')

**${BANNER}**
**Branch**: ${BRANCH}

---

## Files changed (${DIFF_BASIS})

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

${COHORT_SUMMARY}

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
