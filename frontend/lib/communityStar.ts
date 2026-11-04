/**
 * Browser-side calls and pure helpers for the Community Star staff page.
 * lib/api.ts is server-only, so everything a client component needs lives
 * here. No env or Next imports, so vitest and route handlers can share it.
 */

import type {
  CommunityStarApplication,
  CommunityStarPhase,
  CommunityStarProgram,
  CommunityStarPublishable,
  CommunityStarSettings,
  CommunityStarVote,
  CommunityStarVoteStatus,
  CommunityStarVoteSummary,
} from "./types";

const BASE = "/api/proxy/api/community-star";

export const VOTES_CSV_URL = "/api/community-star/votes-csv";
export const PHOTO_MAX_BYTES = 5 * 1024 * 1024;

export const PHASE_LABEL: Record<CommunityStarPhase, string> = {
  coming: "Coming soon",
  open: "Applications open",
  closed: "Applications closed",
  finalists: "Finalists",
  voting: "Voting",
  top5: "Top 5",
  winners: "Winners",
};

/** The message in a failed response: FastAPI sends detail, the Next routes send error. */
export function errorText(data: unknown, status: number): string {
  const body = (data ?? {}) as { detail?: unknown; error?: unknown };
  if (typeof body.detail === "string") return body.detail;
  if (typeof body.error === "string") return body.error;
  return `HTTP ${status}`;
}

async function read<T>(res: Response): Promise<T> {
  // An upload refused by the host in front of us has no JSON body.
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorText(data, res.status));
  return data as T;
}

const get = async <T>(path: string) => read<T>(await fetch(`${BASE}${path}`, { cache: "no-store" }));

const post = async <T>(path: string, body: unknown = {}) =>
  read<T>(await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));

export const fetchProgram = () => get<CommunityStarProgram>("/program");

export const publishStage = (what: CommunityStarPublishable, publish: boolean) =>
  post<unknown>("/program/publish", { what, publish });

export const saveSettings = (settings: Partial<CommunityStarSettings>) =>
  post<unknown>("/program/settings", settings);

export const setDevClock = (now: string | null) => post<unknown>("/program/dev-clock", { now });

export const fetchVoteSummary = () => get<CommunityStarVoteSummary>("/votes/summary");

export function votesQuery(status: CommunityStarVoteStatus | "all", finalistId: number | null, limit = 500): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status !== "all") params.set("status", status);
  if (finalistId !== null) params.set("finalist_id", String(finalistId));
  return params.toString();
}

export const fetchVotes = (status: CommunityStarVoteStatus | "all", finalistId: number | null) =>
  get<CommunityStarVote[]>(`/votes?${votesQuery(status, finalistId)}`);

export const voidVote = (id: number, reason: string) => post<unknown>(`/votes/${id}/void`, { reason });

export const restoreVote = (id: number) => post<unknown>(`/votes/${id}/restore`);

/** Why a file can't be a finalist photo, or null when it can. */
export function photoProblem(file: { type: string; size: number }): string | null {
  if (!file.type.startsWith("image/")) return "Choose an image file";
  if (file.size > PHOTO_MAX_BYTES) return "Photos must be 5 MB or smaller";
  return null;
}

export async function uploadPhoto(id: number, file: File): Promise<CommunityStarApplication> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/community-star/applications/${id}/photo`, { method: "POST", body: form });
  const data = await read<{ application: CommunityStarApplication }>(res);
  return data.application;
}

/** Why a stage can't be published yet, or null when the button can be offered. The server checks again. */
export function publishBlocker(
  what: CommunityStarPublishable,
  program: Pick<CommunityStarProgram, "server_time" | "times" | "top5_published_at">,
  marked: { finalists: number; winners: number },
): string | null {
  if (what === "finalists") return marked.finalists < 1 ? "Mark at least one finalist first." : null;
  if (what === "top5") {
    return new Date(program.server_time) < new Date(program.times.vote_closes)
      ? `Available after voting closes, ${fmtET(program.times.vote_closes)}.`
      : null;
  }
  if (!program.top5_published_at) return "Publish the top 5 first.";
  return marked.winners < 1 ? "Mark at least one winner first." : null;
}

/** Only the settings staff changed, so one save can't undo a change made elsewhere. */
export function changedSettings(
  saved: CommunityStarSettings,
  draft: CommunityStarSettings,
): Partial<CommunityStarSettings> {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(draft) as (keyof CommunityStarSettings)[]) {
    if (draft[key] !== saved[key]) out[key] = draft[key];
  }
  return out as Partial<CommunityStarSettings>;
}

/** Program times read in Eastern, the zone the official dates use. */
export function fmtET(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const when = d.toLocaleString("en-US", {
    timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  return `${when} ET`;
}

/** A datetime-local value (the browser's zone) as an ISO time, or null when blank or invalid. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** The public card's value: the staff override when set, else what the athlete sent. */
export function cardValue(override: string | null | undefined, fallback: string): string {
  return override?.trim() || fallback;
}
