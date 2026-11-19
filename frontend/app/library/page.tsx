import { getLibrary, getLibraryFacets, getLibraryStatus } from "@/lib/api";
import { PAGE_SIZE, filtersFromParams, libraryQuery } from "@/lib/library";
import LibraryView from "@/components/LibraryView";

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

// The filters come from the URL (?athlete=, ?q=, ?sport=, ?posted_from= ...),
// so a filtered view can be linked to and shared.
export default async function LibraryPage({ searchParams }: Props) {
  const raw = await searchParams;
  const { filters, sort } = filtersFromParams({
    get: (name) => {
      const v = raw[name];
      return Array.isArray(v) ? v[0] ?? null : v ?? null;
    },
  });
  const qs = libraryQuery(filters, { sort, limit: PAGE_SIZE });
  const [page, facets, status] = await Promise.all([
    getLibrary(qs).catch(() => null),
    getLibraryFacets(libraryQuery(filters)).catch(() => null),
    getLibraryStatus().catch(() => null),
  ]);
  return (
    <LibraryView
      initialFilters={filters}
      initialSort={sort}
      initialQuery={qs}
      initialPage={page}
      initialFacets={facets}
      status={status}
    />
  );
}
