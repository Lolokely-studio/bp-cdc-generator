import { readdirSync, readFileSync } from "node:fs";
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
const HERE = dirname(fileURLToPath(import.meta.url));
const read = (path: string) => readFileSync(join(HERE, "..", path), "utf8");
const sheet = (name: string) => read(`styles/${name}`);

/** Une classe qui ressemble à une classe CSS, pas à une expression. */
const CLASS_NAME = /^[a-z][a-z0-9-]*(__[a-z0-9-]+)?(--[a-z0-9-]+)?$/;

/** Les classes complètes d'un attribut `className`.
 *
 * Un jeton collé à une interpolation — le `tag--` de
 * `` `tag tag--${tone}` `` — n'est pas une classe mais un préfixe, et son
 * suffixe ne se connaît qu'à l'exécution. On ne le compte pas, et on ne
 * compte pas davantage le nom de la variable interpolée. C'est la limite
 * assumée de ce garde-fou : il attrape une classe littérale devenue
 * orpheline, pas une classe composée à l'exécution. */
function literalClasses(attr: string, isTemplate: boolean): string[] {
  if (!isTemplate) return attr.split(/\s+/);
  const out: string[] = [];
  const chunks = attr.split(/\$\{[^}]*\}/);
  chunks.forEach((chunk, i) => {
    const tokens = chunk.split(/\s+/);
    if (i > 0 && !/^\s/.test(chunk)) tokens.shift();
    if (i < chunks.length - 1 && !/\s$/.test(chunk)) tokens.pop();
    out.push(...tokens);
  });
  return out;
}

function filesUnder(dir: string, ext: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(join(HERE, "..", dir), { withFileTypes: true })) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) out.push(...filesUnder(path, ext));
    else if (entry.name.endsWith(ext)) out.push(path);
  }
  return out;
}

describe("les jetons", () => {
  it("pose la palette slate de la maquette", () => {
    const tokens = sheet("tokens.css");
    for (const [name, value] of [
      ["--ground", "#f8fafc"], ["--surface", "#ffffff"], ["--surface-sunk", "#f1f5f9"],
      ["--ink", "#0f172a"], ["--ink-soft", "#64748b"], ["--rule", "#e2e8f0"],
      ["--ok", "#047857"], ["--wait", "#b45309"], ["--live", "#1d4ed8"],
      ["--stop", "#b91c1c"], ["--idle", "#475569"],
    ]) {
      expect(tokens).toContain(`${name}: ${value}`);
    }
  });

  it("ne garde aucune trace du mode sombre", () => {
    // Le mode sombre doublait chaque jeton. Il est supprimé, pas commenté :
    // une règle commentée revient toujours.
    for (const name of ["tokens.css", "base.css", "app.css", "workspace.css"]) {
      expect(sheet(name)).not.toContain("prefers-color-scheme");
      expect(sheet(name)).not.toContain("data-theme");
    }
  });

  it("ne garde aucune couleur de piste ni aucune ancienne police", () => {
    const all = ["tokens.css", "base.css", "app.css", "workspace.css"]
      .map(sheet).join("\n");
    for (const dead of ["--l0", "--l1", "--l2", "--l3", "--l4", "--l5",
                        "Bricolage", "Hanken"]) {
      expect(all).not.toContain(dead);
    }
  });

  it("n'écrit aucune couleur en dur hors des jetons", () => {
    // Une couleur écrite ailleurs que dans `tokens.css` échappe à la source
    // unique : elle ne suivra pas quand le jeton bougera. Seul le blanc pur
    // est toléré — c'est l'encre posée sur un fond encre, jamais un fond.
    // `rgba()` compte aussi : la barre haute y recopiait `--ground`.
    const outside = ["base.css", "app.css", "workspace.css"].map(sheet).join("\n");
    const hex = [...outside.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0]);
    expect(hex.filter((c) => c.toLowerCase() !== "#fff")).toEqual([]);
    expect(outside).not.toMatch(/\brgba?\(/);
  });

  it("importe les quatre feuilles, dans l'ordre", () => {
    const globals = read("app/globals.css");
    const order = ["tokens.css", "base.css", "app.css", "workspace.css"]
      .map((name) => globals.indexOf(name));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("ne nomme aucun modificateur de colonne comme un composant du socle", () => {
    // `.m-col.facts` percutait `.facts`, la liste clé/valeur du socle, qui
    // est une grille : la colonne mémoire de l'atelier en héritait sans que
    // personne l'ait voulu, et ses enfants s'espaçaient tout seuls. Le
    // défaut a traversé la revue finale — il ne se voit qu'à l'écran.
    const composants = new Set([
      ...sheet("app.css").matchAll(/^\.([a-z][\w-]*)/gm),
      ...sheet("base.css").matchAll(/^\.([a-z][\w-]*)/gm),
    ].map((m) => m[1]));
    const modificateurs = [...sheet("workspace.css").matchAll(/\.m-col\.([a-z-]+)/g)]
      .map((m) => m[1]);

    expect(modificateurs.filter((nom) => composants.has(nom))).toEqual([]);
  });

  it("n'a plus d'échafaudage", () => {
    const globals = read("app/globals.css");
    expect(globals).not.toContain("legacy");
    expect(() => sheet("legacy.css")).toThrow();
  });

  it("ne pose aucune classe qui n'ait de règle nulle part", () => {
    // Le portage retire des classes de l'échafaudage tâche après tâche. Une
    // classe retirée mais encore posée s'affiche nue, sans qu'aucun test ne
    // bronche : jsdom n'applique pas les feuilles. Celui-ci bronche.
    const used = new Map<string, string>();
    for (const f of [...filesUnder("app", ".tsx"), ...filesUnder("components", ".tsx")]) {
      read(f).split("\n").forEach((line, i) => {
        for (const m of line.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
          const isTemplate = m[2] !== undefined;
          for (const name of literalClasses(m[1] ?? m[2] ?? "", isTemplate)) {
            if (CLASS_NAME.test(name) && !used.has(name)) used.set(name, `${f}:${i + 1}`);
          }
        }
      });
    }

    const defined = new Set<string>();
    for (const f of filesUnder("styles", ".css")) {
      for (const m of read(f).matchAll(/\.([A-Za-z][\w-]*)/g)) defined.add(m[1]);
    }

    const orphans = [...used].filter(([name]) => !defined.has(name))
      .map(([name, where]) => `${name} (${where})`);
    expect(orphans).toEqual([]);
  });
});
