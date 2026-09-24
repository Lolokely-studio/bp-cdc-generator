"use client";

import { useState } from "react";
import { Paper } from "@/components/Paper";
import type { ReviewInteraction } from "@/lib/contracts";

export function ReviewPanel({ interaction, onSubmit }: {
  interaction: ReviewInteraction;
  onSubmit: (reponse: unknown) => Promise<void>;
}) {
  const [revising, setRevising] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(reponse: unknown) {
    setBusy(true);
    try {
      await onSubmit(reponse);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="m-status">
        {interaction.score !== null && <span className="tag tag--idle tag--flat">Auto-critique {interaction.score}/10</span>}
        <span className="t-note t-fine">Prête à relire</span>
      </div>
      {interaction.problems.length > 0 && (
        <div className="callout callout--wait">
          <span className="callout__body">
            <b>Ce que l'auto-critique relève</b>
            <ul>{interaction.problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>
          </span>
        </div>
      )}
      <Paper blocks={interaction.blocks} />
      {revising ? (
        <div style={{ marginTop: 18, maxWidth: "72ch" }}>
          <label className="field__label" htmlFor="revision">Que faut-il changer ?</label>
          <textarea id="revision" className="textarea" rows={3} value={feedback}
            onChange={(e) => setFeedback(e.target.value)} />
          <div className="actions actions--start">
            <button className="btn btn--primary" type="button" disabled={busy}
              onClick={() => send({ action: "rewrite", problems: feedback.trim() ? [feedback.trim()] : [] })}>
              Relancer la rédaction
            </button>
            <button className="btn btn--outline" type="button" onClick={() => setRevising(false)}>Annuler</button>
          </div>
        </div>
      ) : (
        <>
          <div className="actions actions--start">
            <button className="btn btn--primary" type="button" disabled={busy}
              onClick={() => send({ action: "accept" })}>Approuver</button>
            <button className="btn btn--outline" type="button" disabled={busy}
              onClick={() => setRevising(true)}>Demander une révision</button>
            <button className="btn btn--outline" type="button" disabled={busy}
              onClick={() => send({ action: "skip" })}>Passer la section</button>
          </div>
          <p className="t-note t-fine">
            Passer la section la garde telle quelle, mais les documents porteront la mention Brouillon.
          </p>
        </>
      )}
    </>
  );
}
