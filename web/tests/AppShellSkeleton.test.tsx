import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppShellSkeleton } from "@/components/AppShellSkeleton";

describe("le seuil de l'application", () => {
  it("se tait d'abord, pour ne pas clignoter", () => {
    // `/me` répond en général en quelques dizaines de millisecondes. Montrer
    // puis retirer un squelette en si peu de temps ne ferait que clignoter,
    // ce qui est pire que ne rien montrer. Même discipline que `WakeGate`.
    const { container } = render(<AppShellSkeleton />);
    expect(container).toBeEmptyDOMElement();
  });

  it("pose la barre haute quand l'attente dure", () => {
    render(<AppShellSkeleton quietMs={0} />);
    // La marque est connue d'avance : elle est posée, pas esquissée. C'est
    // ce qui l'empêche d'apparaître après coup.
    expect(screen.getByText("Esquisse")).toBeInTheDocument();
    expect(document.querySelectorAll(".topbar .bone")).toHaveLength(2);
  });

  it("ne devine aucun contenu", () => {
    // Cette garde enveloppe toutes les pages, qui n'ont pas la même forme :
    // grille de fiches, trois colonnes, deux panneaux. En esquisser une
    // ferait sauter la page deux fois — quand ce squelette cède la place,
    // puis quand celui de l'écran s'installe.
    const { container } = render(<AppShellSkeleton quietMs={0} />);
    expect(container.querySelector("main")).toBeNull();
    expect(container.querySelector(".page")).toBeNull();
  });

  it("annonce l'attente une fois, et cache ses formes", () => {
    render(<AppShellSkeleton quietMs={0} />);
    const statuts = screen.getAllByRole("status");
    expect(statuts).toHaveLength(1);
    expect(statuts[0]).toHaveTextContent("Ouverture de votre espace.");
    for (const bone of document.querySelectorAll(".bone")) {
      expect(bone).toHaveAttribute("aria-hidden", "true");
    }
  });
});
