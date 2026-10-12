import { NextRequest, NextResponse } from "next/server";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";
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
  const { path } = await params;
  const backendPath = `/${path.join("/")}`;
  if (method !== "GET" && session.role !== "admin" && !SELF_SERVICE_POSTS.includes(backendPath)) {
    return NextResponse.json({ detail: "Your account is read-only" }, { status: 403 });
  }
  const url = new URL(backendPath, BACKEND);
  url.search = request.nextUrl.search;

  // POST bodies (approve / decline / update payloads) are forwarded as-is;
  // GETs have none.
  const init: RequestInit = { method, headers: backendHeaders(session) };
  if (method !== "GET") {
    const body = await request.text();
    if (body) {
      init.body = body;
      (init.headers as Record<string, string>)["Content-Type"] =
        request.headers.get("content-type") ?? "application/json";
    }
  }
  const res = await fetch(url.toString(), init);

  const data = await res.json();
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
