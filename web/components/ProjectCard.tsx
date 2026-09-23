import Link from "next/link";
import type { ProjectSummary } from "@/lib/contracts";
import { DOCUMENTS_LABEL, STATUS_TAG, relativeDate } from "@/lib/labels";

export function ProjectCard({ project, now }: { project: ProjectSummary; now?: Date }) {
  const tag = STATUS_TAG[project.run_status];
  const share = project.sections_total ? (project.sections_faites / project.sections_total) * 100 : 0;
  // Un projet terminé n'a plus rien à rédiger : on l'ouvre sur ses documents.
  const href = project.run_status === "done" ? `/projets/${project.id}/exports` : `/projets/${project.id}`;
  const when = relativeDate(project.updated_at, now);
  return (
    <Link className="m-proj" href={href}>
      <span className="m-proj-top">
        <b>{project.nom}</b>
        <span className={`m-tag${tag.done ? " done" : ""}`}>{tag.label}</span>
      </span>
      <span className="m-muted small">{DOCUMENTS_LABEL[project.documents]}</span>
      <span className="m-prog" role="progressbar" aria-label="Sections faites"
        aria-valuemin={0} aria-valuemax={project.sections_total} aria-valuenow={project.sections_faites}>
        <i style={{ width: `${share}%` }} />
      </span>
      <span className="m-muted small">
        {project.sections_faites} sections faites sur {project.sections_total}
        {when ? `, modifié ${when}` : ""}
      </span>
    </Link>
  );
}
