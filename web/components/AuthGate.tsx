"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { TopBar } from "@/components/TopBar";
import { ApiError, api, getToken, setUnauthorizedHandler } from "@/lib/api";

/** Garde de toutes les pages derrière une session.
 *
 * Le jeton est vérifié par `/me` à l'arrivée, et chaque `401` ultérieur
 * — session expirée, révoquée — ramène à la connexion par le gestionnaire
 * que `request` appelle. */
export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace("/connexion"));
    if (!getToken()) {
      router.replace("/connexion");
      return () => setUnauthorizedHandler(null);
    }
    let alive = true;
    api.me()
      .then((me) => { if (alive) setEmail(me.email); })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && error.code === "compte_inactif") {
          router.replace("/compte/en-attente");
        } else if (!(error instanceof ApiError && error.status === 401)) {
          setFailed(true);
        }
      });
    return () => {
      alive = false;
      setUnauthorizedHandler(null);
    };
  }, [router]);

  if (failed) {
    return (
      <main className="m-body">
        <p className="m-err" role="alert">Le serveur n'a pas répondu. Rechargez la page.</p>
      </main>
    );
  }
  if (!email) {
    return <main className="m-body"><p className="m-muted">Chargement…</p></main>;
  }
  return (
    <>
      <TopBar email={email} />
      {children}
    </>
  );
}
