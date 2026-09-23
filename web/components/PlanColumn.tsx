import type { Catalogue, ProjectState } from "@/lib/contracts";
import { DOCUMENT_SHORT, sectionTitle } from "@/lib/labels";

export function PlanColumn({ state, catalogue }: { state: ProjectState; catalogue: Catalogue }) {
  const statuses = new Map(state.sections.map((s) => [`${s.document}.${s.section_id}`, s.statut]));
  const done = state.sections.filter((s) => s.statut === "done" || s.statut === "skipped").length;
  const total = state.plan.length;
  const writing = state.projet.run_status !== "done";
  return (
    <aside className="m-col plan" aria-label="Ordre de rédaction">
      <p className="m-cap">Ordre de rédaction</p>
      <div className="m-prog"><i style={{ width: `${total ? (done / total) * 100 : 0}%` }} /></div>
      <p className="m-muted small">{done} sections sur {total}</p>
      <ol className="m-planlist">
        {state.plan.map((ref, index) => {
          const key = `${ref.document}.${ref.section_id}`;
          const statut = statuses.get(key);
          const current = writing && index === state.curseur;
          const className = current ? "now" : statut === "done" ? "ok" : statut === "skipped" ? "skipped" : "";
          return (
            <li key={key} className={className} aria-current={current ? "step" : undefined}>
              <span className="st" />
              <span>
                {sectionTitle(catalogue, ref.document, ref.section_id)}
                {statut === "skipped" && <span className="m-muted"> · passée</span>}
                {statut === "reopened" && <span className="m-muted"> · à réécrire</span>}
              </span>
              <span className="m-doc">{DOCUMENT_SHORT[ref.document]}</span>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
