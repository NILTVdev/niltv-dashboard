/**
 * Which dashboard pages each role may open. Client-safe (no env), so the
 * middleware, the nav and pages share one table. The backend applies the
 * matching API rules (backend/accounts.py); this file decides only what the
 * browser is shown.
 *
 *   admin    everything
 *   general  analytics, including the athlete roster; read-only
 *   demo     aggregate analytics only; read-only
 *
 * Everyone lands on the NIL TV network page.
 */

import { CAMPUS_CHANNELS, TRUEBLUETV } from "./channels";

export type Role = "admin" | "general" | "demo";

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  general: "General",
  demo: "Demo",
};

// Campus Channels covers the channel sections nested under it (TrueBlueTV's
// Duke Owned, TrueBlue TV and Web Analytics tabs).
const AGGREGATE_PAGES = [
  "/niltv",
  "/niltv-channels",
  CAMPUS_CHANNELS,
  "/niltv-web-analytics",
];
// Athlete-level pages. They sit inside Campus Channels, so canSeePage checks
// them before the section-wide grant above.
const ROSTER_PAGES = [`${TRUEBLUETV}/roster`, `${TRUEBLUETV}/player-details`, `${TRUEBLUETV}/athletes`];
// Every signed-in account can manage its own password.
const SELF_PAGES = ["/account"];

const PAGES: Record<Exclude<Role, "admin">, string[]> = {
  general: [...AGGREGATE_PAGES, ...SELF_PAGES],
  demo: [...AGGREGATE_PAGES, ...SELF_PAGES],
};

function under(pathname: string, page: string): boolean {
  return pathname === page || pathname.startsWith(`${page}/`);
}

export function canSeePage(role: Role, pathname: string): boolean {
  if (role === "admin") return true;
  if (ROSTER_PAGES.some((p) => under(pathname, p))) return role === "general";
  return PAGES[role].some((p) => under(pathname, p));
}

/** Where every role lands after sign-in or when it opens a page it can't see. */
export const HOME = "/niltv";

/** Session fields the browser may see (no secrets). */
export interface SessionUser {
  uid: number;
  email: string;
  name: string;
  role: Role;
}
