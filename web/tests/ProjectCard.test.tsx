import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProjectCard } from "@/components/ProjectCard";
import { summary } from "./fixtures";

const now = new Date("2026-09-22T10:00:00Z");

describe("ProjectCard", () => {
  it("mène un projet terminé à ses exports", () => {
    render(<ProjectCard now={now} project={summary({ run_status: "done", sections_faites: 2, sections_total: 2 })} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/projets/p-1/exports");
    expect(screen.getByText("Terminé")).toHaveClass("m-tag", "done");
  });

  it("mène un projet en cours à la rédaction, avec sa progression", () => {
    render(<ProjectCard now={now} project={summary({ run_status: "waiting", sections_faites: 3, sections_total: 14 })} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/projets/p-1");
    expect(screen.getByText("À vous de répondre")).not.toHaveClass("done");
    expect(screen.getByText("3 sections faites sur 14, modifié il y a 2 heures")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "3");
  });

  it("remplit la barre de progression à hauteur du nombre de sections faites", () => {
    render(<ProjectCard now={now} project={summary({ sections_faites: 3, sections_total: 12 })} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuemax", "12");
    expect(bar.querySelector("i")).toHaveStyle({ width: "25%" });
  });

  it("ne divise pas par zéro quand le plan n'est pas encore connu", () => {
    render(<ProjectCard now={now} project={summary({ sections_faites: 0, sections_total: 0 })} />);
    const bar = screen.getByRole("progressbar");
    expect(bar.querySelector("i")).toHaveStyle({ width: "0%" });
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});
