import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Un routeur STABLE : `AuthGate` dépend de lui dans son effet, et un objet
// neuf à chaque rendu relancerait l'effet à chaque rendu.
const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const replace = router.replace;

import { AuthGate } from "@/components/AuthGate";
import { setToken } from "@/lib/api";

function reply(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

beforeEach(() => replace.mockReset());

describe("AuthGate", () => {
  it("renvoie à la connexion sans jeton, sans appeler l'API", async () => {
    const fetchMock = reply(200, {});
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthGate><p>privé</p></AuthGate>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/connexion"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("privé")).toBeNull();
  });

  it("rend la page et la barre avec une session valide", async () => {
    vi.stubGlobal("fetch", reply(200, { email: "lucie.renard@exemple.fr", compte_actif: true }));
    setToken("abc");
    render(<AuthGate><p>privé</p></AuthGate>);
    expect(await screen.findByText("privé")).toBeInTheDocument();
    expect(screen.getByTitle("lucie.renard@exemple.fr")).toHaveTextContent("LR");
  });

  it("renvoie à l'écran d'attente sur un compte désactivé", async () => {
    vi.stubGlobal("fetch", reply(403, { detail: "compte_inactif" }));
    setToken("abc");
    render(<AuthGate><p>privé</p></AuthGate>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/compte/en-attente"));
  });

  it("renvoie à la connexion sur une session expirée", async () => {
    vi.stubGlobal("fetch", reply(401, { detail: "session_invalide" }));
    setToken("abc");
    render(<AuthGate><p>privé</p></AuthGate>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/connexion"));
    // Pas l'écran de panne en même temps : un 401 avec jeton est un cas
    // prévu, pas une erreur inconnue.
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
