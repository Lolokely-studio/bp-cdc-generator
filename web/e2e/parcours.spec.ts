import { expect, test, type Page } from "@playwright/test";
import { E2E_EMAIL, E2E_PASSWORD } from "./env";

async function login(page: Page) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse e-mail").fill(E2E_EMAIL);
  await page.getByLabel("Mot de passe").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Mes projets" })).toBeVisible();
}

// « Visible » ne suffit pas : dans `ReviewPanel`, les trois boutons
// partagent un seul état `busy`. À l'instant où « Passer la section » est
// cliqué, le même panneau se re-rend avec « Approuver » désactivé mais
// encore visible, avant même que la section suivante n'arrive. Un simple
// `isVisible()` attrapait ce résidu et cliquait un bouton désactivé qui
// allait être démonté — le clic restait bloqué pour le reste du test,
// jusqu'au timeout, pendant qu'un « Approuver » actionnable n'existait
// plus nulle part. Vérifié sur un run réel via `trace.zip` : le second
// `visible()` répondait vrai 13 ms après le clic sur « Passer la
// section », un délai incompatible avec un aller-retour serveur.
const visible = (page: Page, name: string) => {
  const button = page.getByRole("button", { name }).first();
  return button.isVisible().then((ok) => ok && button.isEnabled()).catch(() => false);
};

/** Mène la rédaction jusqu'à son terme, en répondant comme un utilisateur
 * pressé : « je ne sais pas » à tout, une section passée, un arbitrage
 * corrigé et les autres ignorés. Rend ce qui a été rencontré. */
async function driveUntilDone(page: Page, options: { skipOneReview: boolean }) {
  const seen = { questions: 0, reviews: 0, skipped: false, arbitrated: false };
  for (let step = 0; step < 200; step++) {
    if (await page.getByRole("heading", { name: "Rédaction terminée" }).isVisible().catch(() => false)) break;

    if (await visible(page, "Envoyer les réponses")) {
      // Le texte n'est pas l'objet de ce test : le modèle simulé écrit la
      // même chose quoi qu'on réponde. Ce qui est éprouvé, c'est
      // l'enchaînement, et « je ne sais pas » est une réponse valable (§4.2).
      for (const box of await page.getByRole("checkbox").all()) await box.check();
      await page.getByRole("button", { name: "Envoyer les réponses" }).click();
      seen.questions += 1;
    } else if (await visible(page, "Approuver")) {
      if (options.skipOneReview && !seen.skipped) {
        seen.skipped = true;
        await page.getByRole("button", { name: "Passer la section" }).click();
      } else {
        await page.getByRole("button", { name: "Approuver" }).click();
      }
      seen.reviews += 1;
    } else if (await visible(page, "Appliquer et continuer")) {
      let fixed = false;
      for (const group of await page.getByRole("group").all()) {
        const corriger = group.getByRole("button", { name: "Corriger" });
        if (!fixed && (await corriger.isEnabled())) {
          await corriger.click();
          await page.getByLabel("Comment corriger ?").fill("Aligner les dates sur la livraison.");
          fixed = true;
        } else {
          await group.getByRole("button", { name: "Ignorer" }).click();
        }
      }
      seen.arbitrated = true;
      await page.getByRole("button", { name: "Appliquer et continuer" }).click();
    } else {
      await page.waitForTimeout(1000);
    }
  }
  await expect(page.getByRole("heading", { name: "Rédaction terminée" })).toBeVisible();
  return seen;
}

test("du compte aux documents, puis une section rouverte", async ({ page }) => {
  await login(page);

  await page.getByRole("link", { name: "Nouveau projet" }).click();
  await page.getByRole("button", { name: /Cahier des charges/ }).click();
  await page.getByRole("button", { name: "Cadrer mon projet" }).click();
  await page.getByRole("button", { name: "Continuer" }).click();
  await page.getByLabel("Nom du projet").fill("CoachDom");
  await page.getByLabel("Votre idée").fill("Une plateforme de coaching sportif à domicile.");
  await page.getByRole("button", { name: "Analyser mon idée" }).click();
  await expect(page).toHaveURL(/\/projets\/[0-9a-f-]{36}$/);
  const projectUrl = page.url();

  const seen = await driveUntilDone(page, { skipOneReview: true });
  expect(seen.questions).toBeGreaterThan(0);
  expect(seen.skipped).toBe(true);
  expect(seen.arbitrated).toBe(true);
  // Une section passée : les documents seront des brouillons, et l'écran de
  // fin doit le dire plutôt que de le taire.
  await expect(page.getByText(/mention Brouillon/)).toBeVisible();

  // L'export : sans stockage configuré, le dépôt échoue. Ce que vérifie ce
  // pas, c'est que l'échec se voit (§7).
  await page.getByRole("link", { name: "Générer les documents" }).click();
  await expect(page).toHaveURL(/\/exports$/);
  await page.getByRole("button", { name: "Générer les documents" }).click();
  // `getByRole("alert")` seul viole le mode strict : Next.js pose son propre
  // `role="alert"` sur `__next-route-announcer__` (accessibilité des
  // changements de route), toujours présent dans le DOM. On filtre sur le
  // texte pour ne viser que le message d'échec de l'export.
  await expect(page.getByRole("alert").filter({ hasText: "La dernière génération a échoué" }))
    .toBeVisible({ timeout: 180_000 });

  // La réouverture : elle relance un vrai run sur la file de réécriture.
  await page.getByLabel("Section").selectOption({ index: 1 });
  await page.getByLabel("Que faut-il changer ?").fill("Parler aussi des coachs vérifiés.");
  await page.getByRole("button", { name: "Rouvrir et réécrire" }).click();
  await expect(page).toHaveURL(projectUrl);
  // Le backend écrit `running` en base avant de répondre (constat 4 de la
  // revue finale) : l'écran ne doit jamais rester bloqué sur « Rédaction
  // terminée » pendant que la réécriture tourne. Sans cette attente,
  // `driveUntilDone` pouvait sortir dès sa première itération si l'écran
  // n'avait pas encore quitté cette vue — et ne prouvait rien.
  await expect(page.getByRole("heading", { name: "Rédaction terminée" })).toBeHidden();
  // Et la preuve que la section rouverte a vraiment été reprise, pas
  // seulement re-marquée « terminé » sans rien écrire : le plan la montre
  // « à réécrire » tant qu'elle ne l'a pas été.
  await expect(page.locator(".m-planlist li", { hasText: "à réécrire" }).first()).toBeVisible();
  await driveUntilDone(page, { skipOneReview: false });
  await expect(page.locator(".m-planlist li", { hasText: "à réécrire" })).toHaveCount(0);

  // Le tableau de bord voit le projet terminé, avec toutes ses sections.
  await page.getByRole("link", { name: "Mes projets" }).click();
  const card = page.getByRole("link", { name: /CoachDom/ }).first();
  await expect(card).toContainText("Terminé");
});
