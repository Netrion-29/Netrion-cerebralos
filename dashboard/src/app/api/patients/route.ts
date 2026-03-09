import { NextResponse } from "next/server"
import { listPatientSlugs } from "@/lib/paths"
import { readNtdsSummary } from "@/lib/ntds"
import { readProtocols } from "@/lib/protocols"
import type { PatientListItem } from "@/types"

export const dynamic = "force-dynamic"

export async function GET() {
  const slugs = listPatientSlugs()

  const patients: PatientListItem[] = slugs.map((slug) => {
    const ntds_summary = readNtdsSummary(slug)
    const protocols = readProtocols(slug)

    const yes_count = ntds_summary.filter((e) => e.outcome === "YES").length
    const no_count = ntds_summary.filter((e) => e.outcome === "NO").length
    const utd_count = ntds_summary.filter((e) => e.outcome === "UNABLE_TO_DETERMINE").length
    const excluded_count = ntds_summary.filter((e) => e.outcome === "EXCLUDED").length

    const triggered = protocols.filter((p) => p.outcome !== "NOT_TRIGGERED")
    const protocol_compliant_count = triggered.filter((p) => p.outcome === "COMPLIANT").length
    const protocol_noncompliant_count = triggered.filter((p) => p.outcome === "NON_COMPLIANT").length
    const protocol_triggered_count = triggered.length

    return {
      slug,
      display_name: slug.replace(/_/g, " "),
      ntds_summary,
      yes_count,
      no_count,
      utd_count,
      excluded_count,
      has_protocols: protocols.length > 0,
      protocol_compliant_count,
      protocol_noncompliant_count,
      protocol_triggered_count,
    }
  })

  return NextResponse.json(patients)
}
