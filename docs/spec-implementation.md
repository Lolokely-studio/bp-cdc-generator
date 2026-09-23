# Esquisse — spécification d'implémentation

> 17 septembre 2026. Décrit ce qu'il faut construire, pas comment on s'y prendra :
> le découpage en tâches fait l'objet d'un plan séparé.
>
> Le cadrage métier est dans [analyse-cdc-bp.md](analyse-cdc-bp.md), les templates dans
> [templates/](templates/), le parcours et l'architecture dans [mockup.html](mockup.html).
> Cette spec ne les répète pas, elle s'y adosse.

---

## 1. Périmètre

**Dans le périmètre.** Un parcours complet et unique : création de compte, connexion, saisie d'une idée, questions ciblées, rédaction des 30 sections avec relecture sélective, contrôle de cohérence, export Word et PDF des deux documents.

**Hors périmètre, explicitement.** Facturation et paiement. Collaboration à plusieurs sur un projet. Historique des versions d'une section au-delà du dernier état. Recherche web pour alimenter les faits. Interface d'administration : l'activation d'un compte se fait à la main dans la base.

**Contraintes structurantes.** Tout tient sur des paliers gratuits. Un développeur. L'hébergement du backend s'endort après quinze minutes sans trafic et redémarre sans prévenir : la reprise n'est pas une fonctionnalité de confort, c'est une condition de fonctionnement.

---

## 2. Modèle de données

PostgreSQL 17, joint par le pooler Supabase en mode transaction (port 6543). Migrations par Alembic. Schéma `public`.

### 2.1 Tables

```sql
users
  id              uuid primary key default gen_random_uuid()
  email           citext not null unique
  password_hash   text not null           -- argon2id
  is_active       boolean not null default false
  created_at      timestamptz not null default now()
  last_login_at   timestamptz

sessions
  token_hash      bytea primary key       -- sha256 du jeton opaque
  user_id         uuid not null references users(id) on delete cascade
  created_at      timestamptz not null default now()
  expires_at      timestamptz not null
  revoked_at      timestamptz
  index (user_id)

projects
  id              uuid primary key default gen_random_uuid()
  user_id         uuid not null references users(id) on delete cascade
  nom             text not null
  documents       text not null           -- cdc | bp | both
  profil_cdc      text                    -- consultation | cadrage
  profil_bp       text                    -- banque | investisseur
  thread_id       text not null unique    -- thread LangGraph
  run_status      text not null default 'idle'  -- idle | running | waiting | failed | done
  templates_version text not null
  created_at      timestamptz not null default now()
  updated_at      timestamptz not null default now()
  index (user_id, updated_at desc)

facts
  project_id      uuid not null references projects(id) on delete cascade
  fact_id         text not null           -- clé du catalogue
  valeur          jsonb                   -- null si « je ne sais pas »
  source          text not null           -- user | deduced | unknown
  confiance       real                    -- seulement si source = deduced
  updated_at      timestamptz not null default now()
  primary key (project_id, fact_id)

sections
  project_id      uuid not null references projects(id) on delete cascade
  section_id      text not null           -- clé du template
  document        text not null           -- cdc | bp
  ordre           int not null            -- position dans le plan calculé
  statut          text not null default 'pending'
                  -- pending | questions | drafting | review | validated | skipped
  contenu         jsonb                   -- blocs structurés, pas du HTML
  note            int
  revisions       int not null default 0
  valide_par      text                    -- auto | user
  valide_le       timestamptz
  primary key (project_id, section_id)
  index (project_id, ordre)

exports
  id              uuid primary key default gen_random_uuid()
  project_id      uuid not null references projects(id) on delete cascade
  document        text not null           -- cdc | bp
  format          text not null           -- docx | pdf
  storage_path    text not null
  brouillon       boolean not null default false   -- filigrane si sections passées
  created_at      timestamptz not null default now()
  index (project_id)

llm_usage
  id              bigserial primary key
  fournisseur     text not null
  modele          text not null
  route           text not null           -- court | redaction | grand_contexte
  project_id      uuid references projects(id) on delete set null
  requetes        int not null default 1
  tokens          int not null default 0
  issue           text not null           -- ok | quota | erreur | timeout
  at              timestamptz not null default now()
  index (fournisseur, at desc)
```

