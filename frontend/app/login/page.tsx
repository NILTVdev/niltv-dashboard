"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      router.push(data.home ?? "/");
      router.refresh();
    } else {
      setError(data.error ?? "Invalid email or password.");
      setLoading(false);
    }
  }

  return (
    // Fixed so the dark ground covers the whole window, not just the layout's <main> column.
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center bg-[var(--brand)] px-4">
      <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#17171c] p-8 shadow-2xl">
        <div className="flex justify-center mb-6">
          {/* Black-ground export; screen-blended into the dark card. */}
          <Image src="/niltv-logo.png" alt="NIL TV" width={150} height={56}
                 className="mix-blend-screen" priority />
        </div>
        <h1 className="text-center text-lg font-semibold text-white mb-1">
          Network Dashboard
        </h1>
        <p className="text-center text-sm text-white/60 mb-6">
          Sign in to continue
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="text"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="username"
            className="w-full px-4 py-2.5 rounded-lg border border-white/15 bg-white/5 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-[var(--brand-light)] focus:border-transparent"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            className="w-full px-4 py-2.5 rounded-lg border border-white/15 bg-white/5 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-[var(--brand-light)] focus:border-transparent"
          />
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[var(--brand-light)] hover:brightness-110 text-[var(--brand)] text-sm font-semibold py-2.5 rounded-lg transition disabled:opacity-60"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
