import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { authErrorMessage, initials, reopenErrorMessage } from "@/lib/messages";

describe("authErrorMessage", () => {
  it("donne un message par code connu", () => {
    expect(authErrorMessage(new ApiError(401, "identifiants_invalides", null)))
      .toBe("Adresse ou mot de passe incorrect.");
    expect(authErrorMessage(new ApiError(429, "trop_de_tentatives", null)))
      .toBe("Trop de tentatives. Réessayez dans un quart d'heure.");
    expect(authErrorMessage(new ApiError(422, "requete_invalide", null)))
      .toBe("Vérifiez l'adresse, et un mot de passe d'au moins 10 caractères.");
  });

  it("retombe sur un message de réseau pour le reste", () => {
    expect(authErrorMessage(new TypeError("Failed to fetch")))
      .toBe("Le serveur n'a pas répondu. Réessayez dans un instant.");
  });
});

describe("reopenErrorMessage", () => {
  it("explique chaque refus", () => {
    expect(reopenErrorMessage(new ApiError(409, "reouverture_impossible", null)))
      .toBe("La rédaction doit être terminée pour rouvrir une section.");
    expect(reopenErrorMessage(new ApiError(409, "export_deja_en_cours", null)))
      .toBe("Un export est en cours : attendez qu'il se termine.");
    expect(reopenErrorMessage(new ApiError(400, "section_ambigue", null)))
      .toBe("Cette section existe dans les deux documents : la rouvrir n'est pas encore possible.");
  });
});

describe("initials", () => {
  it("prend la première lettre des deux premiers morceaux de l'adresse", () => {
    expect(initials("lucie.renard@exemple.fr")).toBe("LR");
    expect(initials("brice@exemple.fr")).toBe("B");
    expect(initials("@exemple.fr")).toBe("?");
    expect(initials("marie.claire.dupont@exemple.fr")).toBe("MC");
  });
});
