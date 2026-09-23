"use client";

import { createContext, useContext, useSyncExternalStore } from "react";
import { BRANDS, DEFAULT_BRAND, type Brand, type BrandKey } from "@/lib/brands";

// The source of truth is html[data-brand], set before first paint by the
// inline script in app/layout.tsx, so CSS-var colors never flash. This tiny
// external store lets React consumers (nav links, chart hexes) subscribe to
// it: during hydration useSyncExternalStore serves the server snapshot
// (default brand) and re-reads the real attribute right after, so markup
// always matches and the stored choice still applies within the first frames.

const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot(): BrandKey {
  return document.documentElement.dataset.brand === "niltv" ? "niltv" : "truebluetv";
}

function getServerSnapshot(): BrandKey {
  return DEFAULT_BRAND;
}

function setBrandKey(next: BrandKey) {
  document.documentElement.dataset.brand = next;
  try {
    localStorage.setItem("brand", next);
  } catch {
    /* private mode etc. — selection just won't persist */
  }
  listeners.forEach((l) => l());
}

interface BrandContextValue {
  brand: Brand;
  setBrand: (key: BrandKey) => void;
}

const BrandContext = createContext<BrandContextValue>({
  brand: BRANDS[DEFAULT_BRAND],
  setBrand: setBrandKey,
});

export default function BrandProvider({ children }: { children: React.ReactNode }) {
  const key = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return (
    <BrandContext.Provider value={{ brand: BRANDS[key], setBrand: setBrandKey }}>
      {children}
    </BrandContext.Provider>
  );
}

export function useBrand() {
  return useContext(BrandContext);
}
