/** Trois fiches fantômes pendant l'appel : la page ne saute pas quand les
 * vraies arrivent. L'annonce est réservée au lecteur d'écran — l'attente
 * est déjà visible pour qui voit l'écran. */
export function ProjectsSkeleton() {
  return (
    <>
      <p className="sr" role="status">Chargement de vos projets.</p>
      <div className="projects" aria-hidden="true">
        {[0, 1, 2].map((index) => (
          <div className="project skeleton" key={index}>
            <span className="project__top">
              <span className="bone bone--title" />
              <span className="bone bone--tag" />
            </span>
            <span className="bone bone--line" />
            <span className="bone bone--ticks" />
            <span className="bone bone--short" />
          </div>
        ))}
      </div>
    </>
  );
}
