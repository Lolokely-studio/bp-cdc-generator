# Esquisse

Génère un cahier des charges et un business plan à partir d'une idée de projet,
en posant des questions ciblées plutôt qu'en demandant de remplir un formulaire.

### En deux mots

Un porteur de projet décrit son idée en quelques phrases. L'agent en extrait ce
qu'il peut, demande le reste, rédige les sections une à une, se relit, et ne
dérange l'utilisateur que lorsque sa relecture n'est pas satisfaite. À la fin,
quatre fichiers : le cahier des charges et le business plan, en Word et en PDF.

### Documents de référence

| Document | Ce qu'il contient |
|---|---|
| [docs/mockup.html](docs/mockup.html) | Prototype cliquable, workflow en 18 étapes, stack technique. À ouvrir dans un navigateur. |
| [docs/analyse-cdc-bp.md](docs/analyse-cdc-bp.md) | Ce que doivent contenir les deux documents, d'après les normes et d'après de vrais documents. Sources en fin de page. |
| [docs/templates/](docs/templates/) | 30 sections et 74 faits, en YAML. Le cœur de valeur du produit. |
| [docs/spec-implementation.md](docs/spec-implementation.md) | Spécification technique. |
| [docs/plans/](docs/plans/) | Feuille de route et plans d'implémentation. |

### Démarrer

Prérequis : Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
docker compose up -d db          # base de développement et de test
cd api && uv sync                # dépendances
uv run alembic upgrade head      # migrations
uv run uvicorn esquisse.app:app --reload --port 8000
```

`curl localhost:8000/health` doit répondre `{"statut":"ok"}`.

### Tests

```bash
cd api && uv run pytest -v
```

Les tests utilisent la base jetable de `docker-compose.yml`, jamais la base
distante. Aucun test ne joint un fournisseur de modèle.

### Configuration

Copier `.env.example` en `.env` à la racine et le remplir. Le fichier `.env`
n'est jamais versionné.

### Comptes

L'inscription est ouverte, mais un compte créé n'est pas utilisable. Le drapeau
`is_active` se bascule à la main dans la base :

```sql
update users set is_active = true where email = 'quelquun@exemple.fr';
```

C'est volontaire : la génération repose sur des paliers gratuits dont les quotas
sont journaliers et partagés. Une inscription libre les épuiserait en une matinée.

### Conventions

Les identifiants du code — fonctions, classes, modules, fichiers — sont en
anglais. Les commentaires, les docstrings et la documentation sont en français.

Dépendances gérées par `uv`, jamais `pip`. `pyproject.toml` déclare, `uv.lock`
verrouille, les deux sont versionnés. Toute commande passe par `uv run`.
