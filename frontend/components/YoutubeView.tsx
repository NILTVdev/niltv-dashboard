"use client";

import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Clock, ExternalLink, Eye, Film, Link2Off, Percent, Search, Timer, Users } from "lucide-react";
import type {
  YoutubeAnalytics, YoutubeChannelSummary, YoutubeSnapshotPoint, YoutubeStatus, YoutubeSummary,
  YoutubeVideo, YoutubeVideoPage,
} from "@/lib/types";
import { COLORS } from "@/lib/theme";
import { fmt, fmtDate } from "@/lib/utils";
import {
  filterVideos, fmtChange, fmtDuration, fmtHours, fmtPercent, sortVideos, viewsPerDay,
  type VideoFormat, type VideoSort,
} from "@/lib/youtube";

const GOLD = "#C9A227";
const PER_PAGE = 25;

/* ── Shared pieces ────────────────────────────────────── */

function KPI({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4 sm:p-5 flex flex-col gap-1 min-w-0">
      <span className="flex items-center gap-1.5 text-xs font-medium text-[#64748b]">{icon}{label}</span>
      <span className="text-xl sm:text-2xl font-bold text-[#0f172a] truncate">{value}</span>
      {sub && <span className="text-xs text-[#94a3b8]">{sub}</span>}
    </div>
  );
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-4 sm:p-6 min-w-0">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-[#0f172a]">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Toggle<T extends string>({ value, options, onChange, label }: {
  value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg bg-[#f1f5f9] p-1" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" onClick={() => onChange(v)} aria-pressed={value === v}
                className={`px-3 py-1.5 rounded-md text-xs font-medium ${value === v ? "bg-white text-[#0f172a] shadow-sm" : "text-[#64748b]"}`}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-10 text-center text-sm text-[#94a3b8]">{children}</div>;
}

function changeSub(n: number | null, period: string): string | undefined {
  return n == null ? undefined : `${fmtChange(n, fmt)} ${period}`;
}

function FormatBadge({ short }: { short: boolean | null }) {
  if (short == null) return <span className="text-xs text-[#94a3b8]">—</span>;
  return (
    <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded ${short ? "bg-[#F5E9BE] text-[#7a5d00]" : "bg-[#f1f5f9] text-[#475569]"}`}>
      {short ? "Short" : "Long"}
    </span>
  );
}

function Thumb({ src }: { src: string | null }) {
  return src
    // eslint-disable-next-line @next/next/no-img-element
    ? <img src={src} alt="" loading="lazy" className="h-9 w-16 shrink-0 rounded object-cover bg-[#f1f5f9]" />
    : <div className="h-9 w-16 shrink-0 rounded bg-[#f1f5f9]" />;
}

/* ── Trend chart ──────────────────────────────────────── */

function TrendChart({ series, field, label, color }: {
  series: YoutubeSnapshotPoint[]; field: "subscribers" | "total_views"; label: string; color: string;
}) {
  const data = series.filter((p) => p[field] != null).map((p) => ({ day: fmtDate(p.day), value: p[field] }));
  return (
    <div className="min-w-0">
      <h3 className="text-xs font-semibold text-[#64748b] uppercase tracking-wide mb-2">{label}</h3>
      {data.length < 2 ? (
        <div className="h-48 flex items-center justify-center text-sm text-[#94a3b8] text-center px-4">
          The trend starts after the second nightly pull.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
            <YAxis tickFormatter={(v) => fmt(v)} tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
            <Tooltip formatter={(v: unknown) => [fmt(v as number), label] as [string, string]}
                     contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

/* ── Channel block: changes + trends ──────────────────── */

function ChangesTable({ channel }: { channel: YoutubeChannelSummary }) {
  const c = channel.changes;
  const rows: [string, number | null, number | null][] = [
    ["Last 7 days", c.subscribers_7d, c.views_7d],
    ["Last 28 days", c.subscribers_28d, c.views_28d],
    ["This month", c.subscribers_month, c.views_month],
    ["Last month", c.subscribers_prior_month, c.views_prior_month],
  ];
  return (
    <div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
            <th className="py-2 pr-2 font-medium">Change</th>
            <th className="py-2 pr-2 font-medium text-right">Subscribers</th>
            <th className="py-2 font-medium text-right">Views</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, subs, views]) => (
            <tr key={label} className="border-b border-[#f1f5f9] last:border-0">
              <td className="py-2 pr-2 text-[#64748b]">{label}</td>
              <td className="py-2 pr-2 text-right font-medium text-[#0f172a]">{fmtChange(subs, fmt)}</td>
              <td className="py-2 text-right font-medium text-[#0f172a]">{fmtChange(views, fmt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-[#94a3b8]">
        A change needs a nightly snapshot at both ends. A dash means one is missing.
      </p>
    </div>
  );
}

/* ── Video table ──────────────────────────────────────── */

const SORTS: readonly (readonly [VideoSort, string])[] = [
  ["views", "Views"],
  ["views_per_day", "Views per day"],
  ["published", "Newest"],
  ["likes", "Likes"],
  ["comments", "Comments"],
];
const FORMATS: readonly (readonly [VideoFormat, string])[] = [
  ["all", "All"], ["shorts", "Shorts"], ["long", "Long-form"],
];

function VideoTable({ page, nowMs }: { page: YoutubeVideoPage; nowMs: number }) {
  const [format, setFormat] = useState<VideoFormat>("all");
  const [sort, setSort] = useState<VideoSort>("views");
  const [query, setQuery] = useState("");
  const [pageNo, setPageNo] = useState(0);

  const rows = useMemo(
    () => sortVideos(filterVideos(page.items, format, query), sort, nowMs),
    [page.items, format, query, sort, nowMs],
  );
  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  const current = Math.min(pageNo, pages - 1);
  const visible = rows.slice(current * PER_PAGE, (current + 1) * PER_PAGE);
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPageNo(0); };

  return (
    <Section title="Videos" aside={<Toggle label="Video length" value={format} options={FORMATS} onChange={reset(setFormat)} />}>
      <div className="flex flex-col sm:flex-row gap-2 mb-4">
        <label className="relative flex-1 min-w-0">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
          <input value={query} onChange={(e) => reset(setQuery)(e.target.value)} placeholder="Search titles"
                 className="w-full border border-[#e2e8f0] rounded-md pl-8 pr-2 py-1.5 text-sm" />
        </label>
        <select value={sort} onChange={(e) => reset(setSort)(e.target.value as VideoSort)} aria-label="Sort videos"
                className="border border-[#e2e8f0] rounded-md px-2 py-1.5 text-sm text-[#475569]">
          {SORTS.map(([v, text]) => <option key={v} value={v}>Sort: {text}</option>)}
        </select>
      </div>

      {!visible.length ? (
        <Empty>{page.items.length ? "No videos match." : "No videos yet."}</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <thead>
              <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
                <th className="py-2 pr-3 font-medium">Video</th>
                <th className="py-2 pr-3 font-medium">Published</th>
                <th className="py-2 pr-3 font-medium text-right">Length</th>
                <th className="py-2 pr-3 font-medium text-right">Views</th>
                <th className="py-2 pr-3 font-medium text-right">Likes</th>
                <th className="py-2 pr-3 font-medium text-right">Comments</th>
                <th className="py-2 font-medium text-right">Views / day</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((v: YoutubeVideo) => {
                const perDay = v.views_per_day ?? viewsPerDay(v, nowMs);
                return (
                  <tr key={v.video_id} className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#fdf9ee]">
                    <td className="py-2 pr-3">
                      <a href={v.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3 group min-w-0">
                        <Thumb src={v.thumbnail_url} />
                        <span className="flex flex-col gap-1 min-w-0">
                          <span className="line-clamp-2 text-[#0f172a] group-hover:text-[#7a5d00]">{v.title ?? v.video_id}</span>
                          <FormatBadge short={v.is_short} />
                        </span>
                      </a>
                    </td>
                    <td className="py-2 pr-3 text-xs text-[#64748b] whitespace-nowrap">{fmtDate(v.published_at)}</td>
                    <td className="py-2 pr-3 text-right text-[#475569] whitespace-nowrap">{fmtDuration(v.duration_sec)}</td>
                    <td className="py-2 pr-3 text-right font-semibold text-[#0f172a]">{fmt(v.views)}</td>
                    <td className="py-2 pr-3 text-right text-[#475569]">{fmt(v.likes)}</td>
                    <td className="py-2 pr-3 text-right text-[#475569]">{fmt(v.comments)}</td>
                    <td className="py-2 text-right text-[#475569]">{perDay == null ? "—" : fmt(Math.round(perDay))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-[#64748b]">
        <span>
          {rows.length} {rows.length === 1 ? "video" : "videos"}
          {page.total > page.items.length && ` (the ${page.items.length} most viewed of ${page.total} loaded)`}.
          {" "}Shorts are videos of 3 minutes or less.
        </span>
        {pages > 1 && (
          <span className="flex items-center gap-2">
            <button type="button" disabled={current === 0} onClick={() => setPageNo(current - 1)}
                    className="px-2 py-1 rounded border border-[#e2e8f0] disabled:opacity-40">Previous</button>
            <span>{current + 1} / {pages}</span>
            <button type="button" disabled={current >= pages - 1} onClick={() => setPageNo(current + 1)}
                    className="px-2 py-1 rounded border border-[#e2e8f0] disabled:opacity-40">Next</button>
          </span>
        )}
      </div>
    </Section>
  );
}

/* ── Analytics ────────────────────────────────────────── */

function NotConnected() {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-[#f8fafc] border border-dashed border-[#cbd5e1] px-4 py-5">
      <Link2Off size={18} className="mt-0.5 shrink-0 text-[#94a3b8]" />
      <div className="text-sm text-[#475569] space-y-1">
        <p className="font-semibold text-[#0f172a]">Not connected</p>
        <p>Watch time and retention come from YouTube Analytics. The channel owner must approve read-only access once with their Google login.</p>
        <p className="text-xs text-[#64748b]">Staff then add the access token to the server. The next nightly pull fills this section. The steps are in the YouTube section of the dashboard README.</p>
      </div>
    </div>
  );
}

function AnalyticsSection({ analytics }: { analytics: YoutubeAnalytics | null }) {
  if (!analytics) {
    return <Section title="Watch Time and Retention"><Empty>Could not load YouTube Analytics.</Empty></Section>;
  }
  if (!analytics.connected) {
    return <Section title="Watch Time and Retention"><NotConnected /></Section>;
  }
  const t = analytics.totals_28d;
  const daily = analytics.daily ?? [];
  if (!t || !daily.length) {
    return <Section title="Watch Time and Retention"><Empty>Connected. The first nightly pull fills this section.</Empty></Section>;
  }
  const chart = daily.slice(-28).map((d) => ({ day: fmtDate(d.day), hours: d.watch_hours ?? 0 }));
  const top = analytics.top_videos ?? [];
  const period = t.start && t.end ? `${fmtDate(t.start)} to ${fmtDate(t.end)}` : "Last 28 days";
  return (
    <Section title="Watch Time and Retention" aside={<span className="text-xs text-[#94a3b8]">{period}</span>}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <KPI icon={<Clock size={14} />} label="Watch hours" value={fmtHours(t.watch_hours)} />
        <KPI icon={<Timer size={14} />} label="Avg view duration" value={fmtDuration(t.average_view_duration_sec)} />
        <KPI icon={<Percent size={14} />} label="Avg % viewed" value={fmtPercent(t.average_view_percentage)} />
        <KPI icon={<Users size={14} />} label="Net subscribers" value={fmtChange(t.subscribers_net, fmt)} />
      </div>

      <h3 className="text-xs font-semibold text-[#64748b] uppercase tracking-wide mb-2">Watch hours per day</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
          <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={40} />
          <Tooltip formatter={(v: unknown) => [fmtHours(v as number), "Watch hours"] as [string, string]}
                   contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
          <Bar dataKey="hours" fill={GOLD} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      <h3 className="text-xs font-semibold text-[#64748b] uppercase tracking-wide mt-6 mb-2">Top videos by watch time</h3>
      {!top.length ? <Empty>No video totals yet.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead>
              <tr className="border-b border-[#e2e8f0] text-left text-[#64748b]">
                <th className="py-2 pr-3 font-medium">Video</th>
                <th className="py-2 pr-3 font-medium text-right">Watch hours</th>
                <th className="py-2 pr-3 font-medium text-right">Views</th>
                <th className="py-2 pr-3 font-medium text-right">Avg duration</th>
                <th className="py-2 font-medium text-right">Avg % viewed</th>
              </tr>
            </thead>
            <tbody>
              {top.map((v) => (
                <tr key={v.video_id} className="border-b border-[#f1f5f9] last:border-0">
                  <td className="py-2 pr-3">
                    <a href={v.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3 min-w-0 hover:text-[#7a5d00]">
                      <Thumb src={v.thumbnail_url} />
                      <span className="line-clamp-2">{v.title ?? v.video_id}</span>
                    </a>
                  </td>
                  <td className="py-2 pr-3 text-right font-semibold text-[#0f172a]">{fmtHours(v.watch_hours)}</td>
                  <td className="py-2 pr-3 text-right text-[#475569]">{fmt(v.views)}</td>
                  <td className="py-2 pr-3 text-right text-[#475569]">{fmtDuration(v.average_view_duration_sec)}</td>
                  <td className="py-2 text-right text-[#475569]">{fmtPercent(v.average_view_percentage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

/* ── Root ─────────────────────────────────────────────── */

export default function YoutubeView({ summary, videos, status, analytics }: {
  summary: YoutubeSummary | null;
  videos: YoutubeVideoPage | null;
  status: YoutubeStatus | null;
  analytics: YoutubeAnalytics | null;
}) {
  const [nowMs] = useState(() => Date.now());

  const header = (
    <div>
      <h1 className="text-2xl font-bold text-[#0f172a]">YouTube</h1>
      <p className="text-sm text-[#64748b] mt-1">
        NIL TV on YouTube. Counts update every night.
        {summary?.last_pulled && <span className="text-[#94a3b8]"> Last pull {fmtDate(summary.last_pulled)}.</span>}
      </p>
    </div>
  );

  if (!summary) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-8 flex flex-col gap-6">
        {header}
        <Empty>Could not load YouTube data. Check that the API is reachable.</Empty>
      </main>
    );
  }

  if (!summary.channels.length) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-8 flex flex-col gap-6">
        {header}
        <section className="bg-white rounded-2xl border border-[#e2e8f0] shadow-sm p-6 text-center">
          <Film size={28} className="mx-auto mb-3 text-[#cbd5e1]" />
          <p className="text-sm font-semibold text-[#0f172a]">No YouTube data yet</p>
          <p className="text-sm text-[#64748b] mt-1">
            {status && !status.configured
              ? "Staff add a YouTube API key to the server. The nightly pull then fills this page."
              : "The first nightly pull fills this page."}
          </p>
        </section>
        <AnalyticsSection analytics={analytics} />
      </main>
    );
  }

  const watchHours = analytics?.connected ? analytics.totals_28d?.watch_hours ?? null : null;

  return (
    <main className="max-w-6xl mx-auto px-4 py-8 flex flex-col gap-6">
      {header}

      {summary.channels.map((ch) => (
        <div key={ch.channel_id} className="flex flex-col gap-4 min-w-0">
          {summary.channels.length > 1 && (
            <a href={ch.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-sm font-semibold text-[#0f172a] hover:text-[#7a5d00]">
              {ch.title ?? ch.channel_id} <ExternalLink size={13} />
            </a>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            <KPI icon={<Users size={14} />} label="Subscribers" value={fmt(ch.subscribers)} sub={changeSub(ch.changes.subscribers_7d, "in 7 days")} />
            <KPI icon={<Eye size={14} />} label="Total views" value={fmt(ch.total_views)} sub={changeSub(ch.changes.views_7d, "in 7 days")} />
            <KPI icon={<Film size={14} />} label="Videos" value={fmt(ch.video_count)} />
            <KPI icon={<Clock size={14} />} label="Watch hours · 28 days"
                 value={watchHours == null ? "—" : fmtHours(watchHours)}
                 sub={analytics?.connected ? undefined : "Not connected"} />
          </div>
          <Section title="Growth" aside={
            <a href={ch.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-[#64748b] hover:text-[#7a5d00]">
              Open channel <ExternalLink size={12} />
            </a>
          }>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <TrendChart series={ch.series} field="subscribers" label="Subscribers" color={COLORS.brand} />
              <TrendChart series={ch.series} field="total_views" label="Total views" color={GOLD} />
              <ChangesTable channel={ch} />
            </div>
          </Section>
        </div>
      ))}

      {videos ? <VideoTable page={videos} nowMs={nowMs} /> : (
        <Section title="Videos"><Empty>Could not load videos.</Empty></Section>
      )}

      <AnalyticsSection analytics={analytics} />
    </main>
  );
}
