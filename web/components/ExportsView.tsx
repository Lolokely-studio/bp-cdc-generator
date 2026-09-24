"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSetCrumbs } from "@/components/Crumbs";
import { ExportFiles } from "@/components/ExportFiles";
import { ExportsSkeleton } from "@/components/ExportsSkeleton";
import { MissingData } from "@/components/MissingData";
import { ReopenForm } from "@/components/ReopenForm";
import { ApiError, api } from "@/lib/api";
import { useCatalogue } from "@/lib/catalogue";
import type { Exports, ProjectState } from "@/lib/contracts";
import { relativeDate } from "@/lib/labels";

export function ExportsView({ projectId, pollMs = 2000 }: { projectId: string; pollMs?: number }) {
  const catalogue = useCatalogue();
  const [exports, setExports] = useState<Exports | null>(null);
  const [state, setState] = useState<ProjectState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadExports = useCallback(async () => {
    try {
      setExports(await api.exports(projectId));
    } catch {
      setError("La liste des documents n'a pas pu être chargée.");
    }
  }, [projectId]);

  useEffect(() => {
    let alive = true;
    void loadExports();
    api.state(projectId)
      .then((value) => { if (alive) setState(value); })
      .catch(() => { if (alive) setError("Le projet n'a pas pu être chargé."); });
    return () => { alive = false; };
  }, [projectId, loadExports]);

  // Le rendu tourne en tâche de fond et son issue n'arrive que par la liste :
  // on la relit tant qu'il tourne, et on s'arrête dès qu'il s'arrête. Ce
  // n'est pas un ping pour tenir un service éveillé (§9.4) — c'est quelqu'un
  // qui attend devant son écran.
  useEffect(() => {
    if (!exports?.en_cours) return;
    const timer = setTimeout(() => { void loadExports(); }, pollMs);
    return () => clearTimeout(timer);
  }, [exports, pollMs, loadExports]);

  async function launch() {
    setBusy(true);
    setError(null);
    try {
      await api.launchExport(projectId);
    } catch (caught) {
      // Un export déjà lancé n'est pas une erreur : la liste va le montrer.
      if (!(caught instanceof ApiError && caught.code === "export_deja_en_cours")) {
        setError("La génération n'a pas pu être lancée.");
      }
    } finally {
      setBusy(false);
    }
    await loadExports();
  }

  // Appelé avant tout retour anticipé : le fil d'ariane doit s'annoncer sur
  // chaque rendu, y compris pendant le chargement, où le nom du projet n'est
  // pas encore connu.
  useSetCrumbs([
    { label: "Mes projets", href: "/projets" },
    { label: state?.projet.nom ?? "Projet", href: `/projets/${projectId}` },
    { label: "Documents" },
  ]);

  if (!exports || !state) {
    // L'erreur prime sur le squelette : montrer des formes qui attendent
    // quelque chose qui ne viendra pas ferait patienter pour rien.
    if (error) {
      return (
        <main className="page">
          <div className="callout callout--stop" role="alert">
            <span className="callout__body">{error}</span>
          </div>
        </main>
      );
    }
    return <ExportsSkeleton />;
  }

  const files = exports.fichiers;
  const latest = [...files].map((file) => file.cree_le).sort().at(-1) ?? null;
  const finished = state.projet.run_status === "done";

  return (
    <main className="page">
      <div className="page__head">
        <div className="page__head-text">
          <h1 className="t-page">{files.length > 0 ? "Vos documents sont prêts" : "Générer les documents"}</h1>
          <p className="page__sub">
            {state.projet.nom}{latest ? `, derniers fichiers ${relativeDate(latest)}` : ""}
          </p>
        </div>
        <div className="btn-row">
          <Link className="btn btn--outline" href={`/projets/${projectId}`}>Retour à la rédaction</Link>
        </div>
      </div>

      {!finished && (
        <div className="callout callout--wait">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" /><path d="M12 7.5V12l3 2" />
          </svg>
          <span className="callout__body">
            La rédaction n'est pas terminée : les documents générés maintenant porteront la
            mention Brouillon.
          </span>
        </div>
      )}

      {!exports.en_cours && exports.dernier_export === "echec" && (
        <div className="callout callout--stop" role="alert">
          <span className="callout__body">
            La dernière génération a échoué. Certains fichiers ont pu être remplacés et
            d'autres non : relancez pour retrouver un jeu complet.
          </span>
        </div>
      )}
      {error && (
        <div className="callout callout--stop" role="alert">
          <span className="callout__body">{error}</span>
        </div>
      )}

      <ExportFiles files={files} />

      {exports.en_cours ? (
        <div className="callout callout--live" role="status">
          <span className="spinner" aria-hidden="true" />
          <span className="callout__body">
            <strong>Génération en cours.</strong> Rendu Word, conversion PDF, puis dépôt des
            fichiers. Le premier export réveille le service de conversion : comptez jusqu'à
            deux minutes.
          </span>
        </div>
      ) : (
        <div className="btn-row">
          <button className="btn btn--primary" type="button" disabled={busy} onClick={launch}>
            {files.length > 0 ? "Régénérer les documents" : "Générer les documents"}
          </button>
        </div>
      )}

      <div className="split">
        <MissingData sections={state.sections} catalogue={catalogue} />
        <ReopenForm projectId={projectId} state={state} catalogue={catalogue}
          disabled={exports.en_cours} />
      </div>
    </main>
  );
}
