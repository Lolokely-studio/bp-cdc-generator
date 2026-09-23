import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReviewPanel } from "@/components/ReviewPanel";
import type { ReviewInteraction } from "@/lib/contracts";

const interaction: ReviewInteraction = {
  id: "i-2", kind: "review", section: "cdc.perimetre", score: 6,
  problems: ["chiffre orphelin : 12 %"],
  blocks: [
    { kind: "paragraph", text: "Le budget est de [Donnée à compléter : budget] euros." },
    { kind: "table", number: 2, title: "Jalons", columns: ["Étape", "Mois"], rows: [["Lancement", "6"]] },
  ],
};

describe("ReviewPanel", () => {
  it("montre le brouillon, sa note et ce que la critique relève", () => {
    render(<ReviewPanel interaction={interaction} onSubmit={vi.fn()} />);
    expect(screen.getByText("Auto-critique 6/10")).toBeInTheDocument();
    expect(screen.getByText("chiffre orphelin : 12 %")).toBeInTheDocument();
    expect(screen.getByText("[Donnée à compléter : budget]").tagName).toBe("MARK");
    expect(screen.getByText("Tableau 2 — Jalons")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Lancement" })).toBeInTheDocument();
  });

  it("approuve la section", async () => {
    const onSubmit = vi.fn(async () => {});
    await userEvent.setup().click(
      render(<ReviewPanel interaction={interaction} onSubmit={onSubmit} />)
        .getByRole("button", { name: "Approuver" }),
    );
    expect(onSubmit).toHaveBeenCalledWith({ action: "accept" });
  });

  it("demande une révision en portant la consigne", async () => {
    const onSubmit = vi.fn(async () => {});
    const user = userEvent.setup();
    render(<ReviewPanel interaction={interaction} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Demander une révision" }));
    await user.type(screen.getByLabelText("Que faut-il changer ?"), "Plus court, et chiffré.");
    await user.click(screen.getByRole("button", { name: "Relancer la rédaction" }));
    expect(onSubmit).toHaveBeenCalledWith({ action: "rewrite", problems: ["Plus court, et chiffré."] });
  });

  it("passe la section, en prévenant de la mention Brouillon", async () => {
    const onSubmit = vi.fn(async () => {});
    const user = userEvent.setup();
    render(<ReviewPanel interaction={interaction} onSubmit={onSubmit} />);
    expect(screen.getByText(/mention Brouillon/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Passer la section" }));
    expect(onSubmit).toHaveBeenCalledWith({ action: "skip" });
  });
});
