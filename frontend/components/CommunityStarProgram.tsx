"use client";

import { useState } from "react";
import { Check, CircleAlert, Clock } from "lucide-react";
import {
  PHASE_LABEL,
  changedSettings,
  fmtET,
  localInputToIso,
  publishBlocker,
  publishStage,
  saveSettings,
  setDevClock,
  unpublishBlocker,
} from "@/lib/communityStar";
import { cn } from "@/lib/utils";
import type { CommunityStarProgram as Program, CommunityStarPublishable, CommunityStarSettings } from "@/lib/types";
import { Banner, Btn, Chip, Field, Panel, PanelTitle } from "./CommunityStarUi";

interface Props {
  program: Program | null;
  marked: { finalists: number; top5: number; winners: number };
  onProgram: (program: Program) => void;
}

const STEPS: { what: CommunityStarPublishable; label: string; field: keyof Pick<Program, "finalists_published_at" | "top5_published_at" | "winners_published_at"> }[] = [
  { what: "finalists", label: "Finalists", field: "finalists_published_at" },
  { what: "top5", label: "Top 5", field: "top5_published_at" },
  { what: "winners", label: "Winners", field: "winners_published_at" },
];

function warning(what: CommunityStarPublishable, publish: boolean, program: Program, marked: Props["marked"]): string {
  if (!publish) {
    return what === "finalists"
      ? "This takes every finalist name off niltv.com and stops voting from showing."
      : `This takes the ${what === "top5" ? "top 5" : "winners"} off niltv.com.`;
  }
  if (what === "finalists") {
    return `${marked.finalists} finalist ${marked.finalists === 1 ? "name goes" : "names go"} public at ${fmtET(program.times.finalists)}, or within a minute if that time has passed. Anyone marked Finalist after this appears too.`;
  }
  if (what === "top5") return `${marked.top5} rows marked Top 5 or Winner show as the top 5 on niltv.com within a minute.`;
  return `${marked.winners} ${marked.winners === 1 ? "winner shows" : "winners show"} on niltv.com within a minute.`;
}

