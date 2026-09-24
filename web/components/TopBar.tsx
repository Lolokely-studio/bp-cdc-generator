"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AccountMenu } from "@/components/AccountMenu";
import { Crumbs, useCrumbs } from "@/components/Crumbs";
import { api, setToken } from "@/lib/api";

export function TopBar({ email }: { email: string }) {
  const router = useRouter();
  const crumbs = useCrumbs();

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
    <header className="topbar">
      <Link className="brand" href="/projets">
        <span className="mark" aria-hidden="true" />
        Esquisse
      </Link>
      {crumbs.length > 0 && <Crumbs items={crumbs} />}
      <AccountMenu email={email} onLogout={logout} />
    </header>
  );
}
