import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import ProjectsPage from "@/app/(app)/projets/page";
import { summary } from "./fixtures";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("le tableau de bord des projets", () => {
  it("dit qu'il charge, sans afficher de carte, pendant l'appel", async () => {
    const { promise } = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(() => promise));
    render(<ProjectsPage />);
    expect(screen.getByText("Chargement…")).toBeInTheDocument();
    expect(document.querySelector(".m-projects")).toBeNull();
  });

  it("affiche les projets reçus, avec la phrase de tête", async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify([summary({ id: "p-1", nom: "CoachDom" }), summary({ id: "p-2", nom: "Autre", run_status: "done" })]),
      { status: 200 },
    ));
    vi.stubGlobal("fetch", fetchMock);
    render(<ProjectsPage />);
    expect(await screen.findByText("CoachDom")).toBeInTheDocument();
    expect(screen.getByText("Autre")).toBeInTheDocument();
    expect(screen.getByText("2 projets, dont 1 en cours de rédaction")).toBeInTheDocument();
  });

  it("affiche l'échec du chargement, sans aucune carte", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "erreur" }), { status: 500 })));
    render(<ProjectsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("La liste des projets n'a pas pu être chargée.");
    expect(document.querySelector(".m-projects")).toBeNull();
    await waitFor(() => expect(screen.queryByText("Chargement…")).toBeNull());
  });
});
