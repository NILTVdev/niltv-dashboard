"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { LogOut, Settings } from "lucide-react";
import { useBrand } from "@/components/BrandProvider";
import { BRANDS, routeForBrand, type BrandKey } from "@/lib/brands";
import { hasRole, ROLE_LABEL, type SessionUser } from "@/lib/roles";

const BRAND_ORDER: BrandKey[] = ["truebluetv", "niltv"];

export default function Navbar({ user }: { user: SessionUser | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const { brand, setBrand } = useBrand();

  if (pathname === "/login") return null;

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/login");
    router.refresh();
  }

  function switchBrand(next: BrandKey) {
    if (next === brand.key) return;
    setBrand(next);
    const dest = routeForBrand(pathname, next);
    if (dest) router.push(dest);
  }

  return (
    <header className="sticky top-0 z-50 bg-[var(--brand)] text-white shadow-md">
      <div className="max-w-screen-xl mx-auto px-4 h-14 flex items-center gap-6">
        <Link href={brand.home} className="flex items-center shrink-0">
          {brand.logoSrc ? (
            <Image
              src={brand.logoSrc}
              alt={brand.label}
              width={brand.logo?.width ?? 120}
              height={brand.logo?.height ?? 28}
              className={brand.logo?.className}
              priority
            />
          ) : (
            <span className="text-lg font-extrabold tracking-tight leading-none">
              NIL<span className="text-[var(--brand-light)]">&nbsp;TV</span>
            </span>
          )}
        </Link>

        <nav className="flex gap-1 flex-1">
          {brand.links.filter((l) => !l.role || hasRole(user?.role, l.role)).map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                pathname === l.href
                  ? "bg-white/20"
                  : "hover:bg-white/10 text-white/80"
              )}
            >
              {l.label}
            </Link>
          ))}
        </nav>

        {/* Brand switcher */}
        <div
          role="tablist"
          aria-label="Brand"
          className="flex items-center rounded-lg bg-white/10 p-0.5 text-xs font-semibold"
        >
          {BRAND_ORDER.map((key) => (
            <button
              key={key}
              role="tab"
              aria-selected={brand.key === key}
              onClick={() => switchBrand(key)}
              className={cn(
                "px-2.5 py-1 rounded-md transition-colors whitespace-nowrap",
                brand.key === key
                  ? "bg-white text-[var(--brand)]"
                  : "text-white/70 hover:text-white"
              )}
            >
              {BRANDS[key].label}
            </button>
          ))}
        </div>

        {hasRole(user?.role, "admin") && (
          <Link
            href="/adminpage"
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
              pathname === "/adminpage" ? "bg-white/20" : "text-white/80 hover:bg-white/10"
            )}
          >
            <Settings size={16} />
            Admin
          </Link>
        )}

        {user && (
          <span className="hidden md:block text-xs text-white/70 whitespace-nowrap" title={ROLE_LABEL[user.role]}>
            {user.username}
          </span>
        )}

        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium text-white/80 hover:bg-white/10 transition-colors"
        >
          <LogOut size={16} />
          Logout
        </button>
      </div>
    </header>
  );
}
