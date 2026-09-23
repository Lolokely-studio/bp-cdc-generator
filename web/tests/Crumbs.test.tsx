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

  it("rend une position seule sans aucun lien", () => {
    render(<Crumbs items={[{ label: "Mes projets" }]} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Mes projets")).toHaveClass("crumbs__here");
  });
});
