import { ApiError, api } from "@/lib/api";
import type { ProjectState } from "@/lib/contracts";

export type AnswerOutcome = "envoyee" | "perimee";

type Deps = {
  answer: (projectId: string, interactionId: string, reponse: unknown) => Promise<{ rejoue: boolean }>;
  state: (projectId: string) => Promise<ProjectState>;
  sleep: (ms: number) => Promise<void>;
};

const defaults: Deps = {
  answer: (projectId, interactionId, reponse) => api.answer(projectId, interactionId, reponse),
  state: (projectId) => api.state(projectId),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

const MAX_ATTEMPTS = 5;

/** Envoie une réponse en tenant le contrat du §6.2.
 *
 * `rejoue: false` : l'étape avait déjà reçu sa réponse — double clic, second
 * onglet. Rien n'est perdu, l'écran doit simplement relire l'état.
 *
 * `409 run_deja_en_cours` : une reprise avance sur le même fil, et CETTE
 * réponse n'a pas été prise. On attend, on relit l'état, et on renvoie si
 * l'interaction attendue est toujours la même ; sinon la réponse est
 * périmée, et l'utilisateur verra la nouvelle étape. */
export async function sendAnswer(
  projectId: string,
  interactionId: string,
  reponse: unknown,
  deps: Deps = defaults,
): Promise<AnswerOutcome> {
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      const result = await deps.answer(projectId, interactionId, reponse);
      return result.rejoue ? "envoyee" : "perimee";
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "run_deja_en_cours") throw error;
      if (attempt === MAX_ATTEMPTS) throw error;
      await deps.sleep(1000 * attempt);
      const current = await deps.state(projectId);
      if (current.interaction?.id !== interactionId) return "perimee";
    }
  }
  throw new ApiError(409, "run_deja_en_cours", null);
}
