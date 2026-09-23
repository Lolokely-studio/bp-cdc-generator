import { describe, expect, it } from "vitest";
import { badgeFor, formatFactValue, humanize } from "@/lib/facts";
import { catalogue } from "./fixtures";

const flat = (value: string) => value.replace(/\s/g, " ");

describe("badgeFor", () => {
  it("distingue une réponse, une déduction et un « je ne sais pas »", () => {
    expect(badgeFor({ fact_id: "x", value: "a", source: "user" }))
      .toEqual({ label: "Vous", className: "user" });
    expect(badgeFor({ fact_id: "x", value: "a", source: "deduced" }))
      .toEqual({ label: "Déduit", className: "inferred" });
    // Une clé présente à null EST une réponse : « je ne sais pas ».
    expect(badgeFor({ fact_id: "x", value: null, source: "user" }))
      .toEqual({ label: "Inconnu", className: "unknown" });
  });
});

describe("formatFactValue", () => {
  it("met chaque type dans ses mots", () => {
    expect(flat(formatFactValue(catalogue.faits.budget_projet, 60_000))).toBe("60 000 €");
    expect(flat(formatFactValue(catalogue.faits.hypothese_croissance, 0.35))).toBe("35 %");
    expect(flat(formatFactValue(catalogue.faits.hypothese_croissance, 35))).toBe("35 %");
    expect(flat(formatFactValue(catalogue.faits.delai_paiement_clients, 30))).toBe("30 jours");
    expect(formatFactValue(catalogue.faits.concurrents, ["Annonces", "Salles"])).toBe("Annonces, Salles");
    expect(formatFactValue(catalogue.faits.deja_lance, true)).toBe("Oui");
    expect(formatFactValue(catalogue.faits.positionnement_prix, "milieu_de_gamme")).toBe("Milieu de gamme");
    expect(formatFactValue(catalogue.faits.nom_projet, "CoachDom")).toBe("CoachDom");
    expect(formatFactValue(catalogue.faits.budget_projet, null)).toBe("Je ne sais pas");
  });
});

describe("humanize", () => {
  it("rend une option lisible", () => {
    expect(humanize("entree_de_gamme")).toBe("Entree de gamme");
  });
});
