#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "$#" -gt 0 ]; then
  PATS=("$@")
else
  PATS=("Anna_Dennis" "William_Simmons" "Timothy_Cowan" "Timothy_Nachtwey")
fi

echo "=============================================="
echo "CerebralOS PR Gate"
echo "Repo: $(pwd)"
echo "=============================================="

for PAT in "${PATS[@]}"; do
  echo
  echo "---- Running pipeline for: $PAT ----"
  ./run_patient.sh "$PAT"

  echo "---- v4 hash: $PAT ----"
  shasum -a 256 "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v4.txt"
done

echo
echo "---- Running regression ----"
python3 _regression_phase1_v2.py

echo
echo "Gate complete."
