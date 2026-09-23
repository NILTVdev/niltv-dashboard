import { NextRequest, NextResponse } from "next/server";
import { authDisabled } from "@/lib/serverEnv";
import { isValidSession } from "@/lib/session";

// Hostnames the dashboard used to be served from, redirected permanently to
// where it lives now. Remove once the old domain association is deleted.
const HOST_REDIRECTS: Record<string, string> = {
  "dashboard.truebluetv.com": "dashboard.niltv.com",
  "dashboard-dev.truebluetv.com": "dashboard-dev.niltv.com",
};

// Paths that never need a session: the login page, the login/logout endpoint
// and the deploy probe.
const PUBLIC_PATHS = ["/login", "/api/auth", "/api/health"];

export async function middleware(request: NextRequest) {
  const host = request.headers.get("host")?.split(":")[0] ?? "";
  const target = HOST_REDIRECTS[host];
  if (target) {
    const url = request.nextUrl.clone();
    url.protocol = "https:";
    url.host = target;
    url.port = "";
    return NextResponse.redirect(url, 308);
  }

  // LOCAL environment: AUTH_DISABLED=true (ignored in production builds).
  if (authDisabled()) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }

  // The cookie must carry the current session token, not merely exist.
  const token = request.cookies.get("auth_token")?.value;
  if (!(await isValidSession(token))) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    const loginUrl = new URL("/login", request.url);
    const res = NextResponse.redirect(loginUrl);
    if (token) res.cookies.delete("auth_token");
    return res;
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Run on every route except static assets (/_next, /favicon.ico, /images)
     * so the host redirect covers /login and the API routes too; the
     * session check itself skips PUBLIC_PATHS above.
     */
    "/((?!_next|favicon\.ico|images).*)",
  ],
};
