import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "DisasterMesh",
  description: "Multi-agent disaster response coordination system",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} antialiased`} style={{ background: "#0a0e17", color: "#f1f5f9" }}>
        {children}
      </body>
    </html>
  );
}
