"use client";

import { useRef, useState } from "react";
import { Check, ExternalLink, Loader2, Upload } from "lucide-react";
import { cardValue, photoProblem, uploadPhoto } from "@/lib/communityStar";
import type { CommunityStarApplication } from "@/lib/types";
import { Btn, Field } from "./CommunityStarUi";

type Row = CommunityStarApplication;

const INPUT = "h-8 w-full rounded-md border px-2 text-sm bg-white";

// A draft keeps staff edits until the saved value itself changes. Saving a
// YouTube link comes back as the bare id, and an upload brings a new photo
// link; both land here without touching the other unsaved fields.
function useDraft(saved: string | null) {
  const value = saved ?? "";
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setDraft(value);
  }
  return [draft, setDraft, draft !== value] as const;
}

export default function CommunityStarCardEditor({ row, busy, live, onSave, onUploaded }: {
  row: Row;
  busy: boolean;
  live: boolean;
  onSave: (fields: Partial<Row>) => void;
  onUploaded: (row: Row) => void;
}) {
  const [name, setName, nameDirty] = useDraft(row.card_name);
  const [school, setSchool, schoolDirty] = useDraft(row.card_school);
  const [sport, setSport, sportDirty] = useDraft(row.card_sport);
  const [community, setCommunity, communityDirty] = useDraft(row.card_community);
  const [photo, setPhoto, photoDirty] = useDraft(row.photo_url);
  const [cause, setCause, causeDirty] = useDraft(row.cause);
  const [video, setVideo, videoDirty] = useDraft(row.youtube_id);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dirty = nameDirty || schoolDirty || sportDirty || communityDirty || photoDirty || causeDirty || videoDirty;

  async function upload(file: File | undefined) {
    if (!file) return;
    const problem = photoProblem(file);
    setUploadError(problem);
    if (problem) return;
    setUploading(true);
    try {
      onUploaded(await uploadPhoto(row.id, file));
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <>
      <div className="space-y-2">
        <Field label="Name on card" hint="Blank uses the application">
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className={INPUT} placeholder={row.full_name} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="School">
            <input value={school} maxLength={160} onChange={(e) => setSchool(e.target.value)} className={INPUT} placeholder={row.school} />
          </Field>
          <Field label="Sport">
            <input value={sport} maxLength={80} onChange={(e) => setSport(e.target.value)} className={INPUT} placeholder={row.sport} />
          </Field>
        </div>
        <Field label="Community">
          <input value={community} maxLength={160} onChange={(e) => setCommunity(e.target.value)} className={INPUT} placeholder={row.community} />
        </Field>
        <Field label="Cause" hint={`One line, ${cause.length}/200`}>
          <input value={cause} maxLength={200} onChange={(e) => setCause(e.target.value)} className={INPUT} placeholder="Reading hour for local kids" />
        </Field>
        <Field label="Round 2 video" hint="YouTube link (posts Dec 10)">
          <input value={video} onChange={(e) => setVideo(e.target.value)} className={INPUT} placeholder="https://youtu.be/..." />
        </Field>
        {row.youtube_id && (
          <a className="inline-flex items-center gap-1 text-xs text-[var(--brand)] hover:underline" href={`https://youtu.be/${row.youtube_id}`} target="_blank" rel="noreferrer">
            Watch saved video <ExternalLink className="h-3 w-3" />
          </a>
        )}
        <Field label="Photo link" hint="Upload below, or paste an image URL">
          <input value={photo} maxLength={500} onChange={(e) => setPhoto(e.target.value)} className={INPUT} placeholder="https://..." />
        </Field>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            className="hidden"
            aria-label={`Photo for ${row.full_name}`}
            onChange={(e) => upload(e.target.files?.[0])}
          />
          <Btn disabled={uploading} onClick={() => fileInput.current?.click()}>
            {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            {uploading ? "Uploading" : "Upload photo"}
          </Btn>
        </div>
        <Btn
          tone="primary"
          disabled={busy || !dirty}
          onClick={() => onSave({
            card_name: name, card_school: school, card_sport: sport, card_community: community,
            photo_url: photo, cause, youtube_id: video,
          })}
        >
          <Check className="h-3.5 w-3.5" /> Save card
        </Btn>
      </div>
      <p className="mt-1 text-xs text-gray-400">Images only, 5 MB at most. The photo is cropped square and saved at once.</p>
      {uploadError && <p className="mt-1 text-xs text-red-700">{uploadError}</p>}
      {live && <p className="mt-1 text-xs text-amber-700">Finalists are published. A saved card can show on niltv.com within a minute.</p>}

      <CardPreview
        name={cardValue(name, row.full_name)}
        school={cardValue(school, row.school)}
        sport={cardValue(sport, row.sport)}
        community={cardValue(community, row.community)}
        photo={photo}
        cause={cause}
      />
    </>
  );
}

// Roughly the finalist card on niltv.com/communitystar (dark, gold accents).
function CardPreview({ name, school, sport, community, photo, cause }: {
  name: string; school: string; sport: string; community: string; photo: string; cause: string;
}) {
  return (
    <div className="mt-3 rounded-xl border border-[#836C42] bg-[#0b0b0f] p-3 text-white">
      <div className="flex gap-3">
        <div className="h-16 w-16 shrink-0 overflow-hidden rounded-md bg-[#17171c] text-[10px] text-gray-500 flex items-center justify-center">
          {photo
            // eslint-disable-next-line @next/next/no-img-element
            ? <img src={photo} alt="" className="h-full w-full object-cover" />
            : "Photo"}
        </div>
        <div className="min-w-0">
          <div className="font-bold uppercase tracking-wide text-[15px] leading-tight">{name}</div>
          <div className="text-[11px] text-[#E8BD6E]">{school} &middot; {sport}</div>
          <div className="text-[11px] text-gray-400">{community}</div>
        </div>
      </div>
      <p className="mt-2 text-xs text-gray-300">{cause || <span className="text-gray-600">Cause line</span>}</p>
    </div>
  );
}