LangGraph crée en plus ses propres tables de points de reprise. Elles grossissent vite : voir §9.3.

### 2.2 Cloisonnement

L'authentification n'étant pas celle de Supabase, `auth.uid()` n'existe pas et les politiques de sécurité au niveau des lignes ne peuvent pas s'y adosser. **Le cloisonnement est porté par l'API.**

Une seule fonction y donne accès :

```python
async def projet_de_lutilisateur(conn, project_id: UUID, user_id: UUID) -> Projet:
    """Renvoie le projet, ou lève NotFound. Jamais Forbidden :
    un projet qui ne vous appartient pas n'existe pas."""
```

Aucune route ne lit `projects` autrement. Un test vérifie qu'aucune requête SQL du dépôt ne mentionne `from projects` hors de ce module.

Des politiques de ligne pourront être ajoutées plus tard en seconde barrière, en posant l'identifiant en `SET LOCAL` au début de chaque transaction — seul mécanisme sûr avec un pooler en mode transaction (voir §9.1).

---

## 3. Comptes et sessions

### 3.1 Jetons opaques, pas de JWT

Le drapeau `is_active` est basculé à la main dans la base et doit prendre effet **immédiatement**. Un jeton auto-porté resterait valable jusqu'à son expiration, y compris après désactivation d'un compte. On retient donc un **jeton opaque de 32 octets aléatoires**, dont seule l'empreinte SHA-256 est stockée, vérifié en base à chaque requête.

Le coût est d'une requête indexée par appel, négligeable aux volumes visés, et la révocation est instantanée.

### 3.2 Parcours

| Route | Comportement |
|---|---|
| `POST /auth/register` | Crée le compte avec `is_active = false`. Répond `201` avec un corps qui dit explicitement que le compte attend son activation. Réponse identique si l'adresse existe déjà : on ne révèle pas qui est inscrit. |
| `POST /auth/login` | `200` et un jeton si le mot de passe est bon **et** le compte actif. `403 compte_inactif` si le compte existe, est valide, mais n'est pas activé. `401` sinon. |
| `POST /auth/logout` | Marque la session révoquée. |
| `GET /me` | Renvoie l'adresse et l'état d'activation. |

Empreintes par **argon2id**. Limitation de débit sur `register` et `login` : dix tentatives par adresse IP et par quart d'heure, en mémoire du processus — suffisant pour une instance unique, à revoir si le service passe à plusieurs.

Réinitialisation de mot de passe : hors périmètre de la première version. Un mot de passe perdu se remet à la main dans la base, comme l'activation.

---

## 4. L'agent

### 4.1 État

```python
class EtatEsquisse(TypedDict):
    project_id: str
    documents: Literal["cdc", "bp", "both"]
    profil_cdc: Literal["consultation", "cadrage"] | None
    profil_bp: Literal["banque", "investisseur"] | None

    idee: str
    faits: Annotated[dict[str, Fait], fusionner_faits]
    plan: list[RefSection]
    curseur: int

    brouillon: list[Bloc] | None
    note: int | None
    problemes: list[str]
    revisions: int
    tours_questions: int
    calculs: dict[str, Any]

    incoherences: list[Incoherence]
```

`Fait`, `Bloc`, `RefSection` et `Incoherence` sont des modèles Pydantic. Le contenu d'une section est une **liste de blocs typés** — paragraphe, tableau, liste, marqueur à compléter — jamais du HTML ni du Markdown : l'export Word part de cette structure, pas du texte affiché.

### 4.2 Le réducteur de faits

C'est la pièce la plus sensible de l'état, et la seule règle non triviale :

```python
def fusionner_faits(actuel, nouveaux):
    """Fusionne sans écraser. Un fait dont la source est « user » ne peut être
    remplacé que par un autre fait « user ». Un fait déduit cède devant une
    réponse de l'utilisateur. Un « je ne sais pas » est une valeur, pas une absence :
    il empêche de reposer la question et devient une hypothèse déclarée dans le texte."""
```

