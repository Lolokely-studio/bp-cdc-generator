import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Depuis l'URL du module, pas depuis `process.cwd()` : le répertoire
// courant de Vitest dépend d'où la commande est lancée.
// `new URL("../x", import.meta.url)` serait la forme la plus directe, mais
// Vite l'intercepte pour son résolveur d'assets statiques dès qu'un
// environnement navigateur (jsdom) est actif, et casse la résolution
// relative quand le chemin contient une partie dynamique. `dirname` +
// `join` reste module-relatif sans déclencher cette transformation.
const ICI = dirname(fileURLToPath(import.meta.url));
const lire = (chemin: string) => readFileSync(join(ICI, "..", chemin), "utf8");
const feuille = (nom: string) => lire(`styles/${nom}`);

describe("les jetons", () => {
  it("pose la palette slate de la maquette", () => {
    const tokens = feuille("tokens.css");
    for (const [nom, valeur] of [
      ["--ground", "#f8fafc"], ["--surface", "#ffffff"], ["--surface-sunk", "#f1f5f9"],
      ["--ink", "#0f172a"], ["--ink-soft", "#64748b"], ["--rule", "#e2e8f0"],
      ["--ok", "#047857"], ["--wait", "#b45309"], ["--live", "#1d4ed8"],
      ["--stop", "#b91c1c"], ["--idle", "#475569"],
    ]) {
      expect(tokens).toContain(`${nom}: ${valeur}`);
    }
  });

  it("ne garde aucune trace du mode sombre", () => {
    // Le mode sombre doublait chaque jeton. Il est supprimé, pas commenté :
    // une règle commentée revient toujours.
    for (const nom of ["tokens.css", "base.css", "app.css", "workspace.css", "legacy.css"]) {
      expect(feuille(nom)).not.toContain("prefers-color-scheme");
      expect(feuille(nom)).not.toContain("data-theme");
    }
  });

  it("ne garde aucune couleur de piste ni aucune ancienne police", () => {
    const toutes = ["tokens.css", "base.css", "app.css", "workspace.css", "legacy.css"]
      .map(feuille).join("\n");
    for (const mort of ["--l0", "--l1", "--l2", "--l3", "--l4", "--l5",
                        "Bricolage", "Hanken"]) {
      expect(toutes).not.toContain(mort);
    }
  });

  it("n'écrit aucune couleur en dur hors des jetons", () => {
    // Une couleur écrite ailleurs que dans `tokens.css` échappe à la source
    // unique : elle ne suivra pas quand le jeton bougera. Seul le blanc pur
    // est toléré — c'est l'encre posée sur un fond encre, jamais un fond.
    // `rgba()` compte aussi : la barre haute y recopiait `--ground`.
    const dehors = ["base.css", "app.css", "workspace.css"].map(feuille).join("\n");
    const hex = [...dehors.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0]);
    expect(hex.filter((c) => c.toLowerCase() !== "#fff")).toEqual([]);
    expect(dehors).not.toMatch(/\brgba?\(/);
  });

  it("importe les cinq feuilles, dans l'ordre", () => {
    const globals = lire("app/globals.css");
    const ordre = ["tokens.css", "base.css", "app.css", "workspace.css", "legacy.css"]
      .map((nom) => globals.indexOf(nom));
    expect(ordre.every((i) => i >= 0)).toBe(true);
    expect([...ordre].sort((a, b) => a - b)).toEqual(ordre);
  });
});
