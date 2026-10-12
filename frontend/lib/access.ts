/**
 * Which dashboard pages each role may open. Client-safe (no env), so the
 * middleware, the nav and pages share one table. The backend applies the
 * matching API rules (backend/accounts.py); this file decides only what the
 * browser is shown.
 *
 *   admin    everything
 *   general  analytics, including the athlete roster; read-only
 *   demo     aggregate analytics only; read-only
 */

export type Role = "admin" | "general" | "demo";

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  general: "General",
  demo: "Demo",
};

const AGGREGATE_PAGES = [
  "/zoomph",
  "/trueblue",
  "/web-analytics",
  "/niltv",
  "/niltv-channels",
  "/niltv-campus-channels",
  "/niltv-web-analytics",
];
const ROSTER_PAGES = ["/", "/player-details", "/athletes"];
// Every signed-in account can manage its own password.
const SELF_PAGES = ["/account"];

const PAGES: Record<Exclude<Role, "admin">, string[]> = {
  general: [...ROSTER_PAGES, ...AGGREGATE_PAGES, ...SELF_PAGES],
  demo: [...AGGREGATE_PAGES, ...SELF_PAGES],
};

function under(pathname: string, page: string): boolean {
  if (page === "/") return pathname === "/";
  return pathname === page || pathname.startsWith(`${page}/`);
}

export function canSeePage(role: Role, pathname: string): boolean {
  if (role === "admin") return true;
  return PAGES[role].some((p) => under(pathname, p));
}

/** Where a role lands after sign-in or when it opens a page it can't see. */
export function homeFor(role: Role): string {
  return role === "demo" ? "/niltv" : "/";
}

/** Session fields the browser may see (no secrets). */
export interface SessionUser {
  uid: number;
  email: string;
  name: string;
  role: Role;
}