Trois invariants, chacun couvert par un test :
1. Une déduction n'écrase jamais une réponse.
2. Un fait répondu n'est plus jamais demandé, ni pour le cahier des charges ni pour le business plan.
3. Modifier un fait marque à rouvrir toutes les sections que `utilise_par` désigne, et elles seules.

### 4.3 Nœuds

Les dix-huit étapes de l'onglet Workflow se traduisent en nœuds. Trois points d'implémentation méritent d'être fixés ici.

**Formulation et pause sont deux nœuds.** `formuler_questions` appelle le modèle, `poser_questions` interrompt. À la reprise, LangGraph rejoue le nœud interrompu et lui seul : l'appel au modèle n'est jamais facturé deux fois.

**Le vérificateur de chiffres est déterministe.** Il extrait les nombres du brouillon par expression régulière et vérifie que chacun figure parmi les faits de type numérique ou parmi les sorties des calculs outillés. Aucun appel au modèle. C'est ce nœud qui rend tenable le choix de ne pas utiliser la recherche web.

**Les calculs sont des outils Python purs.** Le modèle structure les hypothèses, il ne calcule rien : `tam_sam_som`, `marge_unitaire`, `tableau_investissements`, `compte_resultat_3ans`, `plan_tresorerie_12mois`, `seuil_rentabilite`, `point_mort`, `plan_financement_initial`, `plan_financement_3ans`, `annuites_credit`. Chacun prend des hypothèses validées par un schéma et rend des tableaux. Chacun a ses valeurs de référence en test.

### 4.4 Arêtes conditionnelles

```
analyser_manques
  faits requis manquants et tours_questions < 2  → formuler_questions
  section déclarant des calculs dans son template → calculs
  sinon                                          → rediger

verifier_chiffres
  chiffre orphelin et revisions < 2              → rediger
  sinon                                          → critiquer

critiquer
  note < 7 et revisions < 2                      → rediger
  validation == "toujours" ou note < 8           → relire        (interruption)
  sinon                                          → enregistrer

enregistrer
  curseur < len(plan)                            → analyser_manques
  sinon                                          → controle_coherence
```

Les deux seuils font deux choses différentes et ne doivent pas être confondus : **sous 7 la machine réécrit**, **sous 8 après cela elle réveille l'utilisateur**. Ils sont lus depuis `seuil_relecture` dans les templates, pas codés en dur.

### 4.5 Interruptions

Cinq points d'arrêt : documents et profils, saisie de l'idée, lot de questions, relecture d'une section (conditionnelle), arbitrage des incohérences. Chacun appelle `interrupt()` avec une charge utile typée que le front sait afficher.

La relecture porte aussi les blocs du brouillon, pour qu'un navigateur rechargé pendant une relecture ait quelque chose à montrer, et accepte trois réponses : `{"action": "accept"}`, `{"action": "rewrite", "problems": [...]}` et `{"action": "skip"}` — la section est alors enregistrée `skipped` et les documents portent la mention Brouillon (§7).

L'arbitrage des incohérences prend une liste de décisions, `{"index": 0, "decision": "corriger", "consigne": "…"}` ou `{"index": 1, "decision": "ignorer"}`. Une correction met en file de réécriture les sections que l'incohérence nomme ; le run les reprend avant de s'arrêter, sans refaire le contrôle de cohérence. `POST /reopen` emprunte la même file, avec la consigne de l'utilisateur, et n'est permis que sur un projet terminé qui n'est pas en cours d'export.

### 4.6 État du graphe et tables métier

Le point de reprise LangGraph fait foi **pour la reprise**. Les tables `facts` et `sections` sont des **projections** écrites par les nœuds, qui servent à afficher un projet sans réhydrater le graphe.

En cas de divergence, le point de reprise gagne et les projections sont réécrites depuis lui. Une fonction `reprojeter(project_id)` le fait, et elle est appelée au démarrage de tout run repris.

---

## 5. La couche modèles

### 5.1 Routes

Trois routes, définies en configuration, jamais nommées dans le graphe. Un nœud demande une **capacité**.

