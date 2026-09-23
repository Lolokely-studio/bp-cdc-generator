import { execFileSync } from "node:child_process";
import path from "node:path";
import { BACKEND_ENV, E2E_EMAIL, E2E_PASSWORD } from "./env";

/** Migre la base jetable et pose un compte actif.
 *
 * L'activation se fait à la main en production (§3.2) ; ici, c'est le script
 * de la tâche 2 qui la fait, et il refuse toute base qui n'est pas locale.
 *
 * Le chemin se résout avec `__dirname`, pas `import.meta.url` : ce fichier
 * est chargé en CommonJS (le projet n'est pas `"type": "module"`), et
 * Playwright 1.63 sur Node 20 exécute alors `import.meta` littéralement
 * dans un module enveloppé en CommonJS — une `ReferenceError: exports is
 * not defined` avant même la première ligne, vérifié en isolant le cas. */
export default function globalSetup() {
  const options = {
    cwd: path.resolve(__dirname, "../../backend"),
    env: { ...process.env, ...BACKEND_ENV },
    stdio: "inherit" as const,
  };
  execFileSync("uv", ["run", "alembic", "upgrade", "head"], options);
  execFileSync("uv", ["run", "python", "-m", "app.auth.seed", E2E_EMAIL, E2E_PASSWORD], options);
}
