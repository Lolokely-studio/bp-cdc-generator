"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { pendingEmail } from "@/lib/api";

export default function PendingPage() {
  // Lu après le montage : le stockage n'existe pas pendant le rendu serveur.
  const [email, setEmail] = useState<string | null>(null);
  useEffect(() => setEmail(pendingEmail()), []);

  return (
    <main className="m-body m-narrow">
      <h1 className="m-h">Votre compte attend son activation</h1>
      <p className="m-muted">
        Le compte existe, mais il n'ouvre encore rien. Un administrateur le valide dans la base
        avant de vous laisser lancer une rédaction : c'est ce qui permet de maîtriser qui consomme
        les quotas de génération.
      </p>
      {email && (
        <div className="m-pending">
          <b>{email}</b>
          <span className="m-muted small">Compte créé · en attente d'activation</span>
        </div>
      )}
      <p className="m-muted small" style={{ marginTop: 16 }}>
        Revenez vous connecter une fois le compte activé.
      </p>
      <div className="m-actions">
        <Link className="m-btn sec" href="/connexion">Retour à la connexion</Link>
      </div>
    </main>
  );
}
