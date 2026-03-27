#!/usr/bin/env bash
# scripts/check_phi_paths.sh
# Pre-commit hook: block staging of local-only PHI directories.
#
# These paths are .gitignore'd, but this catches forced adds (git add -f).
# Override with:  git commit --no-verify

set -euo pipefail

PHI_PATH_RE="^(data_raw/|outputs/|data_validated/|cerebralos/Patients/|cerebralos/Important Info/)"

blocked=$(git diff --cached --name-only | grep -E "$PHI_PATH_RE" || true)

if [[ -n "$blocked" ]]; then
    echo "BLOCKED — local-only PHI path staged:"
    echo "$blocked"
    echo ""
    echo "These directories must never be committed."
    exit 1
fi
