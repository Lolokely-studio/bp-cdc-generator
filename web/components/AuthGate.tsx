"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { CrumbsProvider } from "@/components/Crumbs";
import { TopBar } from "@/components/TopBar";
import { ApiError, api, getToken, setInactiveHandler, setUnauthorizedHandler } from "@/lib/api";

/** Garde de toutes les pages derrière une session.
 *
 * Le jeton est vérifié par `/me` à l'arrivée. Ensuite, deux gestionnaires
 * de `request` tiennent l'écran à jour sans attendre un rechargement :
 * chaque `401` — session expirée, révoquée — ramène à la connexion, et
 * chaque `403 compte_inactif` — le compte désactivé en cours de route —
 * ramène à l'écran d'attente. */
export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace("/connexion"));
    setInactiveHandler(() => router.replace("/compte/en-attente"));
    if (!getToken()) {
      router.replace("/connexion");
      return () => {
        setUnauthorizedHandler(null);
        setInactiveHandler(null);
      };
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
      setInactiveHandler(null);
    };
  }, [router]);

  if (failed) {
    return (
      <main className="page">
        <p className="callout callout--stop" role="alert">Le serveur n'a pas répondu. Rechargez la page.</p>
      </main>
    );
  }
  if (!email) {
    return <main className="page"><p className="t-note">Chargement…</p></main>;
  }
  return (
    <CrumbsProvider>
      <TopBar email={email} />
      {children}
    </CrumbsProvider>
  );
}
