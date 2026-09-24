"use client";

import { useState } from "react";
import type { Catalogue, InconsistenciesInteraction } from "@/lib/contracts";
import { humanize } from "@/lib/facts";
import { qualifiedTitle } from "@/lib/labels";
import { buildRulings, type Choice } from "@/lib/rulings";

export function CoherencePanel({ interaction, catalogue, onSubmit }: {
  interaction: InconsistenciesInteraction;
  catalogue: Catalogue;
  onSubmit: (reponse: unknown) => Promise<void>;
}) {
  const [choices, setChoices] = useState<Choice[]>(() =>
    // Une incohérence qui ne nomme aucune section du plan n'a rien à faire
    // réécrire : elle ne peut qu'être ignorée, et c'est déjà choisi.
    interaction.inconsistencies.map((inconsistency) => ({
      decision: inconsistency.sections.length === 0 ? "ignorer" : null,
      consigne: "",
    })));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(index: number, patch: Partial<Choice>) {
    setChoices((current) => current.map((choice, i) => (i === index ? { ...choice, ...patch } : choice)));
    setError(null);
  }

  async function submit() {
    const { rulings, error: found } = buildRulings(interaction.inconsistencies, choices);
    setError(found);
    if (found) return;
    setBusy(true);
    try {
      await onSubmit(rulings);
    } finally {
      setBusy(false);
    }
  }

  const count = interaction.inconsistencies.length;
  return (
    <main className="page page--narrow">
      <h1 className="t-page">
        {count === 1 ? "Une incohérence entre les documents" : `${count} incohérences entre les documents`}
      </h1>
      <p className="t-note">
        Choisissez comment les résoudre. Les sections à corriger seront réécrites avant l'export.
      </p>
      {interaction.inconsistencies.map((inconsistency, index) => {
        const choice = choices[index];
        return (
          <div className="m-conf" key={index}>
            <b>{humanize(inconsistency.kind)}</b>
            <p className="t-note t-fine">{inconsistency.description}</p>
            {inconsistency.sections.length > 0 ? (
              <p className="t-note t-fine">
                Sections concernées : {inconsistency.sections.map((q) => qualifiedTitle(catalogue, q)).join(", ")}
              </p>
            ) : (
              <p className="t-note t-fine">Aucune section du plan n'est nommée : seule « Ignorer » est possible.</p>
            )}
            {inconsistency.proposal && <p className="t-fine">Proposition : {inconsistency.proposal}</p>}
            <div className="m-chips" role="group" aria-label={`Incohérence ${index + 1}`}>
              <button className="m-chip" type="button" aria-pressed={choice.decision === "corriger"}
                disabled={inconsistency.sections.length === 0}
                onClick={() => update(index, { decision: "corriger" })}>Corriger</button>
              <button className="m-chip" type="button" aria-pressed={choice.decision === "ignorer"}
                onClick={() => update(index, { decision: "ignorer" })}>Ignorer</button>
            </div>
            {choice.decision === "corriger" && (
              <div style={{ marginTop: 12 }}>
                <label className="m-label" htmlFor={`consigne-${index}`}>Comment corriger ?</label>
                <textarea id={`consigne-${index}`} className="m-input" rows={2} value={choice.consigne}
                  placeholder={inconsistency.proposal ?? ""}
                  onChange={(e) => update(index, { consigne: e.target.value })} />
                <p className="m-hint">
                  {inconsistency.proposal ? "Laissez vide pour appliquer la proposition." : "Une phrase suffit."}
                </p>
              </div>
            )}
          </div>
        );
      })}
      {error && <p className="m-err" role="alert">{error}</p>}
      <div className="m-actions">
        <button className="m-btn" type="button" disabled={busy} onClick={submit}>Appliquer et continuer</button>
      </div>
    </main>
  );
}
