import type { ExportFile } from "@/lib/contracts";
import { DOCUMENT_LABEL } from "@/lib/labels";

/** Les fichiers déposés, un bloc par document.
 *
 * Deux avertissements ne sont jamais tus : un document brouillon, et un PDF
 * produit par le repli — le §7 demande de le dire plutôt que de le masquer. */
export function ExportFiles({ files }: { files: ExportFile[] }) {
  const groups = (["cdc", "bp"] as const)
    .map((document) => ({
      document,
      docx: files.find((file) => file.document === document && file.format === "docx"),
      pdf: files.find((file) => file.document === document && file.format === "pdf"),
    }))
    .filter((group) => group.docx || group.pdf);

  if (groups.length === 0) return null;

  return (
    <>
      <div className="docs">
        {groups.map((group) => {
          const brouillon = Boolean(group.docx?.brouillon || group.pdf?.brouillon);
          return (
            <div className="doc" key={group.document}>
              <span className="sheet" aria-hidden="true"><i /><i /><i /><i /><i /></span>
              <div className="doc__body">
                <p className="doc__title">
                  <span className="t-card">{DOCUMENT_LABEL[group.document]}</span>
                  {brouillon && <span className="tag tag--wait">Brouillon</span>}
                </p>
                <div className="btn-row">
                  {group.docx && (
                    <a className="btn btn--outline btn--sm" href={group.docx.lien} target="_blank" rel="noopener noreferrer">
                      Télécharger le Word
                    </a>
                  )}
                  {group.pdf && (
                    <a className="btn btn--outline btn--sm" href={group.pdf.lien} target="_blank" rel="noopener noreferrer">
                      Télécharger le PDF
                    </a>
                  )}
                </div>
                {brouillon && (
                  <p className="t-fine">
                    Au moins une section a été passée sans validation : le document porte un filigrane.
                  </p>
                )}
                {group.pdf && !group.pdf.fidele && (
                  <p className="t-fine">
                    Ce PDF vient du convertisseur de secours : sa mise en page peut différer de
                    l'original — c'est le Word, qui fait foi.
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <p className="t-note t-fine" style={{ marginTop: 10 }}>
        Les liens expirent au bout de dix minutes : rechargez la page pour en obtenir de neufs.
      </p>
    </>
  );
}
