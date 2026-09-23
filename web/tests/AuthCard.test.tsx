import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthCard } from "@/components/AuthCard";

describe("la carte d'entrée", () => {
  it("porte la marque, le contenu et la note", () => {
    render(<AuthCard footer="Une note."><p>Le contenu.</p></AuthCard>);
    expect(screen.getByRole("link", { name: "Esquisse" })).toHaveAttribute("href", "/projets");
    expect(screen.getByText("Le contenu.")).toBeInTheDocument();
    expect(screen.getByText("Une note.")).toBeInTheDocument();
  });

  it("se passe de note", () => {
    render(<AuthCard><p>Seul.</p></AuthCard>);
    expect(document.querySelector(".auth__foot")).toBeNull();
  });
});
