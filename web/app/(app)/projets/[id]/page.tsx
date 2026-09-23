"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useReducer, useState } from "react";
import { CoherencePanel } from "@/components/CoherencePanel";
import { FactsColumn } from "@/components/FactsColumn";
import { PlanColumn } from "@/components/PlanColumn";
import { WorkspaceCenter } from "@/components/WorkspaceCenter";
import { ApiError, api } from "@/lib/api";
import { sendAnswer } from "@/lib/answer";
import { useCatalogue } from "@/lib/catalogue";
import { useRunStream } from "@/lib/useRunStream";
import { RESYNC_ON, initialLive, liveReducer } from "@/lib/workspace";

// Le délai avant de relire l'état de passage du §6.2 (`waiting` sans
// interaction) : assez court pour ne pas se voir, assez long pour ne pas
// marteler l'API.
const TRANSIENT_MS = 700;

// Constat 5 de la revue finale. Un projet reste `idle` pour toujours quand
// le processus meurt entre l'insertion de la ligne et le démarrage de la
// tâche : la réconciliation du démarrage (§8) ne rattrape que `running`,
// jamais `idle`. Au-delà de ce délai, on cesse de croire qu'un lancement est
// simplement lent : le flux SSE se ferme (§9.4, pas de battement indéfini)
// et l'écran propose « Reprendre » à la place d'attendre pour toujours.
const IDLE_STUCK_MS = 20_000;

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const catalogue = useCatalogue();
  const [live, dispatch] = useReducer(liveReducer, initialLive);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [idleStuck, setIdleStuck] = useState(false);

  const refresh = useCallback(async () => {
    try {
      dispatch({ type: "state", state: await api.state(id) });
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof ApiError && error.status === 404
        ? "Ce projet n'existe pas."
        : "L'état du projet n'a pas pu être chargé.");
    }
  }, [id]);

  useEffect(() => { void refresh(); }, [refresh]);

  const state = live.state;
  const status = state?.projet.run_status;

  // Constat 5 de la revue finale : un projet mort-né reste `idle` pour
  // toujours. Passé `IDLE_STUCK_MS` sans en sortir, on cesse d'y croire —
  // et `idleStuck` retombe dès que le statut change, y compris un retour à
  // `idle` après une reprise qui, elle aussi, resterait mort-née.
  useEffect(() => {
    if (status !== "idle") { setIdleStuck(false); return; }
    const timer = setTimeout(() => setIdleStuck(true), IDLE_STUCK_MS);
    return () => clearTimeout(timer);
  }, [status]);

  // Le flux n'est ouvert que pendant que le run avance : voir
  // `useRunStream`, et le §9.4 sur le quota d'heures d'instance. Un `idle`
  // resté bloqué (`idleStuck`) ferme le flux : rien ne peut plus en arriver,
  // et le laisser ouvert enverrait un battement toutes les quinze secondes
  // pour rien.
  const streaming = status === "running" || (status === "idle" && !idleStuck)
    || (status === "waiting" && !state?.interaction);

  useRunStream(
    id,
    streaming,
    (event) => {
      dispatch({ type: "event", name: event.name, data: event.data });
      if (RESYNC_ON.has(event.name)) void refresh();
    },
    () => { void refresh(); },
  );

  useEffect(() => {
    if (status !== "waiting" || state?.interaction) return;
    const timer = setTimeout(() => { void refresh(); }, TRANSIENT_MS);
    return () => clearTimeout(timer);
  }, [status, state, refresh]);

  async function answer(reponse: unknown) {
    const interaction = state?.interaction;
    if (!interaction) return;
    setNotice(null);
    try {
      const outcome = await sendAnswer(id, interaction.id, reponse);
      if (outcome === "perimee") setNotice("Cette étape avait déjà reçu une réponse : voici où en est le projet.");
      else dispatch({ type: "answered", interactionId: interaction.id });
    } catch (error) {
      setNotice(error instanceof ApiError && error.code === "reponse_mal_formee"
        ? "La réponse n'a pas la forme attendue. Rechargez la page et réessayez."
        : "La réponse n'est pas partie. Vérifiez la connexion et réessayez.");
    }
    await refresh();
  }

  async function resume() {
    setNotice(null);
    try {
      await api.resume(id);
    } catch {
      setNotice("La reprise n'a pas pu être lancée. Réessayez dans un instant.");
    }
    await refresh();
  }

  if (loadError) {
    return (
      <main className="m-body">
        <p className="m-err" role="alert">{loadError}</p>
        <div className="m-actions" style={{ justifyContent: "flex-start" }}>
          <Link className="m-btn sec" href="/projets">Retour aux projets</Link>
        </div>
      </main>
    );
  }
  if (!state) return <main className="m-body"><p className="m-muted">Chargement du projet…</p></main>;

  if (state.interaction?.kind === "inconsistencies") {
    return (
      <>
        {notice && <p className="m-note" role="status">{notice}</p>}
        <CoherencePanel key={state.interaction.id} interaction={state.interaction}
          catalogue={catalogue} onSubmit={answer} />
      </>
    );
  }

  return (
    <div className="m-ws">
      <PlanColumn state={state} catalogue={catalogue} />
      <main className="m-col center">
        {notice && <p className="m-note" role="status">{notice}</p>}
        <WorkspaceCenter projectId={id} live={live} catalogue={catalogue}
          onAnswer={answer} onResume={resume} idleStuck={idleStuck} />
      </main>
      <FactsColumn facts={state.faits} catalogue={catalogue} />
    </div>
  );
}
