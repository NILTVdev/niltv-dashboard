"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, Search } from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";
import type {
  CommunityStarApplication,
  CommunityStarProgram as Program,
  CommunityStarStage,
  CommunityStarSummary,
  CommunityStarVoteSummary,
} from "@/lib/types";
import CommunityStarCardEditor from "./CommunityStarCardEditor";
import CommunityStarProgram from "./CommunityStarProgram";
import { Banner, Btn, Chip, PanelTitle } from "./CommunityStarUi";
import CommunityStarVotes from "./CommunityStarVotes";

interface Props {
  initial: CommunityStarApplication[];
  summary: CommunityStarSummary | null;
  program: Program | null;
  votes: CommunityStarVoteSummary | null;
}

type Row = CommunityStarApplication;

const STAGES: CommunityStarStage[] = ["applied", "shortlist", "finalist", "top5", "winner", "disqualified"];

const STAGE_LABEL: Record<CommunityStarStage, string> = {
  applied: "Applied",
  shortlist: "Shortlist",
  finalist: "Finalist",
  top5: "Top 5",
  winner: "Winner",
  disqualified: "Disqualified",
};

const STAGE_STYLE: Record<CommunityStarStage, string> = {
  applied: "bg-gray-100 text-gray-700 ring-gray-200",
  shortlist: "bg-amber-50 text-amber-800 ring-amber-200",
  finalist: "bg-sky-50 text-sky-800 ring-sky-200",
  top5: "bg-violet-50 text-violet-800 ring-violet-200",
  winner: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  disqualified: "bg-red-50 text-red-700 ring-red-200",
};

// Rows that show a finalist card on niltv.com/communitystar.
const CARD_STAGES: CommunityStarStage[] = ["finalist", "top5", "winner"];
const FINALIST_TARGET = 25;

const SECTIONS = [
  { key: "applications", label: "Applications" },
  { key: "program", label: "Program" },
  { key: "votes", label: "Votes" },
] as const;
type Section = (typeof SECTIONS)[number]["key"];

// "collab" = entries still waiting on the collab invite (the rules count an
// entry once @NILTV and @NILSTAR accept it).
const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "collab", label: "Collab pending" },
  ...STAGES.map((s) => ({ key: s, label: s === "finalist" ? "Finalists" : s === "winner" ? "Winners" : STAGE_LABEL[s] })),
];

function matches(r: Row, filter: string): boolean {
  if (filter === "all") return true;
  if (filter === "collab") return !r.collab_accepted && r.stage !== "disqualified";
  return r.stage === filter;
}

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// The window closes at midnight Pacific; the rules call that "Nov 23, 11:59pm PT".
function fmtPT(closesIso: string): string {
  const last = new Date(new Date(closesIso).getTime() - 60_000);
  return `${last.toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} PT`;
}

