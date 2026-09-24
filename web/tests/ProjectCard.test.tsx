import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProjectCard } from "@/components/ProjectCard";
import { summary } from "./fixtures";

const now = new Date("2026-09-22T10:00:00Z");

describe("ProjectCard", () => {
  it("mène un projet terminé à ses exports", () => {
    render(<ProjectCard now={now} project={summary({ run_status: "done", sections_faites: 2, sections_total: 2 })} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/projets/p-1/exports");
    expect(screen.getByText("Terminé")).toHaveClass("tag", "tag--ok");
  });

  it("mène un projet en cours à la rédaction, avec sa progression", () => {
    render(<ProjectCard now={now} project={summary({ run_status: "waiting", sections_faites: 3, sections_total: 14 })} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/projets/p-1");
    expect(screen.getByText("À vous de répondre")).toHaveClass("tag--wait");
    expect(screen.getByText("modifié il y a 2 heures")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "3");
  });

  it("rend une encoche par section, remplie pour celles qui sont faites", () => {
    render(<ProjectCard now={now} project={summary({ sections_faites: 3, sections_total: 12 })} />);
    const barre = screen.getByRole("progressbar");
    expect(barre).toHaveAttribute("aria-valuemax", "12");
    expect(barre.querySelectorAll("i")).toHaveLength(12);
    expect(barre.querySelectorAll("i.is-done")).toHaveLength(3);
  });

  it("ne rend aucune encoche quand le plan n'est pas encore connu", () => {
    render(<ProjectCard now={now} project={summary({ sections_faites: 0, sections_total: 0 })} />);
    expect(screen.getByRole("progressbar").querySelectorAll("i")).toHaveLength(0);
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});
