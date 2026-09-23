import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ReopenForm } from "@/components/ReopenForm";
import { catalogue, projectState, summary } from "./fixtures";

const done = projectState({ projet: summary({ run_status: "done" }) });

function show(state = done, disabled = false) {
  return render(<ReopenForm projectId="p-1" state={state} catalogue={catalogue} disabled={disabled} />);
}

beforeEach(() => router.push.mockReset());

describe("ReopenForm", () => {
  it("envoie l'identifiant de section sans son document, puis ouvre la rédaction", async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ sections: ["cdc.perimetre"], touchees: 1, run_status: "running" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    show();

    await user.selectOptions(screen.getByLabelText("Section"), "cdc.perimetre");
    await user.type(screen.getByLabelText("Que faut-il changer ?"), "Parler aussi des coachs");
    await user.click(screen.getByRole("button", { name: "Rouvrir et réécrire" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/projets/p-1"));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/projects\/p-1\/sections\/perimetre\/reopen$/);
    expect(JSON.parse(String(init.body))).toEqual({ consigne: "Parler aussi des coachs" });
  });

  it("refuse sans section choisie, sans appeler l'API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    show();
    await userEvent.setup().click(screen.getByRole("button", { name: "Rouvrir et réécrire" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choisissez une section.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("attend la fin de la rédaction", () => {
    show(projectState({ projet: summary({ run_status: "waiting" }) }));
    expect(screen.getByRole("button", { name: "Rouvrir et réécrire" })).toBeDisabled();
    expect(screen.getByText("Possible une fois la rédaction terminée.")).toBeInTheDocument();
  });

  it("traduit le refus de l'API", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: { code: "export_deja_en_cours" } }), { status: 409 })));
    const user = userEvent.setup();
    show();
    await user.selectOptions(screen.getByLabelText("Section"), "cdc.perimetre");
    await user.click(screen.getByRole("button", { name: "Rouvrir et réécrire" }));
    expect(await screen.findByRole("alert"))
      .toHaveTextContent("Un export est en cours : attendez qu'il se termine.");
    expect(router.push).not.toHaveBeenCalled();
  });
});
