import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { getAthleteDirectoryPerson } from "@/lib/api";
import { DIRECTORY_PATH, personPath, toGridPost } from "@/lib/athleteDirectory";
import AthleteDetailView from "@/components/AthleteDetailView";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ key: string }>;
}

// Admin + general (lib/access.ts ROSTER_PAGES). Contact fields arrive only
// for admins: the backend leaves `applications` null for everyone else.
export default async function AthletePage({ params }: Props) {
  const { key } = await params;
  const decoded = decodeURIComponent(key);
  if (!/^(amb|ath|app)-\d+$/.test(decoded)) notFound();

  const detail = await getAthleteDirectoryPerson(decoded);
  if (!detail) notFound();
  // An older record key (say, the signup before they became an ambassador)
  // goes to the person's current page.
  if (detail.person.key !== decoded) redirect(personPath(detail.person.key));

  return (
    <div className="space-y-6">
      <Link href={DIRECTORY_PATH}
            className="inline-flex items-center gap-1.5 text-sm text-[#64748b] transition-colors hover:text-[var(--brand)]">
        <ArrowLeft size={14} /> All athletes
      </Link>
      <AthleteDetailView detail={detail} gridPosts={detail.posts.map(toGridPost)} />
    </div>
  );
}
