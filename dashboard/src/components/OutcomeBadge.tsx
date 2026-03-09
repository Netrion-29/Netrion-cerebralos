import { clsx } from "clsx"
import type { NtdsOutcome, ProtocolOutcome } from "@/types"

type AnyOutcome = NtdsOutcome | ProtocolOutcome

const LABELS: Record<AnyOutcome, string> = {
  YES: "YES",
  NO: "NO",
  UNABLE_TO_DETERMINE: "UTD",
  EXCLUDED: "EXCL",
  COMPLIANT: "COMPLIANT",
  NON_COMPLIANT: "NON-COMPLIANT",
  NOT_TRIGGERED: "NOT TRIGGERED",
  INDETERMINATE: "INDETERMINATE",
}

const CLASSES: Record<AnyOutcome, string> = {
  YES: "bg-red-100 text-red-800 border-red-300",
  NON_COMPLIANT: "bg-red-100 text-red-800 border-red-300",
  NO: "bg-green-100 text-green-800 border-green-300",
  COMPLIANT: "bg-green-100 text-green-800 border-green-300",
  UNABLE_TO_DETERMINE: "bg-yellow-100 text-yellow-800 border-yellow-300",
  INDETERMINATE: "bg-yellow-100 text-yellow-800 border-yellow-300",
  EXCLUDED: "bg-slate-100 text-slate-500 border-slate-200",
  NOT_TRIGGERED: "bg-slate-100 text-slate-500 border-slate-200",
}

interface Props {
  outcome: AnyOutcome
  className?: string
  size?: "sm" | "md"
}

export function OutcomeBadge({ outcome, className, size = "md" }: Props) {
  return (
    <span
      className={clsx(
        "inline-block border rounded font-mono font-semibold",
        size === "sm" ? "text-xs px-1.5 py-0.5" : "text-sm px-2 py-1",
        CLASSES[outcome],
        className
      )}
    >
      {LABELS[outcome] ?? outcome}
    </span>
  )
}
