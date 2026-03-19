#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# ── Audit output directory ──────────────────────────────────
GATE_LOG="outputs/audit/last_gate_output.txt"
HANDOFF_FILE="outputs/audit/codex_handoff.md"
mkdir -p outputs/audit

# ── gate_body: all original gate logic lives here ───────────
gate_body() {
set -euo pipefail   # re-enable inside function/subshell (pipeline runs in subshell)

BASELINE_FILE="scripts/baselines/v4_hashes_v1.json"
V5_BASELINE_FILE="scripts/baselines/v5_hashes_v1.json"
V3_BASELINE_FILE="scripts/baselines/v3_hashes_v1.json"
UPDATE_BASELINE=0
UPDATE_BASELINE_V5=0
UPDATE_BASELINE_V3=0
ARGS=()

for arg in "$@"; do
  if [ "$arg" = "--update-baseline" ]; then
    UPDATE_BASELINE=1
  elif [ "$arg" = "--update-baseline-v5" ]; then
    UPDATE_BASELINE_V5=1
  elif [ "$arg" = "--update-baseline-v3" ]; then
    UPDATE_BASELINE_V3=1
  else
    ARGS+=("$arg")
  fi
done

if [ "${#ARGS[@]}" -gt 0 ]; then
  PATS=()
  for pat in "${ARGS[@]}"; do
    # Accept either the raw filename stem or the underscore slug.
    if [ -f "data_raw/${pat}.txt" ]; then
      PATS+=("$pat")
    elif [ -f "data_raw/${pat//_/ }.txt" ]; then
      PATS+=("${pat//_/ }")
    else
      echo "ERROR: no data_raw file for: $pat" >&2; exit 1
    fi
  done
else
  PATS=("Betty Roll" "David_Gross" "Johnny Stokes" "Larry_Corne" "Ronald Bittner" "Roscella Weatherly")
fi

echo "=============================================="
echo "CerebralOS PR Gate"
echo "Repo: $(pwd)"
echo "Baseline v3: $V3_BASELINE_FILE"
echo "Baseline v4: $BASELINE_FILE"
echo "Baseline v5: $V5_BASELINE_FILE"
if [ "$UPDATE_BASELINE" -eq 1 ]; then
  echo "Mode: update v4 baseline"
elif [ "$UPDATE_BASELINE_V5" -eq 1 ]; then
  echo "Mode: update v5 baseline"
elif [ "$UPDATE_BASELINE_V3" -eq 1 ]; then
  echo "Mode: update v3 baseline"
else
  echo "Mode: validate against baseline"
fi
echo "=============================================="

TMP_HASHES="$(mktemp)"
TMP_V5_HASHES="$(mktemp)"
TMP_V3_HASHES="$(mktemp)"
trap 'rm -f "$TMP_HASHES" "$TMP_V5_HASHES" "$TMP_V3_HASHES"' EXIT

for PAT in "${PATS[@]}"; do
  SLUG="${PAT// /_}"
  echo
  echo "---- Running pipeline for: $PAT (slug: $SLUG) ----"
  ./run_patient.sh "$PAT"

  echo "---- v4 hash: $SLUG ----"
  HASH="$(shasum -a 256 "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v4.txt" | awk '{print $1}')"
  echo "$HASH  outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v4.txt"
  printf '%s %s\n' "$SLUG" "$HASH" >> "$TMP_HASHES"

  echo "---- v5 hash: $SLUG ----"
  V5_HASH="$(shasum -a 256 "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v5.txt" | awk '{print $1}')"
  echo "$V5_HASH  outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v5.txt"
  printf '%s %s\n' "$SLUG" "$V5_HASH" >> "$TMP_V5_HASHES"

  echo "---- v3 hash: $SLUG ----"
  V3_HASH="$(shasum -a 256 "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt" | awk '{print $1}')"
  echo "$V3_HASH  outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt"
  printf '%s %s\n' "$SLUG" "$V3_HASH" >> "$TMP_V3_HASHES"
done

echo
echo "---- Baseline drift check ----"
python3 - "$BASELINE_FILE" "$TMP_HASHES" "$UPDATE_BASELINE" <<'PY'
import json
import sys
from pathlib import Path

baseline_path = Path(sys.argv[1])
current_path = Path(sys.argv[2])
update_baseline = sys.argv[3] == "1"

current = {}
for line in current_path.read_text(encoding="utf-8").splitlines():
    pat, sha = line.strip().split()
    current[pat] = sha

if update_baseline:
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated baseline: {baseline_path}")
    sys.exit(0)

if not baseline_path.is_file():
    print(f"ERROR: baseline file not found: {baseline_path}")
    print("Run: ./scripts/gate_pr.sh --update-baseline")
    sys.exit(1)

baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
ok = True
all_pats = sorted(set(list(current) + list(baseline)))
for pat in all_pats:
    cur = current.get(pat)
    base = baseline.get(pat)
    if cur is None:
        print(f"MISSING in current run: {pat} (expected by baseline)")
        ok = False
    elif base is None:
        print(f"MISSING in baseline: {pat} (present in current run)")
        ok = False
    elif base != cur:
        print(f"MISMATCH {pat}: baseline={base} current={cur}")
        ok = False
    else:
        print(f"MATCH   {pat}: {cur}")

if not ok:
    sys.exit(1)

print("No v4 drift relative to stored baseline.")
PY

echo
echo "---- v5 baseline drift check ----"
python3 - "$V5_BASELINE_FILE" "$TMP_V5_HASHES" "$UPDATE_BASELINE_V5" <<'PY'
import json
import sys
from pathlib import Path

baseline_path = Path(sys.argv[1])
current_path = Path(sys.argv[2])
update_baseline = sys.argv[3] == "1"

current = {}
for line in current_path.read_text(encoding="utf-8").splitlines():
    pat, sha = line.strip().split()
    current[pat] = sha

if update_baseline:
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated v5 baseline: {baseline_path}")
    sys.exit(0)

if not baseline_path.is_file():
    print(f"ERROR: v5 baseline file not found: {baseline_path}")
    print("Run: ./scripts/gate_pr.sh --update-baseline-v5")
    sys.exit(1)

baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
ok = True
all_pats = sorted(set(list(current) + list(baseline)))
for pat in all_pats:
    cur = current.get(pat)
    base = baseline.get(pat)
    if cur is None:
        print(f"MISSING in current run: {pat} (expected by v5 baseline)")
        ok = False
    elif base is None:
        print(f"MISSING in v5 baseline: {pat} (present in current run)")
        ok = False
    elif base != cur:
        print(f"MISMATCH {pat}: v5 baseline={base} current={cur}")
        ok = False
    else:
        print(f"MATCH   {pat}: {cur}")

if not ok:
    sys.exit(1)

print("No v5 drift relative to stored baseline.")
PY

echo
echo "---- v3 baseline drift check ----"
python3 - "$V3_BASELINE_FILE" "$TMP_V3_HASHES" "$UPDATE_BASELINE_V3" <<'PY'
import json
import sys
from pathlib import Path

baseline_path = Path(sys.argv[1])
current_path = Path(sys.argv[2])
update_baseline = sys.argv[3] == "1"

current = {}
for line in current_path.read_text(encoding="utf-8").splitlines():
    pat, sha = line.strip().split()
    current[pat] = sha

if update_baseline:
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated v3 baseline: {baseline_path}")
    sys.exit(0)

if not baseline_path.is_file():
    print(f"ERROR: v3 baseline file not found: {baseline_path}")
    print("Run: ./scripts/gate_pr.sh --update-baseline-v3")
    sys.exit(1)

baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
ok = True
all_pats = sorted(set(list(current) + list(baseline)))
for pat in all_pats:
    cur = current.get(pat)
    base = baseline.get(pat)
    if cur is None:
        print(f"MISSING in current run: {pat} (expected by v3 baseline)")
        ok = False
    elif base is None:
        print(f"MISSING in v3 baseline: {pat} (present in current run)")
        ok = False
    elif base != cur:
        print(f"MISMATCH {pat}: v3 baseline={base} current={cur}")
        ok = False
    else:
        print(f"MATCH   {pat}: {cur}")

if not ok:
    sys.exit(1)

print("No v3 drift relative to stored baseline.")
PY

echo
echo "---- NTDS baseline drift check ----"
python3 scripts/check_ntds_hashes.py

echo
echo "---- NTDS per-event distribution check ----"
python3 scripts/check_ntds_distribution.py

echo
echo "---- Running full test suite (pytest) ----"
PYTHONPATH=. python3 -m pytest tests/ -q

echo
echo "---- Running regression ----"
python3 _regression_phase1_v2.py

echo
echo "---- Cohort invariant check ----"
python3 scripts/audit_cohort_counts.py --check

echo
echo "Gate complete."

}  # end gate_body

# ── Run gate, tee to log, preserve exit code ────────────────
# pipefail (set at top) ensures PIPESTATUS[0] reflects gate_body's
# real exit code.  We disable -e for this one pipeline so that a
# gate failure doesn't abort before we can capture the RC and
# generate the handoff artifact.
set +e
gate_body "$@" 2>&1 | tee "$GATE_LOG"
GATE_RC="${PIPESTATUS[0]}"
set -e

# ── Generate Codex handoff artifact (must not mask gate RC) ─
if [ "$GATE_RC" -eq 0 ]; then
  ./scripts/make_codex_handoff.sh "$GATE_LOG" pass || echo "WARNING: handoff generation failed (gate still PASSED)"
else
  ./scripts/make_codex_handoff.sh "$GATE_LOG" fail || echo "WARNING: handoff generation failed (gate FAILED)"
fi

exit "$GATE_RC"
