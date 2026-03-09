import { NextResponse } from "next/server"
import { readNtdsSummary, readNtdsYear } from "@/lib/ntds"
import { readProtocols } from "@/lib/protocols"
import { sanitizeSlug } from "@/lib/paths"
import type { PatientDetail } from "@/types"

export const dynamic = "force-dynamic"

export async function GET(
  _req: Request,
  { params }: { params: { slug: string } }
) {
  try {
    sanitizeSlug(params.slug)
  } catch {
    return NextResponse.json({ error: "Invalid slug" }, { status: 400 })
  }
  const { slug } = params
  const ntds_summary = readNtdsSummary(slug)
  const protocols = readProtocols(slug)
  const ntds_year = readNtdsYear(slug)

  const detail: PatientDetail = {
    slug,
    display_name: slug.replace(/_/g, " "),
    ntds_summary,
    ntds_year,
    protocols,
    has_protocols: protocols.length > 0,
  }

  return NextResponse.json(detail)
}
