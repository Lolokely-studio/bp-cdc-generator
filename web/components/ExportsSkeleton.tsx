/** L'écran des documents pendant son chargement.
 *
 * Il affichait « Chargement… » sur une page vide, puis tout arrivait d'un
 * coup. Le squelette reprend la mesure de ce qui va venir — l'en-tête, les
 * deux documents, les deux panneaux — pour que rien ne saute.
 *
 * `aria-hidden` sur les formes : elles ne disent rien qu'un lecteur d'écran
 * puisse lire. C'est l'annonce qui porte l'information, une fois. */
export function ExportsSkeleton() {
  return (
    <main className="page skeleton">
      <p className="sr" role="status">Chargement de vos documents.</p>

      <div className="page__head" aria-hidden="true">
        <div className="page__head-text">
          <span className="bone bone--head" />
          <span className="bone bone--sub" />
        </div>
        <div className="btn-row"><span className="bone bone--btn" /></div>
      </div>

      <div className="docs" aria-hidden="true">
        {[0, 1].map((index) => (
          <div className="doc" key={index}>
            <span className="bone bone--sheet" />
            <div className="stack">
              <span className="bone bone--title" />
              <span className="bone bone--short" />
              {/* Deux boutons, comme la vraie fiche : Word et PDF. */}
              <span className="btn-row">
                <span className="bone bone--btn" />
                <span className="bone bone--btn" />
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="split" aria-hidden="true">
        {[0, 1].map((index) => (
          <section className="panel" key={index}>
            <div className="panel__head"><span className="bone bone--title" /></div>
            <div className="panel__body">
              <div className="stack stack--tight">
                <span className="bone bone--para" />
                <span className="bone bone--para" />
                <span className="bone bone--para bone--last" />
              </div>
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}
