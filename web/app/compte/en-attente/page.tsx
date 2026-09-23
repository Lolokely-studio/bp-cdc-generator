"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AuthCard } from "@/components/AuthCard";
import { pendingEmail } from "@/lib/api";

export default function PendingPage() {
  // Lu après le montage : le stockage n'existe pas pendant le rendu serveur.
  const [email, setEmail] = useState<string | null>(null);
  useEffect(() => setEmail(pendingEmail()), []);

  return (
    <AuthCard footer="Revenez vous connecter une fois le compte activé.">
      <h1 className="t-section">Votre compte attend son activation</h1>
      <p className="t-note" style={{ marginTop: ".375rem" }}>
        Il existe, mais il n'ouvre encore rien. Un administrateur l'active avant de vous
        laisser lancer une rédaction : c'est ce qui permet de savoir qui consomme les
        quotas de génération.
      </p>
      {email && (
        <div className="facts" style={{ margin: "1.125rem 0" }}>
          <div className="fact">
            <span className="fact__key">Adresse</span>
            <span className="fact__val">{email}</span>
          </div>
          <div className="fact">
            <span className="fact__key">État</span>
            <span className="fact__val"><span className="tag tag--wait">En attente d'activation</span></span>
          </div>
        </div>
      )}
      <Link className="btn btn--outline btn--block" href="/connexion">Retour à la connexion</Link>
    </AuthCard>
  );
}
