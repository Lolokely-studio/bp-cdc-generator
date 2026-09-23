import { ApiError } from "@/lib/api";

const NETWORK = "Le serveur n'a pas répondu. Réessayez dans un instant.";

/** Jamais « adresse inconnue » : l'API ne le dit pas, l'écran non plus. */
export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "identifiants_invalides": return "Adresse ou mot de passe incorrect.";
      case "trop_de_tentatives": return "Trop de tentatives. Réessayez dans un quart d'heure.";
      case "requete_invalide": return "Vérifiez l'adresse, et un mot de passe d'au moins 10 caractères.";
    }
  }
  return NETWORK;
}

export function reopenErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "reouverture_impossible": return "La rédaction doit être terminée pour rouvrir une section.";
      case "reecriture_deja_lancee":
        return "La réécriture est déjà en route : suivez-la sur l'écran de rédaction.";
      case "export_deja_en_cours": return "Un export est en cours : attendez qu'il se termine.";
      case "section_ambigue":
        return "Cette section existe dans les deux documents : la rouvrir n'est pas encore possible.";
      case "section_introuvable": return "Cette section n'existe plus.";
      case "projet_introuvable": return "Ce projet n'existe pas.";
    }
  }
  return NETWORK;
}

export function initials(email: string): string {
  const parts = email.split("@")[0].split(/[._-]+/).filter(Boolean);
  const letters = parts.slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  return letters || "?";
}
