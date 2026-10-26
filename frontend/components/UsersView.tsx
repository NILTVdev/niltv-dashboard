"use client";

import { useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";
import { ROLE_LABEL, type Role } from "@/lib/access";

interface DashboardUser {
  id: number;
  email: string;
  name: string;
  role: Role;
  active: boolean;
  created_at: string | null;
  created_by: string | null;
  last_login_at: string | null;
}

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything: onboarding, uploads, reports, user accounts",
  general: "Analytics and the athlete roster, read-only",
  demo: "Aggregate analytics only, read-only",
};
const ROLES: Role[] = ["admin", "general", "demo"];

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/proxy/api/users/${path}`, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? data?.error ?? `HTTP ${res.status}`);
  return data as T;
}

export default function UsersView() {
  const [users, setUsers] = useState<DashboardUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({ email: "", name: "", role: "general" as Role, password: "" });
  const [busy, setBusy] = useState(false);
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [resetPw, setResetPw] = useState("");

  async function load() {
    try {
      setUsers(await call<DashboardUser[]>(""));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(done);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function create(e: React.FormEvent) {
    e.preventDefault();
    run(async () => {
      await call("", form);
      setForm({ email: "", name: "", role: form.role, password: "" });
    }, `Account created for ${form.email.trim().toLowerCase()}. Share the password with them directly.`);
  }

  const update = (u: DashboardUser, patch: Partial<DashboardUser> & { password?: string }, done: string) =>
    run(() => call(`${u.id}/update`, patch), done);

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-bold tracking-tight">Users</h1>
        <p className="text-sm text-gray-500 mt-1">
          One account per person. Disabling an account cuts off its access on its next click.
        </p>
      </div>

      <div className="mb-5 grid gap-2 sm:grid-cols-3 text-xs">
        {ROLES.map((r) => (
          <div key={r} className="rounded-lg border bg-white px-3 py-2">
            <div className="font-semibold">{ROLE_LABEL[r]}</div>
            <div className="text-gray-500">{ROLE_HELP[r]}</div>
          </div>
        ))}
      </div>

      {error && <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}
      {notice && <div className="mb-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</div>}

      <form onSubmit={create} className="mb-6 rounded-xl border bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center gap-2 font-semibold"><UserPlus className="h-4 w-4" /> Add an account</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <input required type="email" placeholder="Email" value={form.email}
                 onChange={(e) => setForm({ ...form, email: e.target.value })}
                 className="h-9 rounded-md border px-3 text-sm" />
          <input required placeholder="Name" value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })}
                 className="h-9 rounded-md border px-3 text-sm" />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
                  className="h-9 rounded-md border px-2 text-sm bg-white">
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <input required type="text" minLength={10} placeholder="Starting password (10+ characters)" value={form.password}
                 autoComplete="new-password"
                 onChange={(e) => setForm({ ...form, password: e.target.value })}
                 className="h-9 rounded-md border px-3 text-sm" />
          <button type="submit" disabled={busy}
                  className="h-9 rounded-md bg-[var(--brand)] px-3 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
            Create account
          </button>
        </div>
      </form>

      <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last sign-in</th>
              <th className="px-3 py-2">Created</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {users.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-gray-400">No accounts yet. Create the first admin above.</td></tr>
            )}
            {users.map((u) => (
              <tr key={u.id} className={cn(!u.active && "bg-gray-50 text-gray-400")}>
                <td className="px-3 py-2">
                  <div className="font-medium">{u.name}</div>
                  <div className="text-xs text-gray-500">{u.email}</div>
                </td>
                <td className="px-3 py-2">
                  <select value={u.role} disabled={busy}
                          onChange={(e) => update(u, { role: e.target.value as Role }, `${u.email} is now ${ROLE_LABEL[e.target.value as Role]}.`)}
                          className="h-8 rounded-md border px-2 text-xs bg-white">
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                  </select>
                </td>
                <td className="px-3 py-2 text-xs">{u.active ? "Active" : "Disabled"}</td>
                <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{u.last_login_at ? fmtDate(u.last_login_at) : "Never"}</td>
                <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">
                  {u.created_at ? fmtDate(u.created_at) : ""}{u.created_by ? ` by ${u.created_by}` : ""}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {resetFor === u.id ? (
                    <span className="inline-flex items-center gap-1">
                      <input type="text" minLength={10} placeholder="New password" value={resetPw} autoComplete="new-password"
                             onChange={(e) => setResetPw(e.target.value)} className="h-8 w-44 rounded-md border px-2 text-xs" />
                      <button disabled={busy || resetPw.length < 10}
                              onClick={() => { update(u, { password: resetPw }, `Password reset for ${u.email}.`); setResetFor(null); setResetPw(""); }}
                              className="h-8 rounded-md bg-[var(--brand)] px-2 text-xs font-semibold text-white disabled:opacity-50">Save</button>
                      <button onClick={() => { setResetFor(null); setResetPw(""); }} className="h-8 rounded-md border px-2 text-xs">Cancel</button>
                    </span>
                  ) : (
                    <span className="inline-flex gap-1">
                      <button disabled={busy} onClick={() => setResetFor(u.id)}
                              className="h-8 rounded-md border px-2 text-xs font-semibold hover:bg-gray-50">Reset password</button>
                      <button disabled={busy}
                              onClick={() => update(u, { active: !u.active }, `${u.email} ${u.active ? "disabled" : "enabled"}.`)}
                              className={cn("h-8 rounded-md border px-2 text-xs font-semibold",
                                u.active ? "border-red-200 text-red-700 hover:bg-red-50" : "hover:bg-gray-50")}>
                        {u.active ? "Disable" : "Enable"}
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
