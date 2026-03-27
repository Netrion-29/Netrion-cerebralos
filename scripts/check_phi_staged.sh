#!/usr/bin/env bash
# scripts/check_phi_staged.sh
# Pre-commit hook: scan staged file content for obvious PHI markers.
#
# Defense-in-depth — .gitignore blocks most PHI paths, but this catches
# patient data that reaches an unexpected location.
#
# Override with:  git commit --no-verify

set -euo pipefail

# --- Allowlist (files that legitimately discuss PHI field names) --------
is_allowlisted() {
    case "$1" in
        scripts/check_phi_staged.sh) return 0 ;;
        .pre-commit-config.yaml)     return 0 ;;
    esac
    return 1
}

# --- PHI patterns (grep -E) --------------------------------------------
# Line-anchored label + non-whitespace value = likely real patient data.
# This is a guardrail, not a complete PHI solution.
PHI_REGEX=$(cat <<'EOF'
^PATIENT_NAME:[[:space:]]*[^[:space:]]|^MRN:[[:space:]]*[^[:space:]]|^MRN #:[[:space:]]*[^[:space:]]|^CSN:[[:space:]]*[^[:space:]]|^DOB:[[:space:]]*[^[:space:]]|^Date of Birth:[[:space:]]*[^[:space:]]|^SSN:[[:space:]]*[^[:space:]]|^Social Security:[[:space:]]*[^[:space:]]|^Medical Record Number:[[:space:]]*[^[:space:]]
EOF
)

# --- Scan staged files --------------------------------------------------
blocked=0
git diff --cached --name-only -z --diff-filter=ACMR | while IFS= read -r -d '' file; do
    # Skip missing / binary files
    [[ -f "$file" ]] || continue
    if file --brief "$file" 2>/dev/null | grep -qiE 'binary|image|pdf'; then
        continue
    fi

    # Skip allowlisted paths
    if is_allowlisted "$file"; then
        continue
    fi

    # Check staged content (index version, not working tree)
    matches=$(git show ":$file" 2>/dev/null | grep -nE "$PHI_REGEX" || true)
    if [[ -n "$matches" ]]; then
        echo "!! PHI marker found — $file"
        echo "$matches" | head -5
        if [[ $(echo "$matches" | wc -l) -gt 5 ]]; then
            echo "   … and more"
        fi
        echo ""
        blocked=1
    fi
done

if [[ $blocked -eq 1 ]]; then
    echo "BLOCKED: staged files contain possible PHI markers."
    echo "Review the flagged lines. If they are false positives, commit with:"
    echo "  git commit --no-verify"
    exit 1
fi
