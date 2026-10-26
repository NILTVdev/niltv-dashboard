import { getAthletes } from "@/lib/api";
import RosterTable from "@/components/RosterTable";

export const dynamic = "force-dynamic";

export default async function RosterPage() {
  const allAthletes = await getAthletes();
  // Only show athletes that have IG data pulled
  const athletes = allAthletes.filter((a) => a.ig_followers != null);
  const sports = [...new Set(athletes.map((a) => a.sport).filter(Boolean) as string[])].sort();

  return (
    <div>
      <h1 className="text-xl font-bold text-[#0f172a] mb-1">
        Roster Overview <span className="text-base font-normal text-[#64748b]">— {athletes.length} Athletes</span>
      </h1>
      <p className="text-sm text-[#64748b] mb-5">
        Search, filter, and drill into athlete social performance.
      </p>
      <RosterTable athletes={athletes} sports={sports} />
    </div>
  );
}
