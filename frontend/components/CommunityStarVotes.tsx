"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { VOTES_CSV_URL, fetchVoteSummary, fetchVotes, fmtET, restoreVote, voidVote } from "@/lib/communityStar";
import { cn } from "@/lib/utils";
import type {
  CommunityStarMailStatus,
  CommunityStarVote as Vote,
  CommunityStarVoteStatus,
  CommunityStarVoteSummary as Summary,
} from "@/lib/types";
import { Banner, Btn, Chip, Panel, PanelTitle } from "./CommunityStarUi";

type StatusFilter = CommunityStarVoteStatus | "all";

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "confirmed", label: "Confirmed" },
  { key: "pending", label: "Pending" },
  { key: "void", label: "Void" },
];

const STATUS_TONE: Record<CommunityStarVoteStatus, "ok" | "warn" | "bad"> = {
  confirmed: "ok",
  pending: "warn",
  void: "bad",
};

const MAIL_LABEL: Record<CommunityStarMailStatus, string> = { queued: "Queued", sent: "Sent", failed: "Failed" };

export default function CommunityStarVotes({ initial }: { initial: Summary | null }) {
  const [summary, setSummary] = useState(initial);
  const [votes, setVotes] = useState<Vote[] | null>(null);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [finalistId, setFinalistId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextSummary, nextVotes] = await Promise.all([fetchVoteSummary(), fetchVotes(status, finalistId)]);
      setSummary(nextSummary);
      setVotes(nextVotes);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [status, finalistId]);

  useEffect(() => { void load(); }, [load]);

  async function act(action: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    try {
      await action();
      await load();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    }
  }

  if (!summary) {
    return (
      <Panel>
        <p className="text-sm text-gray-500">
          {loading ? "Loading votes." : `Vote counts aren’t available on this API yet.${error ? ` (${error})` : ""}`}
        </p>
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      {error && <Banner>{error}</Banner>}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Chip tone="ok">{summary.totals.confirmed} confirmed</Chip>
        <Chip tone={summary.totals.pending ? "warn" : "default"}>{summary.totals.pending} pending</Chip>
        <Chip>{summary.totals.void} void</Chip>
        <span className="mx-1 text-gray-300">|</span>
        <Chip>{summary.mail.sent} mail sent</Chip>
        <Chip>{summary.mail.queued} queued</Chip>
        <Chip tone={summary.mail.failed ? "bad" : "default"}>{summary.mail.failed} failed</Chip>
        <div className="flex gap-2 sm:ml-auto">
          <Btn disabled={loading} onClick={load}>
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> Refresh
          </Btn>
          <a
            href={VOTES_CSV_URL}
            className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50 max-sm:px-3 max-sm:py-2 max-sm:text-sm"
          >
            <Download className="h-3.5 w-3.5" /> Download CSV
          </a>
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Team only. Counts never appear on niltv.com. A void after close doesn&rsquo;t change the frozen board. The
        official top 5 is what you mark and publish.
      </p>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2 overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Finalist</th>
                <th className="px-3 py-2 text-right">Confirmed</th>
                <th className="px-3 py-2 text-right">Pending</th>
                <th className="px-3 py-2 text-right">Void</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {summary.finalists.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-8 text-center text-gray-400">No votes yet.</td></tr>
              )}
              {summary.finalists.map((f) => (
                <tr
                  key={f.id}
                  className={cn("cursor-pointer hover:bg-gray-50", finalistId === f.id && "bg-[var(--brand-pale)]/40")}
                  onClick={() => setFinalistId(finalistId === f.id ? null : f.id)}
                >
                  <td className="px-3 py-2 font-medium">{f.name}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{f.confirmed}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-500">{f.pending}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-500">{f.void}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel>
          <PanelTitle>Flags to review</PanelTitle>
          {summary.flags.length === 0 ? (
            <p className="text-sm text-gray-400">Nothing flagged.</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {summary.flags.map((flag, i) => (
                <li key={`${flag.kind}-${i}`}>
                  {flag.label}
                  {flag.vote_ids.length > 0 && <span className="text-gray-500"> · {flag.vote_ids.length} {flag.vote_ids.length === 1 ? "vote" : "votes"}</span>}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-gray-400">Flags are hints. Nothing is voided on its own.</p>
        </Panel>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-lg bg-gray-100 p-1 w-fit">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setStatus(f.key)}
                className={cn(
                  "h-7 whitespace-nowrap px-3 rounded-md text-xs font-semibold transition-colors",
                  status === f.key ? "bg-white text-[var(--brand)] shadow-sm" : "text-gray-600 hover:text-gray-900",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          {finalistId !== null && (
            <Btn onClick={() => setFinalistId(null)}>
              Clear {summary.finalists.find((f) => f.id === finalistId)?.name ?? "finalist"}
            </Btn>
          )}
          <span className="text-xs text-gray-500">Latest 500 shown. The CSV has every vote.</span>
        </div>

        <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Voter</th>
                <th className="px-3 py-2">Finalist</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Mail</th>
                <th className="px-3 py-2">Voted</th>
                <th className="px-3 py-2">Confirmed</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {votes === null && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">Loading votes.</td></tr>
              )}
              {votes?.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">No votes match.</td></tr>
              )}
              {votes?.map((v) => (
                <VoteRow key={v.id} vote={v} onVoid={(reason) => act(() => voidVote(v.id, reason))} onRestore={() => act(() => restoreVote(v.id))} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function VoteRow({ vote, onVoid, onRestore }: {
  vote: Vote;
  onVoid: (reason: string) => Promise<boolean>;
  onRestore: () => Promise<boolean>;
}) {
  const [voiding, setVoiding] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<boolean>) {
    setBusy(true);
    const ok = await action();
    setBusy(false);
    if (ok) {
      setVoiding(false);
      setReason("");
    }
  }

  return (
    <tr className="align-top">
      <td className="px-3 py-2 break-all">{vote.email}</td>
      <td className="px-3 py-2">{vote.finalist_name}</td>
      <td className="px-3 py-2 text-xs">
        <Chip tone={STATUS_TONE[vote.status]}>{vote.status}</Chip>
        {vote.status === "void" && vote.void_reason && (
          <div className="mt-1 text-gray-500">
            {vote.void_reason}{vote.voided_by ? ` · ${vote.voided_by}` : ""}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap" title={vote.mail_last_error ?? undefined}>
        <span className={cn(vote.mail_status === "failed" && "font-semibold text-red-700")}>{MAIL_LABEL[vote.mail_status]}</span>
        {vote.sends > 1 && ` · ${vote.sends} sends`}
      </td>
      <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fmtET(vote.created_at)}</td>
      <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fmtET(vote.confirmed_at)}</td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {vote.status === "void" ? (
          <Btn disabled={busy} onClick={() => run(onRestore)}>Restore</Btn>
        ) : voiding ? (
          <div className="flex items-center justify-end gap-1">
            <input
              value={reason}
              maxLength={300}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason"
              aria-label={`Reason to void vote ${vote.id}`}
              className="h-7 w-36 rounded-md border px-2 text-xs bg-white"
            />
            <Btn tone="danger" disabled={busy || !reason.trim()} onClick={() => run(() => onVoid(reason.trim()))}>Void</Btn>
            <Btn disabled={busy} onClick={() => setVoiding(false)}>Cancel</Btn>
          </div>
        ) : (
          <Btn onClick={() => setVoiding(true)}>Void</Btn>
        )}
      </td>
    </tr>
  );
}
