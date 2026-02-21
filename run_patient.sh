#!/usr/bin/env bash
set -euo pipefail

PAT="${1:-}"
if [[ -z "$PAT" ]]; then
  echo "Usage: ./run_patient.sh Anna_Dennis"
  exit 1
fi

export PYTHONPATH="$(pwd)"

echo "== Running patient: $PAT =="

# Evidence
python3 cerebralos/ingest/parse_patient_txt.py --in "data_raw/$PAT.txt"

# Evidence raw_line_id validation (fail-fast — AGENTS §5)
python3 cerebralos/validation/validate_evidence_raw_line_id.py \
  --in "outputs/evidence/$PAT/patient_evidence_v1.json"

# Timeline
mkdir -p "outputs/timeline/$PAT"
python3 cerebralos/timeline/build_patient_days.py \
  --in "outputs/evidence/$PAT/patient_evidence_v1.json" \
  --out "outputs/timeline/$PAT/patient_days_v1.json"

# Features
mkdir -p "outputs/features/$PAT"
python3 -m cerebralos.features.build_patient_features_v1 \
  --in "outputs/timeline/$PAT/patient_days_v1.json" \
  --out "outputs/features/$PAT/patient_features_v1.json"

# Contract validation (fail-fast on schema drift)
python3 cerebralos/validation/validate_patient_features_contract_v1.py \
  --in "outputs/features/$PAT/patient_features_v1.json"

# Render v3
mkdir -p "outputs/reporting/$PAT"
python3 cerebralos/reporting/render_trauma_daily_notes_v3.py \
  --in "outputs/timeline/$PAT/patient_days_v1.json" \
  --out "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt"

# Render v4 (features-driven, clinically self-sufficient)
python3 cerebralos/reporting/render_trauma_daily_notes_v4.py \
  --features "outputs/features/$PAT/patient_features_v1.json" \
  --days "outputs/timeline/$PAT/patient_days_v1.json" \
  --out "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v4.txt"

echo "---- sanity checks ----"
echo -n "noise(ADS/OMNICELL): "
grep -ciE "ADS Dispense|OMNICELL" "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt" || true

echo -n "bogus physician impression in Imaging: "
grep -cE "Imaging.*IMPRESSION.*Patient is a" "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt" || true

echo -n "Hospital Course count: "
grep -ciE "^Hospital Course:" "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt" || true

echo -n "NURSING_NOTE lines emitted: "
grep -ciE "NURSING_NOTE" "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt" || true

echo ""
echo "OUTPUT FILE:"
echo "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt"
echo ""
head -n 80 "outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt"

# Features QA (non-fatal)
echo ""
echo "---- features QA ----"
python3 cerebralos/validation/report_features_qa.py --pat "$PAT" || true

# Audit pack (opt-in via CEREBRAL_AUDIT=1)
if [[ "${CEREBRAL_AUDIT:-0}" == "1" ]]; then
  echo ""
  echo "---- audit pack ----"
  python3 cerebralos/validation/build_audit_pack.py --pat "$PAT" || true
fi

# Drafts daily packet (opt-in via CEREBRAL_DRAFTS=1)
if [[ "${CEREBRAL_DRAFTS:-0}" == "1" ]]; then
  echo ""
  echo "---- drafts packet ----"
  python3 cerebralos/reporting/render_drafts_packet_v1.py --pat "$PAT" || true
fi

# GREEN CARD v1 (opt-in via CEREBRAL_GREEN=1)
if [[ "${CEREBRAL_GREEN:-0}" == "1" ]]; then
  echo ""
  echo "---- green card v1 ----"
  mkdir -p "outputs/green_card/$PAT"
  python3 -m cerebralos.green_card.extract_green_card_v1 --pat "$PAT" || true
  python3 -m cerebralos.green_card.render_green_card_v1 --pat "$PAT" || true
  python3 cerebralos/validation/report_green_card_qa.py --pat "$PAT" || true
fi

# Trauma Excellence Dashboard (opt-in via CEREBRAL_DASHBOARD=1)
if [[ "${CEREBRAL_DASHBOARD:-0}" == "1" ]]; then
  echo ""
  echo "---- trauma excellence dashboard ----"
  python3 -m cerebralos.reporting.excel_trauma_dashboard_v2 --patient "$PAT" || true
fi
