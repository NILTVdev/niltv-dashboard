import type { ReactNode } from "react";
import Link from "next/link";
import { ExternalLink, Eye, Lock } from "lucide-react";
import FollowerChart from "./FollowerChart";
import PostsGrid from "./PostsGrid";
import AthleteAvatar from "./AthleteAvatar";
import { SelfReported, StatusBadge } from "./AthleteDirectoryView";
import InstagramIcon from "./icons/InstagramIcon";
import { fmt, fmtDate } from "@/lib/utils";
import { Poster } from "./LibraryView";
import { answerRows, clipsTitle, socialUrl } from "@/lib/athleteDirectory";
import { LIBRARY } from "@/lib/access";
import { qcLabel } from "@/lib/library";
import type { DirectoryApplication, DirectoryDetail, DirectorySource, LibraryItem, Post } from "@/lib/types";

interface Props {
  detail: DirectoryDetail;
  gridPosts: Post[];
}

const SOURCE_LABEL: Record<DirectorySource, string> = {
  athlete: "Duke roster",
  ambassador: "Ambassador registry",
  application: "Signup form",
};

const FOLLOWER_SOURCE_LABEL = {
  ambassador: "Measured, ambassador pull",
  roster: "Measured, roster pull",
  application: "Self-reported on the signup form",
} as const;

