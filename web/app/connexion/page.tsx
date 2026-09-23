"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { AuthCard } from "@/components/AuthCard";
import { ApiError, api, rememberPendingEmail, setToken } from "@/lib/api";
import { authErrorMessage } from "@/lib/messages";

const MIN_PASSWORD = 10;

const TABS = ["login", "register"] as const;
type Tab = (typeof TABS)[number];

export default function ConnexionPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Tab>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const register = mode === "register";

  // Une référence par onglet : on donne le focus à l'élément lui-même, tout
  // de suite. Interroger le DOM après coup obligerait à attendre un rendu,
  // et l'assertion de focus du test deviendrait une course.
  const tabRefs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({});

  function selectTab(tab: Tab, withFocus: boolean) {
    setMode(tab);
    setError(null);
    if (withFocus) tabRefs.current[tab]?.focus();
  }

  // Flèches, Début et Fin déplacent la sélection ET le focus : c'est le
  // motif « onglets automatiques », celui qu'attend un lecteur d'écran.
  function onTabKey(event: KeyboardEvent<HTMLDivElement>) {
    const index = TABS.indexOf(mode);
    const next: Tab | undefined = {
      ArrowRight: TABS[(index + 1) % 2],
      ArrowLeft: TABS[(index + 1) % 2],
      Home: TABS[0],
      End: TABS[1],
    }[event.key];
    if (!next) return;
    event.preventDefault();
    selectTab(next, true);
  }

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
    <AuthCard footer="L'accès se fait sur demande. Le compte est créé tout de suite, et activé à la main avant la première rédaction.">
      <div className="tabs" role="tablist" aria-label="Connexion ou création de compte"
        onKeyDown={onTabKey}>
        {([["login", "Se connecter"], ["register", "Créer un compte"]] as const).map(([value, label]) => (
          <button key={value} className="tabs__tab" type="button" role="tab"
            ref={(el) => { tabRefs.current[value] = el; }}
            id={`onglet-${value}`} aria-controls={`volet-${value}`}
            aria-selected={mode === value} tabIndex={mode === value ? 0 : -1}
            onClick={() => selectTab(value, false)}>
            {label}
          </button>
        ))}
      </div>

      <form id={`volet-${mode}`} role="tabpanel" aria-labelledby={`onglet-${mode}`}
        onSubmit={submit} noValidate>
        <label className="field">
          <span className="field__label">Adresse e-mail</span>
          <input className="input" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <div className="field">
          {/* La note d'aide reste hors du `<label>` : nichée dedans, elle
              s'ajoute au nom accessible du champ (« Mot de passe Dix
              caractères au moins. »), ce que `getByLabelText("Mot de
              passe")` ne reconnaît plus. `aria-describedby` la relie sans
              toucher au nom. */}
          <label>
            <span className="field__label">Mot de passe</span>
            <input className="input" type="password" required
              autoComplete={register ? "new-password" : "current-password"}
              aria-describedby={register ? "password-hint" : undefined}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {register && <span id="password-hint" className="field__hint">Dix caractères au moins.</span>}
        </div>
        {error && (
          <div className="callout callout--stop" role="alert" style={{ marginTop: "1rem" }}>
            <span className="callout__body">{error}</span>
          </div>
        )}
        <div style={{ marginTop: "1.125rem" }}>
          <button className="btn btn--primary btn--block" type="submit" disabled={busy}>
            {register ? "Demander un accès" : "Se connecter"}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}
