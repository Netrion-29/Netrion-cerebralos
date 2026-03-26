import { notFound } from "next/navigation"
import { listPatientSlugs } from "@/lib/paths"
import { readNtdsSummary, readNtdsYear } from "@/lib/ntds"
import { readProtocols } from "@/lib/protocols"
import type { PatientDetail } from "@/types"
import { PatientHeader } from "@/components/PatientHeader"
import { ProtocolList } from "@/components/ProtocolList"
import { PatientDetailClient } from "./PatientDetailClient"
import Link from "next/link"

interface Props {
  params: { slug: string }
}

export function generateStaticParams() {
  return listPatientSlugs().map((slug) => ({ slug }))
}

export default function PatientDetailPage({ params }: Props) {
  const { slug } = params

  const validSlugs = new Set(listPatientSlugs())
  if (!validSlugs.has(slug)) notFound()

  const ntds_summary = readNtdsSummary(slug)
  const protocols = readProtocols(slug)
  const ntds_year = readNtdsYear(slug)

  const patient: PatientDetail = {
    slug,
    display_name: slug.replace(/_/g, " "),
    ntds_summary,
    ntds_year,
    protocols,
    has_protocols: protocols.length > 0,
  }

  return (
    <div className="space-y-5">
      {/* Back */}
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 transition-colors">
        ← All patients
      </Link>

      {/* Header */}
      <PatientHeader patient={patient} />

      {/* Two-column layout on large screens */}
      <div className="flex flex-col lg:flex-row gap-5">
        {/* Left: NTDS */}
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
            NTDS Events
          </h3>
          <PatientDetailClient slug={slug} summary={ntds_summary} />
        </div>

        {/* Right: Protocols */}
        {patient.has_protocols && (
          <div className="lg:w-96 shrink-0">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
              Protocols
            </h3>
            <ProtocolList protocols={protocols} />
          </div>
        )}
      </div>
    </div>
  )
}
