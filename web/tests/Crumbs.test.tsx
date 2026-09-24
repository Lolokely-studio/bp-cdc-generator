import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Crumbs } from "@/components/Crumbs";

describe("le fil d'ariane", () => {
  it("lie les maillons précédents et pas le dernier", () => {
    render(<Crumbs items={[
      { label: "Mes projets", href: "/projets" },
      { label: "CoachDom", href: "/projets/p-1" },
      { label: "Documents" },
    ]} />);
    expect(screen.getByRole("link", { name: "Mes projets" })).toHaveAttribute("href", "/projets");
    expect(screen.getByRole("link", { name: "CoachDom" })).toHaveAttribute("href", "/projets/p-1");
    expect(screen.queryByRole("link", { name: "Documents" })).toBeNull();
    expect(screen.getByText("Documents")).toHaveClass("crumbs__here");
  });

  it("pose chaque maillon en enfant direct, comme le sélecteur l'exige", () => {
    // `.crumbs > :not(.crumbs__here)` masque les maillons précédents sous
    // 48 rem. Une enveloppe sans classe entre les deux masquerait tout, y
    // compris la position courante. jsdom n'applique pas le CSS : c'est la
    // forme du DOM qu'on verrouille ici.
    render(<Crumbs items={[
      { label: "Mes projets", href: "/projets" },
      { label: "Documents" },
    ]} />);
    const nav = document.querySelector(".crumbs")!;
    const children = [...nav.children];
    expect(children.map((el) => el.className)).toEqual(["", "crumbs__sep", "crumbs__here"]);
    expect(children[0].tagName).toBe("A");
  });

  it("rend une position seule sans aucun lien", () => {
    render(<Crumbs items={[{ label: "Mes projets" }]} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Mes projets")).toHaveClass("crumbs__here");
  });
});
