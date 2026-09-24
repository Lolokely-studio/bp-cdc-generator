"use client";

import type { ProjectSummary, RunStatus } from "@/lib/contracts";
import { STATUS_TAG } from "@/lib/labels";

export type Filters = { query: string; status: "" | RunStatus };

/** Sans accents ni majuscules : « Éléonore » se cherche « eleonore ». */
const folded = (text: string) =>
  text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

export function filterProjects(projects: ProjectSummary[], { query, status }: Filters) {
  const needle = folded(query.trim());
  return projects.filter((project) =>
    (!needle || folded(project.nom).includes(needle)) &&
    (!status || project.run_status === status));
}

// `idle` et `running` portent le même libellé : les offrir deux fois
// donnerait deux entrées « En cours » dans la liste déroulante.
const STATUSES: RunStatus[] = ["waiting", "running", "done", "failed"];

export function ProjectFilters({ value, onChange }: {
  value: Filters;
  onChange: (value: Filters) => void;
}) {
  return (
    <div className="filters">
      <div className="search">
        <span className="search__icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.8" aria-hidden="true">
            <circle cx="10.5" cy="10.5" r="6" /><path d="m15 15 4.5 4.5" />
          </svg>
        </span>
        <input className="input" type="search" aria-label="Rechercher un projet"
          placeholder="Rechercher un projet" value={value.query}
          onChange={(e) => onChange({ ...value, query: e.target.value })} />
      </div>
      <select className="select" aria-label="Filtrer par état" value={value.status}
        onChange={(e) => onChange({ ...value, status: e.target.value as Filters["status"] })}>
        <option value="">Tous les états</option>
        {STATUSES.map((status) => (
          <option key={status} value={status}>{STATUS_TAG[status].label}</option>
        ))}
      </select>
    </div>
  );
}
