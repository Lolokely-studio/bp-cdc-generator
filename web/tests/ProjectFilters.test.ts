import { describe, expect, it } from "vitest";
import { filterProjects } from "@/components/ProjectFilters";
import { summary } from "./fixtures";

const projets = [
  summary({ id: "a", nom: "Atelier de torréfaction Noria", run_status: "waiting" }),
  summary({ id: "b", nom: "Halle bio de Vernon", run_status: "done" }),
  summary({ id: "c", nom: "Crèche Éléonore", run_status: "done" }),
];

describe("le filtre des projets", () => {
  it("ne retire rien quand rien n'est demandé", () => {
    expect(filterProjects(projets, { query: "", status: "" })).toHaveLength(3);
  });

  it("cherche sans tenir compte de la casse ni des accents", () => {
    // « Éléonore » se tape souvent « eleonore » : un filtre qui ne le
    // trouve pas passe pour cassé.
    expect(filterProjects(projets, { query: "eleonore", status: "" }).map((p) => p.id))
      .toEqual(["c"]);
    expect(filterProjects(projets, { query: "NORIA", status: "" }).map((p) => p.id))
      .toEqual(["a"]);
  });

  it("filtre sur l'état", () => {
    expect(filterProjects(projets, { query: "", status: "done" }).map((p) => p.id))
      .toEqual(["b", "c"]);
  });

  it("combine les deux", () => {
    expect(filterProjects(projets, { query: "halle", status: "done" }).map((p) => p.id))
      .toEqual(["b"]);
    expect(filterProjects(projets, { query: "halle", status: "waiting" })).toEqual([]);
  });
});
