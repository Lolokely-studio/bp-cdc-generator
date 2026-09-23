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
| [backend/app/templates/](backend/app/templates/) | 30 sections et 75 faits, en YAML. Le cœur de valeur du produit. |
| [docs/spec-implementation.md](docs/spec-implementation.md) | Spécification technique. |
| [docs/plans/](docs/plans/) | Feuille de route et plans d'implémentation. |
| [web/](web/) | L'application Next.js, l'interface — voir « Le front » plus bas. |

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
cd backend && uv run pytest -q
```

563 tests (6 désélectionnés), en moins d'une minute. Ils utilisent la base
jetable de `docker-compose.yml`, jamais la base distante, et aucun ne joint
un fournisseur de modèle ni le stockage : les tests marqués `network` sont
exclus par défaut (voir « La couche modèles »).

### Configuration

Copier `backend/.env.example` en `backend/.env` et le remplir. Le fichier
`.env` n'est jamais versionné.

## La couche modèles

Cinq fournisseurs gratuits, tous compatibles avec l'API Chat Completions
d'OpenAI : un seul adaptateur, cinq URL de base. Un appelant demande une
**capacité**, pas un fournisseur :

```python
from app.llm.gateway import complete, stream
from app.llm.types import Message

reponse = await complete("court", [Message("user", "…")], schema=MonSchema)
async for evenement in stream("redaction", messages, project_id=pid):
    ...
