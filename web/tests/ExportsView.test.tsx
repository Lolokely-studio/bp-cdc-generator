import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router, useParams: () => ({ id: "p-1" }) }));

import { ExportsView } from "@/components/ExportsView";
import { StaticCatalogue } from "@/lib/catalogue";
import { catalogue, projectState, summary } from "./fixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const DONE = projectState({ projet: summary({ run_status: "done" }) });
const FILE = {
  document: "cdc", format: "docx", brouillon: false, fidele: true,
  lien: "https://stockage.test/cdc.docx", cree_le: "2026-09-22T09:00:00Z",
};

function routeFetch(handlers: Record<string, () => Response>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(url).pathname}`;
    const handler = handlers[key];
    if (!handler) throw new Error(`appel inattendu : ${key}`);
    return handler();
  });
}

function show() {
  return render(
    <StaticCatalogue catalogue={catalogue}><ExportsView projectId="p-1" pollMs={50} /></StaticCatalogue>,
  );
}

describe("ExportsView", () => {
  it("lance une génération et relit la liste", async () => {
    const fetchMock = routeFetch({
      "GET /projects/p-1/state": () => json(DONE),
      "GET /projects/p-1/exports": () => json({ en_cours: false, dernier_export: null, fichiers: [] }),
      "POST /projects/p-1/exports": () => json({ export: "en_cours" }, 202),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Générer les documents" }));
    const calls = () => fetchMock.mock.calls.map((call) => `${(call[1] as RequestInit | undefined)?.method ?? "GET"}`);
    await waitFor(() => expect(calls().filter((method) => method === "POST")).toHaveLength(1));
    await waitFor(() => expect(calls().filter((method) => method === "GET").length).toBeGreaterThan(2));
  });

  it("montre l'attente pendant le rendu, puis les fichiers, puis cesse de relire", async () => {
    const answers = [
      { en_cours: true, dernier_export: null, fichiers: [] },
      { en_cours: false, dernier_export: "ok", fichiers: [FILE] },
    ];
    const fetchMock = routeFetch({
      "GET /projects/p-1/state": () => json(DONE),
      "GET /projects/p-1/exports": () => json(answers.length > 1 ? answers.shift() : answers[0]),
    });
    vi.stubGlobal("fetch", fetchMock);
    show();

    expect(await screen.findByText(/réveille le service de conversion/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Télécharger le Word" })).toBeInTheDocument();
    const settled = fetchMock.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(fetchMock.mock.calls.length).toBe(settled);
  });

  it("dit qu'une génération a échoué sans rien perdre", async () => {
    vi.stubGlobal("fetch", routeFetch({
      "GET /projects/p-1/state": () => json(DONE),
      "GET /projects/p-1/exports": () => json({ en_cours: false, dernier_export: "echec", fichiers: [] }),
    }));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("La dernière génération a échoué");
  });

  it("prévient qu'un export lancé avant la fin sera un brouillon", async () => {
    vi.stubGlobal("fetch", routeFetch({
      "GET /projects/p-1/state": () => json(projectState({ projet: summary({ run_status: "waiting" }) })),
      "GET /projects/p-1/exports": () => json({ en_cours: false, dernier_export: null, fichiers: [] }),
    }));
    show();
    expect(await screen.findByText(/porteront la mention Brouillon/)).toBeInTheDocument();
  });
});