| Route | Chaîne | Usage |
|---|---|---|
| `court` | Groq → NVIDIA Build → Mistral | Extraction, questions, hypothèses chiffrées, auto-critique |
| `redaction` | Gemini → Mistral → NVIDIA Build | Rédaction des sections, en flux |
| `grand_contexte` | OpenRouter → Gemini | Contrôle de cohérence |

Les quotas par fournisseur et les modèles essayés dans l'ordre sont ceux du §« Modèles essayés » de l'onglet Stack.

### 5.2 Compteurs et bascule préventive

Avant chaque appel, `budget_disponible(fournisseur, tokens_estimes)` interroge `llm_usage` sur les fenêtres glissantes du fournisseur — minute, jour — et répond oui ou non.

Pour la rédaction, l'estimation porte sur **la section entière**, prompt et sortie comprise. Si le budget ne couvre pas la section, on bascule **avant d'ouvrir le flux**, jamais au milieu. C'est ce qui évite qu'un paragraphe s'efface sous les yeux de l'utilisateur.

Si une coupure survient malgré tout, la section repart entière sur le fournisseur suivant et l'API émet un événement `section_restart`, que le front traite en vidant le texte affiché.

### 5.3 Ordre des essais

```
pour fournisseur dans route:
    si budget insuffisant: fournisseur suivant
    pour modele dans fournisseur.modeles:
        essayer
        sortie hors schéma  → modèle suivant
        429 ou 5xx          → fournisseur suivant
        succès              → enregistrer llm_usage et rendre
tous épuisés → ErreurAucunFournisseur
```

`ErreurAucunFournisseur` ne perd rien : le point de reprise est intact, le projet passe en `run_status = 'failed'` et l'utilisateur voit un bouton « Reprendre ».

---

## 6. Surface de l'API

FastAPI. Toutes les routes hors `/auth` exigent un jeton de session et un compte actif.

```
POST   /auth/register
POST   /auth/login
POST   /auth/logout
GET    /me

GET    /catalogue                         titres des sections, forme des faits

GET    /projects                          liste du propriétaire
POST   /projects                          crée, démarre le run
GET    /projects/{id}                     entête et progression
GET    /projects/{id}/state               plan, faits, interaction en attente
POST   /projects/{id}/answer              répond à l'interaction courante, reprend le run
POST   /projects/{id}/resume              relance après échec ou redémarrage
POST   /projects/{id}/sections/{sid}/reopen
GET    /projects/{id}/stream              flux SSE
POST   /projects/{id}/exports             lance le rendu des documents
GET    /projects/{id}/exports             liste, avec liens signés
```

### 6.1 Flux SSE

Le navigateur se connecte **directement au backend**, sans passer par les fonctions du front et leurs limites de durée.

| Événement | Charge utile |
|---|---|
| `interaction` | Une interruption à afficher, typée |
| `token` | Un fragment de texte en cours de rédaction |
| `section_restart` | Le flux repart sur un autre fournisseur : vider l'affichage |
| `score` | Note et problèmes relevés par l'auto-critique |
| `section_saved` | Section figée, validée automatiquement ou par l'utilisateur |
| `progress` | Curseur, total, nombre de sections relues |
| `error` | Message affichable et possibilité de reprise |
| `done` | Run terminé, liens d'export |

### 6.2 Idempotence des réponses

`POST /answer` porte l'identifiant de l'interaction à laquelle il répond. Si le run a déjà dépassé ce point — double clic, reconnexion, onglet resté ouvert — la requête ne rejoue rien et renvoie l'état courant avec `200`. Sans cela, un réseau instable fait avancer le graphe deux fois.

**Une exception, décidée pendant le plan 4.** Si un run avance déjà sur le même fil au moment de la réponse, `/answer` renvoie `409` avec le code `run_deja_en_cours`, et non `200`. Ce cas arrive quand une reprise (`/resume`) est en cours : un run planté laisse son interruption en attente, donc la réponse porte un identifiant encore valide, mais c'est la reprise qui avance. Répondre `200` avec `rejoue: false` ferait croire à l'utilisateur que sa réponse est passée alors qu'elle est jetée. Le front, sur ce `409`, relit `/state` et renvoie la réponse si l'interruption est toujours la même.

