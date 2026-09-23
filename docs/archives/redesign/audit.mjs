// Audit de responsivité des maquettes : chaque page à quatre largeurs.
// On cherche trois choses, et seulement celles-là : un débordement
// horizontal, une cible tactile trop petite, un lien interne cassé.
// Playwright vient de `web/` : c'est le seul endroit du dépôt où il est
// installé, et on ne va pas en ajouter une deuxième copie pour trois
// mesures.
import playwright from "../../../web/node_modules/playwright-core/index.js";
const { chromium } = playwright;
import { readdirSync } from "node:fs";

const RACINE = new URL(".", import.meta.url).pathname;
const BASE = "http://localhost:8731";
const LARGEURS = [390, 768, 1024, 1440];

const pages = readdirSync(RACINE).filter((f) => f.endsWith(".html")).sort();
const navigateur = await chromium.launch();
const contexte = await navigateur.newContext({ bypassCSP: true });
await contexte.route("**/*", (r) => r.continue());
const page = await contexte.newPage();

const ennuis = [];

for (const fichier of pages) {
  for (const largeur of LARGEURS) {
    await page.setViewportSize({ width: largeur, height: 900 });
    await page.goto(`${BASE}/${fichier}?v=${Date.now()}`, { waitUntil: "networkidle" });

    const constat = await page.evaluate((largeur) => {
      const out = { deborde: 0, coupables: [], petites: [], liens: [] };

      // 1. Débordement horizontal de la page entière.
      out.deborde = Math.max(0, document.documentElement.scrollWidth - largeur);

      // 2. Quel élément dépasse à droite.
      if (out.deborde > 0) {
        for (const el of document.querySelectorAll("body *")) {
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) continue;
          if (r.right > largeur + 1) {
            out.coupables.push(
              `${el.tagName.toLowerCase()}.${[...el.classList].join(".")} → ${Math.round(r.right)}px`,
            );
          }
        }
        out.coupables = [...new Set(out.coupables)].slice(0, 5);
      }

      // 3. Cibles tactiles : tout ce qui se clique doit tenir 32 px.
      const cliquables = "a[href], button, input:not([type=hidden]), select, textarea, [role=tab], [role=radio]";
      for (const el of document.querySelectorAll(cliquables)) {
        const cible = el.type === "checkbox" && el.closest("label") ? el.closest("label") : el;
        const r = cible.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.height < 32 || r.width < 24) {
          const nom = (el.textContent || el.getAttribute("aria-label") || el.type || "?").trim().slice(0, 34);
          out.petites.push(`${Math.round(r.width)}×${Math.round(r.height)} « ${nom} »`);
        }
      }
      out.petites = [...new Set(out.petites)];

      // 4. Liens internes.
      for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute("href");
        if (href && !href.startsWith("#") && !href.startsWith("http")) out.liens.push(href);
      }
      out.liens = [...new Set(out.liens)];
      return out;
    }, largeur);

    if (constat.deborde > 0) {
      ennuis.push(`DÉBORDE  ${fichier} @${largeur} : ${constat.deborde}px — ${constat.coupables.join(" | ")}`);
    }
    for (const p of constat.petites) {
      ennuis.push(`PETITE   ${fichier} @${largeur} : ${p}`);
    }
    if (largeur === 1440) {
      for (const lien of constat.liens) {
        if (!pages.includes(lien)) ennuis.push(`LIEN     ${fichier} → ${lien} n'existe pas`);
      }
    }
  }
}

await navigateur.close();

console.log(`${pages.length} pages × ${LARGEURS.length} largeurs = ${pages.length * LARGEURS.length} combinaisons`);
if (ennuis.length === 0) console.log("Rien à signaler.");
else ennuis.forEach((e) => console.log(e));
