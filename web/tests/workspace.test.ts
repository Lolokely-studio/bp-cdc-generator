import { describe, expect, it } from "vitest";
import { initialLive, liveReducer, type Live } from "@/lib/workspace";
import { projectState, summary } from "./fixtures";

function withState(overrides = {}): Live {
  return liveReducer(initialLive, { type: "state", state: projectState(overrides) });
}

const event = (name: string, data: Record<string, unknown> = {}) => ({ type: "event" as const, name, data });

describe("liveReducer", () => {
  it("accumule les fragments et vide sur un redémarrage de flux", () => {
    let live = withState();
    live = liveReducer(live, event("token", { text: "Bon" }));
    live = liveReducer(live, event("token", { text: "jour" }));
    expect(live.draft).toBe("Bonjour");
    live = liveReducer(live, event("score", { score: 4, problems: ["trop vague"] }));
    live = liveReducer(live, event("section_restart", { document: "cdc", section_id: "perimetre" }));
    expect(live.draft).toBe("");
    // La note portait sur l'essai abandonné : elle ne doit pas juger le
    // texte qui repart de zéro.
    expect(live.score).toBeNull();
  });

  it("garde la note de l'auto-critique jusqu'à l'enregistrement", () => {
    let live = liveReducer(withState(), event("token", { text: "x" }));
    live = liveReducer(live, event("score", { score: 6, problems: ["trop court"] }));
    expect(live.score).toEqual({ score: 6, problems: ["trop court"] });
    live = liveReducer(live, event("section_saved", {}));
    expect(live.score).toBeNull();
    expect(live.draft).toBe("");
  });

  it("montre une interaction reçue par le flux, sans attendre /state", () => {
    const live = liveReducer(withState(), event("interaction", {
      id: "i-1", kind: "questions", questions: [{ fact_id: "budget_projet", question: "Quel budget ?" }],
    }));
    expect(live.state?.interaction?.id).toBe("i-1");
    expect(live.state?.projet.run_status).toBe("waiting");
  });

  it("ignore une interaction mal formée", () => {
    const before = withState();
    expect(liveReducer(before, event("interaction", { id: "i-1", kind: "inconnue" }))).toBe(before);
  });

  it("retient le nombre de sections restant à réécrire, et l'oublie hors réécriture", () => {
    let live = liveReducer(withState(), event("progress", { cursor: 3, total: 14, reecriture: 2 }));
    expect(live.rework).toBe(2);
    live = liveReducer(live, event("progress", { cursor: 4, total: 14 }));
    expect(live.rework).toBeNull();
  });

  it("porte l'erreur d'un run, mais pas l'avis d'un flux en retard", () => {
    let live = liveReducer(withState(), event("error", { code: "flux_en_retard", message: "x", reprenable: true }));
    expect(live.error).toBeNull();
    live = liveReducer(live, event("error", { code: "run_en_echec", message: "quota", reprenable: true }));
    expect(live.error).toEqual({ code: "run_en_echec", message: "quota", reprenable: true });
  });

  it("efface l'erreur quand l'état relu n'est plus en échec", () => {
    let live = liveReducer(withState(), event("error", { code: "run_en_echec", message: "x", reprenable: true }));
    live = liveReducer(live, { type: "state", state: projectState({ projet: summary({ run_status: "running" }) }) });
    expect(live.error).toBeNull();
  });

  it("donne une erreur par défaut à un projet relu en échec", () => {
    const live = withState({ projet: summary({ run_status: "failed" }) });
    expect(live.error).toMatchObject({ code: "run_en_echec", reprenable: true });
  });

  it("passe en rédaction dès qu'une réponse est partie, et ne la repose pas", () => {
    const review = { id: "i-1", kind: "review" as const, section: "cdc.perimetre", score: 7, problems: [], blocks: [] };
    const waiting = { projet: summary({ run_status: "waiting" }), interaction: review };
    let live = liveReducer(withState(waiting), { type: "answered", interactionId: "i-1" });
    expect(live.state?.interaction).toBeNull();
    expect(live.state?.projet.run_status).toBe("running");

    // `/state` relu trop tôt montre encore l'interaction : on ne la repose pas.
    live = liveReducer(live, { type: "state", state: projectState(waiting) });
    expect(live.state?.interaction).toBeNull();
    live = liveReducer(live, event("interaction", review));
    expect(live.state?.interaction).toBeNull();

    // Une interaction NOUVELLE s'affiche, et la garde tombe.
    live = liveReducer(live, { type: "state", state: projectState({ ...waiting, interaction: { ...review, id: "i-2" } }) });
    expect(live.state?.interaction?.id).toBe("i-2");
    expect(live.answered).toBeNull();

    // Réponse à cette deuxième interaction, puis une interaction ENCORE plus
    // récente arrive directement par le flux (pas par /state) : la garde
    // tombe aussi par ce chemin-là.
    live = liveReducer(live, { type: "answered", interactionId: "i-2" });
    expect(live.answered).toBe("i-2");
    live = liveReducer(live, event("interaction", { ...review, id: "i-3" }));
    expect(live.state?.interaction?.id).toBe("i-3");
    expect(live.answered).toBeNull();
  });

  it("garde la garde tant que /state rend `running` avec la même interaction", () => {
    // `POST /answer` écrit `running` avant que le graphe ait consommé
    // l'interruption (`app.runs.runner.advance`) : `/state` relu juste après
    // peut donc rendre `running`, pas seulement `waiting`, AVEC la même
    // interaction. La reposer ferait répondre deux fois (constat 2 de la
    // revue finale).
    const review = { id: "i-1", kind: "review" as const, section: "cdc.perimetre", score: 7, problems: [], blocks: [] };
    let live = liveReducer(withState({ projet: summary({ run_status: "waiting" }), interaction: review }),
      { type: "answered", interactionId: "i-1" });
    live = liveReducer(live, { type: "state", state: projectState({ projet: summary({ run_status: "running" }), interaction: review }) });
    expect(live.state?.interaction).toBeNull();
    expect(live.state?.projet.run_status).toBe("running");
  });

  it("montre l'échec d'un run même s'il porte encore l'interaction répondue", () => {
    const review = { id: "i-1", kind: "review" as const, section: "cdc.perimetre", score: 7, problems: [], blocks: [] };
    let live = liveReducer(withState({ projet: summary({ run_status: "waiting" }), interaction: review }),
      { type: "answered", interactionId: "i-1" });
    live = liveReducer(live, { type: "state", state: projectState({ projet: summary({ run_status: "failed" }), interaction: review }) });
    expect(live.state?.projet.run_status).toBe("failed");
  });

  it("marque le projet terminé sur l'événement de fin", () => {
    const live = liveReducer(liveReducer(withState(), event("token", { text: "x" })), event("done"));
    expect(live.state?.projet.run_status).toBe("done");
    expect(live.draft).toBe("");
  });
});