**Un état de passage à connaître.** Pendant un `/answer`, `/state` peut renvoyer `run_status: waiting` avec `interaction: null` : la ligne n'est pas encore mise à jour alors que le point de reprise a déjà consommé la réponse. Le front relit `/state` quand il rencontre cet état.

**Réponse consommée, ligne en retard.** Juste après un `/answer` accepté, `/state` peut encore rendre l'interaction à laquelle on vient de répondre : la ligne dit `waiting` tant que le run n'a pas repris. Le front retient l'identifiant auquel il a répondu et ne repose pas la question tant que c'est le même — sauf si le run passe en `failed`, qui doit se voir.

---

## 7. Export

1. Les sections validées, sous forme de blocs, alimentent un modèle Word par `docxtpl`. Jamais le texte affiché à l'écran.
2. Les graphiques du prévisionnel sont produits par `matplotlib` et insérés en images.
3. Les données manquantes sont rassemblées en annexe « Données à compléter ».
4. Les `.docx` sont convertis en PDF par Gotenberg, sur un service séparé tiré d'une image officielle épinglée : la conversion ne tient pas dans les 512 Mo du service principal. Ce service dort pendant toute la rédaction et n'est réveillé qu'ici (§9.4).
5. Les quatre fichiers vont dans Supabase Storage, servis par lien signé à expiration courte.

Si une section a été passée sans validation, un filigrane « Brouillon » est appliqué aux deux formats.

En cas d'échec de Gotenberg, repli documenté : un PDF produit depuis du HTML. Le PDF cesse alors d'être identique au Word, ce qui doit être dit à l'utilisateur plutôt que masqué.

---

## 8. Erreurs et reprises

Le service d'hébergement gratuit s'endort après quinze minutes et redémarre sans prévenir. Un run en cours meurt. Ce n'est pas un cas limite, c'est le cas courant.

| Situation | Comportement attendu |
|---|---|
| Backend endormi à l'ouverture | Le front appelle `/health` et affiche un écran d'attente pendant le réveil, environ une minute |
| Redémarrage pendant un run | `run_status` reste à `running` alors que rien ne tourne. Au chargement suivant, l'API détecte l'incohérence, passe en `failed` et propose « Reprendre » |
| Reprise | `POST /resume` réhydrate le thread depuis le dernier point de reprise, rejoue `reprojeter()`, relance |
| Flux SSE coupé | Le front se reconnecte et appelle `/state` : aucun état ne vit dans la connexion |
| Tous les fournisseurs épuisés | Run en `failed`, message explicite sur le quota, reprise possible le lendemain sans rien perdre |

---

## 9. Contraintes d'exploitation

### 9.1 Pooler en mode transaction

Vérifié le 17 septembre 2026 sur la base cible.

- Les requêtes préparées passent : aucune précaution côté client.
- `SET LOCAL` fonctionne dans une transaction.
- **L'état de session ne doit servir à rien.** Il a survécu au test parce que le test était seul sur le pool ; en charge, la connexion est réattribuée et l'état disparaît sans erreur. C'est le pire mode de panne : silencieux. Aucun code ne pose de variable de session hors transaction.

### 9.2 Une seule instance

La limitation de débit et tout cache éventuel vivent en mémoire du processus, ce qui n'est correct que tant qu'il n'y a qu'une instance. C'est une hypothèse à écrire dans le code, pas à sous-entendre.

Depuis le plan 4, le bus d'événements et le registre des runs vivent aussi en mémoire. La commande de démarrage fixe donc `--workers 1` : sans cela, uvicorn lit `WEB_CONCURRENCY`, que Render fixe d'après le nombre de processeurs, et un plan plus grand démarrerait deux workers sans que rien ne le signale.

**Risque accepté : ne pas déployer pendant qu'un run est actif.** Lors d'un déploiement sans interruption, Render démarre la nouvelle instance à côté de l'ancienne pendant environ 90 secondes. La réconciliation au démarrage de la nouvelle passerait à `failed` les runs encore vivants de l'ancienne, et un clic sur « Reprendre » en lancerait un second sur le même point de reprise. Ce risque est accepté tant qu'il n'y a pas d'utilisateur réel. Il doit être traité avant la mise en service : soit en désactivant le déploiement sans interruption, soit par un verrou en base indiquant quelle instance pilote quel run.

