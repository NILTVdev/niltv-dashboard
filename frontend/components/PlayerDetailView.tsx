"use client";

import { useState, useMemo, useEffect } from "react";
import FollowerChart from "@/components/FollowerChart";
import LikesChart from "@/components/LikesChart";
import PostsGrid from "@/components/PostsGrid";
import InstagramIcon from "@/components/icons/InstagramIcon";
import { fmt, fmtDate } from "@/lib/utils";
import type { Athlete, Snapshot, Post } from "@/lib/types";

const API = "/api/proxy";

interface Props {
  athletes: Athlete[];
  sports: string[];
}

export default function PlayerDetailView({ athletes, sports }: Props) {
  const [sport, setSport] = useState("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [engagementByDay, setEngagementByDay] = useState<{ date: string; likes: number; comments: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const [prevSport, setPrevSport] = useState(sport);

  const roster = useMemo(() => {
    if (sport === "all") return athletes;
    return athletes.filter((a) => a.sport === sport);
  }, [athletes, sport]);

  const athlete = useMemo(
    () => athletes.find((a) => a.id === selectedId) ?? null,
    [athletes, selectedId]
  );

  // Reset player selection + detail data when the sport filter changes.
  // Done during render (React's "adjusting state when a value changes" pattern)
  // instead of in an effect, to avoid cascading renders.
  if (sport !== prevSport) {
    setPrevSport(sport);
    setSelectedId(null);
    setSnapshots([]);
    setPosts([]);
    setEngagementByDay([]);
  }

  // Fetch detail data when player selected. Data is cleared on deselect by the
  // player <select> handler, so this effect only ever fetches.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;

    Promise.all([
      fetch(`${API}/api/snapshots/athletes/${selectedId}`).then((r) => r.json()) as Promise<Snapshot[]>,
      fetch(`${API}/api/posts/athletes/${selectedId}`).then((r) => r.json()) as Promise<Post[]>,
      fetch(`${API}/api/posts/athletes/${selectedId}/engagement-by-day`).then((r) => r.json()).catch(() => []) as Promise<{ date: string; likes: number; comments: number }[]>,
    ])
      .then(([snaps, p, eng]) => {
        if (cancelled) return;
        setSnapshots(snaps);
        setPosts(p);
        setEngagementByDay(eng);
      })
      .catch(() => {
        if (cancelled) return;
        setSnapshots([]);
        setPosts([]);
        setEngagementByDay([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const avgLikes =
    posts.length > 0
      ? Math.round(posts.reduce((s, p) => s + (p.like_count ?? 0), 0) / posts.length)
      : null;

  return (
    <div className="space-y-6">
      {/* Selectors */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Sport filter */}
          <div>
            <label className="block text-xs font-semibold text-[#64748b] mb-1.5">
              Select Sport
            </label>
            <select
              value={sport}
              onChange={(e) => setSport(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
            >
              <option value="all">All Sports</option>
              {sports.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {/* Player selector */}
          <div>
            <label className="block text-xs font-semibold text-[#64748b] mb-1.5">
              Select Player
            </label>
            <select
              value={selectedId ?? ""}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : null;
                setSelectedId(id);
                if (id === null) {
                  setSnapshots([]);
                  setPosts([]);
                  setEngagementByDay([]);
                  setLoading(false);
                } else {
                  setLoading(true);
                }
              }}
              className="w-full px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
            >
              <option value="">— Choose a player —</option>
              {roster.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} — {a.sport ?? "N/A"}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-xs text-[#94a3b8]">
          Tip: use the roster search first, then pick a player here.
        </p>
      </div>

      {/* Player detail */}
      {loading && (
        <div className="text-center py-12 text-sm text-[#94a3b8]">Loading…</div>
      )}

      {athlete && !loading && (
        <>
          {/* Header card */}
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h2 className="text-2xl font-bold text-[#0f172a]">{athlete.name}</h2>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  {athlete.sport && (
                    <span className="text-xs bg-[var(--brand-pale)] text-[var(--brand)] font-medium px-2 py-0.5 rounded-full">
                      {athlete.sport}
                    </span>
                  )}
                  {/* Year hidden until the roster import populates it */}
                </div>
                {snapshots[0]?.ig_bio && (
                  <p className="text-sm text-[#64748b] mt-3 max-w-xl">
                    {snapshots[0].ig_bio}
                  </p>
                )}
              </div>
              {athlete.ig_handle && (
                <a
                  href={`https://instagram.com/${athlete.ig_handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[#e2e8f0] text-sm hover:bg-[#f8fafc] transition-colors"
                >
                  <InstagramIcon size={14} /> @{athlete.ig_handle}
                </a>
              )}
            </div>

            {/* KPIs */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6">
              {[
                { label: "IG Followers", value: fmt(athlete.ig_followers) },
                { label: "IG Posts", value: fmt(athlete.ig_posts) },
                { label: "Avg Likes", value: fmt(avgLikes) },
                { label: "Last Pulled", value: fmtDate(athlete.last_pulled) },
              ].map((k) => (
                <div key={k.label} className="text-center">
                  <p className="text-xs text-[#94a3b8] mb-0.5">{k.label}</p>
                  <p className="text-lg font-bold text-[var(--brand)]">{k.value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Follower chart */}
          {snapshots.length > 0 && (
            <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
              <h3 className="text-sm font-semibold text-[#0f172a] mb-4">
                Instagram Followers Over Time
              </h3>
              <FollowerChart snapshots={snapshots} />
            </div>
          )}

          {/* Likes over time */}
          {posts.length > 0 && (
            <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
              <h3 className="text-sm font-semibold text-[#0f172a] mb-4">
                Likes Over Time
              </h3>
              <LikesChart posts={posts} engagementByDay={engagementByDay} />
            </div>
          )}

          {/* Recent posts */}
          <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
            <h3 className="text-sm font-semibold text-[#0f172a] mb-4">
              Recent Instagram Posts
            </h3>
            <PostsGrid posts={posts} />
          </div>
        </>
      )}

      {!athlete && !loading && (
        <div className="text-center py-16 text-sm text-[#94a3b8]">
          Select a player above to view their details.
        </div>
      )}
    </div>
  );
}
