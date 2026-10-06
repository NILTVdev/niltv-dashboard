import AdminView from "@/components/AdminView";
import UsersAdmin from "@/components/UsersAdmin";
import { getSessionUser } from "@/lib/serverSession";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const me = await getSessionUser();
  return (
    <div className="space-y-6">
      <AdminView />
      <UsersAdmin me={me?.username ?? null} />
    </div>
  );
}
