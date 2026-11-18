import { getLibrary, getLibraryFacets, getLibraryStatus } from "@/lib/api";
import { NO_FILTERS, PAGE_SIZE, libraryQuery } from "@/lib/library";
import LibraryView from "@/components/LibraryView";

export const dynamic = "force-dynamic";

export default async function LibraryPage() {
  const qs = libraryQuery(NO_FILTERS, { sort: "newest", limit: PAGE_SIZE });
  const [page, facets, status] = await Promise.all([
    getLibrary(qs).catch(() => null),
    getLibraryFacets().catch(() => null),
    getLibraryStatus().catch(() => null),
  ]);
  return <LibraryView initialQuery={qs} initialPage={page} initialFacets={facets} status={status} />;
}
