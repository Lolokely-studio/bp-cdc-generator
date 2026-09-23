import { describe, expect, it } from "vitest";
import { buildAnswers, hintFor, parseAnswer, parseNumber } from "@/lib/answers";
import type { FactDefinition } from "@/lib/contracts";
import { catalogue } from "./fixtures";

const def = (type: string, extra: Partial<FactDefinition> = {}): FactDefinition =>
  ({ libelle: "x", type, unite: null, options: [], exemple: null, ...extra });
const typed = (raw: string) => ({ raw, unknown: false });

describe("parseNumber", () => {
  it("lit les nombres tapés à la française", () => {
    expect(parseNumber("60 000")).toBe(60_000);
    expect(parseNumber("60 000 €")).toBe(60_000);
    expect(parseNumber("12,5")).toBe(12.5);
    expect(parseNumber("35 %")).toBe(35);
    expect(parseNumber("-20")).toBe(-20);
  });

  it("refuse ce qui n'est pas un seul nombre", () => {
    for (const raw of ["", "douze", "12 ou 15", "1.200,50", "12,5,3", "5-6"]) {
      expect(parseNumber(raw)).toBeNull();
    }
  });
});

describe("parseAnswer", () => {
  it("rend null sur « je ne sais pas », quel que soit le champ", () => {
    expect(parseAnswer(def("montant"), { raw: "n'importe quoi", unknown: true }))
      .toEqual({ ok: true, value: null });
  });

  it("typa les nombres et refuse le reste", () => {
    for (const type of ["montant", "nombre", "pourcentage", "duree"]) {
      expect(parseAnswer(def(type), typed("60 000"))).toEqual({ ok: true, value: 60_000 });
      expect(parseAnswer(def(type), typed("beaucoup")))
        .toEqual({ ok: false, error: "Entrez un nombre, ou cochez « Je ne sais pas »." });
    }
  });

  it("distingue un champ numérique jamais renseigné d'un champ numérique illisible", () => {
    const jamaisRenseigne = parseAnswer(def("montant"), typed(""));
    const illisible = parseAnswer(def("montant"), typed("beaucoup"));
    // Chacun dit quoi faire : répondre, ou cocher « Je ne sais pas ».
    expect(jamaisRenseigne).toEqual({ ok: false, error: "Répondez, ou cochez « Je ne sais pas »." });
    expect(illisible).toEqual({ ok: false, error: "Entrez un nombre, ou cochez « Je ne sais pas »." });
    // La raison d'être de la distinction : les deux messages ne se
    // confondent pas, sans quoi deux champs vides afficheraient le mot à
    // mot d'une saisie fautive qu'aucun des deux n'a commise.
    expect(jamaisRenseigne.ok ? undefined : jamaisRenseigne.error)
      .not.toBe(illisible.ok ? undefined : illisible.error);
  });

  it("dit aussi quoi faire pour un champ de texte jamais renseigné", () => {
    expect(parseAnswer(def("texte_court"), typed("")))
      .toEqual({ ok: false, error: "Répondez, ou cochez « Je ne sais pas »." });
  });

  it("coupe une liste ligne par ligne", () => {
    expect(parseAnswer(def("liste"), typed("Annonces\n\n  Salles de sport \n")))
      .toEqual({ ok: true, value: ["Annonces", "Salles de sport"] });
    expect(parseAnswer(def("liste"), typed("   ")).ok).toBe(false);
  });

  it("n'accepte qu'une option du catalogue", () => {
    const definition = catalogue.faits.positionnement_prix;
    expect(parseAnswer(definition, typed("premium"))).toEqual({ ok: true, value: "premium" });
    expect(parseAnswer(definition, typed("luxe")).ok).toBe(false);
  });

  it("lit oui et non en booléen", () => {
    expect(parseAnswer(def("booleen"), typed("oui"))).toEqual({ ok: true, value: true });
    expect(parseAnswer(def("booleen"), typed("non"))).toEqual({ ok: true, value: false });
    expect(parseAnswer(def("booleen"), typed("")).ok).toBe(false);
  });

  it("traite tout le reste en texte, sans blancs autour", () => {
    expect(parseAnswer(def("texte_long"), typed("  Une idée.  "))).toEqual({ ok: true, value: "Une idée." });
    expect(parseAnswer(undefined, typed("Une idée."))).toEqual({ ok: true, value: "Une idée." });
    expect(parseAnswer(def("texte_court"), typed("  ")).ok).toBe(false);
  });
});

describe("buildAnswers", () => {
  it("garde les réponses valides et signale les autres, fait par fait", () => {
    const questions = [{ fact_id: "budget_projet", question: "?" }, { fact_id: "concurrents", question: "?" }];
    const { answers, errors } = buildAnswers(questions, catalogue.faits, {
      budget_projet: typed("60 000"),
      concurrents: typed(""),
    });
    expect(answers).toEqual({ budget_projet: 60_000 });
    expect(Object.keys(errors)).toEqual(["concurrents"]);
  });

  it("traite un champ jamais touché comme vide", () => {
    const { answers, errors } = buildAnswers([{ fact_id: "budget_projet", question: "?" }], catalogue.faits, {});
    expect(answers).toEqual({});
    expect(errors.budget_projet).toBeTruthy();
  });
});

describe("hintFor", () => {
  it("dit l'unité attendue et donne l'exemple du catalogue", () => {
    expect(hintFor(catalogue.faits.concurrents)).toBe("Une réponse par ligne.");
    expect(hintFor(catalogue.faits.budget_projet)).toBe("En euros. Par exemple : 60000.");
    expect(hintFor(catalogue.faits.delai_paiement_clients)).toBe("En jours.");
    expect(hintFor(catalogue.faits.hypothese_croissance)).toBe("En pourcentage, par exemple 35.");
    // L'exemple du catalogue finit parfois par un point : on n'en met pas deux.
    expect(hintFor(catalogue.faits.nom_projet)).toBe("Par exemple : CoachDom.");
    expect(hintFor(undefined)).toBeNull();
  });
});