### 9.3 Purge des points de reprise

La base gratuite plafonne à 500 Mo et passe en lecture seule au-delà. Les points de reprise LangGraph sont volumineux : un état complet à chaque nœud, sur trente sections.

Une tâche de purge supprime les points intermédiaires d'un projet terminé, en gardant le dernier. Elle tourne à la fin d'un run et, en filet, au démarrage de l'application.

Le stockage des fichiers a son propre plafond, distinct de celui de la base. Quatre fichiers par projet, quelques centaines de kilooctets chacun : ce n'est pas le point de tension, mais supprimer un projet doit supprimer ses exports.


### 9.4 Déploiement sur Render

Vérifié dans la documentation Render le 17 septembre 2026.

**Le déploiement par Docker fonctionne, de deux façons.** Soit Render construit l'image à partir du `Dockerfile` du dépôt — il suffit de déclarer le langage « Docker » à la création du service —, soit il tire une image déjà construite depuis un registre : n'importe quel registre public, et Docker Hub, GitHub ou GitLab pour le privé. Aucune de ces deux voies n'est réservée à un plan payant.

Le backend suit la première voie : `Dockerfile` au dépôt, construction chez Render, déploiement automatique à chaque poussée. Gotenberg suit la seconde : image officielle épinglée, tirée du registre. **Un service déployé depuis une image pré-construite ne bénéficie pas du déploiement automatique** : le mettre à jour demande un redéploiement manuel. Pour une version épinglée de Gotenberg, c'est exactement le comportement souhaité.

**`docker-compose` n'est pas un format de déploiement chez Render.** Un service correspond à un `Dockerfile` ou à une image. Le `docker-compose.yml` du dépôt sert au développement local, à faire tourner le backend et Gotenberg côte à côte sur la machine du développeur, et à rien d'autre. Pour décrire les deux services de production dans le dépôt, le format est `render.yaml`.

**Les variables d'environnement définies dans Render sont transmises comme arguments de construction** à l'image. Utile, mais à manier avec précaution : ce qui entre dans une couche d'image y reste. Les clés d'API sont lues à l'exécution, jamais pendant la construction.

**La contrainte qui décide vraiment : 750 heures d'instance gratuites par espace de travail et par mois.** Elles sont partagées entre tous les services gratuits, pas attribuées à chacun. Un mois compte 744 heures : **un seul service allumé en permanence épuise le quota**. Deux services qui veillent ensemble pendant une génération consomment deux heures par heure écoulée.

En pratique, les deux services s'endorment après quinze minutes sans trafic, donc l'enveloppe tient largement pour l'usage visé. Mais deux conséquences sont à écrire dans le code plutôt qu'à découvrir :

1. **Ne jamais mettre en place de ping périodique pour empêcher la mise en veille.** C'est le réflexe habituel contre le réveil d'une minute, et ici il épuiserait le quota du mois en deux services. Le réveil se traite côté interface, par un écran d'attente, pas en gardant les machines allumées.
2. **Ne réveiller Gotenberg qu'au moment de l'export.** Il n'a rien à faire pendant la rédaction, qui dure l'essentiel d'une session. Le premier appel de conversion paiera une minute de réveil, sur une opération qui n'est pas interactive.

Les minutes de construction et la bande passante sortante sont également décomptées, et un dépassement suspend les services si aucun moyen de paiement n'est enregistré. La reconstruction de l'image doit donc rester peu fréquente, ce que garantit le cache de couches décrit en §11.1.

**Un point à vérifier dans l'interface, que la documentation ne tranche pas.** Gotenberg n'a pas d'authentification native. L'idéal serait un service privé, joignable uniquement par les autres services du compte sur le réseau interne. La documentation ne dit pas si les services privés existent en version gratuite. Si ce n'est pas le cas, Gotenberg sera un service web public, et le risque est à qualifier : il ne s'agit pas d'une fuite de documents — Gotenberg ne conserve rien et ne reçoit que ce que notre API lui envoie — mais d'un détournement de ressources, quelqu'un s'en servant pour ses propres conversions. À arbitrer avant la mise en service.

