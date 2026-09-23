// Brand registry for the TrueBlueTV <-> NILTV dashboard switcher.
//
// Theming works two ways, both driven by the html[data-brand] attribute set
// before first paint (see the inline script in app/layout.tsx):
//   - className colors use CSS vars (--brand / --brand-light / --brand-pale,
//     defined in globals.css) and re-theme instantly with no re-render;
//   - recharts props can't resolve CSS vars (SVG presentation attributes),
//     so chart components read hex values from useBrand().colors instead.

export type BrandKey = "truebluetv" | "niltv";

export interface BrandColors {
  brand: string;      // primary (nav, KPI numbers, main chart series)
  brandLight: string; // secondary accent (second chart series, hovers)
  brandPale: string;  // tinted background chips/pills
}

export interface Brand {
  key: BrandKey;
  label: string;
  /** Logo image URL, or null to render the text wordmark. */
  logoSrc: string | null;
  /** Rendered logo box (px) and the class that makes it sit on the dark bar. */
  logo?: { width: number; height: number; className: string };
  home: string;
  links: { href: string; label: string }[];
  colors: BrandColors;
}

export const DEFAULT_BRAND: BrandKey = "truebluetv";

export const BRANDS: Record<BrandKey, Brand> = {
  truebluetv: {
    key: "truebluetv",
    label: "TrueBlue TV",
    logoSrc:
      "https://i0.wp.com/truebluetv.com/wp-content/uploads/2025/07/TrueblueLogo.webp?w=320&ssl=1",
    logo: { width: 120, height: 28, className: "brightness-0 invert" },
    home: "/",
    links: [
      { href: "/", label: "Roster" },
      { href: "/player-details", label: "Player Details" },
      { href: "/zoomph", label: "Duke Owned" },
      { href: "/trueblue", label: "TrueBlue TV" },
      { href: "/web-analytics", label: "Web Analytics" },
    ],
    colors: { brand: "#003087", brandLight: "#00539b", brandPale: "#e8eef7" },
  },
  niltv: {
    key: "niltv",
    label: "NIL TV",
    // 150x56 export on a black ground; screen-blended so the black drops
    // into the near-black bar.
    logoSrc: "/niltv-logo.png",
    logo: { width: 107, height: 40, className: "mix-blend-screen" },
    home: "/niltv",
    links: [
      { href: "/niltv", label: "Network" },
      { href: "/niltv-channels", label: "Channel Insights" },
      { href: "/niltv-campus-channels", label: "Campus Channels" },
      { href: "/niltv-onboarding", label: "Onboarding" },
      { href: "/niltv-web-analytics", label: "Web Analytics" },
    ],
    // Dark network look: near-black primary, brass-gold accent, warm pale.
    colors: { brand: "#101014", brandLight: "#b4975a", brandPale: "#f6f2e9" },
  },
};

// Where to land when switching brands from a page the other brand owns.
// Pages both brands share (adminpage, athletes detail) stay put.
const COUNTERPARTS: Record<string, string> = {
  "/web-analytics": "/niltv-web-analytics",
  "/niltv-web-analytics": "/web-analytics",
  "/trueblue": "/niltv",
  "/niltv": "/trueblue",
};

export function routeForBrand(pathname: string, next: BrandKey): string | null {
  const target = BRANDS[next];
  if (target.links.some((l) => l.href === pathname)) return null; // already valid
  if (COUNTERPARTS[pathname] && target.links.some((l) => l.href === COUNTERPARTS[pathname])) {
    return COUNTERPARTS[pathname];
  }
  const other = BRANDS[next === "niltv" ? "truebluetv" : "niltv"];
  // Leaving a page the previous brand owns -> go to the new brand's home.
  if (other.links.some((l) => l.href === pathname)) return target.home;
  return null; // shared page (admin, athlete detail, ...) — stay
}
