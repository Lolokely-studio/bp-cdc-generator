import type { Inconsistency } from "@/lib/contracts";

export type Choice = { decision: "corriger" | "ignorer" | null; consigne: string };
export type Ruling =
  | { index: number; decision: "corriger"; consigne: string | null }
  | { index: number; decision: "ignorer" };

/** Met les choix de l'écran dans la forme qu'`arbitrate` attend.
 *
 * Une consigne vide est envoyée à `null` : le backend applique alors la
 * proposition du contrôle de cohérence. Sans proposition ET sans consigne,
 * il n'y aurait rien à corriger — on le demande plutôt que de laisser partir
 * un arbitrage vide. */
export function buildRulings(
  inconsistencies: Inconsistency[],
  choices: Choice[],
): { rulings: Ruling[]; error: string | null } {
  for (let index = 0; index < inconsistencies.length; index++) {
    const choice = choices[index];
    if (!choice || choice.decision === null) {
      return { rulings: [], error: "Choisissez une suite pour chaque incohérence." };
    }
    if (choice.decision === "corriger" && !choice.consigne.trim() && !inconsistencies[index].proposal) {
      return {
        rulings: [],
        error: `Dites comment corriger l'incohérence ${index + 1}, ou choisissez « Ignorer ».`,
      };
    }
  }
  const rulings = inconsistencies.map((_, index): Ruling => {
    const choice = choices[index];
    return choice.decision === "corriger"
      ? { index, decision: "corriger", consigne: choice.consigne.trim() || null }
      : { index, decision: "ignorer" };
  });
  return { rulings, error: null };
}