---

## 10. Tests

**Aucun test ne joint un vrai fournisseur.** Un modèle simulé déterministe, alimenté par des fixtures, répond à la place.

| Niveau | Objet |
|---|---|
| Unitaire | Réducteur de faits et ses trois invariants ; analyse des manques ; vérificateur de chiffres ; budget et ordre des essais ; les dix calculs financiers, avec valeurs de référence |
| Intégration | Le graphe de bout en bout avec modèle simulé : un projet complet, trente sections, sans intervention humaine hors interruptions scriptées |
| Sécurité | Un projet d'un autre utilisateur répond `404` ; un compte inactif est refusé partout ; aucune requête sur `projects` hors du module d'accès |
| Reprise | Interruption brutale au milieu d'un run, reprise, état identique |
| Bout en bout | Playwright sur le parcours complet, modèle simulé |

Intégration continue par GitHub Actions, base PostgreSQL éphémère en conteneur, mêmes migrations qu'en production. Les dépendances sont installées par `uv sync --frozen`, de sorte que l'intégration continue échoue si le verrou n'est pas à jour plutôt que de résoudre une version différente en silence.

---

## 11. Configuration

```
SUPABASE_DB_HOST / _PORT / _USER / _PASSWORD / _NAME
SUPABASE_URL / SUPABASE_SERVICE_KEY          Storage uniquement, à ajouter au .env
GEMINI_API_KEY MISTRAL_AI_API_KEY OPENROUTER_API_KEY
NVIDIA_API_KEY GROQ_CLOUD_API_KEY
LANGSMITH_API_KEY / LANGSMITH_PROJECT
GOTENBERG_URL
SESSION_TTL_HOURS
ESQUISSE_FAKE_LLM                            tests et développement
```

`CEREBRAS_CLOUD_API_KEY` est présente mais volontairement hors routage.

### 11.1 Outillage Python

Les dépendances du backend sont gérées par **`uv`**, pas par `pip`. Concrètement :

- `pyproject.toml` déclare les dépendances, `uv.lock` les verrouille. Les deux sont versionnés.
- L'environnement se crée et se met à jour par `uv sync` ; en intégration continue et dans l'image Docker, par `uv sync --frozen`, qui refuse d'installer si le verrou ne correspond pas au manifeste.
- Les commandes passent par `uv run` — `uv run pytest`, `uv run alembic upgrade head`, `uv run uvicorn` — ce qui évite d'avoir à activer un environnement et supprime l'écart entre la machine du développeur et le conteneur.
- L'image du service backend installe `uv`, copie `pyproject.toml` et `uv.lock`, puis `uv sync --frozen --no-dev` avant de copier le code : les dépendances restent dans une couche mise en cache tant que le verrou ne bouge pas.
- Aucun `requirements.txt` n'est maintenu. Si un hébergeur en réclame un, il est produit à la demande par `uv export`, jamais édité à la main.

Le dépôt suit la structure décrite dans l'onglet Stack du mockup.

---

## 12. Ce qui reste ouvert

**Aucun plafond par compte.** Un compte activé peut lancer autant de projets qu'il veut et épuiser à lui seul les mille requêtes quotidiennes de Gemini. Un plafond — projets par jour, ou rédactions par jour — sera probablement nécessaire. C'est une décision de produit, pas d'architecture, et elle ne bloque pas la construction.

**La note vient du modèle.** Choix assumé le 17 septembre. Elle varie d'un appel à l'autre, donc une même section peut s'arrêter ou passer selon l'exécution. Les sept sections marquées `toujours` s'arrêtent de toute façon, ce qui borne le risque. À surveiller dans LangSmith : la proportion de sections passées sans relecture, et surtout celles qui sont rouvertes ensuite par l'utilisateur.

**Réinitialisation de mot de passe.** Repoussée. Se fait à la main dans la base, comme l'activation.

**Consignes et grilles.** Adossées à un cahier des charges réel et à un plan d'affaires réel, jamais éprouvées sur un vrai projet. C'est l'évaluation qui tranchera.
