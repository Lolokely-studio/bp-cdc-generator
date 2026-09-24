import type { Metadata } from "next";
import { Inter, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";
import { WakeGate } from "@/components/WakeGate";
import "./globals.css";

// Inter porte l'interface, Source Serif la prose des sections rédigées —
// pour qu'un document ressemble à un document, et pas à un écran.
const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-serif", display: "swap" });

export const metadata: Metadata = {
  title: "Esquisse",
  description: "Cahier des charges et business plan, rédigés avec vous.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr" className={`${sans.variable} ${serif.variable}`}>
      <body>
        <div className="shell">
          <WakeGate>{children}</WakeGate>
        </div>
      </body>
    </html>
  );
}
