import type { Metadata } from "next";
import "./globals.css";
import Navbar from "@/components/Navbar";
import BrandProvider from "@/components/BrandProvider";
import { getSessionUser } from "@/lib/serverSession";

export const metadata: Metadata = {
  title: "NIL TV Network — Dashboard",
  description: "NIL TV & TrueBlue TV social media analytics",
};

// Runs before first paint so the CSS-var theme never flashes the wrong brand.
const brandInit = `try{var b=localStorage.getItem("brand");document.documentElement.dataset.brand=(b==="niltv"||b==="truebluetv")?b:"truebluetv"}catch(e){document.documentElement.dataset.brand="truebluetv"}`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getSessionUser();
  return (
    <html lang="en" data-brand="truebluetv" suppressHydrationWarning>
      <body className="antialiased">
        <script dangerouslySetInnerHTML={{ __html: brandInit }} />
        <BrandProvider>
          <Navbar user={user} />
          <main className="max-w-screen-xl mx-auto px-4 py-6">{children}</main>
        </BrandProvider>
      </body>
    </html>
  );
}
