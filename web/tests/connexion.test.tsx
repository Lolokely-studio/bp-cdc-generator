import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn(), push: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const push = router.push;

import ConnexionPage from "@/app/connexion/page";
import { getToken, pendingEmail } from "@/lib/api";

function reply(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

async function fill(email: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Adresse e-mail"), email);
  await user.type(screen.getByLabelText("Mot de passe"), password);
  return user;
}

beforeEach(() => push.mockReset());

describe("la page de connexion", () => {
  it("pose le jeton et mène aux projets", async () => {
    vi.stubGlobal("fetch", reply(200, { jeton: "j-123" }));
    render(<ConnexionPage />);
    const user = await fill("lucie@exemple.fr", "motdepasse123");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projets"));
    expect(getToken()).toBe("j-123");
  });

  it("mène à l'écran d'attente sur un compte inactif, sans jeton", async () => {
    vi.stubGlobal("fetch", reply(403, { detail: "compte_inactif" }));
    render(<ConnexionPage />);
    const user = await fill("lucie@exemple.fr", "motdepasse123");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/compte/en-attente"));
    expect(getToken()).toBeNull();
    expect(pendingEmail()).toBe("lucie@exemple.fr");
  });

  it("affiche le refus d'un mot de passe", async () => {
    vi.stubGlobal("fetch", reply(401, { detail: "identifiants_invalides" }));
    render(<ConnexionPage />);
    const user = await fill("lucie@exemple.fr", "mauvais-mot");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Adresse ou mot de passe incorrect.");
    expect(push).not.toHaveBeenCalled();
  });

  it("inscrit, puis mène à l'écran d'attente sans poser de jeton", async () => {
    const fetchMock = reply(201, { compte_actif: false, message: "Compte créé." });
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnexionPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Créer un compte" }));
    await fill("lucie@exemple.fr", "motdepasse123");
    await user.click(screen.getByRole("button", { name: "Demander un accès" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/compte/en-attente"));
    expect(getToken()).toBeNull();
    expect(String((fetchMock.mock.calls[0] as unknown as [string])[0])).toMatch(/\/auth\/register$/);
  });

  it("refuse un mot de passe trop court à l'inscription, sans appeler l'API", async () => {
    const fetchMock = reply(201, {});
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnexionPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Créer un compte" }));
    await fill("lucie@exemple.fr", "court");
    await user.click(screen.getByRole("button", { name: "Demander un accès" }));
    expect(await screen.findByRole("alert"))
      .toHaveTextContent("Le mot de passe doit faire au moins 10 caractères.");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
