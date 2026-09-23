import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import {
  API_URL, ApiError, api, errorCode, getToken, request, setInactiveHandler, setToken,
  setUnauthorizedHandler,
} from "@/lib/api";

function reply(status: number, body: unknown) {
  return vi.fn(async () => new Response(
    body === undefined ? null : JSON.stringify(body),
    { status, headers: { "Content-Type": "application/json" } },
  ));
}

afterEach(() => {
  setUnauthorizedHandler(null);
  setInactiveHandler(null);
});

describe("errorCode", () => {
  it("lit les trois formes que FastAPI donne à `detail`", () => {
    expect(errorCode("compte_inactif")).toBe("compte_inactif");
    expect(errorCode({ code: "run_deja_en_cours" })).toBe("run_deja_en_cours");
    expect(errorCode([{ loc: ["body"], msg: "x" }])).toBe("requete_invalide");
    expect(errorCode(undefined)).toBe("erreur_inconnue");
  });
});

describe("request", () => {
  it("envoie le jeton en Bearer et le corps en JSON", async () => {
    const fetchMock = reply(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    setToken("abc");
    await request("/x", z.object({ ok: z.boolean() }), { method: "POST", body: { a: 1 } });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_URL}/x`);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer abc");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });

  it("n'envoie aucun en-tête d'autorisation sans jeton", async () => {
    const fetchMock = reply(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await request("/x", z.object({ ok: z.boolean() }));
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.headers).not.toHaveProperty("Authorization");
  });

  it("traduit une erreur en ApiError avec son code", async () => {
    vi.stubGlobal("fetch", reply(409, { detail: { code: "run_deja_en_cours" } }));
    const error = (await request("/x", z.unknown()).catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.code).toBe("run_deja_en_cours");
  });

  it("efface le jeton et prévient sur un 401 quand un jeton était posé", async () => {
    vi.stubGlobal("fetch", reply(401, { detail: "session_invalide" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setToken("perime");
    await expect(request("/x", z.unknown())).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("ne prévient pas sur un 401 sans jeton : c'est un mot de passe refusé", async () => {
    vi.stubGlobal("fetch", reply(401, { detail: "identifiants_invalides" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(request("/x", z.unknown())).rejects.toMatchObject({ code: "identifiants_invalides" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("prévient sur un 403 compte_inactif avec un jeton posé, sans l'effacer", async () => {
    vi.stubGlobal("fetch", reply(403, { detail: { code: "compte_inactif" } }));
    const handler = vi.fn();
    setInactiveHandler(handler);
    setToken("abc");
    await expect(request("/x", z.unknown())).rejects.toMatchObject({ code: "compte_inactif" });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(getToken()).toBe("abc");
  });

  it("ne prévient pas sur un 403 compte_inactif sans jeton : la connexion le traite déjà", async () => {
    vi.stubGlobal("fetch", reply(403, { detail: { code: "compte_inactif" } }));
    const handler = vi.fn();
    setInactiveHandler(handler);
    await expect(request("/x", z.unknown())).rejects.toMatchObject({ code: "compte_inactif" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("ne prévient pas sur un 403 d'un autre code, même avec un jeton posé", async () => {
    vi.stubGlobal("fetch", reply(403, { detail: { code: "acces_refuse" } }));
    const handler = vi.fn();
    setInactiveHandler(handler);
    setToken("abc");
    await expect(request("/x", z.unknown())).rejects.toMatchObject({ code: "acces_refuse" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("refuse une réponse qui ne suit pas son contrat", async () => {
    vi.stubGlobal("fetch", reply(200, { jeton: 42 }));
    await expect(api.login("a@b.fr", "x")).rejects.toThrow();
  });

  it("accepte un 204 sans corps", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    setToken("abc");
    await expect(api.logout()).resolves.toBeUndefined();
  });

  it("encode l'identifiant de section dans l'adresse de réouverture", async () => {
    const fetchMock = reply(200, { sections: [], touchees: 0, run_status: "running" });
    vi.stubGlobal("fetch", fetchMock);
    await api.reopen("p1", "a/b", null);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_URL}/projects/p1/sections/a%2Fb/reopen`);
    expect(init.body).toBe('{"consigne":null}');
  });
});
