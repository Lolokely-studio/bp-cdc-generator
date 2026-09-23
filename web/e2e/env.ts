export const API_PORT = 8100;
export const WEB_PORT = 3101;
// `esquisse.test`, réservé par la RFC 2606 pour les environnements de test,
// est aussi celui que `email-validator` rejette par défaut comme domaine
// « special-use » (voir sa liste `SPECIAL_USE_DOMAIN_NAMES`) : `EmailStr`
// refuserait chaque connexion avec `requete_invalide`. `esquisse.example`
// est le seul domaine de la même RFC que la bibliothèque laisse passer.
export const E2E_EMAIL = "e2e@esquisse.example";
export const E2E_PASSWORD = "motdepasse-e2e-0923";

/** L'environnement du backend de bout en bout.
 *
 * CHAQUE VARIABLE EST POSÉE EXPLICITEMENT, y compris à vide. `backend/.env`
 * porte les réglages du poste — la vraie base Supabase, les vraies clés de
 * modèles, le vrai stockage — et seules les variables d'environnement le
 * recouvrent. En oublier une ferait tourner le parcours sur la production.
 *
 * Le stockage est laissé vide À DESSEIN : l'export échoue au dépôt, et le
 * parcours vérifie que l'écran le dit au lieu de faire croire à des
 * fichiers qui n'existent pas. */
export const BACKEND_ENV: Record<string, string> = {
  SUPABASE_DB_HOST: "localhost",
  SUPABASE_DB_PORT: "5433",
  SUPABASE_DB_USER: "esquisse",
  SUPABASE_DB_PASSWORD: "esquisse",
  SUPABASE_DB_NAME: "esquisse_test",
  ESQUISSE_FAKE_LLM: "true",
  CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
  SUPABASE_URL: "",
  SUPABASE_SERVICE_ROLE_KEY: "",
  GOTENBERG_URL: "",
  GEMINI_API_KEY: "",
  MISTRAL_AI_API_KEY: "",
  OPENROUTER_API_KEY: "",
  NVIDIA_API_KEY: "",
  GROQ_CLOUD_API_KEY: "",
};
