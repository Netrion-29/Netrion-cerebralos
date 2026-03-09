import path from "path"
import fs from "fs"

/**
 * Resolve the outputs directory.
 * - Set OUTPUTS_DIR env var to override (e.g., absolute path in CI or Vercel).
 * - Default: two levels up from dashboard/ → netrion-cerebralos/outputs/
 */
export function getOutputsDir(): string {
  if (process.env.OUTPUTS_DIR) return process.env.OUTPUTS_DIR
  return path.resolve(process.cwd(), "..", "outputs")
}

export function getNtdsDir(slug: string): string {
  return path.join(getOutputsDir(), "ntds", slug)
}

export function getProtocolsDir(slug: string): string {
  return path.join(getOutputsDir(), "protocols", slug)
}

/** List all patient slugs by reading ntds/ subdirectories. */
export function listPatientSlugs(): string[] {
  const ntdsRoot = path.join(getOutputsDir(), "ntds")
  const entries = fs.readdirSync(ntdsRoot, { withFileTypes: true })
  return entries
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .filter((name) => {
      // Exclude stale/test dirs (start with _ or are all-digit prefixed test cases)
      if (name.startsWith("_")) return false
      if (/^\d/.test(name)) return false
      // Must contain underscore (First_Last format)
      return name.includes("_")
    })
    .sort()
}
