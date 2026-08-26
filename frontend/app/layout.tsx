import type { Metadata } from "next";
import { Manrope, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Swapped from the default create-next-app Geist fonts to match the
// approved Eivanta Console design mockup: Manrope for UI text, IBM Plex
// Mono for numeric/tabular data (ledger amounts, agent status, timestamps)
// -- chosen to lean into this product's own terminal/quant identity
// (Live Swarm Telemetry, DuckDB) rather than a generic AI-app look.
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Eivanta Console",
  description: "Eivanta -- Enterprise AI Systems & Business Intelligence Gateway",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${manrope.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
