"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { Catalogue } from "@/lib/contracts";

const CatalogueContext = createContext<Catalogue | null>(null);

/** Le catalogue, lu une fois par session d'onglet : titres des sections,
 * libellés et types des faits. Il ne change qu'à un déploiement. */
export function CatalogueProvider({ children }: { children: ReactNode }) {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    api.catalogue()
      .then((value) => { if (alive) setCatalogue(value); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, []);

  if (failed) {
    return (
      <main className="page">
        <p className="callout callout--stop" role="alert">Le catalogue des sections n'a pas pu être chargé. Rechargez la page.</p>
      </main>
    );
  }
  if (!catalogue) return <main className="page"><p className="t-note">Chargement…</p></main>;
  return <CatalogueContext.Provider value={catalogue}>{children}</CatalogueContext.Provider>;
}

/** Pour les tests : un catalogue fourni tel quel, sans appel à l'API. */
export function StaticCatalogue({ catalogue, children }: { catalogue: Catalogue; children: ReactNode }) {
  return <CatalogueContext.Provider value={catalogue}>{children}</CatalogueContext.Provider>;
}

export function useCatalogue(): Catalogue {
  const catalogue = useContext(CatalogueContext);
  if (!catalogue) throw new Error("useCatalogue appelé hors de CatalogueProvider");
  return catalogue;
}
