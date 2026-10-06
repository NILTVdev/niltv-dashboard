"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, KeyRound, Trash2, UserPlus, CheckCircle2, XCircle } from "lucide-react";
import { fmtDate } from "@/lib/utils";
import { ROLES, ROLE_LABEL, type Role } from "@/lib/roles";

interface DashboardUser {
  id: number;
  username: string;
  role: Role;
  created_at: string | null;
  last_login_at: string | null;
}

const ROLE_HELP: Record<Role, string> = {
  viewer: "Data screens only",
  onboarding: "Data screens + onboarding workflow",
  admin: "Everything, including this page",
};

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/proxy/api/users${path}`, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : data?.error ?? `HTTP ${res.status}`);
  }
  return data as T;
}

const input =
  "px-3 py-2 rounded-lg border border-[#e2e8f0] text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand)] focus:border-transparent";
const button =
  "flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-[#e2e8f0] bg-white text-[#64748b] hover:text-[var(--brand)] hover:border-[var(--brand)] transition-colors disabled:opacity-50";

export default function UsersAdmin({ me }: { me: string | null }) {
  const [users, setUsers] = useState<DashboardUser[] | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<{ username: string; password: string; role: Role }>({
    username: "", password: "", role: "viewer",
  });
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await call<DashboardUser[]>(""));
    } catch (e) {
      setStatus({ ok: false, message: (e as Error).message });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function run(id: number | "new", fn: () => Promise<unknown>, done: string): Promise<boolean> {
    setBusy(id);
    setStatus(null);
    try {
      await fn();
      setStatus({ ok: true, message: done });
      await load();
      return true;
    } catch (e) {
      setStatus({ ok: false, message: (e as Error).message });
      return false;
    } finally {
      setBusy(null);
    }
  }

  function addUser(e: React.FormEvent) {
    e.preventDefault();
    const username = form.username.trim().toLowerCase();
    run("new", () => call("", { ...form, username }), `Added ${username}`).then((ok) => {
      if (ok) setForm((f) => ({ ...f, username: "", password: "" }));
    });
  }

  function changeRole(u: DashboardUser, role: Role) {
    run(u.id, () => call(`/${u.id}/update`, { role }), `${u.username} is now ${ROLE_LABEL[role]}`);
  }

  function savePassword(u: DashboardUser) {
    run(u.id, () => call(`/${u.id}/update`, { password: resetPassword }),
      `Password changed for ${u.username}; they have been signed out`).then((ok) => {
      if (!ok) return;
      setResetFor(null);
      setResetPassword("");
    });
  }

  function remove(u: DashboardUser) {
    if (!window.confirm(`Remove ${u.username}? They will be signed out and cannot sign in again.`)) return;
    run(u.id, () => call(`/${u.id}/delete`, {}), `Removed ${u.username}`);
  }

  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[#0f172a]">Users</h2>
          <p className="text-xs text-[#64748b]">
            Everyone signs in with their own account. Changing a role or password signs that person out.
          </p>
        </div>
        {status && (
          <span className={`flex items-center gap-1 text-xs ${status.ok ? "text-emerald-600" : "text-red-500"}`}>
            {status.ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
            {status.message}
          </span>
        )}
      </div>

      <form onSubmit={addUser} className="flex flex-wrap items-center gap-2">
        <input
          className={input}
          placeholder="Username"
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          autoComplete="off"
          required
        />
        <input
          className={input}
          type="password"
          placeholder="Password (10+ characters)"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          autoComplete="new-password"
          minLength={10}
          required
        />
        <select
          className={input}
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
          aria-label="Role"
        >
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}: {ROLE_HELP[r]}</option>)}
        </select>
        <button type="submit" className={button} disabled={busy === "new"}>
          {busy === "new" ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
          Add user
        </button>
      </form>

      {users === null ? (
        <p className="text-xs text-[#64748b]">Loading…</p>
      ) : users.length === 0 ? (
        <p className="text-xs text-[#64748b]">No users yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[#64748b] border-b border-[#e2e8f0]">
                <th className="py-2 pr-4 font-medium">Username</th>
                <th className="py-2 pr-4 font-medium">Role</th>
                <th className="py-2 pr-4 font-medium">Last sign-in</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-[#f1f5f9] last:border-0">
                  <td className="py-2 pr-4 text-[#0f172a] font-medium whitespace-nowrap">
                    {u.username}
                    {u.username === me && <span className="ml-1.5 text-[#94a3b8] font-normal">(you)</span>}
                  </td>
                  <td className="py-2 pr-4">
                    <select
                      className={input}
                      value={u.role}
                      disabled={busy === u.id}
                      onChange={(e) => changeRole(u, e.target.value as Role)}
                      aria-label={`Role for ${u.username}`}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                    </select>
                  </td>
                  <td className="py-2 pr-4 text-[#64748b] whitespace-nowrap">
                    {u.last_login_at ? fmtDate(u.last_login_at) : "Never"}
                  </td>
                  <td className="py-2">
                    <div className="flex items-center justify-end gap-2">
                      {resetFor === u.id ? (
                        <>
                          <input
                            className={input}
                            type="password"
                            placeholder="New password"
                            value={resetPassword}
                            onChange={(e) => setResetPassword(e.target.value)}
                            autoComplete="new-password"
                            minLength={10}
                            autoFocus
                          />
                          <button className={button} disabled={busy === u.id || resetPassword.length < 10}
                                  onClick={() => savePassword(u)}>
                            Save
                          </button>
                          <button className={button} onClick={() => { setResetFor(null); setResetPassword(""); }}>
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button className={button} disabled={busy === u.id}
                                onClick={() => { setResetFor(u.id); setResetPassword(""); }}>
                          <KeyRound size={14} />
                          Reset password
                        </button>
                      )}
                      <button
                        className={`${button} hover:!text-red-600 hover:!border-red-300`}
                        disabled={busy === u.id || u.username === me}
                        title={u.username === me ? "You cannot remove your own account" : undefined}
                        onClick={() => remove(u)}
                      >
                        {busy === u.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
