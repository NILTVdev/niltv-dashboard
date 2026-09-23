import { NextRequest, NextResponse } from "next/server";

import { API_KEY, BACKEND_URL as BACKEND } from "@/lib/serverEnv";
import { isValidSession } from "@/lib/session";

/**
 * Catch-all proxy: forwards client-side requests to the backend
 * with the X-API-Key header attached (keeps the key server-side).
 *
 * Usage: fetch("/api/proxy/api/zoomph/summary?author=foo")
 *   → GET https://api.niltv.com/api/zoomph/summary?author=foo
 *
 * Only a valid dashboard session may use it: the key never leaves the server
 * and an anonymous caller gets 401.
 */
async function proxyRequest(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
  method: string,
) {
  if (!(await isValidSession(request.cookies.get("auth_token")?.value))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { path } = await params;
  const backendPath = `/${path.join("/")}`;
  const url = new URL(backendPath, BACKEND);
  url.search = request.nextUrl.search;

  // POST bodies (approve / decline / update payloads) are forwarded as-is;
  // GETs have none.
  const init: RequestInit = { method, headers: { "X-API-Key": API_KEY } };
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
