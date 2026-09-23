import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import NewProjectPage from "@/app/(app)/projets/nouveau/page";
import { StaticCatalogue } from "@/lib/catalogue";
import { catalogue, summary } from "./fixtures";

function page() {
  return render(<StaticCatalogue catalogue={catalogue}><NewProjectPage /></StaticCatalogue>);
}

beforeEach(() => router.push.mockReset());

describe("la création d'un projet", () => {
  it("envoie le choix, le profil et l'idée, puis ouvre la rédaction", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(summary({ id: "p-9" })), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    page();

    await user.click(screen.getByRole("button", { name: /Cahier des charges/ }));
    expect(screen.queryByText("Qui lira le business plan ?")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Cadrer mon projet" }));
    await user.click(screen.getByRole("button", { name: "Continuer" }));
    await user.type(screen.getByLabelText("Nom du projet"), "CoachDom");
    await user.type(screen.getByLabelText("Votre idée"), "Des coachs à domicile.");
    await user.click(screen.getByRole("button", { name: "Analyser mon idée" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/projets/p-9"));
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(String(init.body))).toEqual({
      nom: "CoachDom", documents: "cdc", profil_cdc: "cadrage", profil_bp: null,
      idee: "Des coachs à domicile.",
    });
  });

  it("annonce le nombre de sections du profil choisi", async () => {
    const user = userEvent.setup();
    page();
    expect(screen.getByRole("button", { name: /Cahier des charges/ })).toHaveTextContent("3 sections");
    await user.click(screen.getByRole("button", { name: "Cadrer mon projet" }));
    expect(screen.getByRole("button", { name: /Cahier des charges/ })).toHaveTextContent("2 sections");
  });

  it("refuse un nom ou une idée vides, sans appeler l'API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    page();
    await user.click(screen.getByRole("button", { name: "Continuer" }));
    await user.click(screen.getByRole("button", { name: "Analyser mon idée" }));
    expect(screen.getByText("Donnez un nom au projet.")).toBeInTheDocument();
    expect(screen.getByText("Décrivez votre idée en quelques phrases.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
