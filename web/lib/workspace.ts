import { Interaction, type ProjectState } from "@/lib/contracts";

export type LiveError = { code: string; message: string; reprenable: boolean };

/** Ce que l'écran de rédaction affiche : le dernier `/state`, plus ce que le
 * flux apporte entre deux lectures — le texte qui s'écrit, la note, ce qui
 * reste à réécrire, l'erreur d'un run. */
export type Live = {
  state: ProjectState | null;
  draft: string;
  score: { score: number; problems: string[] } | null;
  rework: number | null;
  error: LiveError | null;
  // L'interaction à laquelle on vient de répondre. Tant que la ligne dit
  // encore `waiting` OU `running`, `/state` peut la montrer : `POST /answer`
  // écrit `running` avant que le graphe ait consommé l'interruption
  // (`app.runs.runner.advance`), et `/state` relu juste après peut donc
  // rendre l'une ou l'autre AVEC la même interaction. La reposer ferait
  // répondre deux fois.
  answered: string | null;
};

export const initialLive: Live = {
  state: null, draft: "", score: null, rework: null, error: null, answered: null,
};

export type LiveAction =
  | { type: "state"; state: ProjectState }
  | { type: "event"; name: string; data: Record<string, unknown> }
  | { type: "answered"; interactionId: string };

/** Les événements qui rendent l'écran périmé : après eux, on relit `/state`. */
export const RESYNC_ON = new Set(["interaction", "section_saved", "done", "error"]);

// Un projet relu en échec sans que le flux ait dit pourquoi : après un
// rechargement de page, par exemple.
const DEFAULT_FAILURE: LiveError = { code: "run_en_echec", message: "", reprenable: true };

export function liveReducer(live: Live, action: LiveAction): Live {
  switch (action.type) {
    case "state": {
      const status = action.state.projet.run_status;
      if (live.answered && (status === "waiting" || status === "running")
          && action.state.interaction?.id === live.answered) {
        // La réponse n'est pas encore consommée : on garde l'écran de
        // rédaction. Seuls `waiting` et `running` sont traités ainsi — un
        // `failed` (ou un `done`) doit se voir, même s'il porte encore la
        // même interaction.
        return {
          ...live,
          state: { ...action.state, interaction: null, projet: { ...action.state.projet, run_status: "running" } },
        };
      }
      return {
        ...live,
        answered: null,
        state: action.state,
        // Une interaction affiche son propre contenu : le texte du flux,
        // lui, appartenait à l'étape d'avant.
        draft: action.state.interaction ? "" : live.draft,
        error: status === "failed" ? live.error ?? DEFAULT_FAILURE : null,
        rework: status === "running" || status === "idle" ? live.rework : null,
      };
    }
    case "answered":
      if (!live.state) return live;
      return {
        ...live,
        answered: action.interactionId,
        draft: "",
        score: null,
        state: { ...live.state, interaction: null, projet: { ...live.state.projet, run_status: "running" } },
      };
    case "event":
      return onEvent(live, action.name, action.data);
  }
}

function onEvent(live: Live, name: string, data: Record<string, unknown>): Live {
  switch (name) {
    case "token":
      return typeof data.text === "string" ? { ...live, draft: live.draft + data.text } : live;
    case "section_restart":
      // Le flux repart entier sur un autre fournisseur (§5.2) : ce qui
      // s'affichait était un faux départ — texte ET verdict de l'essai
      // abandonné, sinon la note affichée jugerait un texte qui n'existe
      // plus.
      return { ...live, draft: "", score: null };
    case "score":
      return {
        ...live,
        score: {
          score: typeof data.score === "number" ? data.score : 0,
          problems: Array.isArray(data.problems) ? data.problems.map(String) : [],
        },
      };
    case "section_saved":
      return { ...live, draft: "", score: null };
    case "progress":
      return { ...live, rework: typeof data.reecriture === "number" ? data.reecriture : null };
    case "interaction": {
      const parsed = Interaction.safeParse(data);
      if (!parsed.success || !live.state || parsed.data.id === live.answered) return live;
      return {
        ...live,
        // Une interaction NEUVE : la garde posée par la dernière réponse
        // n'a plus rien à protéger.
        answered: null,
        draft: "",
        state: { ...live.state, interaction: parsed.data, projet: { ...live.state.projet, run_status: "waiting" } },
      };
    }
    case "error":
      // L'avis de retard n'est pas une panne du run : le flux se rouvrira
      // et relira l'état tout seul.
      if (data.code === "flux_en_retard") return live;
      return {
        ...live,
        error: {
          code: typeof data.code === "string" ? data.code : "erreur",
          message: typeof data.message === "string" ? data.message : "",
          reprenable: data.reprenable !== false,
        },
      };
    case "done":
      if (!live.state) return live;
      return { ...live, draft: "", rework: null, state: { ...live.state, projet: { ...live.state.projet, run_status: "done" } } };
    default:
      return live;
  }
}
