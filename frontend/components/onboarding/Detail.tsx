import { useState } from "react";
import { Ban, Check, ChevronDown, ChevronUp, Circle, CircleDashed, ExternalLink, MinusCircle } from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";
import { fmtWhen } from "@/lib/onboarding";
import type { Application, ApplicationEvent, ApplicationStep } from "@/lib/types";
import Actions from "./Actions";
import Btn from "./Btn";

export default function Detail({ row, busy, onRun }: { row: Application; busy: boolean; onRun: (a: string, b?: unknown) => void }) {
  // Draft starts from the saved notes; after Save the row comes back with the
  // same text, so no sync effect is needed.
  const [notes, setNotes] = useState(row.notes ?? "");
  const [more, setMore] = useState(false);
  const answers = row.answers ?? {};
  const consents: [string, boolean][] = [
    ["18+ confirmed", row.confirm_age],
    ["Terms + Privacy", row.consent_terms],
  ];
  const missing = new Set(row.missing_for_approval);
  const socials = [
    row.instagram && { label: `@${row.instagram}`, href: `https://instagram.com/${row.instagram}`, n: row.instagram_followers, site: "Instagram" },
    row.tiktok && { label: `@${row.tiktok}`, href: `https://www.tiktok.com/@${row.tiktok}`, n: row.tiktok_followers, site: "TikTok" },
    row.youtube && { label: row.youtube.replace(/^https?:\/\/(www\.)?/, ""), href: /^https?:/.test(row.youtube) ? row.youtube : `https://youtube.com/${row.youtube}`, n: row.youtube_subscribers, site: "YouTube" },
  ].filter(Boolean) as { label: string; href: string; n: string | null; site: string }[];

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      {/* Steps */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Checklist</h3>
        <ol className="space-y-2">
          {row.progress.map((s) => (
            <li key={s.key} className="flex items-start gap-2">
              <span className="mt-0.5"><StepIcon state={s.state} /></span>
              <div>
                <div className={cn("text-sm font-medium", s.state === "todo" && "text-gray-400")}>{s.label}</div>
                {(s.detail || s.at) && (
                  <div className="text-xs text-gray-500">{[s.detail, fmtWhen(s.at)].filter(Boolean).join(" · ")}</div>
                )}
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-4 space-y-1 text-xs text-gray-600">
          {row.docusign_envelope_id && (
            <div>
              Envelope <code className="text-[11px]">{row.docusign_envelope_id}</code> ({row.docusign_status})
              {row.agreement_sent_at && <> · sent {fmtWhen(row.agreement_sent_at)}</>}
              {row.agreement_reminded_at && <> · last reminded {fmtWhen(row.agreement_reminded_at)}</>}
            </div>
          )}
          {row.stripe_account_id && (
            <div className="flex items-center gap-1">
              <a className="text-[var(--brand)] hover:underline inline-flex items-center gap-1"
                 href={`https://dashboard.stripe.com/connect/accounts/${row.stripe_account_id}`} target="_blank" rel="noreferrer">
                {row.stripe_account_id} <ExternalLink className="h-3 w-3" />
              </a>
              {row.stripe_payouts_enabled ? <span className="text-emerald-700">payouts enabled</span> : <span className="text-amber-700">payouts off</span>}
            </div>
          )}
          {row.stripe_requirements_due && row.stripe_requirements_due.length > 0 && (
            <div>Stripe still needs: {row.stripe_requirements_due.join(", ")}</div>
          )}
          {row.payout_link && (
            <div className="truncate">Payout link: <a className="text-[var(--brand)] hover:underline" href={row.payout_link} target="_blank" rel="noreferrer">{row.payout_link}</a></div>
          )}
          {row.decline_reason && <div className="text-red-700">Declined: {row.decline_reason}</div>}
        </div>
        <div className="mt-4 flex flex-wrap gap-1">
          <Actions row={row} busy={busy} onRun={onRun} withRefresh />
        </div>
        {row.missing_for_approval.length > 0 && (
          <div className="mt-2 text-xs text-amber-700">Before approval: {row.missing_for_approval.join(", ")}</div>
        )}
      </section>

      {/* Application: the four things approval needs, then everything else behind View more */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Application</h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
          <Dt>Name</Dt><Dd><Need ok={!missing.has("name")}>{[row.first_name, row.last_name].filter(Boolean).join(" ")}</Need></Dd>
          <Dt>Email</Dt><Dd><Need ok={!missing.has("email")}><a className="hover:underline" href={`mailto:${row.email}`}>{row.email}</a></Need></Dd>
          <Dt>Roster</Dt><Dd><Need ok={!missing.has("roster link")}>{row.roster_link && <a className="text-[var(--brand)] hover:underline break-all" href={row.roster_link} target="_blank" rel="noreferrer">{row.roster_link.replace(/^https?:\/\/(www\.)?/, "")}</a>}</Need></Dd>
          <Dt>Socials</Dt><Dd><Need ok={!missing.has("a social link")}>
            <span className="flex flex-wrap gap-x-3 gap-y-0.5">
              {socials.map((x) => (
                <span key={x.site}><a className="text-[var(--brand)] hover:underline" href={x.href} target="_blank" rel="noreferrer">{x.label}</a>{x.n && <span className="text-gray-500"> {x.n}</span>}</span>
              ))}
            </span>
          </Need></Dd>
          <Dt>School</Dt><Dd>{[row.university, row.sport, row.year].filter(Boolean).join(" · ")}{row.campus_channel_label && row.campus_channel !== "other" ? <span className="text-gray-500"> · {row.campus_channel_label}</span> : ""}</Dd>
        </dl>
        <button type="button" onClick={() => setMore(!more)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-[var(--brand)] hover:underline">
          {more ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />} {more ? "Less" : "View more"}
        </button>
        {more && (
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm border-t pt-2">
            <Dt>Phone</Dt><Dd>{row.phone}</Dd>
            <Dt>College email</Dt><Dd>{row.college_email}</Dd>
            <Dt>International</Dt><Dd>{row.international === true ? "yes" : row.international === false ? "no" : ""}</Dd>
            <Dt>NIL deals</Dt><Dd>{[row.nil_deals_done && `done: ${row.nil_deals_done}`, row.nil_deals_wanted && `wants: ${row.nil_deals_wanted}`].filter(Boolean).join(" · ")}</Dd>
            <Dt>Purpose</Dt><Dd className="whitespace-pre-wrap">{row.purpose}</Dd>
            <Dt>Content</Dt><Dd className="whitespace-pre-wrap">{row.content_type}</Dd>
            <Dt>Other followers</Dt><Dd>{row.other_followers}</Dd>
            <Dt>About</Dt><Dd className="whitespace-pre-wrap">{row.description}</Dd>
            <Dt>Source</Dt><Dd>{row.source}{row.submit_count > 1 ? ` · submitted ${row.submit_count}×` : ""}{typeof answers.universityAsTyped === "string" && answers.universityAsTyped !== row.university ? ` · school typed as "${answers.universityAsTyped}"` : ""}</Dd>
          </dl>
        )}
        <div className="mt-3 flex flex-wrap gap-1">
          {consents.map(([label, ok]) => (
            <span key={label} className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
              ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-gray-50 text-gray-500 ring-gray-200 line-through")}>
              {label}
            </span>
          ))}
          {row.consent_version && <span className="text-[11px] text-gray-400 self-center ml-1">v{row.consent_version} · {fmtDate(row.consent_at)}</span>}
        </div>
        {more && Object.keys(answers).length > 0 && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-gray-500">Raw answers</summary>
            <pre className="mt-1 max-h-64 overflow-auto rounded bg-white p-2 text-[11px]">{JSON.stringify(answers, null, 2)}</pre>
          </details>
        )}
      </section>

      {/* Notes + timeline */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Notes</h3>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="w-full rounded-md border bg-white px-2 py-1.5 text-sm"
          placeholder="Internal notes (never shown to the athlete)"
        />
        <div className="mt-1 text-right">
          <Btn disabled={busy || notes === (row.notes ?? "")} onClick={() => onRun("update", { notes })}>Save notes</Btn>
        </div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mt-4 mb-2">Timeline</h3>
        {row.events ? (
          <ol className="space-y-1.5 text-xs max-h-72 overflow-auto pr-1">
            {[...row.events].reverse().map((e, i) => <EventLine key={i} e={e} />)}
          </ol>
        ) : (
          <div className="text-xs text-gray-400">Loading…</div>
        )}
      </section>
    </div>
  );
}

function StepIcon({ state }: { state: ApplicationStep["state"] }) {
  const cls = "h-4 w-4";
  switch (state) {
    case "done": return <Check className={cn(cls, "text-emerald-600")} />;
    case "current": return <CircleDashed className={cn(cls, "text-[var(--brand-light)]")} />;
    case "blocked": return <Ban className={cn(cls, "text-red-500")} />;
    case "skipped": return <MinusCircle className={cn(cls, "text-gray-400")} />;
    default: return <Circle className={cn(cls, "text-gray-300")} />;
  }
}

function Need({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-start gap-1">
      {ok ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" /> : <MinusCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />}
      <span>{children || <span className="text-amber-700">missing</span>}</span>
    </span>
  );
}

function Dt({ children }: { children: React.ReactNode }) {
  return <dt className="text-gray-500">{children}</dt>;
}
function Dd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <dd className={cn("text-gray-900 min-h-[1.25rem]", className)}>{children}</dd>;
}

function EventLine({ e }: { e: ApplicationEvent }) {
  const isErr = e.kind === "error";
  const d = e.detail ?? {};
  const bits: string[] = [];
  if (typeof d.by === "string") bits.push(`by ${d.by}`);
  if (typeof d.reason === "string" && d.reason) bits.push(d.reason);
  if (typeof d.mode === "string") bits.push(d.mode);
  if (typeof d.error === "string") bits.push(d.error);
  if (Array.isArray(d.currently_due) && d.currently_due.length) bits.push(`due: ${(d.currently_due as string[]).join(", ")}`);
  if (d.payouts_enabled === true) bits.push("payouts enabled");
  return (
    <li className={cn("flex gap-2", isErr && "text-red-700")}>
      <span className="text-gray-400 whitespace-nowrap w-28 shrink-0">{fmtWhen(e.at)}</span>
      <span>
        <span className="font-medium">{e.kind.replace(/_/g, " ")}</span>
        {e.actor && <span className="text-gray-400"> · {e.actor}</span>}
        {bits.length > 0 && <span className="text-gray-600"> — {bits.join(" · ")}</span>}
      </span>
    </li>
  );
}
