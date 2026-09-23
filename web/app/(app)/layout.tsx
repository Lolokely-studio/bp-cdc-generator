"use client";

import type { ReactNode } from "react";
import { AuthGate } from "@/components/AuthGate";
import { CatalogueProvider } from "@/lib/catalogue";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGate>
      <CatalogueProvider>{children}</CatalogueProvider>
    </AuthGate>
  );
}
