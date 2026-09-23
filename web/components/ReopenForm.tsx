"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { Catalogue, ProjectState } from "@/lib/contracts";
import { DOCUMENT_SHORT, sectionTitle } from "@/lib/labels";
import { reopenErrorMessage } from "@/lib/messages";

export function ReopenForm({ projectId, state, catalogue, disabled }: {
  projectId: string;
  state: ProjectState;
  catalogue: Catalogue;
  disabled: boolean;
}) {
  const router = useRouter();
  const [section, setSection] = useState("");
  const [consigne, setConsigne] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // §6 : la réouverture n'est permise que sur un projet terminé, et jamais
  // pendant un export.
  const possible = state.projet.run_status === "done" && !disabled;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!section) {
      setError("Choisissez une section.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      // La route prend l'identifiant seul : le document se déduit du plan.
      const [, sectionId] = section.split(".", 2);
      await api.reopen(projectId, sectionId, consigne.trim() || null);
      router.push(`/projets/${projectId}`);
    } catch (caught) {
      setError(reopenErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <p className="m-cap">Rouvrir une section</p>
      <p className="m-muted small">
        La section est réécrite, avec celles qui s'appuient sur elle. Il faudra régénérer les documents ensuite.
      </p>
      <div style={{ marginTop: 12 }}>
        <label className="m-label" htmlFor="reopen-section">Section</label>
        <select id="reopen-section" className="m-input" value={section} disabled={!possible}
          onChange={(event) => setSection(event.target.value)}>
          <option value="">Choisir…</option>
          {state.plan.map((ref) => {
            const value = `${ref.document}.${ref.section_id}`;
            return (
              <option key={value} value={value}>
                {DOCUMENT_SHORT[ref.document]} · {sectionTitle(catalogue, ref.document, ref.section_id)}
              </option>
            );
          })}
        </select>
      </div>
      <div style={{ marginTop: 12 }}>
        <label className="m-label" htmlFor="reopen-consigne">Que faut-il changer ?</label>
        <textarea id="reopen-consigne" className="m-input" rows={3} value={consigne} disabled={!possible}
          onChange={(event) => setConsigne(event.target.value)} />
        <p className="m-hint">
          {possible
            ? "Sans consigne, la section est reprise en tenant compte des faits actuels."
            : "Possible une fois la rédaction terminée."}
        </p>
      </div>
      {error && <p className="m-err" role="alert">{error}</p>}
      <div className="m-actions" style={{ justifyContent: "flex-start" }}>
        <button className="m-btn sec" type="submit" disabled={!possible || busy}>Rouvrir et réécrire</button>
      </div>
    </form>
  );
}
