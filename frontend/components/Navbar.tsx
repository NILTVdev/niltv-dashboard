"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { LogOut, UserCircle, Users } from "lucide-react";
import { canSeePage, HOME, ROLE_LABEL, type SessionUser } from "@/lib/access";
import { CAMPUS_CHANNELS } from "@/lib/channels";

// Channel sections (TrueBlueTV's tabs) live under Campus Channels and carry
// their own sub-nav, so they never appear here.
const LINKS = [
  { href: "/niltv", label: "Network" },
  { href: "/niltv-channels", label: "Channel Insights" },
  { href: CAMPUS_CHANNELS, label: "Campus Channels" },
  { href: "/niltv-onboarding", label: "Onboarding" },
  { href: "/niltv-web-analytics", label: "Web Analytics" },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<SessionUser | null>(null);

  // Who is signed in: drives which links show. Re-read on navigation so a
  // fresh sign-in under another account is picked up.
  useEffect(() => {
    if (pathname === "/login") return;
    fetch("/api/auth")
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, [pathname]);

  // When the links scroll, keep the current page's link in view.
  const navRef = useRef<HTMLElement>(null);
  useEffect(() => {
    navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [pathname, me]);

  if (pathname === "/login") return null;

  const links = me ? LINKS.filter((l) => canSeePage(me.role, l.href)) : [];

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-50 bg-[var(--brand)] text-white shadow-md">
      <div className="max-w-screen-xl mx-auto px-4 h-14 flex items-center gap-3 sm:gap-6">
        <Link href={HOME} className="flex items-center shrink-0">
          {/* 150x56 export on a black ground; screen-blended so the black
              drops into the near-black bar. */}
          <Image src="/niltv-logo.png" alt="NIL TV" width={107} height={40}
                 className="mix-blend-screen h-8 w-auto sm:h-10" priority />
        </Link>

        {/* On a narrow screen the links scroll sideways inside the bar
            instead of pushing the whole page wider. */}
        <nav ref={navRef} className="flex flex-1 min-w-0 gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {links.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "shrink-0 whitespace-nowrap px-2 sm:px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  active ? "bg-white/20" : "hover:bg-white/10 text-white/80"
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>

        {me?.role === "admin" && (
          <Link href="/users" title="Dashboard accounts"
                className={cn("flex shrink-0 items-center gap-1.5 px-2 py-1.5 rounded-md text-sm font-medium transition-colors",
                  pathname === "/users" ? "bg-white/20" : "text-white/80 hover:bg-white/10")}>
            <Users size={16} />
            <span className="hidden sm:inline">Users</span>
          </Link>
        )}
        {me && (
          <Link href="/account" title={`${me.email} · ${ROLE_LABEL[me.role]}`}
                className={cn("flex shrink-0 items-center gap-1.5 px-2 py-1.5 rounded-md text-sm font-medium transition-colors whitespace-nowrap",
                  pathname === "/account" ? "bg-white/20" : "text-white/80 hover:bg-white/10")}>
            <UserCircle size={16} />
            {/* Phones get the icons only; the title still names the account. */}
            <span className="hidden max-w-[9rem] truncate sm:inline">{me.name}</span>
            <span className="hidden rounded bg-white/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide sm:inline">
              {ROLE_LABEL[me.role]}
            </span>
          </Link>
        )}

        <button
          onClick={handleLogout}
          title="Logout"
          className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium text-white/80 hover:bg-white/10 transition-colors"
        >
          <LogOut size={16} />
          <span className="hidden sm:inline">Logout</span>
        </button>
      </div>
    </header>
  );
}
