import { NextRequest, NextResponse } from "next/server";
import { backendHeaders, getSession, SESSION_COOKIE } from "@/lib/session";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";

// Filters the export passes on to the backend. Anything else is dropped.
const FILTERS = ["q", "sport", "school", "campus", "status", "source", "partner_consent",
  "min_followers", "max_followers", "has_content", "include_declined", "sort"];

/**
 * The athlete directory export. The proxy only speaks JSON, and this file
 * holds athlete emails and phone numbers, so it has its own admin-only route
 * and is never cached. The backend refuses non-admins as well.
 */
export async function GET(request: NextRequest) {
  const session = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (session.role !== "admin") {
    return NextResponse.json({ error: "Admins only" }, { status: 403 });
  }

  const params = new URLSearchParams();
  for (const name of FILTERS) {
    const v = request.nextUrl.searchParams.get(name);
    if (v) params.set(name, v);
  }
  const qs = params.toString();
  const res = await fetch(`${BACKEND}/api/athlete-directory/export.csv${qs ? `?${qs}` : ""}`, {
    headers: backendHeaders(session),
    cache: "no-store",
    redirect: "manual",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "Export failed" }, { status: res.status === 403 ? 403 : 502 });
  }

  return new NextResponse(res.body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": 'attachment; filename="athletes.csv"',
      "Cache-Control": "no-store",
    },
  });
}
