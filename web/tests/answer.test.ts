import { describe, expect, it, vi } from "vitest";
import { sendAnswer } from "@/lib/answer";
import { ApiError } from "@/lib/api";
import { projectState } from "./fixtures";

const REVIEW = { id: "i-1", kind: "review" as const, section: "cdc.perimetre", score: 7, problems: [], blocks: [] };
const busy = () => new ApiError(409, "run_deja_en_cours", { code: "run_deja_en_cours" });

function deps(answers: Array<() => Promise<{ rejoue: boolean; run_status: string }>>, states = [projectState({ interaction: REVIEW })]) {
  return {
    answer: vi.fn(async () => (answers.shift() as () => Promise<{ rejoue: boolean; run_status: string }>)()),
    state: vi.fn(async () => states.shift() ?? projectState({ interaction: REVIEW })),
    sleep: vi.fn(async () => {}),
  };
}

describe("sendAnswer", () => {
  it("rend « envoyee » quand le run reprend", async () => {
    const d = deps([async () => ({ rejoue: true, run_status: "running" })]);
    await expect(sendAnswer("p-1", "i-1", { action: "accept" }, d)).resolves.toBe("envoyee");
    expect(d.answer).toHaveBeenCalledWith("p-1", "i-1", { action: "accept" });
  });

  it("rend « perimee » quand l'étape avait déjà reçu sa réponse", async () => {
    const d = deps([async () => ({ rejoue: false, run_status: "running" })]);
    await expect(sendAnswer("p-1", "i-1", {}, d)).resolves.toBe("perimee");
  });

  it("renvoie après un 409 si l'interaction est toujours la même", async () => {
    const d = deps([async () => { throw busy(); }, async () => ({ rejoue: true, run_status: "running" })]);
    await expect(sendAnswer("p-1", "i-1", {}, d)).resolves.toBe("envoyee");
    expect(d.answer).toHaveBeenCalledTimes(2);
    expect(d.sleep).toHaveBeenCalledTimes(1);
  });

  it("déclare la réponse périmée après un 409 si l'interaction a changé", async () => {
    const d = deps([async () => { throw busy(); }],
      [projectState({ interaction: { ...REVIEW, id: "i-2" } })]);
    await expect(sendAnswer("p-1", "i-1", {}, d)).resolves.toBe("perimee");
    expect(d.answer).toHaveBeenCalledTimes(1);
  });

  it("laisse passer toute autre erreur", async () => {
    const d = deps([async () => { throw new ApiError(422, "reponse_mal_formee", null); }]);
    await expect(sendAnswer("p-1", "i-1", {}, d)).rejects.toMatchObject({ code: "reponse_mal_formee" });
    expect(d.state).not.toHaveBeenCalled();
  });

  it("abandonne après cinq 409 d'affilée", async () => {
    const d = deps(Array.from({ length: 5 }, () => async () => { throw busy(); }));
    await expect(sendAnswer("p-1", "i-1", {}, d)).rejects.toMatchObject({ code: "run_deja_en_cours" });
    expect(d.answer).toHaveBeenCalledTimes(5);
  });
});
