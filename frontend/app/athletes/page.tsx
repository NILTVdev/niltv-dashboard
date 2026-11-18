import { getAthleteDirectory, getAthleteDirectoryFacets, viewerSession } from "@/lib/api";
import { filtersFromParams, filtersToApiQuery } from "@/lib/athleteDirectory";
import AthleteDirectoryView from "@/components/AthleteDirectoryView";

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

// Admin + general (lib/access.ts ROSTER_PAGES); the backend refuses demo too.
export default async function AthletesPage({ searchParams }: Props) {
  const raw = await searchParams;
  const filters = filtersFromParams({
    get: (name) => {
      const v = raw[name];
      return Array.isArray(v) ? v[0] ?? null : v ?? null;
    },
  });
  const [page, facets, session] = await Promise.all([
    getAthleteDirectory(filtersToApiQuery(filters)).catch(() => null),
    getAthleteDirectoryFacets().catch(() => null),
    viewerSession(),
  ]);
  return (
    <AthleteDirectoryView
      initialFilters={filters}
      initialPage={page}
      facets={facets}
      isAdmin={session?.role === "admin"}
    />
  );
}
