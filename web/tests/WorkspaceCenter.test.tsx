import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceCenter } from "@/components/WorkspaceCenter";
import { initialLive, liveReducer, type Live } from "@/lib/workspace";
import { catalogue, projectState, summary } from "./fixtures";

function live(state: Parameters<typeof projectState>[0], extra: Partial<Live> = {}): Live {
  return { ...liveReducer(initialLive, { type: "state", state: projectState(state) }), ...extra };
}

function show(value: Live, onResume = vi.fn(async () => {})) {
  render(<WorkspaceCenter projectId="p-1" live={value} catalogue={catalogue}
    onAnswer={vi.fn(async () => {})} onResume={onResume} />);
  return onResume;
}

describe("WorkspaceCenter", () => {
  it("propose de reprendre un run en échec", async () => {
    const onResume = show(live({ projet: summary({ run_status: "failed" }) }));
    expect(screen.getByText("La rédaction s'est interrompue")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Reprendre" }));
    expect(onResume).toHaveBeenCalled();
  });

  it("mène un projet fini à ses documents, en signalant les sections passées", () => {
    show(live({
      projet: summary({ run_status: "done" }),
      sections: [{ section_id: "perimetre", document: "cdc", ordre: 1, statut: "skipped",
        blocks: [], note: null, revisions: 1 }],
    }));
    expect(screen.getByRole("link", { name: "Générer les documents" }))
      .toHaveAttribute("href", "/projets/p-1/exports");
    expect(screen.getByText(/mention Brouillon/)).toBeInTheDocument();
  });

  it("montre la section courante et le texte qui arrive", () => {
    show(live({ curseur: 1 }, { draft: "Premier paragraphe.\n\nSecond paragraphe." }));
    expect(screen.getByRole("heading", { name: "Périmètre" })).toBeInTheDocument();
    expect(screen.getByText("Section 2 sur 2")).toBeInTheDocument();
    expect(screen.getByText("Rédaction en cours")).toBeInTheDocument();
    expect(screen.getByText("Second paragraphe.")).toBeInTheDocument();
  });

  it("dit ce qui reste à reprendre pendant une réécriture", () => {
    show(live({ curseur: 0 }, { draft: "x", rework: 2 }));
    expect(screen.getByText("Réécriture en cours · encore 2 sections")).toBeInTheDocument();
  });

  it("annonce l'analyse de l'idée avant la première question", () => {
    show(live({}));
    expect(screen.getByText("L'agent lit votre idée et prépare ses questions.")).toBeInTheDocument();
  });

  it("annonce le contrôle de cohérence une fois le plan épuisé", () => {
    show(live({ curseur: 2 }));
    expect(screen.getByRole("heading", { name: "Contrôle de cohérence" })).toBeInTheDocument();
  });

  it("n'affiche pas le panneau de reprise sur un idle ordinaire, sans idleStuck", () => {
    show(live({ projet: summary({ run_status: "idle" }) }));
    expect(screen.queryByText("La rédaction n'a pas démarré")).toBeNull();
    expect(screen.getByText("L'agent lit votre idée et prépare ses questions.")).toBeInTheDocument();
  });

  it("affiche le panneau de reprise quand idleStuck est vrai, et lance la reprise", async () => {
    const value = live({ projet: summary({ run_status: "idle" }) });
    const onResume = vi.fn(async () => {});
    render(<WorkspaceCenter projectId="p-1" live={value} catalogue={catalogue}
      onAnswer={vi.fn(async () => {})} onResume={onResume} idleStuck />);
    expect(screen.getByText("La rédaction n'a pas démarré")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Lancer la rédaction" }));
    expect(onResume).toHaveBeenCalled();
  });

  it("affiche le lot de questions en attente", () => {
    show(live({
      projet: summary({ run_status: "waiting" }),
      interaction: { id: "i-1", kind: "questions",
        questions: [{ fact_id: "budget_projet", question: "Quel est votre budget ?" }] },
    }));
    expect(screen.getByLabelText("Quel est votre budget ?")).toBeInTheDocument();
  });
});
