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
# Label + trailing digit = likely real patient data, not code references.
# Structural value patterns (SSN, phone) are always checked.
PHI_REGEX=$(cat <<'EOF'
MRN[[:space:]]*:[[:space:]]*[0-9]|CSN[[:space:]]*:[[:space:]]*[0-9]|DOB[[:space:]]*:[[:space:]]*[0-9]|SSN[[:space:]]*:[[:space:]]*[0-9]|Date of Birth[[:space:]]*:[[:space:]]*[0-9]|Medical Record Number[[:space:]]*:[[:space:]]*[0-9]|Social Security[[:space:]]*:[[:space:]]*[0-9]|Patient Name[[:space:]]*:[[:space:]]*[A-Z]|[0-9]{3}-[0-9]{2}-[0-9]{4}|\([0-9]{3}\)[[:space:]]*[0-9]{3}-[0-9]{4}
EOF
)

# --- Scan staged files --------------------------------------------------
blocked=0
staged=$(git diff --cached --name-only --diff-filter=ACM)

for file in $staged; do
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
