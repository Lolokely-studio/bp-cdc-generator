import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QuestionsForm } from "@/components/QuestionsForm";
import type { QuestionsInteraction } from "@/lib/contracts";
import { catalogue } from "./fixtures";

const interaction: QuestionsInteraction = {
  id: "i-1", kind: "questions",
  questions: [
    { fact_id: "budget_projet", question: "Quel est votre budget ?" },
    { fact_id: "concurrents", question: "Qui sont vos concurrents ?" },
    { fact_id: "positionnement_prix", question: "Où vous situez-vous ?" },
    { fact_id: "hypothese_croissance", question: "Quelle croissance visez-vous ?" },
  ],
};

const fieldOf = (question: string) => screen.getByLabelText(question);
const boxOf = (question: string) =>
  within(fieldOf(question).closest(".m-q") as HTMLElement).getByRole("checkbox");

describe("QuestionsForm", () => {
  it("donne à chaque question le champ de son type", () => {
    render(<QuestionsForm interaction={interaction} catalogue={catalogue} onSubmit={vi.fn()} />);
    expect(fieldOf("Quel est votre budget ?").tagName).toBe("INPUT");
    expect(fieldOf("Qui sont vos concurrents ?").tagName).toBe("TEXTAREA");
    expect(fieldOf("Où vous situez-vous ?").tagName).toBe("SELECT");
    expect(within(fieldOf("Où vous situez-vous ?")).getByRole("option", { name: "Milieu de gamme" }))
      .toBeInTheDocument();
    expect(screen.getByText("Une réponse par ligne.")).toBeInTheDocument();
  });

  it("envoie des réponses typées, « je ne sais pas » compris", async () => {
    const onSubmit = vi.fn(async () => {});
    const user = userEvent.setup();
    render(<QuestionsForm interaction={interaction} catalogue={catalogue} onSubmit={onSubmit} />);

    await user.type(fieldOf("Quel est votre budget ?"), "60 000");
    await user.type(fieldOf("Qui sont vos concurrents ?"), "Annonces\nSalles de sport");
    await user.selectOptions(fieldOf("Où vous situez-vous ?"), "premium");
    await user.click(boxOf("Quelle croissance visez-vous ?"));
    expect(fieldOf("Quelle croissance visez-vous ?")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Envoyer les réponses" }));

    expect(onSubmit).toHaveBeenCalledWith({
      budget_projet: 60_000,
      concurrents: ["Annonces", "Salles de sport"],
      positionnement_prix: "premium",
      hypothese_croissance: null,
    });
  });

  it("refuse d'envoyer un lot incomplet et dit quel champ pèche", async () => {
    const onSubmit = vi.fn(async () => {});
    const user = userEvent.setup();
    render(<QuestionsForm interaction={interaction} catalogue={catalogue} onSubmit={onSubmit} />);

    await user.type(fieldOf("Quel est votre budget ?"), "beaucoup");
    await user.click(screen.getByRole("button", { name: "Envoyer les réponses" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Entrez un nombre, ou cochez « Je ne sais pas ».")).toBeInTheDocument();
    expect(screen.getAllByText(/Je ne sais pas ./).length).toBeGreaterThan(1);
  });
});
