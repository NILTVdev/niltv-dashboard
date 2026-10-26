import { redirect } from "next/navigation";
import { canSeePage } from "@/lib/access";
import { viewerSession } from "@/lib/api";
import { CAMPUS_CHANNELS, TRUEBLUETV_TABS } from "@/lib/channels";

// The channel opens on the first tab the viewer's role can see (demo has no roster).
export default async function TrueBlueTVPage() {
  const role = (await viewerSession())?.role ?? "demo";
  const tab = TRUEBLUETV_TABS.find((t) => canSeePage(role, t.href));
  redirect(tab?.href ?? CAMPUS_CHANNELS);
}
