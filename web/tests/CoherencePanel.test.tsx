import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CoherencePanel } from "@/components/CoherencePanel";
import type { InconsistenciesInteraction } from "@/lib/contracts";
import { buildRulings, type Choice } from "@/lib/rulings";
import { catalogue } from "./fixtures";

const INCONSISTENCIES = [
  { kind: "dates", description: "Le lancement précède la livraison.",
    sections: ["cdc.perimetre", "bp.etude_marche"], proposal: "Décaler le lancement à six mois." },
  { kind: "financement", description: "Le financement ne couvre pas le besoin.",
    sections: [], proposal: null },
];

const interaction: InconsistenciesInteraction = {
  id: "i-9", kind: "inconsistencies", inconsistencies: INCONSISTENCIES,
};

const choice = (decision: Choice["decision"], consigne = ""): Choice => ({ decision, consigne });

describe("buildRulings", () => {
  it("exige une décision par incohérence", () => {
    expect(buildRulings(INCONSISTENCIES, [choice("ignorer"), choice(null)]).error)
      .toBe("Choisissez une suite pour chaque incohérence.");
  });

  it("exige une consigne quand il n'y a pas de proposition", () => {
    expect(buildRulings(INCONSISTENCIES, [choice("ignorer"), choice("corriger")]).error)
      .toBe("Dites comment corriger l'incohérence 2, ou choisissez « Ignorer ».");
  });

  it("laisse la consigne vide quand une proposition existe : le backend l'appliquera", () => {
    expect(buildRulings(INCONSISTENCIES, [choice("corriger"), choice("ignorer")]))
      .toEqual({ error: null, rulings: [
        { index: 0, decision: "corriger", consigne: null },
        { index: 1, decision: "ignorer" },
      ] });
  });

  it("rend la consigne saisie, sans blancs", () => {
    expect(buildRulings(INCONSISTENCIES, [choice("corriger", "  Décaler à 6 mois  "), choice("ignorer")]).rulings[0])
      .toEqual({ index: 0, decision: "corriger", consigne: "Décaler à 6 mois" });
  });
});

describe("CoherencePanel", () => {
  it("nomme les sections concernées avec leurs titres", () => {
    render(<CoherencePanel interaction={interaction} catalogue={catalogue} onSubmit={vi.fn()} />);
    expect(screen.getByText("Sections concernées : CDC · Périmètre, BP · Étude de marché")).toBeInTheDocument();
  });

  it("ne laisse qu'« Ignorer » à une incohérence qui ne nomme aucune section du plan", () => {
    render(<CoherencePanel interaction={interaction} catalogue={catalogue} onSubmit={vi.fn()} />);
    const second = screen.getByRole("group", { name: "Incohérence 2" });
    expect(within(second).getByRole("button", { name: "Corriger" })).toBeDisabled();
    expect(within(second).getByRole("button", { name: "Ignorer" })).toHaveAttribute("aria-pressed", "true");
  });

  it("envoie un arbitrage par incohérence", async () => {
    const onSubmit = vi.fn(async () => {});
    const user = userEvent.setup();
    render(<CoherencePanel interaction={interaction} catalogue={catalogue} onSubmit={onSubmit} />);

    const first = screen.getByRole("group", { name: "Incohérence 1" });
    await user.click(within(first).getByRole("button", { name: "Corriger" }));
    await user.type(screen.getByLabelText("Comment corriger ?"), "Décaler à 6 mois");
    await user.click(screen.getByRole("button", { name: "Appliquer et continuer" }));

    expect(onSubmit).toHaveBeenCalledWith([
      { index: 0, decision: "corriger", consigne: "Décaler à 6 mois" },
      { index: 1, decision: "ignorer" },
    ]);
  });

  it("refuse d'envoyer tant qu'une incohérence n'est pas tranchée", async () => {
    const onSubmit = vi.fn(async () => {});
    const user = userEvent.setup();
    const seul = { ...interaction, inconsistencies: [INCONSISTENCIES[0]] };
    render(<CoherencePanel interaction={seul} catalogue={catalogue} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Appliquer et continuer" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choisissez une suite pour chaque incohérence.");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
