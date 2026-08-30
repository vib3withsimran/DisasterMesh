import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DisasterMesh — Incident Dashboard",
  description:
    "Multi-agent disaster response coordination system. Fuses satellite, social, citizen, and IoT signals into verified, prioritized, and dispatched incidents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 antialiased">{children}</body>
    </html>
  );
}