```

Les trois routes — `court`, `redaction`, `grand_contexte` — et les quotas de
chaque palier vivent dans `app/llm/providers.py`. Ce sont des réglages : les
offres gratuites bougent, et les quotas plus vite que le reste.

**Développer sans réseau.** `ESQUISSE_FAKE_LLM=true` dans le `.env` remplace
le transport par un modèle simulé déterministe. La sélection de route et
l'écriture de `llm_usage` restent les mêmes ; les lignes s'écrivent sous le
nom de fournisseur `fake`, sans toucher aux compteurs réels.

**Vérifier que les modèles existent encore.** Un modèle gratuit peut
disparaître sans préavis. La campagne réseau, exclue de la suite ordinaire,
interroge chaque modèle du catalogue :

```bash
ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network -v
```

## L'agent

Un graphe LangGraph, dans `app/agent/`, conduit l'entretien section par
section : il extrait de l'idée ce qu'il peut, pose un lot de questions quand un
fait requis manque, calcule ce qui se calcule (dix calculs financiers dans
`finance.py`, jamais confiés au modèle), rédige, se relit et ne soumet une
section à l'utilisateur que si sa note est basse ou si le gabarit l'exige.
L'état complet vit dans un point de reprise PostgreSQL, qui fait foi ; les
tables `facts` et `sections` n'en sont que des projections, pour l'affichage.

## L'API

| Route | Rôle |
|---|---|
| `POST /projects` | Crée le projet et démarre son run en tâche de fond |
| `GET /projects`, `GET /projects/{id}` | La liste du propriétaire, l'entête d'un projet |
| `GET /projects/{id}/state` | Plan, faits, sections, interaction en attente |
| `POST /projects/{id}/answer` | Répond à l'interaction en cours et relance le run |
| `GET /projects/{id}/stream` | Le flux SSE de la rédaction |
| `POST /projects/{id}/resume` | Relance un run mort (après un plantage ou un redémarrage) |
| `POST /projects/{id}/sections/{sid}/reopen` | Rouvre une section et celles qui en dépendent |

Un projet qui n'appartient pas à l'appelant répond toujours `404`, jamais
`403`, avec le même corps qu'un projet inexistant.

**Un run ne vit jamais dans une requête HTTP.** Il avance dans une tâche de
fond et publie sur un bus d'événements en mémoire ; le flux SSE s'y abonne.
Une connexion coupée ne perd rien : le front se reconnecte et relit `/state`.
Trois comportements que le front doit connaître :

- `/answer` renvoie **`409 run_deja_en_cours`** quand une reprise avance
  déjà ; le front relit `/state` et renvoie sa réponse si l'interaction est
  toujours la même ;
- `/state` peut montrer un instant `run_status: waiting` avec
  `interaction: null`, pendant qu'une réponse est consommée ; le front relit ;
- au démarrage, l'application passe à `failed` les runs qu'aucune tâche ne
  pilote plus, et `/resume` les relance.

**Une seule instance.** Le bus et le registre des runs vivent en mémoire du
processus : la commande de démarrage fixe `--workers 1`. Voir aussi le risque
de déploiement plus bas.

## L'export

Chaque document sort en Word et en PDF, depuis les blocs structurés et jamais
depuis le texte affiché. Le Word part d'un modèle, `app/export/templates/model.docx`,
que l'on peut remplacer par un fichier refait dans Word tant qu'il garde les
balises `{{ title }}`, `{{ draft_notice }}` et `{{p body }}`. Le PDF vient de
Gotenberg ; s'il échoue, un PDF est produit depuis du HTML, et l'utilisateur
voit qu'il n'est plus identique au Word. Les fichiers sont déposés dans un
bucket Supabase **privé** et servis par lien signé de dix minutes.

Il faut pour cela, dans `backend/.env` : `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY` (qui ne quitte jamais le serveur) et
`SUPABASE_BUCKET_NAME`.

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

**Deux services.** L'API, et Gotenberg pour la conversion en PDF. Les services
privés sont payants chez Render : Gotenberg est donc un service web public,
protégé par son authentification de base. Tous deux s'endorment après quinze
minutes ; Gotenberg n'est réveillé qu'à l'export. Ne mettez jamais en place de
ping pour les garder éveillés : les 750 heures gratuites du mois sont
partagées entre les services, et un seul service allumé en permanence les
épuise.

**Risque accepté : ne pas déployer pendant qu'un run est actif.** Pendant un
déploiement, l'ancienne et la nouvelle instance tournent ensemble environ
90 secondes, et la nouvelle passerait à `failed` les runs vivants de
l'ancienne. Sans utilisateur réel, le risque est nul ; il doit être traité
avant la mise en service (spec §9.2).

## Le front

`web/` est une application Next.js 16, hébergée sur Vercel, qui parle
directement au backend : le jeton de session voyage dans l'en-tête
`Authorization`, et la rédaction se suit par un flux SSE lu avec `fetch`
(`EventSource` ne sait pas envoyer d'en-tête).

```bash
cd web
npm ci
cp .env.example .env.local     # NEXT_PUBLIC_API_URL, lue à la construction
npm run dev                    # http://localhost:3001
npm run typecheck && npm test  # typage et tests unitaires
npm run e2e                    # parcours complet, backend et front démarrés par Playwright
```

Le port 3001 n'est pas un caprice : Gotenberg occupe le 3000 en local.

**Ce que la pile ne contient pas.** L'onglet Stack de la maquette annonçait
Tailwind, shadcn/ui et React Hook Form. Le style retenu est celui de la
maquette elle-même, écrit en classes `.m-*` sur des variables CSS : les
reprendre telles quelles est plus fidèle et plus court que les traduire, et
des formulaires de trois champs n'ont pas besoin d'une bibliothèque. Zod
reste, pour valider chaque réponse de l'API contre son contrat.

**Un compte pour développer.** L'activation d'un compte se fait à la main
dans la base (§3.2). Sur la base jetable, le script s'en charge :

```bash
cd backend
SUPABASE_DB_HOST=localhost SUPABASE_DB_PORT=5433 SUPABASE_DB_USER=esquisse \
SUPABASE_DB_PASSWORD=esquisse SUPABASE_DB_NAME=esquisse_test \
uv run python -m app.auth.seed moi@exemple.fr "un mot de passe"
```

Il refuse toute base qui n'est pas locale.

**Déploiement sur Vercel.** Racine du projet : `web/`. Une seule variable,
`NEXT_PUBLIC_API_URL`, qui porte l'adresse du service Render. Elle est
inscrite dans le code envoyé au navigateur au moment de la construction :
la changer demande un redéploiement. En face, le service Render doit porter
`CORS_ORIGINS` avec le domaine Vercel, sans quoi le navigateur bloque chaque
appel.

**Ce que le front ne fait jamais :** appeler `/health` en boucle pour tenir
le backend éveillé. Les 750 heures d'instance mensuelles sont partagées
entre les services (§9.4) ; le réveil se traite par un écran d'attente, et
le flux SSE se ferme dès que le run cesse d'avancer.

### Tests de bout en bout

```bash
cd web && npm run e2e
```

Playwright démarre lui-même le backend (port 8100) et le front (port 3101,
construit à neuf) : jamais le serveur de développement du poste, qui lirait
`backend/.env` et donc les vrais identifiants. Trois parcours, un modèle
simulé, jamais la vraie base ni le vrai stockage. Le premier mène quatorze
sections jusqu'au bout, avec une relecture passée, un arbitrage, un export
qui échoue faute de stockage configuré (voulu — l'écran doit le dire), puis
une réouverture qui réécrit une section : sous la minute ici avec le modèle
simulé, d'où le délai de dix minutes prévu dans `playwright.config.ts` pour
une machine plus lente.
