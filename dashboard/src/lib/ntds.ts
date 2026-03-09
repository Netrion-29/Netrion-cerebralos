import fs from "fs"
import path from "path"
import { getNtdsDir } from "./paths"
import type { NtdsSummaryItem, NtdsEventDetail } from "@/types"

/** Read the 2026 NTDS summary for a patient. Falls back to 2025 if not found. */
export function readNtdsSummary(slug: string): NtdsSummaryItem[] {
  const dir = getNtdsDir(slug)
  const candidates = ["ntds_summary_2026_v1.json", "ntds_summary_2025_v1.json"]
  for (const fname of candidates) {
    const fpath = path.join(dir, fname)
    if (fs.existsSync(fpath)) {
      const raw = fs.readFileSync(fpath, "utf-8")
      return JSON.parse(raw) as NtdsSummaryItem[]
    }
  }
  return []
}

/** Detect the NTDS year used for a patient (2026 preferred). */
export function readNtdsYear(slug: string): number {
  const dir = getNtdsDir(slug)
  if (fs.existsSync(path.join(dir, "ntds_summary_2026_v1.json"))) return 2026
  if (fs.existsSync(path.join(dir, "ntds_summary_2025_v1.json"))) return 2025
  return 2026
}

/** Read a single NTDS event detail file by event_id (1-based). */
export function readNtdsEvent(slug: string, eventId: number): NtdsEventDetail | null {
  const dir = getNtdsDir(slug)
  const year = readNtdsYear(slug)
  const padded = String(eventId).padStart(2, "0")
  const fname = `ntds_event_${padded}_${year}_v1.json`
  const fpath = path.join(dir, fname)
  if (!fs.existsSync(fpath)) return null
  const raw = fs.readFileSync(fpath, "utf-8")
  return JSON.parse(raw) as NtdsEventDetail
}
