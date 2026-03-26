# CerebralOS Dashboard

> **⚠️ LEGACY — SOFT-ARCHIVED (2026-03-22)**
>
> This Next.js dashboard is **not the active product path**. It is preserved
> for reference only. Do not invest new development effort here.
>
> The active product direction is the **PI RN Casefile v1** — a single-patient
> case file / chart. See `docs/roadmaps/PI_RN_CASEFILE_V1.md` for the full
> product direction document.
>
> **Why soft-archived:**
> - Primary user (PI RN) needs a single-patient review experience, not a
>   cross-patient dashboard.
> - This dashboard was a useful prototype but is not trusted as the
>   production surface.
> - Future cross-patient views (Phase 6) will be built on the new
>   `patient_bundle_v1` architecture, not this codebase.
>
> **What this means:**
> - This code is NOT deleted — it remains for reference and historical context.
> - No files have been moved or removed.
> - The dashboard may still run locally (`npm run dev`) but is not maintained.
> - Bug fixes, feature additions, and dependency updates are not planned.

Local-first Next.js 14 dashboard for NTDS event outcomes and protocol compliance.

## Quick Start

```bash
cd dashboard
npm install
npm run dev
# → http://localhost:3333
```

## Data Sources

Reads directly from `../outputs/` (relative to `dashboard/`):

- `outputs/ntds/{slug}/ntds_summary_2026_v1.json` — 21-item outcome array
- `outputs/ntds/{slug}/ntds_event_NN_2026_v1.json` — full event with gate trace
- `outputs/protocols/{slug}/` — old format (`protocol_results_v1.json`) or new format (one file per protocol)

Override location with `OUTPUTS_DIR=/absolute/path npm run dev`.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|--------|
| `DASHBOARD_PASSWORD` | **Yes** (production) | unset (auth disabled in dev) | Shared access password. In production (`NODE_ENV=production`), the dashboard returns HTTP 503 on all routes if this is not set. |
| `OUTPUTS_DIR` | No | `../outputs/` | Absolute path to the CerebralOS outputs directory. |
| `NODE_ENV` | No | `development` | Set automatically by Next.js. Controls cookie `secure` flag and fail-closed auth behavior. |

## API Routes

| Route | Description |
|-------|-------------|
| `GET /api/patients` | All patients with summary counts (returns `[]` if outputs dir missing) |
| `GET /api/patients/[slug]` | Full patient detail (returns `400` for invalid slugs) |
| `GET /api/patients/[slug]/events/[eventId]` | NTDS event detail with gate trace (returns `400` for invalid slugs) |

Slugs containing `..`, `/`, `\`, or null bytes are rejected with HTTP 400. If `OUTPUTS_DIR` (or the default `../outputs/`) does not exist, the patient list returns an empty array instead of crashing.

## Type Check

```bash
npm run typecheck
```

## Vercel Upgrade Path

1. Move `outputs/` to Vercel Blob / S3; set `OUTPUTS_BASE_URL` env var in `paths.ts`
2. Generate `outputs/manifest.json` slug list for serverless discovery
3. Set `DASHBOARD_PASSWORD` in Vercel project settings (auth middleware already exists in `src/middleware.ts`)
4. Configure remaining env vars as needed
