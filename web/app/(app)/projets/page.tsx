"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSetCrumbs } from "@/components/Crumbs";
import { ProjectCard } from "@/components/ProjectCard";
import { api } from "@/lib/api";
import type { ProjectSummary } from "@/lib/contracts";
import { projectsHeadline } from "@/lib/labels";

export default function ProjectsPage() {
  useSetCrumbs([{ label: "Mes projets" }]);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    api.projects()
      .then((value) => { if (alive) setProjects(value); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, []);

  return (
    <main className="m-body">
      <div className="m-head">
        <div>
          <h1 className="m-h">Mes projets</h1>
          {projects && <p className="m-muted">{projectsHeadline(projects)}</p>}
        </div>
        <Link className="m-btn" href="/projets/nouveau">Nouveau projet</Link>
      </div>
      {failed && <p className="m-err" role="alert">La liste des projets n'a pas pu être chargée.</p>}
      {!projects && !failed && <p className="m-muted">Chargement…</p>}
      {projects && projects.length > 0 && (
        <div className="m-projects">
          {projects.map((project) => <ProjectCard key={project.id} project={project} />)}
        </div>
      )}
    </main>
  );
}
