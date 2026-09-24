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
    <section className="panel">
      <div className="panel__head"><h2 className="t-section">Rouvrir une section</h2></div>
      <form className="panel__body" onSubmit={submit} noValidate>
        <p className="t-note" style={{ marginBottom: 14 }}>
          La section est réécrite, avec celles qui s'appuient sur elle. Il faudra régénérer les documents ensuite.
        </p>
        <label className="field">
          <span className="field__label">Section</span>
          <select className="select" value={section} disabled={!possible}
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
        </label>
        <div className="field">
          <label className="field__label" htmlFor="reopen-consigne">Que faut-il changer ?</label>
          <textarea id="reopen-consigne" className="textarea" rows={3} value={consigne} disabled={!possible}
            onChange={(event) => setConsigne(event.target.value)} aria-describedby="reopen-aide" />
          <span className="field__hint" id="reopen-aide">
            {possible
              ? "Sans consigne, la section est reprise en tenant compte des faits actuels."
              : "Possible une fois la rédaction terminée."}
          </span>
        </div>
        {error && (
          <div className="callout callout--stop" role="alert">
            <span className="callout__body">{error}</span>
          </div>
        )}
        <div className="actions actions--start actions--plain">
          <button className="btn btn--outline" type="submit" disabled={!possible || busy}>Rouvrir et réécrire</button>
        </div>
      </form>
    </section>
  );
}
