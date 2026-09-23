"use client";

import Link from "next/link";
import { Fragment, createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Crumb = { label: string; href?: string };

/** Le fil d'ariane porte toute la navigation : il n'y a pas de rail. */
export function Crumbs({ items }: { items: Crumb[] }) {
  const last = items.length - 1;
  return (
    <nav className="crumbs" aria-label="Fil d'ariane">
      {items.map((item, index) => (
        <Fragment key={`${item.label}-${index}`}>
          {index > 0 && <span className="crumbs__sep" aria-hidden="true">/</span>}
          {index === last || !item.href
            ? <span className="crumbs__here">{item.label}</span>
            : <Link href={item.href}>{item.label}</Link>}
        </Fragment>
      ))}
    </nav>
  );
}

// La barre haute ne connaît pas les routes : chaque page annonce sa
// position. Sans cela, il faudrait analyser l'URL et retrouver le nom du
// projet, que seule la page a déjà chargé.
const CrumbsContext = createContext<{
  items: Crumb[];
  set: (items: Crumb[]) => void;
}>({ items: [], set: () => {} });

export function CrumbsProvider({ children }: { children: ReactNode }) {
  const [items, set] = useState<Crumb[]>([]);
  return <CrumbsContext.Provider value={{ items, set }}>{children}</CrumbsContext.Provider>;
}

export function useCrumbs() {
  return useContext(CrumbsContext).items;
}

/** Annonce la position de la page. Le tableau est comparé par son contenu :
 * une page qui le reconstruit à chaque rendu ne boucle pas. */
export function useSetCrumbs(items: Crumb[]) {
  const { set } = useContext(CrumbsContext);
  const serialized = JSON.stringify(items);
  useEffect(() => { set(JSON.parse(serialized) as Crumb[]); }, [serialized, set]);
}
