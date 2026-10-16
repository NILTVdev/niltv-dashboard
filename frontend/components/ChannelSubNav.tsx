"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { canSeePage, type Role } from "@/lib/access";
import { CAMPUS_CHANNELS, type ChannelTab } from "@/lib/channels";

/**
 * Breadcrumb + tab bar for a campus channel's own pages. Tabs the role can't
 * open are hidden. `nested` keeps a tab lit on pages that have no tab of
 * their own (an athlete opened from the roster).
 */
export default function ChannelSubNav({
  channel,
  tabs,
  role,
  nested,
}: {
  channel: string;
  tabs: ChannelTab[];
  role: Role;
  /** Path prefix -> the tab it belongs to, for pages without a tab. */
  nested?: Record<string, string>;
}) {
  const pathname = usePathname();
  const visible = tabs.filter((t) => canSeePage(role, t.href));
  const owner = Object.entries(nested ?? {}).find(([prefix]) => pathname.startsWith(`${prefix}/`))?.[1];

  return (
    <div className="mb-6">
      <div className="flex items-center gap-1.5 text-sm text-[#64748b]">
        <Link href={CAMPUS_CHANNELS} className="hover:text-[var(--brand)] transition-colors">
          Campus Channels
        </Link>
        <ChevronRight size={14} />
        <span className="font-semibold text-[#0f172a]">{channel}</span>
      </div>
      <nav className="mt-3 flex gap-1 overflow-x-auto border-b border-[#e2e8f0]">
        {visible.map((t) => {
          const active = pathname === t.href || pathname.startsWith(`${t.href}/`) || owner === t.href;
          return (
            <Link
              key={t.href}
              href={t.href}
              className={cn(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "border-[var(--brand-light)] text-[#0f172a]"
                  : "border-transparent text-[#64748b] hover:text-[#0f172a]"
              )}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
