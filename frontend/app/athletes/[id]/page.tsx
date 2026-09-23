import { notFound } from "next/navigation";
import Link from "next/link";
import { getAthlete, getSnapshots, getPosts } from "@/lib/api";
import FollowerChart from "@/components/FollowerChart";
import LikesChart from "@/components/LikesChart";
import PostsGrid from "@/components/PostsGrid";
import { fmt, fmtDate } from "@/lib/utils";
import { ArrowLeft } from "lucide-react";
import InstagramIcon from "@/components/icons/InstagramIcon";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AthleteDetailPage({ params }: Props) {
  const { id } = await params;
  const athleteId = parseInt(id, 10);
  if (isNaN(athleteId)) notFound();

  const [athlete, snapshots, posts] = await Promise.all([
    getAthlete(athleteId).catch(() => null),
    getSnapshots(athleteId).catch(() => []),
    getPosts(athleteId).catch(() => []),
  ]);

  if (!athlete) notFound();

  const latest = snapshots[0];
  const avgLikes =
    posts.length > 0
      ? Math.round(
          posts.reduce((s, p) => s + (p.like_count ?? 0), 0) / posts.length
        )
      : null;

  const kpis = [
    { label: "IG Followers", value: fmt(athlete.ig_followers) },
    { label: "IG Posts", value: fmt(athlete.ig_posts) },
    { label: "Avg Likes", value: fmt(avgLikes) },
    { label: "Last Pulled", value: fmtDate(athlete.last_pulled) },
  ];

  return (
    <div className="space-y-6">
      {/* Back */}
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-[#64748b] hover:text-[var(--brand)] transition-colors"
      >
        <ArrowLeft size={14} /> Back to Roster
      </Link>

      {/* Header */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-[#0f172a]">{athlete.name}</h1>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {athlete.sport && (
                <span className="text-xs bg-[var(--brand-pale)] text-[var(--brand)] font-medium px-2 py-0.5 rounded-full">
                  {athlete.sport}
                </span>
              )}
              {/* Year hidden until the roster import populates it */}
            </div>
            {latest?.ig_bio && (
              <p className="text-sm text-[#64748b] mt-3 max-w-xl">{latest.ig_bio}</p>
            )}
          </div>
          <div className="flex gap-2">
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
        </div>

        {/* KPI grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6">
          {kpis.map((k) => (
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
          <h2 className="text-sm font-semibold text-[#0f172a] mb-4">
            Instagram Followers Over Time
          </h2>
          <FollowerChart snapshots={snapshots} />
        </div>
      )}

      {/* Likes over time */}
      {posts.length > 0 && (
        <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
          <h2 className="text-sm font-semibold text-[#0f172a] mb-4">
            Likes Over Time
          </h2>
          <LikesChart posts={posts} />
        </div>
      )}

      {/* Recent posts */}
      <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6">
        <h2 className="text-sm font-semibold text-[#0f172a] mb-4">
          Recent Instagram Posts
        </h2>
        <PostsGrid posts={posts} />
      </div>
    </div>
  );
}
