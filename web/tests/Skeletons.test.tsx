import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExportsSkeleton } from "@/components/ExportsSkeleton";
import { ProjectsSkeleton } from "@/components/ProjectsSkeleton";
import { WorkspaceSkeleton } from "@/components/WorkspaceSkeleton";

/** Les trois écrans d'attente suivent la même règle : une annonce pour le
 * lecteur d'écran, et des formes qui ne disent rien. Un squelette bavard
 * ferait lire une douzaine de blocs vides à qui ne voit pas l'écran. */
const SQUELETTES = [
  ["les projets", ProjectsSkeleton, "Chargement de vos projets."],
  ["les documents", ExportsSkeleton, "Chargement de vos documents."],
  ["l'atelier", WorkspaceSkeleton, "Chargement du projet."],
] as const;

describe("les écrans d'attente", () => {
  it.each(SQUELETTES)("%s s'annonce une fois, et une seule", (_nom, Squelette, annonce) => {
    render(<Squelette />);
    const statuts = screen.getAllByRole("status");
    expect(statuts).toHaveLength(1);
    expect(statuts[0]).toHaveTextContent(annonce);
  });

  it.each(SQUELETTES)("%s cache ses formes au lecteur d'écran", (_nom, Squelette) => {
    const { container } = render(<Squelette />);
    const os = container.querySelectorAll(".bone");
    expect(os.length).toBeGreaterThan(3);
    for (const bone of os) {
      // Chaque forme vit sous un ancêtre `aria-hidden` : elles n'ont aucun
      // texte à lire, et les énumérer n'apprendrait rien.
      expect(bone.closest("[aria-hidden='true']")).not.toBeNull();
    }
  });

  it("l'atelier pose déjà ses trois colonnes", () => {
    // Le squelette reprend la mesure de l'écran qui vient : sans les trois
    // colonnes, la page sauterait au moment où il cède la place — ce qu'il
    // est précisément censé éviter.
    const { container } = render(<WorkspaceSkeleton />);
    expect(container.querySelector(".m-ws")).not.toBeNull();
    expect(container.querySelector(".m-col.plan")).not.toBeNull();
    expect(container.querySelector(".m-col.center")).not.toBeNull();
    // `m-col--facts`, pas `m-col facts` : `.facts` est un composant du socle,
    // et la colonne en héritait une grille que personne n'avait demandée.
    expect(container.querySelector(".m-col--facts")).not.toBeNull();
  });

  it("les documents posent déjà leurs deux fiches et leurs deux panneaux", () => {
    const { container } = render(<ExportsSkeleton />);
    expect(container.querySelectorAll(".docs .doc")).toHaveLength(2);
    expect(container.querySelectorAll(".split .panel")).toHaveLength(2);
  });
});
