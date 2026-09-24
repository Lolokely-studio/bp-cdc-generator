"use client";

import { useEffect, useState } from "react";

/** Le seuil de l'application, pendant que la session se vérifie.
 *
 * Il affichait « Chargement… » sur une page vide. Il pose maintenant la
 * barre haute, dont la marque est connue d'avance, avec des formes là où
 * viendront le fil d'ariane et le compte.
 *
 * **Le corps reste vide à dessein.** Cette garde enveloppe toutes les pages
 * de l'application, et elles n'ont pas la même forme : la liste est une
 * grille de fiches, l'atelier trois colonnes, les documents deux panneaux.
 * En deviner une ferait sauter la page deux fois — une fois quand ce
 * squelette cède la place, une autre quand celui de l'écran s'installe.
 * Chaque écran a le sien, et il prend le relais tout de suite.
 *
 * `quietMs` reprend la discipline de `WakeGate` : `/me` répond en général en
 * quelques dizaines de millisecondes, et montrer puis retirer un squelette
 * en si peu de temps ne fait que clignoter. On se tait d'abord, on montre
 * ensuite — seulement si l'attente dure. */
export function AppShellSkeleton({ quietMs = 250 }: { quietMs?: number }) {
  const [visible, setVisible] = useState(quietMs === 0);

  useEffect(() => {
    if (quietMs === 0) return;
    const timer = setTimeout(() => setVisible(true), quietMs);
    return () => clearTimeout(timer);
  }, [quietMs]);

  if (!visible) return null;

  return (
    <>
      <p className="sr" role="status">Ouverture de votre espace.</p>
      <header className="topbar skeleton">
        {/* La marque, elle, est connue : la poser tout de suite évite qu'elle
            apparaisse après coup. */}
        <span className="brand">
          <span className="mark" aria-hidden="true" />
          Esquisse
        </span>
        <span className="bone bone--crumb" aria-hidden="true" />
        <span className="bone bone--avatar" aria-hidden="true" />
      </header>
    </>
  );
}
