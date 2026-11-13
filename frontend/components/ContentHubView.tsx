"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, Plus } from "lucide-react";
import { cn, fmtDate } from "@/lib/utils";
import type { HubAsk, HubAskDetail, HubClaim, HubClaimStatus } from "@/lib/types";
import { askBody, EMPTY_ASK, fmtDay, safeHref, spotsLabel, type AskForm } from "@/lib/hub";
import { Banner, Btn, Chip, Field, Panel, PanelTitle } from "./CommunityStarUi";

interface Props {
  initialAsks: HubAsk[];
  initialQueue: HubClaim[];
  loadFailed: boolean;
}

const SECTIONS = [
  { key: "asks", label: "Asks" },
  { key: "queue", label: "Approval queue" },
] as const;
type Section = (typeof SECTIONS)[number]["key"];

// "active" = everything athletes can still claim or that staff may still open.
const FILTERS = [
  { key: "active", label: "Active" },
  { key: "open", label: "Open" },
  { key: "closed", label: "Closed" },
  { key: "all", label: "All" },
] as const;
type Filter = (typeof FILTERS)[number]["key"];

const CLAIM_LABEL: Record<HubClaimStatus, string> = {
  claimed: "Claimed",
  submitted: "Waiting for approval",
  approved: "Approved",
};
const CLAIM_TONE: Record<HubClaimStatus, "default" | "warn" | "ok"> = {
  claimed: "default",
  submitted: "warn",
  approved: "ok",
};

function matches(a: HubAsk, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "active") return a.status !== "closed";
  return a.status === f;
}

async function call<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api/proxy/api/hub/${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    body: init?.body ? JSON.stringify(init.body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    // FastAPI validation errors arrive as a list; show the first message.
    const d = data?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) && d[0]?.msg ? d[0].msg : data?.error;
    throw new Error(msg ?? `HTTP ${res.status}`);
  }
  return data as T;
}

function AthleteLink({ claim }: { claim: HubClaim }) {
  const href = safeHref(claim.link);
  if (!claim.link) return <span className="text-gray-400">No link yet</span>;
  if (!href) return <span className="break-all">{claim.link}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
       className="inline-flex max-w-full items-center gap-1 text-[var(--brand)] hover:underline">
      <span className="truncate">{claim.link}</span>
      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
    </a>
  );
}

