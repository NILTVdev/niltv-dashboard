import { NextRequest, NextResponse } from "next/server";
import { hasRole, type Role } from "@/lib/roles";
import { API_KEY, authDisabled, BACKEND_URL } from "@/lib/serverEnv";
import { readSession, SESSION_COOKIE, SESSION_HEADER } from "@/lib/session";

// Hostnames the dashboard used to be served from, redirected permanently to
// where it lives now. Remove once the old domain association is deleted.
const HOST_REDIRECTS: Record<string, string> = {
  "dashboard.truebluetv.com": "dashboard.niltv.com",
  "dashboard-dev.truebluetv.com": "dashboard-dev.niltv.com",
};

// Paths that never need a session: the login page, the login/logout endpoint
// and the deploy probe.
const PUBLIC_PATHS = ["/login", "/api/auth", "/api/health"];

// Minimum role per path prefix; everything else needs any signed-in user
// (viewer). The backend enforces the same roles on its API routes, so these
// rules decide what a user is shown; the backend decides what they can do.
const ROLE_RULES: [string, Role][] = [
  ["/adminpage", "admin"],
  ["/api/brand/upload", "admin"],
  ["/api/trueblue/upload", "admin"],
  ["/api/proxy/api/users", "admin"],
  ["/api/proxy/api/reports", "admin"],
  ["/niltv-onboarding", "onboarding"],
  ["/api/proxy/api/applications", "onboarding"],
];

function matches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

// A signed token can outlive the account: the backend retires it when the
// user is removed or their role or password changes. Page loads ask the
// backend so that takes effect at once; API calls skip this because the
// backend checks the session on each of them anyway. A backend that cannot
// be reached is not treated as a sign-out (the page's data calls fail instead).
async function sessionRevoked(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
      headers: { "X-API-Key": API_KEY, [SESSION_HEADER]: token },
      cache: "no-store",
    });
    return res.status === 401;
  } catch {
    return false;
  }
}

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
  if (PUBLIC_PATHS.some((p) => matches(pathname, p))) {
    return NextResponse.next();
  }

  // The cookie must carry a validly signed, unexpired session, not merely exist.
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const session = await readSession(token);
  const isApi = pathname.startsWith("/api/");
  if (!session || (!isApi && token && (await sessionRevoked(token)))) {
    if (isApi) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    const loginUrl = new URL("/login", request.url);
    const res = NextResponse.redirect(loginUrl);
    if (token) res.cookies.delete(SESSION_COOKIE);
    return res;
  }

  const rule = ROLE_RULES.find(([prefix]) => matches(pathname, prefix));
  if (rule && !hasRole(session.role, rule[1])) {
    if (isApi) {
      return NextResponse.json({ error: `Requires the ${rule[1]} role` }, { status: 403 });
    }
    return NextResponse.redirect(new URL("/", request.url));
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
