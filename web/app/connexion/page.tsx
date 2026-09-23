"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ApiError, api, rememberPendingEmail, setToken } from "@/lib/api";
import { authErrorMessage } from "@/lib/messages";

const MIN_PASSWORD = 10;

export default function ConnexionPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const register = mode === "register";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (register && password.length < MIN_PASSWORD) {
      setError(`Le mot de passe doit faire au moins ${MIN_PASSWORD} caractères.`);
      return;
    }
    setBusy(true);
    try {
      if (register) {
        await api.register(email, password);
        rememberPendingEmail(email);
        router.push("/compte/en-attente");
        return;
      }
      const { jeton } = await api.login(email, password);
      setToken(jeton);
      router.push("/projets");
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "compte_inactif") {
        rememberPendingEmail(email);
        router.push("/compte/en-attente");
        return;
      }
      setError(authErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="m-body m-narrow">
      <h1 className="m-h">{register ? "Créer un compte" : "Se connecter"}</h1>
      <p className="m-muted">
        {register
          ? "L'accès se fait sur demande : le compte est créé tout de suite, mais activé à la main avant la première rédaction."
          : "Entrez les identifiants d'un compte activé."}
      </p>
      <form onSubmit={submit} noValidate>
        <div style={{ marginTop: 20 }}>
          <label className="m-label" htmlFor="email">Adresse e-mail</label>
          <input id="email" className="m-input" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div style={{ marginTop: 14 }}>
          <label className="m-label" htmlFor="password">Mot de passe</label>
          <input id="password" className="m-input" type="password" required
            autoComplete={register ? "new-password" : "current-password"}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p className="m-err" role="alert">{error}</p>}
        <div className="m-actions">
          <button className="m-btn sec" type="button"
            onClick={() => { setMode(register ? "login" : "register"); setError(null); }}>
            {register ? "J'ai déjà un compte" : "Créer un compte"}
          </button>
          <button className="m-btn" type="submit" disabled={busy}>
            {register ? "Demander un accès" : "Se connecter"}
          </button>
        </div>
      </form>
    </main>
  );
}
