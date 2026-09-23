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
        {interaction.score !== null && <span className="m-src user">Auto-critique {interaction.score}/10</span>}
        <span className="m-muted small">Prête à relire</span>
      </div>
      {interaction.problems.length > 0 && (
        <div className="m-note">
          <b>Ce que l'auto-critique relève</b>
          <ul>{interaction.problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>
        </div>
      )}
      <Paper blocks={interaction.blocks} />
      {revising ? (
        <div style={{ marginTop: 18, maxWidth: "72ch" }}>
          <label className="m-label" htmlFor="revision">Que faut-il changer ?</label>
          <textarea id="revision" className="m-input" rows={3} value={feedback}
            onChange={(e) => setFeedback(e.target.value)} />
          <div className="m-actions" style={{ justifyContent: "flex-start" }}>
            <button className="m-btn" type="button" disabled={busy}
              onClick={() => send({ action: "rewrite", problems: feedback.trim() ? [feedback.trim()] : [] })}>
              Relancer la rédaction
            </button>
            <button className="m-btn sec" type="button" onClick={() => setRevising(false)}>Annuler</button>
          </div>
        </div>
      ) : (
        <>
          <div className="m-actions" style={{ justifyContent: "flex-start" }}>
            <button className="m-btn" type="button" disabled={busy}
              onClick={() => send({ action: "accept" })}>Approuver</button>
            <button className="m-btn sec" type="button" disabled={busy}
              onClick={() => setRevising(true)}>Demander une révision</button>
            <button className="m-btn sec" type="button" disabled={busy}
              onClick={() => send({ action: "skip" })}>Passer la section</button>
          </div>
          <p className="m-muted small">
            Passer la section la garde telle quelle, mais les documents porteront la mention Brouillon.
          </p>
        </>
      )}
    </>
  );
}
