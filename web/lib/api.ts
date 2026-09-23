import { z } from "zod";
import {
  AnswerResult, Catalogue, Documents, Exports, Health, LaunchResult, LoginResult, Me,
  ProjectState, ProjectSummary, RegisterResult, ReopenResult, ResumeResult,
} from "@/lib/contracts";

// Le navigateur parle directement au backend (§6.1). L'adresse est inscrite
// dans le code au moment de la construction.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "esquisse.jeton";
const PENDING_EMAIL_KEY = "esquisse.adresse-en-attente";

// Le stockage peut lever — navigation privée, stockage bloqué. Un jeton
// illisible vaut « pas de jeton » : l'utilisateur se reconnecte.
export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* rien à faire : la session ne survivra pas au rechargement */ }
}

export function rememberPendingEmail(email: string): void {
  try { sessionStorage.setItem(PENDING_EMAIL_KEY, email); } catch { /* affichage seulement */ }
}

export function pendingEmail(): string | null {
  try { return sessionStorage.getItem(PENDING_EMAIL_KEY); } catch { return null; }
}

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, readonly detail: unknown) {
    super(`${status} ${code}`);
    this.name = "ApiError";
  }
}

/** Le code d'une erreur de l'API. FastAPI met `detail` en chaîne
 * (`"compte_inactif"`), en objet (`{"code": …}`), ou en liste pour un `422`
 * de validation. */
export function errorCode(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "requete_invalide";
  if (detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string") {
    return (detail as { code: string }).code;
  }
  return "erreur_inconnue";
}

let onUnauthorized: (() => void) | null = null;
let onInactive: (() => void) | null = null;

/** Appelé quand une session posée est refusée : expirée, révoquée. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** Appelé quand un compte déjà connecté est désactivé en cours de session
 * (§3.1) : la désactivation doit prendre effet tout de suite, pas au
 * prochain rechargement fortuit. Le jeton n'est PAS effacé ici — la
 * session reste valable, c'est le compte qui attend son activation, et
 * l'utilisateur retrouvera ses projets une fois activé. Un `403
 * compte_inactif` SANS jeton — la connexion d'un compte non activé — ne
 * déclenche rien : c'est la page de connexion qui le traite déjà. */
export function setInactiveHandler(handler: (() => void) | null): void {
  onInactive = handler;
}

type RequestOptions = { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal };

export async function request<T>(path: string, schema: z.ZodType<T>, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    cache: "no-store",
  });
  const payload: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined);

  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : undefined;
    const code = errorCode(detail);
    // Un 401 SANS jeton est un mot de passe refusé à la connexion ; AVEC
    // jeton, c'est une session morte, et tout l'écran doit le savoir.
    if (response.status === 401 && token) {
      setToken(null);
      onUnauthorized?.();
    }
    // Un 403 compte_inactif AVEC jeton : le compte vient d'être désactivé
    // pendant que la session tournait. SANS jeton, c'est juste la connexion
    // d'un compte non activé — déjà traitée par la page de connexion.
    if (response.status === 403 && token && code === "compte_inactif") {
      onInactive?.();
    }
    throw new ApiError(response.status, code, detail);
  }
  return schema.parse(payload);
}

export type ProjectCreation = {
  nom: string;
  documents: Documents;
  profil_cdc: string | null;
  profil_bp: string | null;
  idee: string;
};

export const api = {
  health: () => request("/health", Health),
  register: (email: string, motDePasse: string) =>
    request("/auth/register", RegisterResult, { method: "POST", body: { email, mot_de_passe: motDePasse } }),
  login: (email: string, motDePasse: string) =>
    request("/auth/login", LoginResult, { method: "POST", body: { email, mot_de_passe: motDePasse } }),
  logout: () => request("/auth/logout", z.undefined(), { method: "POST" }),
  me: () => request("/me", Me),
  catalogue: () => request("/catalogue", Catalogue),
  projects: () => request("/projects", z.array(ProjectSummary)),
  createProject: (body: ProjectCreation) => request("/projects", ProjectSummary, { method: "POST", body }),
  state: (id: string) => request(`/projects/${id}/state`, ProjectState),
  answer: (id: string, interactionId: string, reponse: unknown) =>
    request(`/projects/${id}/answer`, AnswerResult, {
      method: "POST", body: { interaction_id: interactionId, reponse },
    }),
  resume: (id: string) => request(`/projects/${id}/resume`, ResumeResult, { method: "POST" }),
  reopen: (id: string, sectionId: string, consigne: string | null) =>
    request(`/projects/${id}/sections/${encodeURIComponent(sectionId)}/reopen`, ReopenResult, {
      method: "POST", body: { consigne },
    }),
  launchExport: (id: string) => request(`/projects/${id}/exports`, LaunchResult, { method: "POST" }),
  exports: (id: string) => request(`/projects/${id}/exports`, Exports),
};
