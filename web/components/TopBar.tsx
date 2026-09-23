"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { initials } from "@/lib/messages";

export function TopBar({ email }: { email: string }) {
  const router = useRouter();

  async function logout() {
    try {
      await api.logout();
    } catch {
      // La session sera oubliée ici de toute façon ; côté serveur, elle
      // expirera d'elle-même.
    }
    setToken(null);
    router.replace("/connexion");
  }

  return (
    <header className="m-bar">
      <Link className="m-logo" href="/projets">
        <span className="mark" aria-hidden="true" />
        Esquisse
      </Link>
      <div className="m-bar-r">
        <Link className="m-link" href="/projets">Mes projets</Link>
        <span className="m-avatar" title={email}>{initials(email)}</span>
        <button className="m-link" type="button" onClick={logout}>Se déconnecter</button>
      </div>
    </header>
  );
}
