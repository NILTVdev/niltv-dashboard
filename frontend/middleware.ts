import { NextRequest, NextResponse } from "next/server";
import { authDisabled } from "@/lib/serverEnv";
import { canSeePage, HOME } from "@/lib/access";
import { SESSION_COOKIE, bootstrapOpen, getSession, refreshSession, sessionCookieOptions } from "@/lib/session";

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

  // The cookie must carry a signed, unexpired session, not merely exist.
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  let session = await getSession(token);
  // A shared-login session ends as soon as the first admin account exists.
  if (session?.uid === 0 && !(await bootstrapOpen())) session = null;
  // A personal account is re-read from the backend at most every RECHECK_SECONDS:
  // a role change updates the cookie, a disabled account is signed out.
  let renewed: { token: string; maxAge: number } | null = null;
  if (session && session.uid > 0) {
    const r = await refreshSession(session);
    if (r.kind === "ended") session = null;
    else if (r.kind === "renewed") {
      session = r.session;
      renewed = { token: r.token, maxAge: r.maxAge };
      // This request's page and route handlers read the new cookie too.
      request.cookies.set(SESSION_COOKIE, r.token);
    }
  }
  if (!session) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    const loginUrl = new URL("/login", request.url);
    const res = NextResponse.redirect(loginUrl);
    if (token) res.cookies.delete(SESSION_COOKIE);
    return res;
  }

  // Pages the role can't see send it to its home page. API routes check the
  // role themselves (proxy, uploads) and the backend checks every call.
  // The router serves the decoded path (/truebluetv/%72oster is the roster),
  // so the role check must see it decoded too. Undecodable paths go home.
  let page: string | null;
  try {
    page = decodeURIComponent(pathname);
  } catch {
    page = null;
  }
  const res = !pathname.startsWith("/api/") && (page === null || !canSeePage(session.role, page))
    ? NextResponse.redirect(new URL(HOME, request.url))
    : NextResponse.next({ request: { headers: request.headers } });
  if (renewed) res.cookies.set(SESSION_COOKIE, renewed.token, sessionCookieOptions(renewed.maxAge));
  return res;
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
