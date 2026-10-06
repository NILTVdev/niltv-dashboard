// Dashboard roles, lowest to highest. Safe to import from client components.
// The backend (backend/auth.py) enforces the same ladder on the API routes;
// the checks here only decide which pages and links a user is shown.
export const ROLES = ["viewer", "onboarding", "admin"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABEL: Record<Role, string> = {
  viewer: "Viewer",
  onboarding: "Onboarding",
  admin: "Admin",
};

export function hasRole(role: Role | null | undefined, minimum: Role): boolean {
  if (!role) return false;
  return ROLES.indexOf(role) >= ROLES.indexOf(minimum);
}

/** The signed-in user as the UI sees it. */
export interface SessionUser {
  username: string;
  role: Role;
}
