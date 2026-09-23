import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";
import { WakeGate } from "@/components/WakeGate";
import "./globals.css";

// Le trio de la maquette : Bricolage Grotesque pour les titres, Hanken
// Grotesk pour le texte, Source Serif 4 pour la prose des documents.
const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const text = Hanken_Grotesk({ subsets: ["latin"], variable: "--font-text", display: "swap" });
const paper = Source_Serif_4({ subsets: ["latin"], variable: "--font-paper", display: "swap" });

export const metadata: Metadata = {
  title: "Esquisse",
  description: "Cahier des charges et business plan, rédigés avec vous.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr" className={`${display.variable} ${text.variable} ${paper.variable}`}>
      <body>
        <div className="app-shell">
          <WakeGate>{children}</WakeGate>
        </div>
      </body>
    </html>
  );
}
