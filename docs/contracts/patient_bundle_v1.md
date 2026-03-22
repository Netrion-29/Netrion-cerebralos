# Contract: `patient_bundle_v1.json`

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-22                                               |
| Status      | **LOCKED** — enforced by validator                       |
| Version     | 1.0                                                      |
| Direction   | See `docs/roadmaps/PI_RN_CASEFILE_V1.md`                 |

---

## 1. Purpose

`patient_bundle_v1.json` is the assembled single-patient artifact that
combines all upstream pipeline outputs into one deterministic JSON file.

It is the **single input** for the future PI RN Casefile renderer.

The bundle does NOT recompute anything — it reads existing pipeline
artifacts and assembles them into a curated shape optimised for
single-patient case review.

---

## 2. Output Location

```
outputs/casefile/$SLUG/patient_bundle_v1.json
```

Where `$SLUG` is the underscore-normalised patient name (e.g. `Betty_Roll`).

---

## 3. Top-Level Schema

Allowed top-level keys (exactly):

```
build, patient, summary, compliance, daily, consultants, artifacts, warnings
```

No extras allowed. No keys may be missing.

Enforced by: `cerebralos/validation/validate_patient_bundle_contract_v1.py`

---

## 4. Key Descriptions

### `build` (required, dict)

Assembler metadata. Always present.

| Field | Type | Description |
|-------|------|-------------|
| `bundle_version` | string | Always `"1.0"` |
| `generated_at_utc` | string | ISO-8601 UTC timestamp |
| `assembler` | string | Always `"build_patient_bundle_v1"` |

### `patient` (required, dict)

Patient demographics from `patient_evidence_v1.json → meta`.

| Field | Type | Description |
|-------|------|-------------|
| `patient_id` | string | Patient ID (may be `"DATA_NOT_AVAILABLE"`) |
| `patient_name` | string | Full patient name |
| `dob` | string | Date of birth |
| `slug` | string | Filesystem-safe slug |
| `arrival_datetime` | string or null | Arrival timestamp |
| `discharge_datetime` | string or null | Discharge timestamp |
| `trauma_category` | string | Trauma activation category |

### `summary` (required, dict)

Feature-layer summaries supporting the trauma summary header.
Each key is copied from `patient_features_v1.json → features.*`.

| Key | Source | Fail-closed |
|-----|--------|-------------|
| `mechanism` | `features.mechanism_region_v1` | `null` if absent |
| `pmh` | `features.pmh_social_allergies_v1` | `null` if absent |
| `anticoagulants` | `features.anticoag_context_v1` | `null` if absent |
| `demographics` | `features.demographics_v1` | `null` if absent |
| `activation` | `features.category_activation_v1` | `null` if absent |
| `shock_trigger` | `features.shock_trigger_v1` | `null` if absent |
| `age` | `features.age_extraction_v1` | `null` if absent |

### `compliance` (required, dict)

NTDS and protocol compliance data. Optional artifacts produce `null`
when the upstream files do not exist.

| Key | Source | Fail-closed |
|-----|--------|-------------|
| `ntds_summary` | `ntds_summary_2026_v1.json` | `null` if absent |
| `ntds_event_outcomes` | Compact extract from per-event JSONs | `null` if absent |
| `protocol_results` | `protocol_results_v1.json` | `null` if absent |

### `daily` (required, dict)

Per-day clinical data keyed by `YYYY-MM-DD`. Each day contains curated
fields from `patient_features_v1.json → days[date]` and
`patient_features_v1.json → features`.

| Key | Source | Fail-closed |
|-----|--------|-------------|
| `vitals` | `features.vitals_canonical_v1` per-day | `null` if absent |
| `labs` | `days[date].labs` | `null` if absent |
| `gcs` | `days[date].gcs_daily` | `null` if absent |
| `ventilator` | `features.ventilator_settings_v1` per-day | `null` if absent |
| `plans` | `features.trauma_daily_plan_by_day_v1` per-day | `null` if absent |
| `consultant_plans` | `features.consultant_day_plans_by_day_v1` per-day | `null` if absent |

### `consultants` (required, dict or null)

Consultant event summary from `features.consultant_events_v1`.
`null` if the feature module is absent.

### `artifacts` (required, dict)

Relative paths to upstream artifact files. Enables the casefile renderer
to deep-link or cross-reference source files.

| Key | Type | Required |
|-----|------|----------|
| `evidence_path` | string | Yes |
| `timeline_path` | string | Yes |
| `features_path` | string | Yes |
| `ntds_summary_path` | string or null | No (null if NTDS not run) |
| `protocol_results_path` | string or null | No (null if protocols not run) |
| `v5_report_path` | string or null | No (null if v5 not generated) |

### `warnings` (required, list)

Bundle-level warnings. Includes:
- Warnings inherited from `patient_features_v1.json → warnings`
- Any missing-artifact notices generated during assembly

---

## 5. Data Provenance

| Bundle section | Source artifact |
|----------------|----------------|
| `patient` | `patient_evidence_v1.json → meta` |
| `summary` | `patient_features_v1.json → features.*` |
| `compliance.ntds_*` | `outputs/ntds/$SLUG/ntds_summary_2026_v1.json` + per-event files |
| `compliance.protocol_results` | `outputs/protocols/$SLUG/protocol_results_v1.json` |
| `daily` | `patient_features_v1.json → days.*` + `features.*` |
| `consultants` | `patient_features_v1.json → features.consultant_events_v1` |
| `warnings` | `patient_features_v1.json → warnings` + assembler warnings |

---

## 6. Fail-Closed Behavior

- **Required artifacts missing** (evidence, features, timeline): assembler
  exits with error code 1. No bundle written.
- **Optional artifacts missing** (NTDS, protocols, v5 report): the
  corresponding bundle fields are set to `null`. A warning is appended
  to `warnings[]`. Bundle is still written.
- **Unknown top-level keys in input**: ignored (assembler reads only
  documented paths).
- **Contract violation in output**: validator rejects the bundle.

---

## 7. Intentionally Excluded from v1

| Excluded | Reason |
|----------|--------|
| Raw evidence `items[]` array | Too large; `artifacts.evidence_path` is sufficient |
| Full timeline day items | Per-day feature summaries are the curated view |
| Individual NTDS event full JSON payloads | Compact outcomes included; full files referenced via path |
| v5/v4/v3 text content | Path reference only |
| Excel dashboard data | Separate surface |
| HTML report data | Legacy surface |
| LDA episode detail | Available via features if needed; not curated for v1 header |
| Injury-specific feature modules | Complex; defer to v1.1 when casefile renderer needs them |

---

End.
