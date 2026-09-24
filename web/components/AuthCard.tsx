import Link from "next/link";
import type { ReactNode } from "react";

/** La pièce commune aux trois écrans d'entrée : connexion, compte en
 * attente, réveil du serveur. Les reconnaître l'une dans l'autre dit qu'on
 * est encore au seuil, et pas déjà dans l'application. */
export function AuthCard({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth">
      <Link className="auth__brand" href="/projets">
        <span className="mark" aria-hidden="true" />
        Esquisse
      </Link>
      <div className="auth__card">{children}</div>
      {footer && <p className="auth__foot">{footer}</p>}
    </div>
  );
}
