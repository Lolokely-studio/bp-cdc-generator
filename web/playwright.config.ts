import { defineConfig } from "@playwright/test";
import { API_PORT, BACKEND_ENV, WEB_PORT } from "./e2e/env";

export default defineConfig({
  testDir: "./e2e",
  // Un parcours complet sur trente sections simulées prend des minutes, pas
  // des secondes.
  timeout: 600_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  webServer: [
    {
      command: `uv run uvicorn app.main:app --port ${API_PORT} --workers 1`,
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/health`,
      // JAMAIS `reuseExistingServer` : un serveur de développement déjà
      // lancé lit `backend/.env`, donc la vraie base et les vraies clés.
      reuseExistingServer: false,
      timeout: 120_000,
      env: BACKEND_ENV,
    },
    {
      // `NEXT_PUBLIC_API_URL` est inscrite dans le code À LA CONSTRUCTION :
      // on construit ici, on ne réutilise pas un `next dev` du poste.
      command: `npx next build && npx next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/connexion`,
      reuseExistingServer: false,
      timeout: 600_000,
      env: { NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}` },
    },
  ],
});
