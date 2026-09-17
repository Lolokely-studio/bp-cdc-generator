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

## Ce qui n'est dans aucun plan

Relecture des consignes et des grilles des 30 sections, plafond par compte, réinitialisation de mot de passe, interface d'administration. Ce sont des décisions ouvertes listées au §12 de la spec, pas des tâches en attente.

## État

- [x] Plan 1 — écrit : [2026-09-17-01-socle-backend.md](2026-09-17-01-socle-backend.md)
- [ ] Plan 2 — à écrire quand le plan 1 est terminé
- [ ] Plan 3
- [ ] Plan 4
- [ ] Plan 5
- [ ] Plan 6
