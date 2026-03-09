import type { PatientDetail } from "@/types"
import { OutcomeBadge } from "./OutcomeBadge"

interface Props {
  patient: PatientDetail
}

export function PatientHeader({ patient }: Props) {
  const yes = patient.ntds_summary.filter((e) => e.outcome === "YES").length
  const no = patient.ntds_summary.filter((e) => e.outcome === "NO").length
  const utd = patient.ntds_summary.filter((e) => e.outcome === "UNABLE_TO_DETERMINE").length
  const excl = patient.ntds_summary.filter((e) => e.outcome === "EXCLUDED").length

  const triggered = patient.protocols.filter((p) => p.outcome !== "NOT_TRIGGERED")
  const compliant = triggered.filter((p) => p.outcome === "COMPLIANT").length
  const nonCompliant = triggered.filter((p) => p.outcome === "NON_COMPLIANT").length

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{patient.display_name}</h1>
          <p className="text-xs text-slate-400 mt-0.5">NTDS {patient.ntds_year} · {patient.ntds_summary.length} events</p>
        </div>

        <div className="flex flex-wrap gap-2 items-center">
          {yes > 0 && (
            <span className="flex items-center gap-1">
              <OutcomeBadge outcome="YES" size="sm" />
              <span className="text-sm font-semibold text-slate-700">×{yes}</span>
            </span>
          )}
          {utd > 0 && (
            <span className="flex items-center gap-1">
              <OutcomeBadge outcome="UNABLE_TO_DETERMINE" size="sm" />
              <span className="text-sm font-semibold text-slate-700">×{utd}</span>
            </span>
          )}
          {no > 0 && (
            <span className="flex items-center gap-1">
              <OutcomeBadge outcome="NO" size="sm" />
              <span className="text-sm font-semibold text-slate-700">×{no}</span>
            </span>
          )}
          {excl > 0 && (
            <span className="flex items-center gap-1">
              <OutcomeBadge outcome="EXCLUDED" size="sm" />
              <span className="text-sm font-semibold text-slate-700">×{excl}</span>
            </span>
          )}

          {patient.has_protocols && (
            <>
              <span className="text-slate-300">|</span>
              {nonCompliant > 0 && (
                <span className="flex items-center gap-1">
                  <OutcomeBadge outcome="NON_COMPLIANT" size="sm" />
                  <span className="text-sm font-semibold text-slate-700">×{nonCompliant}</span>
                </span>
              )}
              {compliant > 0 && (
                <span className="flex items-center gap-1">
                  <OutcomeBadge outcome="COMPLIANT" size="sm" />
                  <span className="text-sm font-semibold text-slate-700">×{compliant}</span>
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
