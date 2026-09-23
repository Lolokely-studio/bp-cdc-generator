import type { DocumentKind, Section } from "@/lib/contracts";

// La même expression que `_EMBEDDED_MARKER` côté export : un modèle place
// parfois le marqueur au milieu d'une phrase au lieu d'un bloc à lui.
const EMBEDDED = /\[Donnée à compléter\s*:\s*([^\]]+?)\s*\]/g;

export function splitMarkers(text: string): { text: string; marker: boolean }[] {
  const parts: { text: string; marker: boolean }[] = [];
  let last = 0;
  for (const match of text.matchAll(EMBEDDED)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start), marker: false });
    parts.push({ text: match[0], marker: true });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), marker: false });
  return parts;
}

export type Missing = { label: string; document: DocumentKind; sectionId: string };

/** Les données à compléter d'un projet, dans l'ordre où elles apparaissent.
 *
 * Même contenu que l'annexe de l'export, mais calculé ici : l'écran les
 * montre avant que les documents soient produits. */
export function missingData(sections: Section[]): Missing[] {
  const found: Missing[] = [];
  const seen = new Set<string>();
  for (const section of sections) {
    const add = (label: string) => {
      const key = `${section.document}.${section.section_id}|${label}`;
      if (seen.has(key)) return;
      seen.add(key);
      found.push({ label, document: section.document, sectionId: section.section_id });
    };
    for (const block of section.blocks) {
      if (block.kind === "placeholder") add(block.label.trim());
      const texts =
        block.kind === "paragraph" ? [block.text]
        : block.kind === "list" ? block.items
        : block.kind === "table" ? block.rows.flat()
        : [];
      for (const text of texts) {
        for (const match of text.matchAll(EMBEDDED)) add(match[1].trim());
      }
    }
  }
  return found;
}
