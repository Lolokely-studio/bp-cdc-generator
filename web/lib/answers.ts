import type { FactDefinition } from "@/lib/contracts";

export type FieldState = { raw: string; unknown: boolean };
export type Parsed = { ok: true; value: unknown } | { ok: false; error: string };

const NUMERIC = new Set(["montant", "nombre", "pourcentage", "duree"]);
const NOT_A_NUMBER = "Entrez un nombre, ou cochez « Je ne sais pas ».";

/** Lit un nombre tapé à la française : « 60 000 », « 12,5 », « 1 200 € », « 35 % ».
 *
 * Rend `null` sur tout ce qui n'est pas UN nombre : « 12 ou 15 » ne doit pas
 * devenir 12. Un chiffre inventé ici traverserait tout le reste — les faits,
 * les calculs, le vérificateur de chiffres — sans que rien ne le rattrape. */
export function parseNumber(raw: string): number | null {
  // Espace ordinaire, insécable, fine insécable : les trois que produisent un
  // clavier, un copier-coller et un tableur.
  const cleaned = raw.replace(/[\s  €%]/g, "").replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return null;
  return Number(cleaned);
}

export function parseAnswer(definition: FactDefinition | undefined, field: FieldState): Parsed {
  // « Je ne sais pas » est une RÉPONSE (§4.2) : le fait existe, à null, et la
  // question ne sera plus posée.
  if (field.unknown) return { ok: true, value: null };
  const raw = field.raw.trim();
  const type = definition?.type ?? "texte_court";

  if (NUMERIC.has(type)) {
    // Un champ vide (jamais touché, ou vidé) n'a rien de « pas un nombre » :
    // c'est juste une réponse manquante. Le distinguer d'une saisie invalide
    // évite aussi que deux champs numériques vides partagent le mot à mot
    // d'une erreur, ce qu'un lecteur d'écran annoncerait comme un seul
    // message répété sans dire quel champ il vise.
    if (!raw) return { ok: false, error: "Répondez, ou cochez « Je ne sais pas »." };
    const value = parseNumber(raw);
    return value === null ? { ok: false, error: NOT_A_NUMBER } : { ok: true, value };
  }
  if (type === "booleen") {
    if (raw === "oui") return { ok: true, value: true };
    if (raw === "non") return { ok: true, value: false };
    return { ok: false, error: "Choisissez oui ou non, ou cochez « Je ne sais pas »." };
  }
  if (type === "choix") {
    return definition && definition.options.includes(raw)
      ? { ok: true, value: raw }
      : { ok: false, error: "Choisissez une option, ou cochez « Je ne sais pas »." };
  }
  if (type === "liste") {
    const items = raw.split("\n").map((line) => line.trim()).filter(Boolean);
    return items.length > 0
      ? { ok: true, value: items }
      : { ok: false, error: "Entrez au moins une ligne, ou cochez « Je ne sais pas »." };
  }
  return raw ? { ok: true, value: raw } : { ok: false, error: "Répondez, ou cochez « Je ne sais pas »." };
}

export function buildAnswers(
  // `question` optionnel : seul `fact_id` sert ici, mais les appelants
  // passent toujours un `QuestionsInteraction["questions"]` complet.
  questions: { fact_id: string; question?: string }[],
  definitions: Record<string, FactDefinition>,
  fields: Record<string, FieldState>,
): { answers: Record<string, unknown>; errors: Record<string, string> } {
  const answers: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const { fact_id } of questions) {
    const parsed = parseAnswer(definitions[fact_id], fields[fact_id] ?? { raw: "", unknown: false });
    if (parsed.ok) answers[fact_id] = parsed.value;
    else errors[fact_id] = parsed.error;
  }
  return { answers, errors };
}

/** Ce qui se dit sous le champ : l'unité attendue, puis l'exemple du
 * catalogue — montré, jamais pré-rempli. */
export function hintFor(definition: FactDefinition | undefined): string | null {
  if (!definition) return null;
  const parts: string[] = [];
  if (definition.type === "liste") parts.push("Une réponse par ligne.");
  if (definition.type === "montant") parts.push("En euros.");
  if (definition.type === "pourcentage") parts.push("En pourcentage, par exemple 35.");
  if (definition.unite && (definition.type === "nombre" || definition.type === "duree")) {
    parts.push(`En ${definition.unite}.`);
  }
  if (definition.exemple !== null && definition.exemple !== undefined && definition.exemple !== "") {
    const shown = Array.isArray(definition.exemple)
      ? definition.exemple.map(String).join(", ")
      : String(definition.exemple);
    parts.push(`Par exemple : ${shown.replace(/[.\s]+$/, "")}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}
