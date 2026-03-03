#!/usr/bin/env bash
set -euo pipefail

PAT="${1:-}"
if [[ -z "$PAT" ]]; then
  echo "Usage: ./run_patient.sh Anna_Dennis"
  exit 1
fi

# Slug: filesystem-safe name (spaces → underscores), matches parser's _slugify.
SLUG="${PAT// /_}"

export PYTHONPATH="$(pwd)"

echo "== Running patient: $PAT (slug: $SLUG) =="

# Evidence
python3 cerebralos/ingest/parse_patient_txt.py --in "data_raw/$PAT.txt"

# Evidence raw_line_id validation (fail-fast — AGENTS §5)
python3 cerebralos/validation/validate_evidence_raw_line_id.py \
  --in "outputs/evidence/$SLUG/patient_evidence_v1.json"

# Timeline
mkdir -p "outputs/timeline/$SLUG"
python3 cerebralos/timeline/build_patient_days.py \
  --in "outputs/evidence/$SLUG/patient_evidence_v1.json" \
  --out "outputs/timeline/$SLUG/patient_days_v1.json"

# Features
mkdir -p "outputs/features/$SLUG"
python3 -m cerebralos.features.build_patient_features_v1 \
  --in "outputs/timeline/$SLUG/patient_days_v1.json" \
  --out "outputs/features/$SLUG/patient_features_v1.json"

# Contract validation (fail-fast on schema drift)
python3 cerebralos/validation/validate_patient_features_contract_v1.py \
  --in "outputs/features/$SLUG/patient_features_v1.json"

# Render v3
mkdir -p "outputs/reporting/$SLUG"
python3 cerebralos/reporting/render_trauma_daily_notes_v3.py \
  --in "outputs/timeline/$SLUG/patient_days_v1.json" \
  --out "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt"

# Render v4 (features-driven, clinically self-sufficient)
python3 cerebralos/reporting/render_trauma_daily_notes_v4.py \
  --features "outputs/features/$SLUG/patient_features_v1.json" \
  --days "outputs/timeline/$SLUG/patient_days_v1.json" \
  --out "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v4.txt"

# NTDS Hospital Events — all 21 events (opt-in via CEREBRAL_NTDS=1)
# Runs BEFORE v5 rendering so results can feed into the report.
# Fail-closed: no || true — NTDS failures propagate to caller.
NTDS_SUMMARY=""
if [[ "${CEREBRAL_NTDS:-0}" == "1" ]]; then
  echo ""
  echo "---- NTDS hospital events (2026, all 21) ----"
  python3 -m cerebralos.ntds_logic.run_all_events \
    --year 2026 --patient "data_raw/$PAT.txt"
  NTDS_SUMMARY="outputs/ntds/$SLUG/ntds_summary_2026_v1.json"
fi

# Render v5 (feature-layer clinical narrative — additive, does not replace v3/v4)
# When CEREBRAL_NTDS=1, pass NTDS summary so v5 renders the NTDS SIGNAL SUMMARY section.
V5_NTDS_FLAG=""
if [[ -n "$NTDS_SUMMARY" && -f "$NTDS_SUMMARY" ]]; then
  V5_NTDS_FLAG="--ntds $NTDS_SUMMARY"
fi
python3 cerebralos/reporting/render_trauma_daily_notes_v5.py \
  --features "outputs/features/$SLUG/patient_features_v1.json" \
  --days "outputs/timeline/$SLUG/patient_days_v1.json" \
  $V5_NTDS_FLAG \
  --out "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v5.txt"

echo "---- sanity checks ----"
echo -n "noise(ADS/OMNICELL): "
grep -ciE "ADS Dispense|OMNICELL" "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt" || true

echo -n "bogus physician impression in Imaging: "
grep -cE "Imaging.*IMPRESSION.*Patient is a" "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt" || true

echo -n "Hospital Course count: "
grep -ciE "^Hospital Course:" "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt" || true

echo -n "NURSING_NOTE lines emitted: "
grep -ciE "NURSING_NOTE" "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt" || true

echo ""
echo "OUTPUT FILE:"
echo "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt"
echo ""
head -n 80 "outputs/reporting/$SLUG/TRAUMA_DAILY_NOTES_v3.txt"

# Features QA (non-fatal)
echo ""
echo "---- features QA ----"
python3 cerebralos/validation/report_features_qa.py --pat "$SLUG" || true

# Audit pack (opt-in via CEREBRAL_AUDIT=1)
if [[ "${CEREBRAL_AUDIT:-0}" == "1" ]]; then
  echo ""
  echo "---- audit pack ----"
  python3 cerebralos/validation/build_audit_pack.py --pat "$SLUG" || true
fi

# Drafts daily packet (opt-in via CEREBRAL_DRAFTS=1)
if [[ "${CEREBRAL_DRAFTS:-0}" == "1" ]]; then
  echo ""
  echo "---- drafts packet ----"
  python3 cerebralos/reporting/render_drafts_packet_v1.py --pat "$SLUG" || true
fi

# GREEN CARD v1 (opt-in via CEREBRAL_GREEN=1)
if [[ "${CEREBRAL_GREEN:-0}" == "1" ]]; then
  echo ""
  echo "---- green card v1 ----"
  mkdir -p "outputs/green_card/$SLUG"
  python3 -m cerebralos.green_card.extract_green_card_v1 --pat "$SLUG" || true
  python3 -m cerebralos.green_card.render_green_card_v1 --pat "$SLUG" || true
  python3 cerebralos/validation/report_green_card_qa.py --pat "$SLUG" || true
fi

# Trauma Excellence Dashboard (opt-in via CEREBRAL_DASHBOARD=1)
if [[ "${CEREBRAL_DASHBOARD:-0}" == "1" ]]; then
  echo ""
  echo "---- trauma excellence dashboard ----"
  python3 -m cerebralos.reporting.excel_trauma_dashboard_v2 --patient "$SLUG" || true
fi