export default function CommunityStarProgram({ program, marked, onProgram }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  if (!program) {
    return (
      <Panel>
        <p className="text-sm text-gray-500">The program controls aren&rsquo;t on this API yet. Applications still work.</p>
      </Panel>
    );
  }

  async function run(action: () => Promise<Program>): Promise<boolean> {
    setWorking(true);
    setError(null);
    try {
      onProgram(await action());
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-4">
      {error && <Banner>{error}</Banner>}

      <Panel>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-sm font-semibold">Stage on niltv.com</span>
          <Chip tone="ok">{PHASE_LABEL[program.stage] ?? program.stage}</Chip>
          {program.settings.voting_paused && <Chip tone="bad">Voting paused</Chip>}
          {program.frozen_at && <Chip>Board frozen {fmtET(program.frozen_at)}</Chip>}
          {program.dev_now && <Chip tone="warn">Dev clock on</Chip>}
          <span className="text-gray-500 sm:ml-auto">Server time {fmtET(program.server_time)}</span>
        </div>
        <p className="mt-2 text-xs text-gray-500">
          Voting runs {fmtET(program.times.vote_opens)} to {fmtET(program.times.vote_closes)}. Marking someone Finalist
          publishes nothing. Names appear only after you publish below and the finalists time has passed.
        </p>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelTitle>Publish</PanelTitle>
          <div className="divide-y">
            {STEPS.map((s) => (
              <PublishRow
                key={s.what}
                label={s.label}
                what={s.what}
                at={program[s.field]}
                by={program.published_by}
                program={program}
                marked={marked}
                working={working}
                onConfirm={(publish) => run(() => publishStage(s.what, publish))}
              />
            ))}
          </div>
        </Panel>

        <Panel>
          <PanelTitle>Readiness</PanelTitle>
          <ul className="space-y-1.5 text-sm">
            {program.readiness.map((item) => (
              <li key={item.key} className="flex items-start gap-2">
                {item.ok
                  ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-label="Ready" />
                  : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-label="Needs attention" />}
                <span>
                  {item.label}
                  {item.detail && <span className="text-gray-500"> · {item.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Panel>

        <SettingsForm
          key={JSON.stringify(program.settings)}
          saved={program.settings}
          frozen={Boolean(program.frozen_at)}
          working={working}
          onSave={(s) => run(() => saveSettings(s))}
        />

        {!program.production && <DevClock program={program} working={working} onSet={(now) => run(() => setDevClock(now))} />}
      </div>
    </div>
  );
}

function PublishRow({ label, what, at, by, program, marked, working, onConfirm }: {
  label: string;
  what: CommunityStarPublishable;
  at: string | null;
  by: string | null;
  program: Program;
  marked: Props["marked"];
  working: boolean;
  onConfirm: (publish: boolean) => Promise<boolean>;
}) {
  const [asking, setAsking] = useState(false);
  const published = Boolean(at);
  const blocker = published ? unpublishBlocker(what, program) : publishBlocker(what, program, marked);

  return (
    <div className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">{label}</div>
          <div className="text-xs text-gray-500">
            {published ? `Published ${fmtET(at)}${by ? ` · last action by ${by}` : ""}` : blocker ?? "Not published"}
            {published && blocker && <span className="block">{blocker}</span>}
          </div>
        </div>
        {!asking && (
          <Btn tone={published ? "default" : "primary"} disabled={working || Boolean(blocker)} onClick={() => setAsking(true)}>
            {published ? "Unpublish" : "Publish"}
          </Btn>
        )}
      </div>
      {asking && (
        <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2.5">
          <p className="text-xs text-amber-900">{warning(what, !published, program, marked)}</p>
          <div className="mt-2 flex gap-2">
            <Btn
              tone={published ? "danger" : "primary"}
              disabled={working}
              onClick={async () => { if (await onConfirm(!published)) setAsking(false); }}
            >
              {published ? `Yes, unpublish ${label.toLowerCase()}` : `Yes, publish ${label.toLowerCase()}`}
            </Btn>
            <Btn disabled={working} onClick={() => setAsking(false)}>Cancel</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

// Remounted by the parent whenever the saved settings change, so the draft
// always starts from what the server holds.
function SettingsForm({ saved, frozen, working, onSave }: {
  saved: CommunityStarSettings;
  frozen: boolean;
  working: boolean;
  onSave: (settings: Partial<CommunityStarSettings>) => void;
}) {
  const [draft, setDraft] = useState(saved);
  const changes = changedSettings(saved, draft);
  const set = <K extends keyof CommunityStarSettings>(key: K, value: CommunityStarSettings[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const whole = (value: number, low: number, high: number) =>
    Number.isFinite(value) ? Math.min(high, Math.max(low, Math.floor(value))) : low;

  return (
    <Panel>
      <PanelTitle>Voting settings</PanelTitle>
      <div className="space-y-2.5">
        <Toggle label="Pause voting" hint="New votes get a try-again message. The stage stays the same." checked={draft.voting_paused} onChange={(v) => set("voting_paused", v)} />
        <Toggle label="Show the leaderboard" hint="Rank and name only. Counts never leave this page." checked={draft.leaderboard_visible} onChange={(v) => set("leaderboard_visible", v)} />
        <Toggle label="Let an unconfirmed vote change finalist" hint="A second try before confirming replaces the pick." checked={draft.allow_pending_change} onChange={(v) => set("allow_pending_change", v)} />
        <div className="grid gap-2 sm:grid-cols-3">
          <Field label="Confirm grace (min)">
            <input type="number" min={0} max={1440} disabled={frozen} value={draft.confirm_grace_minutes} onChange={(e) => set("confirm_grace_minutes", whole(e.target.valueAsNumber, 0, 1440))} className="h-8 w-full rounded-md border px-2 text-sm bg-white disabled:opacity-50" />
          </Field>
          <Field label="Board minimum votes">
            <input type="number" min={1} max={100000} value={draft.board_min_votes} onChange={(e) => set("board_min_votes", whole(e.target.valueAsNumber, 1, 100000))} className="h-8 w-full rounded-md border px-2 text-sm bg-white" />
          </Field>
          <Field label="Card order">
            <select value={draft.card_order} onChange={(e) => set("card_order", e.target.value as CommunityStarSettings["card_order"])} className="h-8 w-full rounded-md border px-2 text-sm bg-white">
              <option value="alphabetical">Alphabetical</option>
              <option value="shuffled">Shuffled</option>
            </select>
          </Field>
        </div>
        <p className="text-xs text-gray-400">
          Confirm grace is how long after close a vote already cast can still be confirmed. It locks once the board
          freezes. These are starting values until staff set the voting rules.
        </p>
      </div>
      <div className="mt-2 text-right">
        <Btn tone="primary" disabled={working || Object.keys(changes).length === 0} onClick={() => onSave(changes)}>
          <Check className="h-3.5 w-3.5" /> Save settings
        </Btn>
      </div>
    </Panel>
  );
}

function Toggle({ label, hint, checked, onChange }: {
  label: string; hint: string; checked: boolean; onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-0.5" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        <span className="block text-xs text-gray-500">{hint}</span>
      </span>
    </label>
  );
}

function DevClock({ program, working, onSet }: {
  program: Program; working: boolean; onSet: (now: string | null) => void;
}) {
  const [value, setValue] = useState("");
  const iso = localInputToIso(value);

  return (
    <Panel className={cn(program.dev_now && "border-amber-300")}>
      <PanelTitle>Dev clock</PanelTitle>
      <p className="text-xs text-gray-500">
        Moves this environment&rsquo;s clock to rehearse a stage. Production ignores it.
        {program.dev_now ? ` Set to ${fmtET(program.dev_now)}.` : " Using real time."}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          type="datetime-local"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label="Dev clock time, in your local zone"
          className="h-8 rounded-md border px-2 text-sm bg-white"
        />
        <Btn disabled={working || !iso} onClick={() => onSet(iso)}><Clock className="h-3.5 w-3.5" /> Set clock</Btn>
        <Btn disabled={working || !program.dev_now} onClick={() => onSet(null)}>Back to real time</Btn>
      </div>
    </Panel>
  );
}
