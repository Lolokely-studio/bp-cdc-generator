import type { Fact, FactDefinition } from "@/lib/contracts";

export type Badge = { label: "Vous" | "Déduit" | "Inconnu"; className: "user" | "inferred" | "unknown" };

export function badgeFor(fact: Fact): Badge {
  // Une valeur nulle vient toujours d'un « je ne sais pas » : l'afficher
  // comme une réponse de l'utilisateur laisserait croire qu'il a répondu.
  if (fact.value === null || fact.value === undefined) return { label: "Inconnu", className: "unknown" };
  return fact.source === "user"
    ? { label: "Vous", className: "user" }
    : { label: "Déduit", className: "inferred" };
}

export function humanize(option: string): string {
  const spaced = option.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const euros = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const plain = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });

export function formatFactValue(definition: FactDefinition | undefined, value: unknown): string {
  if (value === null || value === undefined) return "Je ne sais pas";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  if (typeof value === "number") {
    switch (definition?.type) {
      case "montant":
        return euros.format(value);
      case "pourcentage":
        // Même convention que `_rate` côté backend : sous 1, c'est une
        // fraction ; au-dessus, l'utilisateur a tapé « 35 ».
        return `${plain.format(Math.abs(value) <= 1 ? value * 100 : value)} %`;
      default:
        return definition?.unite ? `${plain.format(value)} ${definition.unite}` : plain.format(value);
    }
  }
  if (definition?.type === "choix" && typeof value === "string") return humanize(value);
  return String(value);
}
