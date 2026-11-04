import { NextRequest, NextResponse } from "next/server";
import { backendHeaders, getSession, SESSION_COOKIE } from "@/lib/session";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";

/**
 * The vote export. The proxy only speaks JSON, and this file holds voter
 * emails, so it has its own admin-only route and is never cached.
 */
export async function GET(request: NextRequest) {
  const session = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (session.role !== "admin") {
    return NextResponse.json({ error: "Admins only" }, { status: 403 });
  }

  const res = await fetch(`${BACKEND}/api/community-star/votes.csv`, {
    headers: backendHeaders(session),
    cache: "no-store",
    redirect: "manual",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "Export failed" }, { status: res.status === 404 ? 404 : 502 });
  }

  return new NextResponse(res.body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": 'attachment; filename="community-star-votes.csv"',
      "Cache-Control": "no-store",
    },
  });
}
