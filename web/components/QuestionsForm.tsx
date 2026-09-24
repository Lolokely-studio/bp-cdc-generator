"use client";

import { useState, type FormEvent } from "react";
import { buildAnswers, hintFor, type FieldState } from "@/lib/answers";
import type { Catalogue, FactDefinition, QuestionsInteraction } from "@/lib/contracts";
import { humanize } from "@/lib/facts";

type Question = QuestionsInteraction["questions"][number];

function QuestionField({ question, definition, field, error, onChange }: {
  question: Question;
  definition: FactDefinition | undefined;
  field: FieldState;
  error: string | undefined;
  onChange: (patch: Partial<FieldState>) => void;
}) {
  const id = `q-${question.fact_id}`;
  const errorId = `${id}-err`;
  const type = definition?.type ?? "texte_court";
  const shared = {
    id,
    disabled: field.unknown,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId : undefined,
  };
  const hint = hintFor(definition);

  let input;
  if (type === "texte_long" || type === "liste") {
    input = <textarea {...shared} className="textarea" rows={type === "liste" ? 4 : 3} value={field.raw}
      onChange={(e) => onChange({ raw: e.target.value })} />;
  } else if (type === "choix" && definition) {
    input = (
      <select {...shared} className="select" value={field.raw} onChange={(e) => onChange({ raw: e.target.value })}>
        <option value="">Choisir…</option>
        {definition.options.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}
      </select>
    );
  } else if (type === "booleen") {
    input = (
      <select {...shared} className="select" value={field.raw} onChange={(e) => onChange({ raw: e.target.value })}>
        <option value="">Choisir…</option>
        <option value="oui">Oui</option>
        <option value="non">Non</option>
      </select>
    );
  } else if (type === "date") {
    input = <input {...shared} className="input" type="date" value={field.raw}
      onChange={(e) => onChange({ raw: e.target.value })} />;
  } else {
    const numeric = ["montant", "nombre", "pourcentage", "duree"].includes(type);
    input = <input {...shared} className="input" inputMode={numeric ? "decimal" : undefined} value={field.raw}
      onChange={(e) => onChange({ raw: e.target.value })} />;
  }

  // L'étiquette ne porte que son intitulé : la note d'aide et la case
  // « je ne sais pas » vivent hors du `<label>`, reliées par
  // `htmlFor`/`id` et `aria-describedby`.
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>{question.question}</label>
      {input}
      {hint && <p className="field__hint">{hint}</p>}
      <label className="check">
        <input type="checkbox" checked={field.unknown} onChange={(e) => onChange({ unknown: e.target.checked })} />
        {" "}Je ne sais pas
      </label>
      {error && <p className="field__error" id={errorId}>{error}</p>}
    </div>
  );
}

export function QuestionsForm({ interaction, catalogue, onSubmit }: {
  interaction: QuestionsInteraction;
  catalogue: Catalogue;
  onSubmit: (reponse: Record<string, unknown>) => Promise<void>;
}) {
  const [fields, setFields] = useState<Record<string, FieldState>>(() =>
    Object.fromEntries(interaction.questions.map((q) => [q.fact_id, { raw: "", unknown: false }])));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  function update(factId: string, patch: Partial<FieldState>) {
    setFields((current) => ({ ...current, [factId]: { ...current[factId], ...patch } }));
    setErrors((current) => {
      if (!current[factId]) return current;
      const { [factId]: _removed, ...rest } = current;
      return rest;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const { answers, errors: found } = buildAnswers(interaction.questions, catalogue.faits, fields);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    try {
      await onSubmit(answers);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <p className="t-note" style={{ marginBottom: 16 }}>
        {interaction.questions.length === 1 ? "Une information manque" : "Quelques informations manquent"} pour
        rédiger cette section.
      </p>
      {interaction.questions.map((question) => (
        <QuestionField key={question.fact_id} question={question}
          definition={catalogue.faits[question.fact_id]}
          field={fields[question.fact_id] ?? { raw: "", unknown: false }}
          error={errors[question.fact_id]}
          onChange={(patch) => update(question.fact_id, patch)} />
      ))}
      <div className="actions actions--start">
        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Envoi…" : "Envoyer les réponses"}
        </button>
      </div>
    </form>
  );
}
