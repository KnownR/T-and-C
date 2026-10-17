import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "What Did I Agree To? — Terms of Service Legal Analyzer",
  description:
    "Local-first contract analysis tool with deterministic citation verification. Identify unfair clauses, arbitration waivers, and unilateral changes with 100% verified quotes.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-indigo-500/30 selection:text-indigo-200">
        {children}
      </body>
    </html>
  );
}
