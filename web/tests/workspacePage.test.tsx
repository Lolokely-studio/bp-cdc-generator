import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router, useParams: () => ({ id: "p-1" }) }));

import WorkspacePage from "@/app/(app)/projets/[id]/page";
import { StaticCatalogue } from "@/lib/catalogue";
import { catalogue, projectState, summary } from "./fixtures";

const QUESTIONS = {
  id: "i-1", kind: "questions" as const,
  questions: [{ fact_id: "nom_projet", question: "Comment s'appelle votre projet ?" }],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const openStream = () => new Response(new ReadableStream<Uint8Array>({ start() {} }));

/** Un aiguilleur de `fetch` : une réponse par « MÉTHODE /chemin ». Un appel
 * non prévu échoue au lieu de passer inaperçu. */
function routeFetch(handlers: Record<string, () => Response>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(url).pathname}`;
    const handler = handlers[key];
    if (!handler) throw new Error(`appel inattendu : ${key}`);
    return handler();
  });
}

function show() {
  return render(<StaticCatalogue catalogue={catalogue}><WorkspacePage /></StaticCatalogue>);
}

beforeEach(() => router.push.mockReset());
afterEach(() => vi.useRealTimers());

describe("l'espace de rédaction", () => {
  it("n'ouvre pas le flux tant qu'une réponse est attendue, et l'ouvre une fois partie", async () => {
    const states = [
      projectState({ projet: summary({ run_status: "waiting" }), interaction: QUESTIONS }),
      projectState({ projet: summary({ run_status: "running" }) }),
    ];
    const fetchMock = routeFetch({
      "GET /projects/p-1/state": () => json(states.length > 1 ? states.shift() : states[0]),
      "POST /projects/p-1/answer": () => json({ rejoue: true, run_status: "running" }),
      "GET /projects/p-1/stream": () => openStream(),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    show();

    await screen.findByLabelText("Comment s'appelle votre projet ?");
    const paths = () => fetchMock.mock.calls.map((call) => String(call[0]));
    expect(paths().some((path) => path.endsWith("/stream"))).toBe(false);

    await user.type(screen.getByLabelText("Comment s'appelle votre projet ?"), "CoachDom");
    await user.click(screen.getByRole("button", { name: "Envoyer les réponses" }));

    await waitFor(() => expect(paths().some((path) => path.endsWith("/stream"))).toBe(true));
    const answer = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/answer"));
    expect(JSON.parse(String((answer?.[1] as RequestInit).body)))
      .toEqual({ interaction_id: "i-1", reponse: { nom_projet: "CoachDom" } });
  });

  it("ne repose pas une question dont la réponse n'est pas encore consommée", async () => {
    // `/state` continue de rendre l'interaction déjà répondue : la ligne dit
    // encore `waiting` le temps que le run reprenne (§6.2).
    const waiting = projectState({ projet: summary({ run_status: "waiting" }), interaction: QUESTIONS });
    const fetchMock = routeFetch({
      "GET /projects/p-1/state": () => json(waiting),
      "POST /projects/p-1/answer": () => json({ rejoue: true, run_status: "running" }),
      "GET /projects/p-1/stream": () => openStream(),
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    show();

    await screen.findByLabelText("Comment s'appelle votre projet ?");
    await user.type(screen.getByLabelText("Comment s'appelle votre projet ?"), "CoachDom");
    await user.click(screen.getByRole("button", { name: "Envoyer les réponses" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Envoyer les réponses" })).toBeNull());
    expect(screen.getByText("L'agent prépare la section…")).toBeInTheDocument();
  });

  it("ferme le flux et propose de lancer la rédaction si le projet reste idle trop longtemps", async () => {
    // Constat 5 de la revue finale : un projet mort-né reste `idle` pour
    // toujours — la réconciliation du démarrage ne rattrape que `running`.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const idle = projectState({ projet: summary({ run_status: "idle" }) });
    const fetchMock = routeFetch({
      "GET /projects/p-1/state": () => json(idle),
      "GET /projects/p-1/stream": () => openStream(),
      "POST /projects/p-1/resume": () => json({ reprise: true, run_status: "running" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    show();

    await screen.findByText("L'agent lit votre idée et prépare ses questions.");
    const paths = () => fetchMock.mock.calls.map((call) => String(call[0]));
    const streamCall = () => fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/stream"));
    await waitFor(() => expect(streamCall()).toBeTruthy());
    const streamSignal = (streamCall()?.[1] as RequestInit | undefined)?.signal;

    // Avant le délai : toujours l'écran d'attente habituel, le flux reste ouvert.
    await act(() => vi.advanceTimersByTimeAsync(19_000));
    expect(screen.queryByText("La rédaction n'a pas démarré")).toBeNull();
    expect(streamSignal?.aborted).toBe(false);

    // Passé le délai : l'écran dit la vérité, et le flux se ferme pour de bon
    // — sans quoi il enverrait un battement toutes les quinze secondes,
    // indéfiniment (§9.4).
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(screen.getByText("La rédaction n'a pas démarré")).toBeInTheDocument();
    expect(streamSignal?.aborted).toBe(true);

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Lancer la rédaction" }));
    await waitFor(() => expect(paths().some((path) => path.endsWith("/resume"))).toBe(true));
  });
});
