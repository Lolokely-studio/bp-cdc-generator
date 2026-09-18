# Esquisse — feuille de route d'implémentation

> 17 septembre 2026. Découpage de [../spec-implementation.md](../spec-implementation.md) en plans exécutables.
> Le périmètre n'est pas réduit : c'est le document qui est découpé, pas le produit.

## Pourquoi six plans et non un seul

Un plan d'implémentation vaut par sa précision — chemins exacts, code de test réel, signatures vérifiables. Cette précision se périme. Un plan de deux cents tâches écrit aujourd'hui serait faux à partir de la centième, parce que les cent premières auront appris quelque chose.

Chaque plan ci-dessous produit un logiciel qui tourne et qui se teste seul. On écrit le suivant quand le précédent est fini, en connaissance de ce qu'il a révélé.

## Ordre et dépendances

```
1. Socle backend ──┬── 2. Couche modèles ──┐
                   │                        ├── 3. L'agent ── 4. API projet et flux
                   └────────────────────────┘                        │
                                                    5. Export ───────┤
                                                                     │
                                                    6. Interface ────┘
```

| # | Plan | Ce qui tourne à la fin | Dépend de |
|---|---|---|---|
| 1 | **Socle backend** | Une API qui démarre, une base migrée, inscription et connexion qui marchent, un compte inactif refusé, un projet d'un autre utilisateur introuvable | — |
| 2 | **Couche modèles** | Les trois routes, les compteurs de quota, la bascule préventive et le repli, un modèle simulé déterministe. Testable sans réseau | 1 |
| 3 | **L'agent** | Le graphe complet : 30 sections rédigées de bout en bout avec le modèle simulé, sans interface | 1, 2 |
| 4 | **API projet et flux** | Les routes de projet, les interruptions exposées en HTTP, le flux SSE, la reprise après redémarrage | 3 |
| 5 | **Export** | Word et PDF produits depuis les blocs structurés, déposés au stockage, servis par lien signé | 3 |
| 6 | **Interface** | Le parcours de la maquette, en vrai | 4, 5 |

## Conventions d'exécution, valables pour tous les plans

Tirées de l'exécution du plan 1, où elles ont manqué.

**Un seul commit de plan par tâche.** Quand une relecture trouve un défaut dans
le code que le plan impose, le plan se corrige — sinon le brief régénéré fait
réécrire le même défaut à la tâche suivante. Mais ces corrections se groupent
par tâche, en un commit, et non une par constat. Le plan 1 en a produit dix-huit
sur un seul fichier, ce qui noie l'historique du code dans du bruit de
documentation.

**Corriger le plan et le brief dans le même geste.** Deux fois pendant le plan 1,
le brief a été régénéré sans que le plan soit corrigé, ou l'inverse. Les deux
divergences portaient sur des protections réelles — l'affectation ferme des
variables de test, un nom de test. Le plan est la source, le brief en dérive :
l'un sans l'autre est une régression silencieuse.

**Vérifier le plan avant de l'exécuter, pas pendant.** Trois contrôles qui
auraient épargné des tours de correction au plan 1, à passer une fois le plan
écrit :
- analyse syntaxique de chaque bloc de code (`ast.parse`), qui attrape les
  fragments incohérents ;
- balayage des identifiants, pour que les conventions de nommage soient tenues
  partout et pas seulement dans les définitions ;
- audit croisé des renvois entre tâches — ce qu'une tâche produit contre ce que
  la suivante consomme, nom par nom.

**Ne jamais laisser une édition du plan non commitée pendant qu'un sous-agent
travaille.** Deux fois, un agent a nettoyé l'arbre de travail et effacé des
modifications en cours sur un fichier qui ne le concernait pas. Les dispatches
interdisent désormais explicitement `git checkout`, `restore`, `stash`, `clean`
et `reset`, mais la vraie protection est de commiter avant de dispatcher.

## Ce qui n'est dans aucun plan

Relecture des consignes et des grilles des 30 sections, plafond par compte, réinitialisation de mot de passe, interface d'administration. Ce sont des décisions ouvertes listées au §12 de la spec, pas des tâches en attente.

## État

- [x] Plan 1 — **livré et fusionné** : [2026-09-17-01-socle-backend.md](2026-09-17-01-socle-backend.md) — 59 tests
- [x] Restructuration — **livrée et fusionnée** : [2026-09-18-02-restructuration.md](2026-09-18-02-restructuration.md)
- [x] Plan 2 — **livré et fusionné** : [2026-09-18-03-couche-modeles.md](2026-09-18-03-couche-modeles.md) — 149 tests
      Cinq fournisseurs derrière un seul adaptateur compatible OpenAI, trois routes,
      compteurs sur `llm_usage`, bascule préventive, repli, modèle simulé déterministe.
      Le catalogue Mistral a été mesuré sur la clé réelle : la famille `mistral-small`
      répond 429 dès le premier appel, `ministral-8b` et `ministral-3b` répondent.
- [ ] Plan 3
- [ ] Plan 4
- [ ] Plan 5
- [ ] Plan 6
