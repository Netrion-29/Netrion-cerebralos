import Link from "next/link"
import { clsx } from "clsx"
import type { PatientListItem, NtdsOutcome } from "@/types"

const DOT_CLASSES: Record<NtdsOutcome, string> = {
  YES: "bg-red-500",
  NO: "bg-green-500",
  UNABLE_TO_DETERMINE: "bg-yellow-400",
  EXCLUDED: "bg-slate-300",
}

interface Props {
  patient: PatientListItem
}

export function PatientCard({ patient }: Props) {
  const triggered = patient.protocol_triggered_count
  const compliant = patient.protocol_compliant_count
  const nonCompliant = patient.protocol_noncompliant_count

  return (
    <Link
      href={`/patients/${patient.slug}`}
      className="flex items-center gap-4 px-4 py-3 bg-white border border-slate-200 rounded-lg hover:border-slate-400 hover:shadow-sm transition-all group"
    >
      {/* Name */}
      <div className="w-40 shrink-0">
        <span className="font-semibold text-slate-800 group-hover:text-blue-700 transition-colors">
          {patient.display_name}
        </span>
      </div>

      {/* Dot grid */}
      <div className="flex flex-wrap gap-1 flex-1">
        {patient.ntds_summary.map((item) => (
          <span
            key={item.event_id}
            title={`E${item.event_id}: ${item.canonical_name} — ${item.outcome}`}
            className={clsx("w-3.5 h-3.5 rounded-full inline-block", DOT_CLASSES[item.outcome])}
          />
        ))}
      </div>

      {/* NTDS count chips */}
      <div className="flex gap-2 text-xs font-mono shrink-0">
        {patient.yes_count > 0 && (
          <span className="bg-red-100 text-red-800 border border-red-300 px-1.5 py-0.5 rounded">
            {patient.yes_count}Y
          </span>
        )}
        {patient.utd_count > 0 && (
          <span className="bg-yellow-100 text-yellow-800 border border-yellow-300 px-1.5 py-0.5 rounded">
            {patient.utd_count}U
          </span>
        )}
        <span className="bg-green-100 text-green-800 border border-green-300 px-1.5 py-0.5 rounded">
          {patient.no_count}N
        </span>
      </div>

      {/* Protocol chip */}
      {patient.has_protocols && (
        <div className="shrink-0 text-xs">
          {nonCompliant > 0 ? (
            <span className="bg-red-100 text-red-800 border border-red-300 px-1.5 py-0.5 rounded">
              {nonCompliant}/{triggered} NC
            </span>
          ) : (
            <span className="bg-green-100 text-green-800 border border-green-300 px-1.5 py-0.5 rounded">
              {compliant}/{triggered} C
            </span>
          )}
        </div>
      )}
    </Link>
  )
}
