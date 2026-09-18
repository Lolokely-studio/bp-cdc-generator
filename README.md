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
| [backend/app/templates/](backend/app/templates/) | 30 sections et 74 faits, en YAML. Le cœur de valeur du produit. |
| [docs/spec-implementation.md](docs/spec-implementation.md) | Spécification technique. |
| [docs/plans/](docs/plans/) | Feuille de route et plans d'implémentation. |

### Démarrer

Prérequis : Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
cd backend
uv sync                          # dépendances
docker compose up -d db          # base de développement et de test
uv run alembic upgrade head      # migrations
uv run uvicorn app.main:app --reload --port 8000
```

Ces commandes visent la base jetable de `docker-compose.yml`, qui est aussi la
valeur par défaut de la configuration : **sans fichier `.env`, tout fonctionne
en local sans rien régler.**

Si vous placez un `.env` dans `backend/`, il l'emporte sur ces valeurs par
défaut. S'il pointe vers une base distante, `alembic upgrade head` refusera de
s'exécuter en nommant l'hôte — c'est voulu, voir « Déployer ». Gardez donc des
valeurs locales dans votre `.env`, ou pas de `.env` du tout : les identifiants
de production se renseignent dans le tableau de bord de l'hébergeur, pas sur
votre disque.

`curl localhost:8000/health` doit répondre `{"statut":"ok"}`.

### Déployer

Les migrations ne tournent pas au démarrage du conteneur : appliquer un schéma
sur la base réelle est un geste délibéré, pas un effet de bord d'un réveil.
Avant un déploiement qui change le schéma, depuis votre poste :

```bash
cd backend && ESQUISSE_ALLOW_REMOTE_MIGRATIONS=1 uv run alembic upgrade head
```

Sans cette variable, la commande refuse de s'exécuter contre autre chose qu'une
base locale, et nomme l'hôte qu'elle a refusé.

### Tests

```bash
cd backend && uv run pytest -v
```

Les tests utilisent la base jetable de `docker-compose.yml`, jamais la base
distante. Aucun test ne joint un fournisseur de modèle.

### Configuration

Copier `backend/.env.example` en `backend/.env` et le remplir. Le fichier
`.env` n'est jamais versionné.

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

## Déploiement sur Render

Le Blueprint est `backend/render.yaml`, pas `render.yaml` : Render le cherche
à la racine par défaut, il faut donc renseigner **Blueprint Path** =
`backend/render.yaml` à la création du Blueprint.

Les chemins qu'il contient — `dockerfilePath`, `dockerContext` — restent
relatifs à la **racine du dépôt** et non au fichier : c'est pourquoi ils
commencent par `./backend/`.

Les variables marquées `sync: false` se saisissent dans le tableau de bord du
service. Aucun identifiant de production ne vit dans le dépôt.
