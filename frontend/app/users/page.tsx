import UsersView from "@/components/UsersView";

export const dynamic = "force-dynamic";

// Admin-only: the middleware sends other roles to their home page, and the
// backend refuses /api/users for them.
export default function UsersPage() {
  return <UsersView />;
}
