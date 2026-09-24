/** L'atelier pendant son chargement.
 *
 * Il affichait « Chargement du projet… » sur une page vide, alors que
 * l'écran qui arrive a trois colonnes. Le squelette les pose tout de suite :
 * le plan à gauche, ce qu'on écrit au centre, la mémoire à droite. */
export function WorkspaceSkeleton() {
  return (
    <div className="m-ws skeleton">
      <p className="sr" role="status">Chargement du projet.</p>

      <aside className="m-col plan" aria-hidden="true">
        <span className="bone bone--short" />
        <div className="m-prog" />
        <div className="stack stack--tight" style={{ marginTop: "1rem" }}>
          {Array.from({ length: 9 }, (_, index) => (
            <span className="bone bone--line" key={index} />
          ))}
        </div>
      </aside>

      <main className="m-col center" aria-hidden="true">
        <span className="bone bone--tag" />
        <span className="bone bone--head" style={{ marginTop: "0.75rem" }} />
        <div className="m-paper" style={{ marginTop: "1.5rem" }}>
          <div className="stack stack--tight">
            {Array.from({ length: 7 }, (_, index) => (
              <span className="bone bone--para" key={index} />
            ))}
            <span className="bone bone--para bone--last" />
          </div>
        </div>
      </main>

      <aside className="m-col m-col--facts" aria-hidden="true">
        <span className="bone bone--short" />
        <div className="stack" style={{ marginTop: "1rem" }}>
          {Array.from({ length: 6 }, (_, index) => (
            <div className="stack stack--tight" key={index}>
              <span className="bone bone--short" />
              <span className="bone bone--line" />
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
