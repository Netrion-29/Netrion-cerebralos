#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=============================================="
echo "CerebralOS — dev_start"
echo "pwd: $(pwd)"
echo "=============================================="

echo
git status

echo
echo "---- Running PR gate ----"
./scripts/gate_pr.sh

echo
echo "DONE"
echo "OPEN: outputs/audit/codex_handoff.md"