function Card({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm ${className ?? ""}`}>
      {title && <h2 className="mb-4 text-sm font-semibold text-[#0f172a]">{title}</h2>}
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-[#94a3b8]">{label}</dt>
      <dd className="break-words text-sm text-[#0f172a]">{children ?? "—"}</dd>
    </div>
  );
}

function yesNo(v: boolean | null | undefined): string {
  return v == null ? "Not on record" : v ? "Yes" : "No";
}

function Social({ label, href, handle, count, countLabel, selfReported }: {
  label: string; href: string | null; handle: string | null; count?: number | null;
  countLabel?: string; selfReported?: boolean;
}) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-[#f1f5f9] py-2 last:border-0">
      <span className="shrink-0 text-sm text-[#64748b]">{label}</span>
      <span className="min-w-0 text-right text-sm">
        {handle && href ? (
          <a href={href} target="_blank" rel="noopener noreferrer"
             className="block truncate font-medium text-[var(--brand)] hover:underline">
            {handle.startsWith("http") ? handle : `@${handle.replace(/^@/, "")}`}
          </a>
        ) : (
          <span className="text-[#cbd5e1]">—</span>
        )}
        {count != null && (
          <span className="text-xs text-[#64748b]">
            {fmt(count)} {countLabel}
            {selfReported && <SelfReported />}
          </span>
        )}
      </span>
    </div>
  );
}

function ApplicationPanel({ a }: { a: DirectoryApplication }) {
  const extra = answerRows(a.answers);
  return (
    <div className="space-y-4 border-b border-[#f1f5f9] pb-5 last:border-0 last:pb-0">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Email"><a href={`mailto:${a.email}`} className="text-[var(--brand)] hover:underline">{a.email}</a></Field>
        <Field label="College email">
          {a.college_email ? <a href={`mailto:${a.college_email}`} className="text-[var(--brand)] hover:underline">{a.college_email}</a> : null}
        </Field>
        <Field label="Phone">{a.phone ? <a href={`tel:${a.phone}`} className="text-[var(--brand)] hover:underline">{a.phone}</a> : null}</Field>
        <Field label="Name on form">{[a.first_name, a.last_name].filter(Boolean).join(" ") || null}</Field>
        <Field label="Submitted">{fmtDate(a.submitted_at)}</Field>
        <Field label="Pipeline status">{a.status}</Field>
        <Field label="Roster link">
          {a.roster_link ? <a href={a.roster_link} target="_blank" rel="noopener noreferrer" className="text-[var(--brand)] hover:underline">Open</a> : null}
        </Field>
        <Field label="International">{yesNo(a.international)}</Field>
        <Field label="Other followers">{a.other_followers}</Field>
        <Field label="Program email">{yesNo(a.consent_program_email)}</Field>
        <Field label="SMS">{yesNo(a.consent_sms)}</Field>
        <Field label="Marketing">{yesNo(a.consent_marketing)}</Field>
      </dl>
      {(a.purpose || a.description) && (
        <dl className="space-y-3">
          {a.purpose && <Field label="Goal"><span className="whitespace-pre-line">{a.purpose}</span></Field>}
          {a.description && <Field label="About them"><span className="whitespace-pre-line">{a.description}</span></Field>}
        </dl>
      )}
      {extra.length > 0 && (
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {extra.map((r) => <Field key={r.label} label={r.label}>{r.value}</Field>)}
        </dl>
      )}
    </div>
  );
}

function ClipRow({ item }: { item: LibraryItem }) {
  const views = item.performance.views;
  const link = item.performance.permalink;
  return (
    <li className="flex min-w-0 gap-3">
      <Poster item={item} className="h-20 w-[45px] shrink-0 rounded-md" />
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm font-medium text-[#0f172a]">{item.title || "Untitled clip"}</p>
        <p className="mt-0.5 text-xs text-[#64748b]">
          {[item.channel_name, item.posted_at ? fmtDate(item.posted_at) : null, qcLabel(item.qc_state)]
            .filter(Boolean).join(" · ")}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-3 text-xs text-[#64748b]">
          <span className="inline-flex items-center gap-1"><Eye size={12} /> {views == null ? "No views yet" : fmt(views)}</span>
          {link && (
            <a href={link} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 hover:text-[var(--brand)]">
              <ExternalLink size={12} /> Instagram
            </a>
          )}
        </p>
      </div>
    </li>
  );
}

export default function AthleteDetailView({ detail, gridPosts }: Props) {
  const { person: p, history, posts, applications } = detail;
  const clips = detail.clips ?? [];
  const clipsTotal = detail.clips_total ?? clips.length;
  const igHistory = history.flatMap((h) =>
    h.source !== "reported" && h.ig_followers != null && h.pulled_at
      ? [{ pulled_at: h.pulled_at, ig_followers: h.ig_followers }]
      : []);
  const totalViews = posts.reduce((s, x) => s + (x.views ?? 0), 0);

  const kpis = [
    {
      label: "IG followers",
      value: <>{fmt(p.followers)}{p.followers_self_reported && <SelfReported />}</>,
      note: p.followers_source ? `${FOLLOWER_SOURCE_LABEL[p.followers_source]}, ${fmtDate(p.followers_as_of)}` : null,
    },
    { label: "Collab posts", value: fmt(p.collab_posts), note: null },
    { label: "Collab views", value: fmt(p.collab_views), note: null },
    { label: "Collab engagement", value: fmt(p.collab_engagement), note: null },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-start">
          <AthleteAvatar name={p.display_name} src={p.profile_pic_url} size={72} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-2xl font-bold text-[#0f172a]">{p.display_name}</h1>
              <StatusBadge status={p.status} />
            </div>
            <p className="mt-1 text-sm text-[#64748b]">
              {[p.sport, p.school, p.year, p.gender].filter(Boolean).join(" · ") || "No sport or school on record"}
            </p>
            <p className="mt-1 text-xs text-[#94a3b8]">
              Sources: {p.sources.map((s) => SOURCE_LABEL[s]).join(", ")}
              {p.campus ? ` · Campus channel: ${p.campus}` : ""}
              {p.last_pulled ? ` · Last pulled ${fmtDate(p.last_pulled)}` : ""}
            </p>
          </div>
          {p.ig_handle && (
            <a href={socialUrl("instagram", p.ig_handle) ?? "#"} target="_blank" rel="noopener noreferrer"
               className="flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-[#e2e8f0] px-3 py-1.5 text-sm hover:bg-[#f8fafc]">
              <InstagramIcon size={14} /> @{p.ig_handle}
            </a>
          )}
        </div>
        <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {kpis.map((k) => (
            <div key={k.label} className="min-w-0">
              <p className="mb-0.5 text-xs text-[#94a3b8]">{k.label}</p>
              <p className="text-lg font-bold text-[var(--brand)]">{k.value}</p>
              {k.note && <p className="text-[11px] text-[#94a3b8]">{k.note}</p>}
            </div>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Socials">
          <Social label="Instagram" handle={p.ig_handle} href={socialUrl("instagram", p.ig_handle)}
                  count={p.followers} countLabel="followers" selfReported={p.followers_self_reported} />
          <Social label="TikTok" handle={p.tiktok_handle} href={socialUrl("tiktok", p.tiktok_handle)}
                  count={p.tiktok_followers} countLabel="followers" selfReported />
          <Social label="YouTube" handle={p.youtube_handle} href={socialUrl("youtube", p.youtube_handle)}
                  count={p.youtube_subscribers} countLabel="subscribers" selfReported />
          <Social label="X" handle={p.x_handle} href={socialUrl("x", p.x_handle)} />
        </Card>

        <Card title="NIL interests">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Deals done">{p.nil_deals_done}</Field>
            <Field label="Deals wanted">{p.nil_deals_wanted}</Field>
            <Field label="Content type">{p.content_type}</Field>
            <Field label="Partner consent">{yesNo(p.partner_consent)}</Field>
            <Field label="Applied">{p.applied_at ? fmtDate(p.applied_at) : null}</Field>
            <Field label="Application status">{p.application_status}</Field>
          </dl>
        </Card>
      </div>

      <Card title="Instagram followers over time">
        {igHistory.length ? (
          <FollowerChart snapshots={igHistory} />
        ) : (
          <p className="text-sm text-[#94a3b8]">No measured follower history. Signups only report a single number.</p>
        )}
      </Card>

      <Card title={`NIL TV posts${posts.length ? ` (${posts.length}, ${fmt(totalViews)} views)` : ""}`}>
        <PostsGrid posts={gridPosts} />
      </Card>

      <Card title={clipsTitle(clips.length, clipsTotal)}>
        {clips.length ? (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {clips.map((c) => <ClipRow key={c.content_id} item={c} />)}
          </ul>
        ) : (
          <p className="text-sm text-[#94a3b8]">
            No clips in the <Link href={LIBRARY} className="underline underline-offset-2">Library</Link> tag
            {p.ig_handle ? ` @${p.ig_handle}` : " this athlete"}.
          </p>
        )}
      </Card>

      {applications && (
        <Card>
          <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-[#0f172a]">
            <Lock size={14} /> Contact and application answers
          </h2>
          <p className="mb-4 text-xs text-[#94a3b8]">Admins only.</p>
          {applications.length ? (
            <div className="space-y-5">
              {applications.map((a) => <ApplicationPanel key={a.application_id} a={a} />)}
            </div>
          ) : (
            <p className="text-sm text-[#94a3b8]">No signup on record, so no contact details.</p>
          )}
        </Card>
      )}
    </div>
  );
}
