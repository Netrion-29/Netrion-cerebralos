import { NextResponse } from "next/server"
import { readNtdsEvent } from "@/lib/ntds"
import { sanitizeSlug } from "@/lib/paths"

export const dynamic = "force-dynamic"

export async function GET(
  _req: Request,
  { params }: { params: { slug: string; eventId: string } }
) {
  try {
    sanitizeSlug(params.slug)
  } catch {
    return NextResponse.json({ error: "Invalid slug" }, { status: 400 })
  }
  const { slug, eventId } = params
  const id = parseInt(eventId, 10)
  if (isNaN(id)) {
    return NextResponse.json({ error: "Invalid event id" }, { status: 400 })
  }

  const event = readNtdsEvent(slug, id)
  if (!event) {
    return NextResponse.json({ error: "Not found" }, { status: 404 })
  }

  return NextResponse.json(event)
}
