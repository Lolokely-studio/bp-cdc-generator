import { describe, expect, it } from "vitest";
import {
  creationPayload, projectsHeadline, qualifiedTitle, relativeDate, sectionCount, sectionTitle,
} from "@/lib/labels";
import { catalogue, summary } from "./fixtures";

describe("sectionCount", () => {
  it("compte les sections du profil choisi, document par document", () => {
    expect(sectionCount(catalogue, "cdc", "consultation", "banque")).toBe(3);
    expect(sectionCount(catalogue, "cdc", "cadrage", "banque")).toBe(2);
    expect(sectionCount(catalogue, "bp", "cadrage", "investisseur")).toBe(1);
    expect(sectionCount(catalogue, "both", "cadrage", "banque")).toBe(4);
  });
});

describe("titres", () => {
  it("rend le titre du catalogue, ou l'identifiant s'il est inconnu", () => {
    expect(sectionTitle(catalogue, "cdc", "perimetre")).toBe("Périmètre");
    expect(sectionTitle(catalogue, "bp", "inconnue")).toBe("inconnue");
    expect(qualifiedTitle(catalogue, "bp.etude_marche")).toBe("BP · Étude de marché");
    expect(qualifiedTitle(catalogue, "xx.yy")).toBe("xx.yy");
  });
});

describe("projectsHeadline", () => {
  it("dit combien de projets, dont combien en cours", () => {
    expect(projectsHeadline([])).toBe("Aucun projet pour l'instant.");
    expect(projectsHeadline([summary({ run_status: "done" })])).toBe("1 projet");
    expect(projectsHeadline([summary(), summary({ run_status: "done" }), summary({ run_status: "failed" })]))
      .toBe("3 projets, dont 2 en cours de rédaction");
  });
});

describe("relativeDate", () => {
  const now = new Date("2026-09-22T12:00:00Z");
  it("parle comme on parle", () => {
    expect(relativeDate("2026-09-22T11:59:30Z", now)).toBe("à l'instant");
    expect(relativeDate("2026-09-22T11:15:00Z", now)).toBe("il y a 45 minutes");
    expect(relativeDate("2026-09-22T10:00:00Z", now)).toBe("il y a 2 heures");
    expect(relativeDate("2026-09-21T12:00:00Z", now)).toBe("hier");
    expect(relativeDate(null, now)).toBe("");
  });
});

describe("creationPayload", () => {
  it("n'envoie que le profil des documents choisis, et nettoie les blancs", () => {
    expect(creationPayload({ nom: "  CoachDom ", documents: "cdc", profilCdc: "cadrage",
      profilBp: "banque", idee: " Une idée. " }))
      .toEqual({ nom: "CoachDom", documents: "cdc", profil_cdc: "cadrage", profil_bp: null, idee: "Une idée." });
    expect(creationPayload({ nom: "X", documents: "bp", profilCdc: "cadrage", profilBp: "banque", idee: "Y" }))
      .toMatchObject({ profil_cdc: null, profil_bp: "banque" });
    expect(creationPayload({ nom: "X", documents: "both", profilCdc: "cadrage", profilBp: "banque", idee: "Y" }))
      .toMatchObject({ profil_cdc: "cadrage", profil_bp: "banque" });
  });
});
