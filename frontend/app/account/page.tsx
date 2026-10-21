"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ROLE_LABEL, type SessionUser } from "@/lib/access";

export default function AccountPage() {
  const [me, setMe] = useState<SessionUser | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  useEffect(() => {
    fetch("/api/auth").then((r) => (r.ok ? r.json() : null)).then(setMe).catch(() => {});
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== repeat) {
      setMsg({ ok: false, text: "The new passwords do not match." });
      return;
    }
    setBusy(true);
    setMsg(null);
    const res = await fetch("/api/proxy/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (res.ok) {
      // The change ends every session of this account, this one included.
      setCurrent(""); setNext(""); setRepeat("");
      setMsg({ ok: true, text: "Password changed. Sign in again with your new password." });
      await fetch("/api/auth", { method: "DELETE" }).catch(() => {});
      setTimeout(() => router.push("/login"), 1500);
    } else {
      setMsg({ ok: false, text: data?.detail ?? data?.error ?? "Could not change the password." });
    }
  }

  const shared = me?.uid === 0;
  return (
    <div className="max-w-md">
      <h1 className="text-2xl font-bold tracking-tight mb-1">Your account</h1>
      {me && (
        <p className="text-sm text-gray-500 mb-6">
          {me.name} · {me.email} · {ROLE_LABEL[me.role]}
        </p>
      )}
      {shared ? (
        <p className="text-sm text-gray-600">
          You are signed in with the shared login. Create your own admin account on the Users page,
          then sign in with it. The shared login stops working once an admin account exists.
        </p>
      ) : (
        <form onSubmit={submit} className="space-y-3 rounded-xl border bg-white p-4 shadow-sm">
          <div className="font-semibold">Change password</div>
          <input type="password" required placeholder="Current password" value={current} autoComplete="current-password"
                 onChange={(e) => setCurrent(e.target.value)} className="h-9 w-full rounded-md border px-3 text-sm" />
          <input type="password" required minLength={10} placeholder="New password (10+ characters)" value={next} autoComplete="new-password"
                 onChange={(e) => setNext(e.target.value)} className="h-9 w-full rounded-md border px-3 text-sm" />
          <input type="password" required minLength={10} placeholder="Repeat new password" value={repeat} autoComplete="new-password"
                 onChange={(e) => setRepeat(e.target.value)} className="h-9 w-full rounded-md border px-3 text-sm" />
          {msg && <p className={msg.ok ? "text-sm text-emerald-700" : "text-sm text-red-700"}>{msg.text}</p>}
          <button type="submit" disabled={busy}
                  className="h-9 rounded-md bg-[var(--brand)] px-4 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
            Change password
          </button>
        </form>
      )}
    </div>
  );
}
