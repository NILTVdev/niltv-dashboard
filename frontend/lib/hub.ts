/**
 * Content Hub helpers shared by the staff page: turning the New ask form into
 * the body POST /api/hub/asks expects, and the short labels the board shows.
 * Client-safe (no env).
 */

import type { HubAsk } from "./types";

export interface AskForm {
  title: string;
  category: string;
  format: string;
  tags: string;      // comma separated
  summary: string;
  steps: string;     // one per line
  due_on: string;    // "" or "2026-11-14"
  slots: string;     // "" = open to all athletes
}

export const EMPTY_ASK: AskForm = {
  title: "", category: "", format: "", tags: "", summary: "", steps: "", due_on: "", slots: "",
};

export interface AskBody {
  title: string;
  category: string | null;
  format: string | null;
  tags: string[];
  summary: string | null;
  steps: string[];
  due_on: string | null;
  slots: number | null;
  status: "open";
}

/** The form as the API body, or an error to show next to the form. */
export function askBody(f: AskForm): { body: AskBody } | { error: string } {
  const title = f.title.trim();
  if (!title) return { error: "Give the ask a title." };
  let slots: number | null = null;
  if (f.slots.trim()) {
    const n = Number(f.slots.trim());
    if (!Number.isInteger(n) || n < 1) return { error: "Spots must be a whole number, 1 or more, or empty for open to all." };
    slots = n;
  }
  if (f.due_on && !/^\d{4}-\d{2}-\d{2}$/.test(f.due_on)) return { error: "Pick a due date from the calendar." };
  const tags: string[] = [];
  for (const raw of f.tags.split(",")) {
    const t = raw.trim().toLowerCase();
    if (t && !tags.includes(t)) tags.push(t);
  }
  return {
    body: {
      title,
      category: f.category.trim() || null,
      format: f.format.trim() || null,
      tags,
      summary: f.summary.trim() || null,
      steps: f.steps.split("\n").map((s) => s.trim()).filter(Boolean),
      due_on: f.due_on || null,
      slots,
      status: "open",
    },
  };
}

/** "3 of 5 left", "Full", or "Open to all". */
export function spotsLabel(a: Pick<HubAsk, "slots" | "spots_left">): string {
  if (a.slots == null) return "Open to all";
  if (!a.spots_left) return "Full";
  return `${a.spots_left} of ${a.slots} left`;
}

/** "2026-11-14" -> "Nov 14", read as a calendar day so it never slips a day. */
export function fmtDay(day: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day ?? "");
  if (!m) return "";
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** An athlete's link as an href, only when it is http(s). */
export function safeHref(link: string | null): string | null {
  if (!link) return null;
  try {
    const u = new URL(link);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}
