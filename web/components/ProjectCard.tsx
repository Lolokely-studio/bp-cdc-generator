import Link from "next/link";
import type { ProjectSummary } from "@/lib/contracts";
import { DOCUMENTS_LABEL, STATUS_TAG, STATUS_TONE, relativeDate } from "@/lib/labels";

export function ProjectCard({ project, now }: { project: ProjectSummary; now?: Date }) {
  const tag = STATUS_TAG[project.run_status];
  const tone = STATUS_TONE[project.run_status];
  // Un projet terminé n'a plus rien à rédiger : on l'ouvre sur ses documents.
  const href = project.run_status === "done" ? `/projets/${project.id}/exports` : `/projets/${project.id}`;
  const when = relativeDate(project.updated_at, now);
  return (
    <Link className="project" href={href}>
      <span className="project__top">
        <span className="project__name">{project.nom}</span>
        <span className={`tag tag--${tone}`}>{tag.label}</span>
      </span>
      <span className="t-fine">{DOCUMENTS_LABEL[project.documents]}</span>
      {/* Une encoche par section : on lit l'avancement et la taille du
          document d'un seul coup d'œil, ce qu'un pourcentage cache. */}
      <span className="ticks" role="progressbar" aria-label="Sections faites"
        aria-valuemin={0} aria-valuemax={project.sections_total} aria-valuenow={project.sections_faites}>
        {Array.from({ length: project.sections_total }, (_, index) => (
          <i key={index} className={index < project.sections_faites ? "is-done" : undefined} />
        ))}
      </span>
      <span className="project__foot">
        <span className="t-fine">
          <span className="t-num">{project.sections_faites}</span> sur{" "}
          <span className="t-num">{project.sections_total}</span> sections
        </span>
        {when && <span className="t-fine">modifié {when}</span>}
      </span>
    </Link>
  );
}
