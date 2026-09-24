"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSetCrumbs } from "@/components/Crumbs";
import { ProjectCard } from "@/components/ProjectCard";
import { ProjectFilters, filterProjects, type Filters } from "@/components/ProjectFilters";
import { ProjectsSkeleton } from "@/components/ProjectsSkeleton";
import { api } from "@/lib/api";
import type { ProjectSummary } from "@/lib/contracts";
import { projectsHeadline } from "@/lib/labels";

export default function ProjectsPage() {
  useSetCrumbs([{ label: "Mes projets" }]);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [filters, setFilters] = useState<Filters>({ query: "", status: "" });

  useEffect(() => {
    let alive = true;
    api.projects()
      .then((value) => { if (alive) setProjects(value); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, []);

  const visible = projects ? filterProjects(projects, filters) : [];

  return (
    <main className="page">
      <div className="page__head">
        <div className="page__head-text">
          <h1 className="t-page">Mes projets</h1>
          {projects && <p className="page__sub">{projectsHeadline(projects)}</p>}
        </div>
        <div className="btn-row">
          <Link className="btn btn--primary" href="/projets/nouveau">Nouveau projet</Link>
        </div>
      </div>

      {failed && (
        <div className="callout callout--stop" role="alert">
          <span className="callout__body">La liste des projets n'a pas pu être chargée.</span>
        </div>
      )}
      {!projects && !failed && <ProjectsSkeleton />}

      {projects && projects.length === 0 && (
        <div className="empty">
          <span className="empty__mark" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 3h8l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
              <path d="M14 3v5h5M9 13h6M9 17h4" />
            </svg>
          </span>
          <p className="t-card">Rien encore ici</p>
          <p className="empty__body">
            Décrivez votre idée en quelques phrases. Esquisse pose les questions qui
            manquent, puis rédige le cahier des charges, le business plan, ou les deux.
          </p>
          <Link className="btn btn--primary" href="/projets/nouveau">Créer un premier projet</Link>
        </div>
      )}

      {projects && projects.length > 0 && (
        <>
          <ProjectFilters value={filters} onChange={setFilters} />
          {visible.length > 0 ? (
            <div className="projects">
              {visible.map((project) => <ProjectCard key={project.id} project={project} />)}
            </div>
          ) : (
            <div className="empty">
              <p className="t-card">Aucun projet ne correspond</p>
              <p className="empty__body">Essayez un autre mot, ou remettez le filtre sur tous les états.</p>
            </div>
          )}
        </>
      )}
    </main>
  );
}
