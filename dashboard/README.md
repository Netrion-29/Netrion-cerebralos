# CerebralOS Dashboard

Local-first Next.js 14 dashboard for NTDS event outcomes and Deaconess protocol compliance.

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

## API Routes

| Route | Description |
|-------|-------------|
| `GET /api/patients` | All patients with summary counts |
| `GET /api/patients/[slug]` | Full patient detail |
| `GET /api/patients/[slug]/events/[eventId]` | NTDS event detail with gate trace |

## Type Check

```bash
npm run typecheck
```

## Vercel Upgrade Path

1. Move `outputs/` to Vercel Blob / S3; set `OUTPUTS_BASE_URL` env var in `paths.ts`
2. Generate `outputs/manifest.json` slug list for serverless discovery
3. Add auth middleware in `src/middleware.ts`
4. Set env vars in Vercel project settings
