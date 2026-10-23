import { NextRequest, NextResponse } from "next/server";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";
import { isJson, proxyTarget, sameBackendRedirect, sameOrigin } from "@/lib/requestGuards";
import { backendHeaders, getSession, SESSION_COOKIE } from "@/lib/session";

// Writes every account may make for itself (backend/accounts.py SELF_SERVICE).
const SELF_SERVICE_POSTS = ["/api/auth/password"];

/**
 * Catch-all proxy: forwards client-side requests to the backend
 * with the X-API-Key header attached (keeps the key server-side).
 *
 * Usage: fetch("/api/proxy/api/zoomph/summary?author=foo")
 *   → GET https://api.niltv.com/api/zoomph/summary?author=foo
 *
 * Only a valid dashboard session may use it: the key never leaves the server
 * and an anonymous caller gets 401. The signed-in account goes along as
 * X-Dashboard-User (set here, never taken from the browser), and the backend
 * applies that account's role to the call. Non-admin roles are read-only, so
 * their POSTs stop here.
 *
 * The key only ever goes to the configured backend: the path must be a plain
 * /api/... path (lib/requestGuards.ts) and redirects are followed by hand,
 * back to the backend only. POSTs must come from a dashboard page and carry
 * JSON.
 */
async function proxyRequest(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
  method: string,
) {
  const session = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (method !== "GET" && !sameOrigin(request.headers.get("origin"), request.headers.get("host"))) {
    return NextResponse.json({ error: "Cross-site request refused" }, { status: 403 });
  }
  const { path } = await params;
  const url = proxyTarget(path, request.nextUrl.search, BACKEND);
  if (!url) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  if (method !== "GET" && session.role !== "admin" && !SELF_SERVICE_POSTS.includes(url.pathname)) {
    return NextResponse.json({ detail: "Your account is read-only" }, { status: 403 });
  }

  // POST bodies (approve / decline / update payloads) are forwarded as-is;
  // GETs have none.
  const init: RequestInit = { method, headers: backendHeaders(session), redirect: "manual" };
  if (method !== "GET") {
    const body = await request.text();
    if (body) {
      if (!isJson(request.headers.get("content-type"))) {
        return NextResponse.json({ error: "Send JSON" }, { status: 415 });
      }
      init.body = body;
      (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    }
  }
  let res = await fetch(url, init);
  // FastAPI answers /api/x with a 307 to /api/x/ (Next strips the browser's
  // trailing slash first). Follow it once, to the backend only.
  if (res.status === 307 || res.status === 308) {
    const next = sameBackendRedirect(res.headers.get("location"), url);
    if (next) res = await fetch(next, init);
  }

  const data = await res.json().catch(() => undefined);
  if (data === undefined) {
    return NextResponse.json({ error: "Unexpected response from the API" }, { status: 502 });
  }
  return NextResponse.json(data, { status: res.status });
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context, "GET");
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, context, "POST");
}
