import type { Catalogue, Section } from "@/lib/contracts";
import { DOCUMENT_LABEL, sectionTitle } from "@/lib/labels";
import { missingData } from "@/lib/placeholders";

/** Ce que les documents laissent à compléter : la même liste que l'annexe de
 * l'export, montrée avant de les diffuser. */
export function MissingData({ sections, catalogue }: { sections: Section[]; catalogue: Catalogue }) {
  const missing = missingData(sections);
  return (
    <div>
      <p className="m-cap">Données à compléter avant diffusion</p>
      {missing.length === 0 ? (
        <p className="m-muted small">Aucune : rien ne manque dans ce qui a été rédigé.</p>
      ) : (
        <ul className="m-list">
          {missing.map((item, index) => (
            <li key={`${item.document}.${item.sectionId}|${item.label}|${index}`}>
              <span><mark>{item.label}</mark></span>
              <span className="m-muted small">
                {DOCUMENT_LABEL[item.document]}, {sectionTitle(catalogue, item.document, item.sectionId)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
