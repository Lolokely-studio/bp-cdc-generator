import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExportFiles } from "@/components/ExportFiles";
import type { ExportFile } from "@/lib/contracts";

const file = (overrides: Partial<ExportFile> = {}): ExportFile => ({
  document: "cdc", format: "docx", brouillon: false, fidele: true,
  lien: "https://stockage.test/cdc.docx", cree_le: "2026-09-22T09:00:00Z", ...overrides,
});

describe("ExportFiles", () => {
  it("groupe le Word et le PDF par document", () => {
    render(<ExportFiles files={[
      file(), file({ format: "pdf", lien: "https://stockage.test/cdc.pdf" }),
      file({ document: "bp", lien: "https://stockage.test/bp.docx" }),
    ]} />);
    expect(screen.getByText("Cahier des charges")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Télécharger le Word" })).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Télécharger le PDF" }))
      .toHaveAttribute("href", "https://stockage.test/cdc.pdf");
  });

  it("dit qu'un PDF de secours n'a pas la mise en page du Word", () => {
    render(<ExportFiles files={[file({ format: "pdf", fidele: false })]} />);
    expect(screen.getByText(/convertisseur de secours/)).toHaveTextContent("le Word, qui fait foi");
  });

  it("dit pourquoi un document est un brouillon", () => {
    render(<ExportFiles files={[file({ brouillon: true })]} />);
    expect(screen.getByText("Brouillon")).toBeInTheDocument();
    expect(screen.getByText(/passée sans validation/)).toBeInTheDocument();
  });

  it("n'affiche rien sans fichier", () => {
    const { container } = render(<ExportFiles files={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