function NewAskForm({ onPosted, onCancel }: { onPosted: (a: HubAsk) => void; onCancel: () => void }) {
  const [form, setForm] = useState<AskForm>(EMPTY_ASK);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof AskForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const input = "mt-1 w-full rounded-md border px-2.5 py-1.5 text-sm bg-white";

  async function post() {
    const r = askBody(form);
    if ("error" in r) {
      setError(r.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onPosted(await call<HubAsk>("asks", { method: "POST", body: r.body }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Panel className="mb-4">
      <PanelTitle>New ask</PanelTitle>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Ask" hint="required"><input value={form.title} onChange={set("title")} className={input} placeholder="Training Table Trivia" /></Field>
        </div>
        <Field label="Category"><input value={form.category} onChange={set("category")} className={input} placeholder="Trivia, Podcast, Lifestyle" /></Field>
        <Field label="Format"><input value={form.format} onChange={set("format")} className={input} placeholder="Reel, photo set, podcast clip" /></Field>
        <Field label="Due date" hint="empty = no deadline"><input type="date" value={form.due_on} onChange={set("due_on")} className={input} /></Field>
        <Field label="Spots" hint="empty = open to all"><input inputMode="numeric" value={form.slots} onChange={set("slots")} className={input} placeholder="3" /></Field>
        <div className="sm:col-span-2">
          <Field label="Tags" hint="comma separated; athletes filter by these"><input value={form.tags} onChange={set("tags")} className={input} placeholder="football, lifestyle" /></Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Detail"><textarea value={form.summary} onChange={set("summary")} rows={2} className={input} placeholder="One or two sentences on what you are looking for" /></Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Steps" hint="one per line"><textarea value={form.steps} onChange={set("steps")} rows={3} className={input} placeholder={"Film vertical, 30 to 60 seconds\nPost as a collab with @niltv"} /></Field>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}
      <div className="mt-3 flex gap-2">
        <Btn tone="primary" onClick={post} disabled={busy}>{busy ? "Posting…" : "Post ask"}</Btn>
        <Btn onClick={onCancel} disabled={busy}>Cancel</Btn>
      </div>
      <p className="mt-2 text-xs text-gray-400">Posted asks show on the athlete hub right away.</p>
    </Panel>
  );
}

export default function ContentHubView({ initialAsks, initialQueue, loadFailed }: Props) {
  const [asks, setAsks] = useState<HubAsk[]>(initialAsks);
  const [queue, setQueue] = useState<HubClaim[]>(initialQueue);
  const [section, setSection] = useState<Section>("asks");
  const [filter, setFilter] = useState<Filter>("active");
  const [composing, setComposing] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<HubAskDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(loadFailed ? "Could not load the Content Hub. Refresh to try again." : null);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of FILTERS) c[f.key] = asks.filter((a) => matches(a, f.key)).length;
    return c;
  }, [asks]);
  const shown = useMemo(() => asks.filter((a) => matches(a, filter)), [asks, filter]);

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  // After any change: the board, the queue and the open ask all move together.
  async function reload(askId: number | null = openId) {
    const [a, q, d] = await Promise.all([
      call<HubAsk[]>("asks?status=all"),
      call<HubClaim[]>("claims?status=submitted"),
      askId ? call<HubAskDetail>(`asks/${askId}`) : Promise.resolve(null),
    ]);
    setAsks(a);
    setQueue(q);
    setDetail(d);
  }

  function toggle(id: number) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    run(`open-${id}`, async () => setDetail(await call<HubAskDetail>(`asks/${id}`)));
  }

  const approve = (c: HubClaim) =>
    run(`approve-${c.id}`, async () => {
      await call(`claims/${c.id}/approve`, { method: "POST" });
      await reload();
    });

  const close = (a: HubAsk) => {
    if (!window.confirm(`Close "${a.title}"? Athletes can no longer claim it. Existing claims can still be submitted and approved.`)) return;
    run(`close-${a.id}`, async () => {
      await call(`asks/${a.id}/close`, { method: "POST" });
      await reload();
    });
  };

  const openCount = asks.filter((a) => a.status === "open").length;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4 mb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Content Hub</h1>
          <p className="text-sm text-gray-500 mt-1">
            Post content asks for NIL TV athletes, see who claimed them, and approve what they submit.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Chip>{openCount} open asks</Chip>
          <Chip tone={queue.length ? "warn" : "default"}>{queue.length} waiting for approval</Chip>
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
            {s.key === "queue" && queue.length > 0 && <span className="ml-1 text-gray-400">{queue.length}</span>}
          </button>
        ))}
      </div>

      {error && <Banner>{error}</Banner>}

      {section === "asks" && (<>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1 w-fit max-w-full">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
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
          {!composing && <Btn tone="primary" onClick={() => setComposing(true)}><Plus className="h-3.5 w-3.5" /> New ask</Btn>}
        </div>

        {composing && (
          <NewAskForm
            onCancel={() => setComposing(false)}
            onPosted={(a) => {
              setComposing(false);
              setAsks((prev) => [a, ...prev]);
              setFilter("active");
            }}
          />
        )}

        <div className="flex flex-col gap-2">
          {shown.length === 0 && (
            <Panel><p className="text-sm text-gray-500">No asks here yet. Post one with New ask.</p></Panel>
          )}
          {shown.map((a) => {
            const isOpen = openId === a.id;
            return (
              <Panel key={a.id} className="p-0">
                <button
                  type="button"
                  onClick={() => toggle(a.id)}
                  aria-expanded={isOpen}
                  className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-left"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                      {[a.category, a.format].filter(Boolean).join(" · ") || "Content"}
                    </div>
                    <div className="font-semibold">{a.title}</div>
                    {a.tags.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
                        {a.tags.map((t) => <span key={t} className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-600">{t}</span>)}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-gray-500">{a.due_on ? `Due ${fmtDay(a.due_on)}` : "No deadline"}</span>
                    <Chip tone={a.slots != null && !a.spots_left ? "warn" : "default"}>{spotsLabel(a)}</Chip>
                    <Chip>{a.claimed} claimed</Chip>
                    <Chip tone={a.submitted ? "warn" : "default"}>{a.submitted} to approve</Chip>
                    <Chip tone={a.approved ? "ok" : "default"}>{a.approved} approved</Chip>
                    {a.status !== "open" && <Chip tone="bad">{a.status === "closed" ? "Closed" : "Draft"}</Chip>}
                    {isOpen ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
                  </div>
                </button>

                {isOpen && (
                  <div className="border-t px-4 py-3 text-sm">
                    {a.summary && <p className="text-gray-600">{a.summary}</p>}
                    {a.steps.length > 0 && (
                      <ul className="mt-2 list-disc pl-5 text-gray-600">{a.steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
                    )}
                    <p className="mt-2 text-xs text-gray-400">
                      Posted {fmtDate(a.created_at)}{a.created_by ? ` by ${a.created_by}` : ""}
                      {a.closed_at ? ` · closed ${fmtDate(a.closed_at)}` : ""}
                    </p>

                    <div className="mt-4"><PanelTitle>Athletes</PanelTitle></div>
                    {!detail && <p className="text-gray-500">Loading…</p>}
                    {detail && detail.claims.length === 0 && <p className="text-gray-500">Nobody has claimed this yet.</p>}
                    {detail && detail.claims.length > 0 && (
                      <ul className="divide-y rounded-md border">
                        {detail.claims.map((c) => (
                          <li key={c.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
                            <div className="min-w-[10rem] flex-1">
                              <div className="font-medium">{c.athlete_name}</div>
                              <div className="text-xs text-gray-500">{[c.school, c.sport].filter(Boolean).join(" · ")}</div>
                            </div>
                            <div className="min-w-0 flex-[2] text-xs">
                              <AthleteLink claim={c} />
                              {c.note && <div className="text-gray-500">Note: {c.note}</div>}
                            </div>
                            <Chip tone={CLAIM_TONE[c.status]}>{CLAIM_LABEL[c.status]}</Chip>
                            {c.status === "submitted" && (
                              <Btn tone="primary" onClick={() => approve(c)} disabled={busy !== null}>Approve</Btn>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}

                    {a.status === "open" && (
                      <div className="mt-3">
                        <Btn onClick={() => close(a)} disabled={busy !== null}>Close ask</Btn>
                      </div>
                    )}
                  </div>
                )}
              </Panel>
            );
          })}
        </div>
      </>)}

      {section === "queue" && (
        <div className="flex flex-col gap-2">
          {queue.length === 0 && <Panel><p className="text-sm text-gray-500">Nothing waiting. Submitted links show up here for approval.</p></Panel>}
          {queue.map((c) => (
            <Panel key={c.id} className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="min-w-[12rem] flex-1">
                <div className="text-xs text-gray-500">{c.ask_title}</div>
                <div className="font-semibold">{c.athlete_name}</div>
                <div className="text-xs text-gray-500">{[c.school, c.sport].filter(Boolean).join(" · ")}</div>
              </div>
              <div className="min-w-0 flex-[2] text-sm">
                <AthleteLink claim={c} />
                {c.note && <div className="text-xs text-gray-500">Note: {c.note}</div>}
                {c.submitted_at && <div className="text-xs text-gray-400">Submitted {fmtDate(c.submitted_at)}</div>}
              </div>
              <Btn tone="primary" onClick={() => approve(c)} disabled={busy !== null}>
                {busy === `approve-${c.id}` ? "Approving…" : "Approve"}
              </Btn>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
