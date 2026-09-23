import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MissingData } from "@/components/MissingData";
import type { Section } from "@/lib/contracts";
import { catalogue } from "./fixtures";

const section: Section = {
  section_id: "perimetre", document: "cdc", ordre: 1, statut: "done", note: 8, revisions: 1,
  blocks: [{ kind: "placeholder", label: "Apport des fondateurs" }],
};

describe("MissingData", () => {
  it("nomme chaque trou et la section où il se trouve", () => {
    render(<MissingData sections={[section]} catalogue={catalogue} />);
    expect(screen.getByText("Apport des fondateurs").tagName).toBe("MARK");
    expect(screen.getByText("Cahier des charges, Périmètre")).toBeInTheDocument();
  });

  it("le dit quand il n'en reste aucun", () => {
    render(<MissingData sections={[{ ...section, blocks: [] }]} catalogue={catalogue} />);
    expect(screen.getByText("Aucune : rien ne manque dans ce qui a été rédigé.")).toBeInTheDocument();
  });
});
