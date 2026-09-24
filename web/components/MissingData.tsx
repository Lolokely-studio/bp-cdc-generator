import type { Catalogue, Section } from "@/lib/contracts";
import { DOCUMENT_LABEL, sectionTitle } from "@/lib/labels";
import { missingData } from "@/lib/placeholders";

/** Ce que les documents laissent à compléter : la même liste que l'annexe de
 * l'export, montrée avant de les diffuser. */
export function MissingData({ sections, catalogue }: { sections: Section[]; catalogue: Catalogue }) {
  const missing = missingData(sections);
  return (
    <section className="panel">
      <div className="panel__head"><h2 className="t-section">À compléter avant diffusion</h2></div>
      <div className="panel__body">
        {missing.length === 0 ? (
          <p className="t-note">Aucune : rien ne manque dans ce qui a été rédigé.</p>
        ) : (
          <ul className="rows">
            {missing.map((item, index) => (
              <li key={`${item.document}.${item.sectionId}|${item.label}|${index}`}>
                <span><mark>{item.label}</mark></span>
                <span className="t-fine">
                  {DOCUMENT_LABEL[item.document]}, {sectionTitle(catalogue, item.document, item.sectionId)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="panel__note t-fine">
        Ces mentions figurent aussi en annexe des documents exportés.
      </div>
    </section>
  );
}