async function save(id: number, fields: Partial<Row>): Promise<Row> {
  const res = await fetch(`/api/proxy/api/community-star/applications/${id}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? `HTTP ${res.status}`);
  return data.application as Row;
}

export default function CommunityStarView({ initial, summary, program: initialProgram, votes }: Props) {
  const [rows, setRows] = useState<Row[]>(initial);
  const [program, setProgram] = useState(initialProgram);
  const [section, setSection] = useState<Section>("applications");
  const [filter, setFilter] = useState("all");
  const [school, setSchool] = useState("all");
  const [sport, setSport] = useState("all");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The staff sheet's Dashboard column links to ?id=<n>; open that row.
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("id"));
    if (id) setOpenId(id);
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of FILTERS) c[f.key] = rows.filter((r) => matches(r, f.key)).length;
    return c;
  }, [rows]);

  const tabRows = useMemo(() => rows.filter((r) => matches(r, filter)), [rows, filter]);
  const schools = useMemo(() => countBy(tabRows.map((r) => r.school)), [tabRows]);
  const sports = useMemo(() => countBy(tabRows.map((r) => r.sport)), [tabRows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase().replace(/^@/, "");
    return tabRows.filter((r) => {
      if (school !== "all" && r.school !== school) return false;
      if (sport !== "all" && r.sport !== sport) return false;
      if (q) {
        const hay = `${r.full_name} ${r.email} ${r.instagram} ${r.school} ${r.community}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [tabRows, school, sport, search]);

  async function update(id: number, fields: Partial<Row>) {
    setBusy(id);
    setError(null);
    try {
      const updated = await save(id, fields);
      setRows((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const finalists = rows.filter((r) => CARD_STAGES.includes(r.stage)).length;
  const win = summary?.window;
  const published = Boolean(program?.finalists_published_at);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4 mb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Community Star</h1>
          <p className="text-sm text-gray-500 mt-1">
            Applications for the two $5,000 grants.{" "}
            {published
              ? <>Finalists are published, so stage changes happen here only. The staff sheet shows them.</>
              : <>Review here or in the staff sheet&rsquo;s team columns; the two sync every 15 minutes.</>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Chip>{rows.length} applications</Chip>
          <Chip>{new Set(rows.map((r) => r.school)).size} schools</Chip>
          <Chip>{rows.filter((r) => r.collab_accepted).length} collab accepted</Chip>
          <Chip tone={finalists > FINALIST_TARGET ? "warn" : "default"}>{finalists} / {FINALIST_TARGET} finalists</Chip>
          {win && (
            <Chip tone={win.open ? "ok" : "default"}>
              {win.open ? `Open until ${fmtPT(win.closes)}` : new Date(win.opens) > new Date() ? `Opens ${fmtWhen(win.opens)}` : "Applications closed"}
            </Chip>
          )}
        </div>
      </div>

      <div className="mb-4 flex gap-5 border-b text-sm font-semibold">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setSection(s.key)}
            className={cn(
              "-mb-px border-b-2 pb-2 transition-colors",
              section === s.key ? "border-[var(--brand)] text-[var(--brand)]" : "border-transparent text-gray-500 hover:text-gray-900",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>

      {section === "program" && (
        <CommunityStarProgram
          program={program}
          marked={{ finalists, winners: rows.filter((r) => r.stage === "winner").length }}
          onProgram={setProgram}
        />
      )}
      {section === "votes" && <CommunityStarVotes initial={votes} />}
      {section === "applications" && (<>
      <div className="mb-2 flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 w-fit max-w-full max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:[scrollbar-width:none] max-sm:[&::-webkit-scrollbar]:hidden">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "h-7 shrink-0 whitespace-nowrap px-3 rounded-md text-xs font-semibold transition-colors",
              filter === f.key ? "bg-white text-[var(--brand)] shadow-sm" : "text-gray-600 hover:text-gray-900",
            )}
          >
            {f.label}
            <span className="ml-1 text-gray-400">{counts[f.key] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={school} onChange={(e) => setSchool(e.target.value)} className="h-9 rounded-md border px-2 text-sm bg-white max-sm:min-w-0 max-sm:flex-1">
          <option value="all">Schools ({schools.length})</option>
          {schools.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
        </select>
        <select value={sport} onChange={(e) => setSport(e.target.value)} className="h-9 rounded-md border px-2 text-sm bg-white max-sm:min-w-0 max-sm:flex-1">
          <option value="all">Sports ({sports.length})</option>
          {sports.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
        </select>
        <label className="relative flex-1 min-w-[12rem] sm:max-w-xs sm:ml-auto max-sm:basis-full">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, email, @handle, community"
            className="h-9 w-full rounded-md border pl-8 pr-3 text-sm bg-white"
          />
        </label>
      </div>

      {error && <Banner>{error}</Banner>}

      <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
        <table className="w-full text-sm max-sm:block">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500 max-sm:hidden">
            <tr>
              <th className="px-3 py-2 w-8" />
              <th className="px-3 py-2">Athlete</th>
              <th className="px-3 py-2">School / Sport</th>
              <th className="hidden px-3 py-2 lg:table-cell">Community</th>
              <th className="px-3 py-2">Post</th>
              <th className="px-3 py-2">Collab</th>
              <th className="px-3 py-2">Stage</th>
              <th className="hidden px-3 py-2 lg:table-cell">Applied</th>
            </tr>
          </thead>
          <tbody className="divide-y max-sm:block">
            {filtered.length === 0 && (
              <tr className="max-sm:block">
                <td colSpan={8} className="px-3 py-10 text-center text-gray-400 max-sm:block">
                  {rows.length === 0 ? "No applications yet. The form on niltv.com/communitystar posts here." : "Nothing matches these filters."}
                </td>
              </tr>
            )}
            {filtered.map((r) => {
              const open = openId === r.id;
              return (
                <RowGroup key={r.id}>
                  <tr
                    className={cn("hover:bg-gray-50 cursor-pointer max-sm:grid max-sm:grid-cols-[minmax(0,1fr)_auto] max-sm:gap-x-2 max-sm:px-3 max-sm:py-2",
                      open && "bg-[var(--brand-pale)]/40")}
                    onClick={() => setOpenId(open ? null : r.id)}
                  >
                    <td className="px-3 py-2 text-gray-400 max-sm:hidden">{open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</td>
                    <td className="px-3 py-2 max-sm:p-0">
                      <div className="font-medium">{r.full_name}</div>
                      <div className="text-xs text-gray-500">@{r.instagram}</div>
                    </td>
                    <td className="px-3 py-2 max-sm:col-start-1 max-sm:p-0">
                      <div>{r.school}</div>
                      <div className="text-xs text-gray-500">{[r.sport, r.class_year].join(" · ")}</div>
                    </td>
                    <td className="hidden px-3 py-2 lg:table-cell">{r.community}</td>
                    <td className="px-3 py-2 max-sm:col-start-2 max-sm:row-start-1 max-sm:p-0" onClick={(e) => e.stopPropagation()}>
                      <a className="inline-flex items-center gap-1 text-[var(--brand)] hover:underline" href={r.post_url} target="_blank" rel="noreferrer">
                        Reel <ExternalLink className="h-3 w-3" />
                      </a>
                    </td>
                    <td className="px-3 py-2 max-sm:col-start-1 max-sm:p-0 max-sm:pt-1" onClick={(e) => e.stopPropagation()}>
                      <label className="inline-flex items-center gap-1.5 text-xs text-gray-600">
                        <input
                          type="checkbox"
                          checked={r.collab_accepted}
                          disabled={busy === r.id}
                          onChange={(e) => update(r.id, { collab_accepted: e.target.checked })}
                          aria-label={`Collab accepted for ${r.full_name}`}
                        />
                        <span className="lg:hidden">Collab accepted</span>
                      </label>
                    </td>
                    <td className="px-3 py-2 max-sm:col-start-2 max-sm:p-0 max-sm:pt-1" onClick={(e) => e.stopPropagation()}>
                      <StageSelect value={r.stage} disabled={busy === r.id} onChange={(stage) => update(r.id, { stage })} />
                    </td>
                    <td className="hidden px-3 py-2 text-xs text-gray-500 whitespace-nowrap lg:table-cell">{fmtDate(r.created_at)}</td>
                  </tr>
                  {open && (
                    <tr className="bg-[var(--brand-pale)]/30 max-sm:block">
                      <td colSpan={8} className="px-6 py-4 max-sm:block max-sm:px-4">
                        <Detail
                          row={r}
                          busy={busy === r.id}
                          live={published}
                          onSave={(fields) => update(r.id, fields)}
                          onUploaded={(next) => setRows((prev) => prev.map((x) => (x.id === next.id ? next : x)))}
                        />
                      </td>
                    </tr>
                  )}
                </RowGroup>
              );
            })}
          </tbody>
        </table>
      </div>
      </>)}
    </div>
  );
}

function RowGroup({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function StageSelect({ value, disabled, onChange }: {
  value: CommunityStarStage; disabled?: boolean; onChange: (s: CommunityStarStage) => void;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as CommunityStarStage)}
      className={cn("h-7 rounded-full px-2 text-xs font-semibold ring-1 border-0 disabled:opacity-50", STAGE_STYLE[value])}
      aria-label="Stage"
    >
      {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
    </select>
  );
}

function Detail({ row, busy, live, onSave, onUploaded }: {
  row: Row;
  busy: boolean;
  live: boolean;
  onSave: (fields: Partial<Row>) => void;
  onUploaded: (row: Row) => void;
}) {
  // The draft starts from the saved value; after Save the row comes back with
  // the same value, so no sync effect is needed.
  const [notes, setNotes] = useState(row.notes ?? "");
  const card = CARD_STAGES.includes(row.stage);
  const consents: [string, boolean][] = [
    ["Collab invited", true],
    ["Rules + eligible", true],
    ["18+", true],
    ["Privacy", true],
    ["Email opt-in", row.consent_email],
    ["SMS opt-in", row.consent_sms],
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <section className="lg:col-span-1">
        <PanelTitle>Application</PanelTitle>
        <p className="text-sm whitespace-pre-wrap">{row.work}</p>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
          <Dt>Community</Dt><Dd>{row.community}</Dd>
          {row.organization && (<><Dt>Organization</Dt><Dd>{row.organization}</Dd></>)}
          <Dt>Post</Dt><Dd><a className="text-[var(--brand)] hover:underline break-all" href={row.post_url} target="_blank" rel="noreferrer">{row.post_url.replace(/^https:\/\/www\./, "")}</a></Dd>
          <Dt>Instagram</Dt><Dd><a className="text-[var(--brand)] hover:underline" href={`https://instagram.com/${row.instagram}`} target="_blank" rel="noreferrer">@{row.instagram}</a></Dd>
          <Dt>Email</Dt><Dd><a className="hover:underline" href={`mailto:${row.email}`}>{row.email}</a></Dd>
          <Dt>Phone</Dt><Dd>{row.phone}</Dd>
          <Dt>School</Dt><Dd>{[row.school, row.school_state].filter(Boolean).join(", ")}{!row.school_matched && <span className="text-amber-700"> · typed, not from the list</span>}</Dd>
          <Dt>Applied</Dt><Dd>{fmtWhen(row.created_at)}{row.confirmation_sent ? " · confirmation sent" : " · no confirmation email"}</Dd>
          {row.utm && Object.keys(row.utm).length > 0 && (<><Dt>Source</Dt><Dd>{Object.entries(row.utm).map(([k, v]) => `${k.replace(/^utm_/, "")}=${v}`).join(" · ")}</Dd></>)}
        </dl>
        <div className="mt-3 flex flex-wrap gap-1">
          {consents.map(([label, ok]) => (
            <span key={label} className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
              ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-gray-50 text-gray-500 ring-gray-200 line-through")}>
              {label}
            </span>
          ))}
        </div>
      </section>

      <section>
        <PanelTitle>Review</PanelTitle>
        <div className="flex flex-wrap items-center gap-3">
          <StageSelect value={row.stage} disabled={busy} onChange={(stage) => onSave({ stage })} />
          <label className="inline-flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={row.collab_accepted} disabled={busy}
                   onChange={(e) => onSave({ collab_accepted: e.target.checked })} />
            Collab accepted
          </label>
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={4}
          className="mt-3 w-full rounded-md border bg-white px-2 py-1.5 text-sm"
          placeholder="Notes for the team (never shown to the applicant)"
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          <span className="text-xs text-gray-400">
            {row.reviewed_at ? `Last change ${fmtWhen(row.reviewed_at)}${row.reviewed_by ? ` · ${row.reviewed_by}` : ""}` : ""}
          </span>
          <Btn disabled={busy || notes === (row.notes ?? "")} onClick={() => onSave({ notes })}>Save notes</Btn>
        </div>
      </section>

      <section>
        <PanelTitle>Finalist card</PanelTitle>
        {card
          ? <CommunityStarCardEditor row={row} busy={busy} live={live} onSave={onSave} onUploaded={onUploaded} />
          : <p className="text-sm text-gray-400">Set the stage to Finalist to fill in the card shown on niltv.com/communitystar.</p>}
      </section>
    </div>
  );
}

function countBy(values: (string | null | undefined)[]): [string, number][] {
  const m = new Map<string, number>();
  for (const v of values) if (v) m.set(v, (m.get(v) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function Dt({ children }: { children: React.ReactNode }) {
  return <dt className="text-gray-500">{children}</dt>;
}
function Dd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <dd className={cn("text-gray-900 min-h-[1.25rem]", className)}>{children}</dd>;
}
