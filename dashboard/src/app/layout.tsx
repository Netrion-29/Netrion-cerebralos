import type { Metadata } from "next"
import "./globals.css"
import { PhiBanner } from "@/components/PhiBanner"
import { LogoutButton } from "@/components/LogoutButton"
import Link from "next/link"

export const metadata: Metadata = {
  title: "CerebralOS Dashboard",
  description: "NTDS outcomes and protocol compliance",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-100 text-slate-900 min-h-screen">
        <PhiBanner />
        {/* Offset for PHI banner */}
        <div className="pt-7">
          <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-6">
            <Link href="/" className="font-bold text-lg text-slate-800 hover:text-blue-700 transition-colors">
              CerebralOS
            </Link>
            <nav className="flex gap-4 text-sm text-slate-500">
              <Link href="/" className="hover:text-slate-800 transition-colors">Patients</Link>
            </nav>
            <div className="ml-auto">
              {process.env.DASHBOARD_PASSWORD && <LogoutButton />}
            </div>
          </header>
          <main className="max-w-7xl mx-auto px-4 py-6">{children}</main>
        </div>
      </body>
    </html>
  )
}
