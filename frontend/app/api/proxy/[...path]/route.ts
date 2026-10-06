import { NextRequest, NextResponse } from "next/server";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";
import { backendHeaders } from "@/lib/serverSession";
import { readSession, SESSION_COOKIE } from "@/lib/session";

/**
 * Catch-all proxy: forwards client-side requests to the backend with the
 * X-API-Key header (keeps the key server-side) and the user's session token,
 * which the backend checks on the role-gated routes.
 *
 * Usage: fetch("/api/proxy/api/zoomph/summary?author=foo")
 *   → GET https://api.niltv.com/api/zoomph/summary?author=foo
 *
 * Only a valid dashboard session may use it: the key never leaves the server
 * and an anonymous caller gets 401. When the backend rejects the session
 * (user removed, role or password changed) the cookie is cleared.
 */
async function proxyRequest(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
  method: string,
) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!(await readSession(token))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { path } = await params;
  const backendPath = `/${path.join("/")}`;
  const url = new URL(backendPath, BACKEND);
  url.search = request.nextUrl.search;

  // POST bodies (approve / decline / update payloads) are forwarded as-is;
  // GETs have none.
  const init: RequestInit = { method, headers: backendHeaders(token) };
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
  const response = NextResponse.json(data, { status: res.status });
  if (res.status === 401 && token) response.cookies.delete(SESSION_COOKIE);
  return response;
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
