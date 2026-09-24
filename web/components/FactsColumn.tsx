import type { Catalogue, Fact } from "@/lib/contracts";
import { badgeFor, formatFactValue } from "@/lib/facts";

/** La mémoire du projet : ce que l'agent sait, et d'où il le tient. */
export function FactsColumn({ facts, catalogue }: { facts: Record<string, Fact>; catalogue: Catalogue }) {
  // Un fait hors catalogue n'a ni libellé ni type : il ne s'affiche pas.
  const known = Object.values(facts).filter((fact) => catalogue.faits[fact.fact_id]);
  return (
    <aside className="m-col facts" aria-label="Mémoire du projet">
      <p className="m-cap">Mémoire du projet</p>
      <p className="t-note t-fine">Partagée entre le cahier des charges et le business plan.</p>
      <div className="m-legend">
        <span className="src src--user">Vous</span>
        <span className="src src--inferred">Déduit</span>
        <span className="src src--unknown">Inconnu</span>
      </div>
      {known.length === 0 ? (
        <p className="t-note t-fine">Les informations apparaîtront ici au fil de vos réponses.</p>
      ) : (
        <div className="m-facts">
          {known.map((fact) => {
            const definition = catalogue.faits[fact.fact_id];
            const badge = badgeFor(fact);
            return (
              <div className="m-fact" key={fact.fact_id}>
                <b>
                  {definition.libelle}
                  <span className={`src src--${badge.className}`}>{badge.label}</span>
                </b>
                <span className="v">{formatFactValue(definition, fact.value)}</span>
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}
