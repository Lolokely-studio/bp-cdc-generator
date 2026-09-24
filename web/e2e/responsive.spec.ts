import { expect, test, type Page } from "@playwright/test";
import { E2E_EMAIL, E2E_PASSWORD } from "./env";

// Les quatre largeurs de la maquette. Elles ne visent pas des appareils
// mais les trois paliers du `README.md` du redesign, plus un point de
// chaque côté de la rupture du milieu.
const WIDTHS = [390, 768, 1024, 1440];

async function login(page: Page) {
  await page.goto("/connexion");
  await page.getByLabel("Adresse e-mail").fill(E2E_EMAIL);
  await page.getByLabel("Mot de passe").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Mes projets" })).toBeVisible();
}

/** Ce qui dépasse à droite, et ce qui est trop petit pour un doigt. */
async function problems(page: Page, width: number) {
  return page.evaluate((width) => {
    const out: string[] = [];
    const overflow = document.documentElement.scrollWidth - width;
    if (overflow > 0) {
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width && r.height && r.right > width + 1) {
          out.push(`déborde de ${Math.round(r.right - width)}px : ${el.tagName.toLowerCase()}.${[...el.classList].join(".")}`);
        }
      }
      if (out.length === 0) out.push(`déborde de ${overflow}px, coupable introuvable`);
    }
    const clickable = "a[href], button, input:not([type=hidden]), select, textarea, [role=tab], [role=radio]";
    for (const el of document.querySelectorAll(clickable)) {
      // Une case à cocher enveloppée dans son étiquette : c'est
      // l'étiquette qu'on touche, donc c'est elle qu'on mesure.
      const field = el as HTMLInputElement;
      const target = field.type === "checkbox" && el.closest("label") ? el.closest("label")! : el;
      const r = target.getBoundingClientRect();
      if (r.width && r.height && (r.height < 32 || r.width < 24)) {
        const label = (el.textContent || el.getAttribute("aria-label") || "?").trim().slice(0, 40);
        out.push(`cible de ${Math.round(r.width)}×${Math.round(r.height)} : « ${label} »`);
      }
    }
    return [...new Set(out)];
  }, width);
}

test("les écrans tiennent aux quatre largeurs", async ({ page }) => {
  await login(page);
  const routes = ["/connexion", "/compte/en-attente", "/projets", "/projets/nouveau"];
  for (const route of routes) {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(route);
      // `waitForLoadState` seul ne suffit pas : les fiches fantômes
      // laissent place aux vraies après l'appel, et la mise en page change.
      await page.waitForLoadState("networkidle");
      expect(await problems(page, width), `${route} à ${width}px`).toEqual([]);
    }
  }
});
