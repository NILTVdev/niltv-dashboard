"use client";

import { useState } from "react";
import { initials } from "@/lib/athleteDirectory";

interface Props {
  name: string;
  src: string | null;
  size: number;
}

/** Profile photo, or initials when there is none. Instagram photo URLs
 * expire between nightly refreshes, so a broken image falls back too. */
export default function AthleteAvatar({ name, src, size }: Props) {
  const [broken, setBroken] = useState(false);
  const style = { width: size, height: size };
  if (src && !broken) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt="" style={style} loading="lazy" referrerPolicy="no-referrer"
           onError={() => setBroken(true)}
           className="shrink-0 rounded-full border border-[#e2e8f0] object-cover" />
    );
  }
  return (
    <span aria-hidden style={{ ...style, fontSize: Math.max(11, Math.round(size * 0.36)) }}
          className="flex shrink-0 items-center justify-center rounded-full bg-[var(--brand)] font-semibold text-[var(--brand-light)]">
      {initials(name)}
    </span>
  );
}
