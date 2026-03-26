# Security Policy

## Reporting a Vulnerability

If you discover a security or privacy issue, **do not open a public issue.**

Report it privately via GitHub's
[private vulnerability reporting](https://github.com/Netrion-29/Netrion-cerebralos/security/advisories/new)
or email [security@netrionsystems.com](mailto:security@netrionsystems.com).

## PHI and Patient Data

CerebralOS processes protected health information (PHI) locally. The
following rules apply to all contributors:

- **Never commit patient data.** Raw files (`data_raw/`), generated outputs
  (`outputs/`), and any patient-identifying content must remain local and
  are `.gitignore`'d.
- **Do not post patient-identifying content** in issues, pull requests,
  commit messages, comments, or discussions.
- If you believe PHI has been committed:
  1. Do **not** revert or force-push yourself — that does not remove it
     from Git history.
  2. Report it immediately to the maintainer via private channel.
  3. The maintainer will scrub the data from history using
     `git filter-repo` or GitHub support and force-push the cleaned branch.

## Local-Only Data

The following directories contain sensitive data and must never leave the
local machine:

| Directory | Contents |
|-----------|----------|
| `data_raw/` | Raw Epic `.txt` exports (PHI) |
| `outputs/` | Generated evidence, timelines, reports |
| `data_validated/` | Validated patient extracts |

These are excluded from version control via `.gitignore`.

## Disclaimer

CerebralOS is **not a medical device** and is not intended for independent
clinical decision-making. It is a documentation and governance tool that
surfaces evidence from existing patient records for PI (Performance
Improvement) review. All clinical decisions must be made by qualified
clinicians using primary sources.
