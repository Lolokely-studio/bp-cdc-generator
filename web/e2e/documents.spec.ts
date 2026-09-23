import { expect, test, type Page } from "@playwright/test";
import { E2E_EMAIL, E2E_PASSWORD } from "./env";

const PROJECT = "11111111-2222-3333-4444-555555555555";

async function login(page: Page) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse e-mail").fill(E2E_EMAIL);
  await page.getByLabel("Mot de passe").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Mes projets" })).toBeVisible();
}

test("un export réussi montre ses quatre fichiers et ses réserves", async ({ page }) => {
  // Le dépôt réel demande un bucket Supabase, que le bout en bout n'a pas :
  // seules ces deux réponses sont simulées, tout le reste est le vrai
  // backend.
  await login(page);
  await page.route(`**/projects/${PROJECT}/state`, (route) => route.fulfill({
    json: {
      projet: {
        id: PROJECT, nom: "CoachDom", documents: "both", profil_cdc: "cadrage",
        profil_bp: "banque", run_status: "done", created_at: null, updated_at: null,
        sections_faites: 2, sections_total: 2,
      },
      plan: [{ document: "cdc", section_id: "perimetre", order: 0 }],
      curseur: 1,
      faits: {},
      sections: [{
        section_id: "perimetre", document: "cdc", ordre: 1, statut: "done", note: 8, revisions: 1,
        blocks: [{ kind: "placeholder", label: "Apport des fondateurs" }],
      }],
      interaction: null,
    },
  }));
  await page.route(`**/projects/${PROJECT}/exports`, (route) => route.fulfill({
    json: {
      en_cours: false, dernier_export: "ok",
      fichiers: [
        { document: "cdc", format: "docx", brouillon: true, fidele: true,
          lien: "https://stockage.test/cdc.docx", cree_le: "2026-09-23T09:00:00Z" },
        { document: "cdc", format: "pdf", brouillon: true, fidele: false,
          lien: "https://stockage.test/cdc.pdf", cree_le: "2026-09-23T09:00:00Z" },
      ],
    },
  }));

  await page.goto(`/projets/${PROJECT}/exports`);
  await expect(page.getByRole("heading", { name: "Vos documents sont prêts" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Télécharger le Word" }))
    .toHaveAttribute("href", "https://stockage.test/cdc.docx");
  await expect(page.getByText(/convertisseur de secours/)).toBeVisible();
  await expect(page.getByText("Brouillon")).toBeVisible();
  await expect(page.getByText("Apport des fondateurs")).toBeVisible();
});

test("un serveur endormi donne un écran d'attente, pas une page cassée", async ({ page }) => {
  let calls = 0;
  await page.route("**/health", async (route) => {
    calls += 1;
    if (calls <= 2) await route.abort("connectionrefused");
    else await route.continue();
  });

  await page.goto("/connexion");
  await expect(page.getByRole("heading", { name: "Le serveur se réveille" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Se connecter" })).toBeVisible({ timeout: 30_000 });
});
