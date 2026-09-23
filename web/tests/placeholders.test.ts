import { describe, expect, it } from "vitest";
import type { Section } from "@/lib/contracts";
import { missingData, splitMarkers } from "@/lib/placeholders";

function section(overrides: Partial<Section>): Section {
  return {
    section_id: "perimetre", document: "cdc", ordre: 1, statut: "done",
    blocks: [], note: 8, revisions: 1, ...overrides,
  };
}

describe("splitMarkers", () => {
  it("isole les marqueurs du texte qui les entoure", () => {
    expect(splitMarkers("Budget de [Donnée à compléter : apport initial] à confirmer.")).toEqual([
      { text: "Budget de ", marker: false },
      { text: "[Donnée à compléter : apport initial]", marker: true },
      { text: " à confirmer.", marker: false },
    ]);
  });

  it("rend le texte entier quand il n'y a rien à compléter", () => {
    expect(splitMarkers("Rien à signaler.")).toEqual([{ text: "Rien à signaler.", marker: false }]);
  });
});

describe("missingData", () => {
  it("relève les blocs marqueurs et les marqueurs glissés dans le texte", () => {
    const sections: Section[] = [
      section({
        blocks: [
          { kind: "placeholder", label: "Apport des fondateurs" },
          { kind: "paragraph", text: "Le budget est de [Donnée à compléter : budget] euros." },
          { kind: "list", items: ["[Donnée à compléter : assurance]"] },
          { kind: "table", number: 1, title: "Jalons", columns: ["Étape"],
            rows: [["[Donnée à compléter : date de lancement]"]] },
        ],
      }),
    ];
    expect(missingData(sections).map((m) => m.label)).toEqual([
      "Apport des fondateurs", "budget", "assurance", "date de lancement",
    ]);
  });

  it("ne répète pas un même trou dans une section, mais le suit d'une section à l'autre", () => {
    const blocks: Section["blocks"] = [
      { kind: "paragraph", text: "[Donnée à compléter : budget] puis [Donnée à compléter : budget]" },
    ];
    const found = missingData([
      section({ blocks }),
      section({ section_id: "etude_marche", document: "bp", blocks }),
    ]);
    expect(found).toEqual([
      { label: "budget", document: "cdc", sectionId: "perimetre" },
      { label: "budget", document: "bp", sectionId: "etude_marche" },
    ]);
  });
});
