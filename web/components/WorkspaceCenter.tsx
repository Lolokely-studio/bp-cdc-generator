"use client";

import Link from "next/link";
import { useState } from "react";
import { StreamingPaper } from "@/components/Paper";
import { QuestionsForm } from "@/components/QuestionsForm";
import { ReviewPanel } from "@/components/ReviewPanel";
import type { Catalogue, ProjectState } from "@/lib/contracts";
import { DOCUMENT_LABEL, sectionTitle } from "@/lib/labels";
import type { Live, LiveError } from "@/lib/workspace";

function SectionHead({ state, catalogue }: { state: ProjectState; catalogue: Catalogue }) {
  const ref = state.plan[state.curseur];
  if (!ref) return null;
  return (
    <>
      <div className="m-sechead">
        <span className="m-doc">{DOCUMENT_LABEL[ref.document]}</span>
        <span className="m-muted small">Section {state.curseur + 1} sur {state.plan.length}</span>
      </div>
      <h1 className="m-h">{sectionTitle(catalogue, ref.document, ref.section_id)}</h1>
    </>
  );
}

function FailedPanel({ error, onResume }: { error: LiveError | null; onResume: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="m-done">
      <h1 className="m-h">La rédaction s'est interrompue</h1>
      <p>Rien n'est perdu : chaque étape franchie est enregistrée, et la reprise repart de la dernière.</p>
      {error?.message && <p className="m-muted small">Détail : {error.message}</p>}
      <button className="m-btn" type="button" disabled={busy}
        onClick={async () => { setBusy(true); try { await onResume(); } finally { setBusy(false); } }}>
        Reprendre
      </button>
    </div>
  );
}

function StalledPanel({ onResume }: { onResume: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="m-done">
      <h1 className="m-h">La rédaction n'a pas démarré</h1>
      <p>
        Le lancement n'a pas pris la main depuis l'enregistrement du projet. Rien n'est perdu : vous pouvez le
        relancer.
      </p>
      <button className="m-btn" type="button" disabled={busy}
        onClick={async () => { setBusy(true); try { await onResume(); } finally { setBusy(false); } }}>
        Lancer la rédaction
      </button>
    </div>
  );
}

function DonePanel({ projectId, state }: { projectId: string; state: ProjectState }) {
  const skipped = state.sections.filter((section) => section.statut === "skipped").length;
  return (
    <div className="m-done">
      <h1 className="m-h">Rédaction terminée</h1>
      <p>
        {state.plan.length} sections rédigées, et les documents confrontés l'un à l'autre.
        {skipped > 0 && ` ${skipped} section${skipped > 1 ? "s ont été passées" : " a été passée"} sans validation :
        les documents porteront la mention Brouillon.`}
      </p>
      <Link className="m-btn" href={`/projets/${projectId}/exports`}>Générer les documents</Link>
    </div>
  );
}

function Drafting({ state, live, catalogue }: { state: ProjectState; live: Live; catalogue: Catalogue }) {
  const ref = state.plan[state.curseur];
  if (!ref) {
    return (
      <>
        <h1 className="m-h">Contrôle de cohérence</h1>
        <div className="m-status">
          <span className="m-pulse" aria-hidden="true" />
          <span className="m-muted">L'agent confronte les deux documents.</span>
        </div>
      </>
    );
  }
  // `live.answered` : on vient de répondre, la ligne dit encore `waiting`
  // ou `running` le temps que le run reprenne (§6.2). Sans facts ni
  // sections, ça ressemble à un tout premier chargement — mais ce n'en est
  // pas un, et redire « l'agent lit votre idée » tromperait l'utilisateur
  // qui vient de répondre.
  const starting = state.sections.length === 0 && Object.keys(state.faits).length === 0
    && !live.draft && !live.answered;
  let label: string;
  if (live.rework !== null) {
    label = `Réécriture en cours · encore ${live.rework} section${live.rework > 1 ? "s" : ""}`;
  } else if (starting) {
    label = "L'agent lit votre idée et prépare ses questions.";
  } else if (live.draft) {
    label = "Rédaction en cours";
  } else {
    label = "L'agent prépare la section…";
  }
  return (
    <>
      <SectionHead state={state} catalogue={catalogue} />
      <div className="m-status">
        <span className="m-pulse" aria-hidden="true" />
        <span className="m-muted">{label}</span>
        {live.score && <span className="m-src user">Auto-critique {live.score.score}/10</span>}
      </div>
      {live.draft && <StreamingPaper text={live.draft} />}
    </>
  );
}

/** Le centre de l'écran de rédaction : ce que le projet attend de vous, ou
 * ce qu'il est en train d'écrire. */
export function WorkspaceCenter({ projectId, live, catalogue, onAnswer, onResume, idleStuck = false }: {
  projectId: string;
  live: Live;
  catalogue: Catalogue;
  onAnswer: (reponse: unknown) => Promise<void>;
  onResume: () => Promise<void>;
  // Constat 5 de la revue finale : vrai quand le projet est resté `idle` au
  // delà du délai raisonnable défini par la page — le processus est mort
  // entre l'insertion de la ligne et le démarrage de la tâche, et rien ne le
  // rattrapera jamais tout seul.
  idleStuck?: boolean;
}) {
  const state = live.state;
  if (!state) return null;
  const status = state.projet.run_status;
  const interaction = state.interaction;

  if (status === "failed") return <FailedPanel error={live.error} onResume={onResume} />;
  if (status === "done") return <DonePanel projectId={projectId} state={state} />;
  if (idleStuck) return <StalledPanel onResume={onResume} />;
  if (interaction?.kind === "questions") {
    return (
      <>
        <SectionHead state={state} catalogue={catalogue} />
        <QuestionsForm key={interaction.id} interaction={interaction} catalogue={catalogue} onSubmit={onAnswer} />
      </>
    );
  }
  if (interaction?.kind === "review") {
    return (
      <>
        <SectionHead state={state} catalogue={catalogue} />
        <ReviewPanel key={interaction.id} interaction={interaction} onSubmit={onAnswer} />
      </>
    );
  }
  return <Drafting state={state} live={live} catalogue={catalogue} />;
}
