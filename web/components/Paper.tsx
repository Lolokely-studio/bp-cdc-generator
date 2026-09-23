import { Fragment } from "react";
import type { Block } from "@/lib/contracts";
import { splitMarkers } from "@/lib/placeholders";

function Marked({ text }: { text: string }) {
  return (
    <>
      {splitMarkers(text).map((part, index) =>
        part.marker ? <mark key={index}>{part.text}</mark> : <Fragment key={index}>{part.text}</Fragment>,
      )}
    </>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "paragraph":
      return <p><Marked text={block.text} /></p>;
    case "list":
      return <ul>{block.items.map((item, index) => <li key={index}><Marked text={item} /></li>)}</ul>;
    case "placeholder":
      return <p><mark>Donnée à compléter : {block.label}</mark></p>;
    case "table":
      return (
        <div className="m-tablewrap">
          <table>
            <caption>Tableau {block.number} — {block.title}</caption>
            <thead>
              <tr>{block.columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>{row.map((cell, c) => <td key={c}><Marked text={cell} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
}

/** Les blocs typés, tels que l'export les lira : c'est la même matière. */
export function Paper({ blocks }: { blocks: Block[] }) {
  return <div className="m-paper">{blocks.map((block, index) => <BlockView key={index} block={block} />)}</div>;
}

/** Le texte qui arrive par le flux : de la prose, que les blocs typés
 * remplaceront à l'enregistrement de la section. */
export function StreamingPaper({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).filter((paragraph) => paragraph.trim());
  return (
    <div className="m-paper">
      {paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
      <span className="m-caret" aria-hidden="true" />
    </div>
  );
}
