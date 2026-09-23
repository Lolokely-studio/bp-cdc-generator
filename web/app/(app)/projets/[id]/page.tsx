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

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const catalogue = useCatalogue();
  const [live, dispatch] = useReducer(liveReducer, initialLive);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
  // Le flux n'est ouvert que pendant que le run avance : voir
  // `useRunStream`, et le §9.4 sur le quota d'heures d'instance.
  const streaming = status === "running" || status === "idle"
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
          onAnswer={answer} onResume={resume} />
      </main>
      <FactsColumn facts={state.faits} catalogue={catalogue} />
    </div>
  );
}
