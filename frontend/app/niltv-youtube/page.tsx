import { redirect } from "next/navigation";

// YouTube lives in the Channel Insights YouTube tab. Old links land there.
export default function NiltvYoutubePage() {
  redirect("/niltv-channels?platform=youtube");
}
