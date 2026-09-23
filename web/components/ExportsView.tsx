"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ExportFiles } from "@/components/ExportFiles";
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

  if (!exports || !state) {
    return (
      <main className="m-body">
        <p className="m-muted">Chargement…</p>
        {error && <p className="m-err" role="alert">{error}</p>}
      </main>
    );
  }

  const files = exports.fichiers;
  const latest = [...files].map((file) => file.cree_le).sort().at(-1) ?? null;
  const finished = state.projet.run_status === "done";

  return (
    <main className="m-body">
      <div className="m-head">
        <div>
          <h1 className="m-h">{files.length > 0 ? "Vos documents sont prêts" : "Générer les documents"}</h1>
          <p className="m-muted">
            {state.projet.nom}{latest ? ` · derniers fichiers ${relativeDate(latest)}` : ""}
          </p>
        </div>
        <Link className="m-btn sec" href={`/projets/${projectId}`}>Retour à la rédaction</Link>
      </div>

      {!finished && (
        <p className="m-note">
          La rédaction n'est pas terminée : les documents générés maintenant porteront la mention Brouillon.
        </p>
      )}

      {exports.en_cours ? (
        <ul className="m-steps" aria-live="polite">
          <li className="run">
            <span className="ic" />
            Rendu Word, conversion PDF, puis dépôt des fichiers. Le premier export réveille le service de
            conversion : comptez jusqu'à deux minutes.
          </li>
        </ul>
      ) : (
        <div className="m-actions" style={{ justifyContent: "flex-start", marginTop: 0 }}>
          <button className="m-btn" type="button" disabled={busy} onClick={launch}>
            {files.length > 0 ? "Régénérer les documents" : "Générer les documents"}
          </button>
        </div>
      )}

      {!exports.en_cours && exports.dernier_export === "echec" && (
        <p className="m-err" role="alert">
          La dernière génération a échoué. Les documents précédents, s'il y en a, sont intacts : réessayez.
        </p>
      )}
      {error && <p className="m-err" role="alert">{error}</p>}

      <ExportFiles files={files} />

      <div className="m-split">
        <MissingData sections={state.sections} catalogue={catalogue} />
        <ReopenForm projectId={projectId} state={state} catalogue={catalogue} disabled={exports.en_cours} />
      </div>
    </main>
  );
}
