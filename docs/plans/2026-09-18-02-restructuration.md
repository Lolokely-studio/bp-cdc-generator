# Restructuration du dépôt — plan d'implémentation

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE REQUISE — `superpowers:subagent-driven-development`.
> Les cases `- [ ]` servent au suivi.

**But :** mettre l'arborescence dans sa forme cible avant que les plans 2 à 6 n'y ajoutent du code, pour que les déplacements coûtent une heure maintenant plutôt qu'une journée plus tard.

**Architecture :** aucun changement de comportement. Uniquement des déplacements de fichiers et les mises à jour de chemins qui en découlent. La suite de 59 tests est le garde-fou : elle couvre tous les imports touchés.

**Pile :** inchangée.

**Spec :** [../spec-implementation.md](../spec-implementation.md)

## Contraintes globales

- **Aucun changement de comportement.** Si un test doit être modifié autrement que pour un chemin ou un nom de paquet, c'est qu'un déplacement a dérapé.
- **59 tests avant, 59 tests après.** Ni plus, ni moins.
- **`git mv`, jamais `mv`**, pour que l'historique suive.
- **Aucun `git checkout`, `restore`, `stash`, `clean` ni `reset`.**
- Identifiants du code en anglais, commentaires et docstrings en français.
- Les colonnes SQL, clés JSON et codes d'erreur ne bougent pas.

## Cible

```
backend/                        ← ex api/
├── pyproject.toml, uv.lock, alembic.ini, Dockerfile, .dockerignore
├── migrations/
├── app/                        ← ex esquisse/
│   ├── main.py                 ← ex app.py (évite `app.app:app`)
│   ├── core/                   ← config, db, security, rate_limit, safety
│   ├── auth/
│   ├── projects/
│   └── templates/              ← ex docs/templates/
└── tests/

docs/
├── spec-implementation.md, analyse-cdc-bp.md, mockup.html
├── plans/
└── archives/design/            ← ex docs/design/
```

---

## Tâche 1 : déplacer, en une fois

**Fichiers :** tout `api/`, `docs/templates/`, `docs/design/`.

- [ ] **Étape 1 : relever l'état de départ**

```bash
cd api && uv run pytest -q | tail -1   # doit afficher 59 passed
```

- [ ] **Étape 2 : les déplacements**

```bash
cd "$(git rev-parse --show-toplevel)"
git mv api backend
git mv backend/esquisse backend/app
git mv backend/app/app.py backend/app/main.py
mkdir -p backend/app/core
for f in config db security rate_limit safety; do git mv backend/app/$f.py backend/app/core/$f.py; done
touch backend/app/core/__init__.py && git add backend/app/core/__init__.py
git mv docs/templates backend/app/templates
mkdir -p docs/archives && git mv docs/design docs/archives/design
```

- [ ] **Étape 3 : les chemins qui en dépendent**

Quatre corrections ne se déduisent pas d'un simple remplacement de texte :

1. `backend/app/core/config.py` — `_REPO_ROOT` passait par `parents[2]` depuis `api/esquisse/`. Depuis `backend/app/core/` il faut **`parents[3]`**. Vérifier en affichant la valeur, pas en comptant de tête.
2. `backend/tests/test_isolation.py` — le chemin du paquet inspecté : `parents[1] / "esquisse"` devient `parents[1] / "app"`, et le fichier autorisé suit.
3. `backend/Dockerfile` — la commande devient `uvicorn app.main:app`.
4. `backend/tests/conftest.py` — `api_root = parents[1]` reste juste, il désigne `backend/`. Ne pas y toucher.

Puis le remplacement mécanique de `esquisse` par `app` dans les imports de `backend/app/` et `backend/tests/`, et de `api` par `backend` dans `render.yaml`, `.github/workflows/ci.yml`, `README.md` et `docker-compose.yml` s'il y figure.

Attention : `esquisse` apparaît aussi comme **valeur** — identifiant de base et d'utilisateur PostgreSQL dans `conftest.py`, `docker-compose.yml` et l'intégration continue, nom du projet dans `pyproject.toml`, préfixe de `ESQUISSE_ALLOW_REMOTE_MIGRATIONS` et `ESQUISSE_FAKE_LLM`, et `esquisse.test` dans le test de `SET LOCAL`. Aucune de ces occurrences ne change. Seuls changent les chemins d'import.

- [ ] **Étape 4 : les liens de la documentation**

`docs/analyse-cdc-bp.md` pointe vers `docs/templates/` ; `README.md` aussi. Les deux deviennent `backend/app/templates/`. Le README mentionne `api/` dans ses commandes : elles deviennent `backend/`.

- [ ] **Étape 5 : vérifier**

```bash
cd backend && uv run pytest -q | tail -1        # 59 passed
uv run alembic upgrade head                      # doit passer sur la base locale
docker build -t esquisse-api .                   # doit réussir
grep -rn "\bapi/" ../README.md ../render.yaml ../.github/workflows/ci.yml   # doit être vide
grep -rn "from esquisse\|import esquisse" app tests                          # doit être vide
```

Et vérifier que `_REPO_ROOT` tombe bien sur la racine :

```bash
cd backend && uv run python -c "from app.core.config import _REPO_ROOT; print(_REPO_ROOT)"
```

Attendu : le chemin de la racine du dépôt, pas `backend/`.

- [ ] **Étape 6 : commiter**

```bash
git add -A
git commit -m "refactor: arborescence cible (backend/, paquet app, templates dans le paquet)"
```

---

## Ce que ce plan ne fait pas

`.env`, `.env.example`, `docker-compose.yml` et `render.yaml` restent à la racine. Le premier porte des clés que le service d'export du plan 5 lira aussi ; le troisième orchestrera le backend et Gotenberg au plan 5 ; le quatrième décrit plusieurs services.

## À traiter dans la foulée, pendant qu'on est dans les tests

Un résidu de la relecture finale du plan 1, parqué et à solder ici puisque cette tâche touche déjà les tests :

`test_rate_limit_separates_distinct_forwarded_addresses` n'emploie que des en-têtes `X-Forwarded-For` à une seule entrée. Il passe donc aussi bien sous une implémentation qui prendrait la première entrée que sous celle qui prend la dernière : il ne discrimine pas. Lui donner deux entrées avec des dernières valeurs différentes, comme le fait son jumeau.
