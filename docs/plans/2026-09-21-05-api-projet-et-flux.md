# Plan 4 — API projet et flux

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE — utiliser
> `superpowers:subagent-driven-development` pour exécuter ce plan tâche par
> tâche. Les étapes portent des cases à cocher (`- [ ]`).

**Objectif :** rendre l'agent joignable depuis l'extérieur — créer un projet,
répondre à ses questions en HTTP, suivre la rédaction en direct, et reprendre
un run que le redémarrage de l'hébergement a tué.

**Architecture :** un run vit dans une tâche asyncio de fond, jamais dans une
requête HTTP. Il publie ce qu'il fait sur un bus d'événements en mémoire ; les
connexions SSE s'y abonnent. Une connexion coupée ne perd donc rien : le front
se reconnecte et rappelle `/state`. Le point de reprise LangGraph reste la
source de vérité, les tables `facts` et `sections` restent des projections.

**Pile :** FastAPI, asyncio, LangGraph 1.2.11, psycopg 3. SSE écrit à la main
sur `StreamingResponse` — le protocole tient en vingt lignes et une
dépendance de plus se paierait à chaque déploiement.

**Spec :** [../spec-implementation.md](../spec-implementation.md) — §6 pour la
surface de l'API, §6.1 pour les événements, §6.2 pour l'idempotence, §8 pour
les reprises, §9.2 et §9.3 pour l'instance unique et la purge.

**Revue du plan 3 :** [2026-09-18-04-agent-revue.md](2026-09-18-04-agent-revue.md).
Trois constats y attendent ce plan-ci, et sont traités par les tâches
ci-dessous plutôt que reportés encore : `purge_checkpoints` sans appelant
(tâches 3 et 7), `reproject` sans appelant (tâche 7), `mark_for_reopening`
sans appelant (tâche 7).

---

## Contraintes globales

Copiées de la spec et des plans précédents. Elles s'ajoutent implicitement aux
exigences de chaque tâche.

- **Identifiants de code en anglais** — fonctions, classes, variables,
  constantes, noms de tests, fixtures, modules, fichiers, clés d'état du
  graphe. **Commentaires et docstrings en français.**
- **Les champs des corps de requête et de réponse HTTP sont en français**,
  comme tout le reste du contrat d'API. C'est le précédent posé par le plan 1
  et vérifié avant d'écrire ce plan : `/auth/register` attend `mot_de_passe`,
  `/auth/login` rend `jeton`. Un `password` au milieu de `mot_de_passe`
  obligerait le front à retenir laquelle des deux conventions s'applique à
  quelle route. Les **noms d'événements SSE** font exception et restent tels
  que le §6.1 les écrit.
- **Restent en français**, ce sont des valeurs de contrat et non des
  identifiants : noms de colonnes SQL, valeurs de `run_status`
  (`idle`, `running`, `waiting`, `failed`, `done`), identifiants de gabarits
  et de faits, **codes d'erreur d'API**, et les noms d'événements SSE du §6.1
  (`interaction`, `token`, `section_restart`, `score`, `section_saved`,
  `progress`, `error`, `done`) — le front les attend au caractère près.
- **Tout tourne sur des paliers gratuits.** Aucun service ni modèle payant.
- **`uv` uniquement**, jamais `pip`.
- **Ne jamais lancer les tests marqués `network`.** La suite est
  `uv run pytest -m "not network"` depuis `backend/`. Elle est à **374 passés,
  5 désélectionnés** au démarrage de ce plan.
- **Une seule instance** (§9.2). Le bus d'événements et le registre des runs
  vivent en mémoire du processus. C'est une hypothèse à **écrire dans le
  code**, pas à sous-entendre.
- **Aucun état de session PostgreSQL** (§9.1). Le pooler en mode transaction
  réattribue les connexions ; une variable de session posée hors transaction
  disparaît sans erreur.
- **Aucune requête sur `projects` hors de `app/projects/repository.py`.**
  C'est le module qui porte le filtre sur le propriétaire ; le contourner,
  c'est l'oublier.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `app/runs/events.py` | Le bus en mémoire : publier, s'abonner, le comportement quand personne n'écoute ou quand un abonné traîne |
| `app/runs/runner.py` | Le pilote : démarrer, reprendre, conduire le graphe jusqu'à l'interruption suivante, tenir `run_status`, purger à la fin |
| `app/runs/registry.py` | Les tâches vivantes, une par projet, et le refus d'en lancer deux |
| `app/projects/routes.py` | Les routes de projet, `/answer`, `/resume`, `/reopen` |
| `app/projects/schemas.py` | Les corps de requête et de réponse |
| `app/projects/stream.py` | La route SSE et l'encodage du protocole |
| `app/projects/repository.py` | *(modifié)* la liste du propriétaire, la mise à jour de `run_status` |
| `app/agent/nodes.py` | *(modifié)* publication des `token`, `section_restart`, `score`, `section_saved`, `progress` |
| `app/main.py` | *(modifié)* réconciliation des runs orphelins et purge de filet au démarrage |

Pourquoi `app/runs/` et non `app/projects/` : le pilote et le bus ne savent
rien des routes HTTP, et les routes ne savent rien d'asyncio. Les mélanger
rendrait le pilote intestable sans client HTTP.

**Pas de `ContextVar` pour joindre le bus depuis les nœuds.** La première
version de ce plan en prévoyait un, par crainte que les nœuds n'aient pas de
quoi nommer le projet au moment de publier. C'est faux : `EsquisseState`
porte `project_id` depuis le plan 3, et chaque nœud le lit déjà pour
facturer ses appels au modèle. Un `ContextVar` aurait ajouté un état
implicite, invisible dans les signatures et cassé par tout ce qui traverse
une frontière de tâche — pour rien.

---

## Ordre et dépendances

```
1. Bus d'événements ── 2. Publication depuis le graphe ── 3. Pilote de run ──┬── 4. Routes de projet ──┬── 5. Réponse idempotente
                                                                             │                         └── 6. Flux SSE
                                                                             └────────────────────────────── 7. Reprise et réouverture
```

Les tâches 5 et 6 sont indépendantes l'une de l'autre et peuvent se faire en
parallèle après la 4. Tout le reste est séquentiel.

---

### Tâche 1 : le bus d'événements

**Fichiers :**
- Créer : `backend/app/runs/__init__.py` (vide)
- Créer : `backend/app/runs/events.py`
- Test : `backend/tests/test_events.py`

**Interfaces :**
- Produit :
  - `RunEvent` — `@dataclass(frozen=True)` avec `name: str` et `data: dict`
  - `publish(project_id: str, event: RunEvent) -> None` — synchrone, ne
    bloque jamais, sans effet si personne n'écoute
  - `subscribe(project_id: str) -> AsyncIterator[RunEvent]` — gestionnaire de
    contexte asynchrone rendant un itérateur
  - `LAGGED` — l'événement `error` émis à l'abonné qu'on abandonne
  - `SUBSCRIBER_QUEUE_SIZE = 256`
- Consomme : rien.

**Ce que la tâche doit trancher, et comment :**

Trois cas limites décident de la forme de ce module. Ils sont tranchés ici,
pas laissés à l'implémenteur :

1. **Personne n'écoute.** `publish` est alors sans effet et *ne bloque pas*.
   Un run doit tourner exactement pareil sans navigateur connecté — c'est le
   cas normal sur un hébergement qui s'endort.
2. **Un abonné arrive en retard.** Il ne reçoit pas ce qui a précédé. Le bus
   n'a pas d'historique : le §8 de la spec dit « aucun état ne vit dans la
   connexion », et le front qui se reconnecte rappelle `/state`. Un historique
   ici serait un second état à tenir cohérent avec le point de reprise.
3. **Un abonné traîne.** Sa file est bornée. Quand elle déborde, on ne jette
   pas des événements au hasard — on **abandonne l'abonné** avec un dernier
   événement `error` qui lui dit de se reconnecter. Jeter silencieusement
   laisserait le front afficher un texte amputé sans jamais le savoir.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_events.py
import asyncio

import pytest

from app.runs.events import (
    LAGGED,
    SUBSCRIBER_QUEUE_SIZE,
    RunEvent,
    publish,
    subscribe,
)


async def _drain(iterator, count):
    """Les `count` premiers événements, avec un délai : un test qui attend
    indéfiniment sur une file vide ne dit pas ce qui ne va pas."""
    collected = []
    for _ in range(count):
        collected.append(await asyncio.wait_for(anext(iterator), timeout=1))
    return collected


async def test_publishing_without_a_subscriber_does_nothing_and_does_not_block():
    # Le cas normal : le run tourne, aucun navigateur n'est connecté.
    publish("projet-sans-public", RunEvent("progress", {"cursor": 1}))


async def test_a_subscriber_receives_what_is_published_after_it_arrives():
    async with subscribe("projet-a") as events:
        publish("projet-a", RunEvent("token", {"text": "Bonjour"}))
        publish("projet-a", RunEvent("token", {"text": " monde"}))
        received = await _drain(events, 2)
    assert [e.name for e in received] == ["token", "token"]
    assert "".join(e.data["text"] for e in received) == "Bonjour monde"


async def test_a_late_subscriber_misses_what_came_before():
    # Voulu : le bus n'a pas d'historique. Le front qui se reconnecte
    # rappelle `/state`, qui lit le point de reprise.
    publish("projet-b", RunEvent("token", {"text": "perdu"}))
    async with subscribe("projet-b") as events:
        publish("projet-b", RunEvent("token", {"text": "reçu"}))
        received = await _drain(events, 1)
    assert received[0].data["text"] == "reçu"


async def test_two_subscribers_both_receive_everything():
    async with subscribe("projet-c") as premier:
        async with subscribe("projet-c") as second:
            publish("projet-c", RunEvent("score", {"score": 8}))
            assert (await _drain(premier, 1))[0].data["score"] == 8
            assert (await _drain(second, 1))[0].data["score"] == 8


async def test_a_subscriber_of_another_project_receives_nothing():
    async with subscribe("projet-d") as events:
        publish("projet-e", RunEvent("token", {"text": "pas pour toi"}))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(events), timeout=0.05)


async def test_a_subscriber_that_falls_behind_is_dropped_with_an_error():
    """Le débordement ne jette pas des événements en silence : il coupe
    l'abonné en lui disant de se reconnecter. Un texte amputé sans avertir
    serait pire qu'une coupure franche."""
    async with subscribe("projet-f") as events:
        for index in range(SUBSCRIBER_QUEUE_SIZE + 10):
            publish("projet-f", RunEvent("token", {"text": str(index)}))
        received = []
        # Un délai par élément, et non un simple `async for` : sans lui, une
        # régression qui n'émettrait jamais l'avis de retard ferait PENDRE ce
        # test au lieu de l'échouer, et une mutation qui fait pendre ne
        # prouve rien.
        #
        # Mais ce délai ouvre un second trou, qu'il faut refermer dans le
        # même geste : il finit la boucle aussi bien quand l'itérateur
        # s'arrête tout seul que quand il ne s'arrête JAMAIS. Sans distinguer
        # les deux, supprimer le `return` d'`_iterate` laisserait les sept
        # tests au vert — le dernier élément reçu resterait l'avis de retard,
        # et seule la connexion SSE, plus tard, finirait par couper. Le
        # contrat du bus serait alors tenu par le caprice du client.
        ended_by = None
        try:
            while True:
                received.append(
                    await asyncio.wait_for(anext(events), timeout=1))
        except StopAsyncIteration:
            ended_by = "exhausted"
        except asyncio.TimeoutError:
            ended_by = "timeout"
    assert ended_by == "exhausted", (
        "l'itérateur ne s'est pas arrêté de lui-même après l'avis de retard"
    )
    assert received[-1].name == "error"
    assert received[-1].data == LAGGED.data
    assert len(received) == SUBSCRIBER_QUEUE_SIZE


async def test_the_channel_disappears_when_its_last_subscriber_leaves():
    from app.runs.events import _channels

    async with subscribe("projet-g"):
        assert "projet-g" in _channels
    assert "projet-g" not in _channels, (
        "un canal survivant à ses abonnés est une fuite : un run par projet, "
        "sur la durée de vie du processus"
    )
```

- [ ] **Étape 2 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_events.py -v
```

Attendu : `ModuleNotFoundError: No module named 'app.runs'`.

- [ ] **Étape 3 : écrire le module**

```python
# backend/app/runs/events.py
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

# La file d'un abonné. Deux cent cinquante-six fragments, c'est plusieurs
# secondes de rédaction : un navigateur momentanément lent a le temps de se
# rattraper, un navigateur parti ne mange pas la mémoire du processus.
SUBSCRIBER_QUEUE_SIZE = 256


@dataclass(frozen=True)
class RunEvent:
    """Un événement du §6.1. `name` est la valeur de contrat que le front
    attend au caractère près, `data` ce qu'il affiche."""

    name: str
    data: dict = field(default_factory=dict)


# Le dernier événement d'un abonné qu'on abandonne. Le front sait quoi en
# faire : se reconnecter et rappeler `/state`, comme après n'importe quelle
# coupure. C'est le §8, « aucun état ne vit dans la connexion ».
LAGGED = RunEvent("error", {
    "code": "flux_en_retard",
    "message": "Le flux a pris trop de retard. Reconnectez-vous pour "
               "retrouver l'état courant.",
    "reprenable": True,
})

# Un canal par projet, chacun portant les files de ses abonnés.
#
# CE DICTIONNAIRE VIT EN MÉMOIRE DU PROCESSUS. C'est l'hypothèse « une seule
# instance » du §9.2, et elle est écrite ici plutôt que sous-entendue : avec
# deux instances derrière un répartiteur, un navigateur abonné sur l'une ne
# verrait rien de ce que publie l'autre, sans la moindre erreur. Le jour où
# une seconde instance devient nécessaire, ce module devient un vrai courtier
# — Redis ou `LISTEN/NOTIFY` — et c'est le seul à changer.
_channels: dict[str, set[asyncio.Queue]] = {}


def publish(project_id: str, event: RunEvent) -> None:
    """Publie sans bloquer et sans rien attendre de personne.

    Synchrone à dessein : les nœuds du graphe l'appellent au milieu d'un flux
    de fragments, et un `await` de plus par fragment coûterait une bascule de
    tâche par mot rédigé. `put_nowait` sur une file bornée suffit.
    """
    subscribers = _channels.get(project_id)
    if not subscribers:
        return
    # Une copie : `_drop_lagging` retire l'abonné du canal, et muter un
    # ensemble qu'on parcourt lèverait une `RuntimeError`.
    for queue in list(subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            _drop_lagging(project_id, queue)


def _drop_lagging(project_id: str, queue: asyncio.Queue) -> None:
    """Coupe l'abonné en retard, une fois pour toutes.

    Le retirer du canal AVANT de poser l'avis est ce qui rend l'opération
    idempotente, et ce n'est pas une élégance : sans cela, chaque publication
    suivante retrouverait la file pleine, sortirait un fragment de plus et
    glisserait un nouvel avis derrière. L'abonné recevrait alors des
    fragments amputés AVANT de voir le premier avis — exactement ce que
    cette branche existe pour éviter.

    La file est pleine par définition : pour y glisser `LAGGED`, il faut
    d'abord faire de la place. On sort le plus ancien, ce qui est le moins
    mauvais choix — l'abonné sera coupé de toute façon.
    """
    _channels.get(project_id, set()).discard(queue)
    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:  # pragma: no cover — la file est pleine
        pass
    queue.put_nowait(LAGGED)


@asynccontextmanager
async def subscribe(project_id: str) -> AsyncIterator[AsyncIterator[RunEvent]]:
    """S'abonne aux événements d'un projet, le temps du bloc.

    Gestionnaire de contexte et non simple générateur : un abonné dont la
    connexion tombe doit retirer sa file, sinon `publish` continue d'y écrire
    pour un navigateur parti et le canal ne disparaît jamais.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
    _channels.setdefault(project_id, set()).add(queue)
    try:
        yield _iterate(queue)
    finally:
        subscribers = _channels.get(project_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                del _channels[project_id]


async def _iterate(queue: asyncio.Queue) -> AsyncIterator[RunEvent]:
    """Rend les événements jusqu'à l'avis de retard, qui clôt l'itération
    après avoir été rendered — l'abonné doit le voir passer, c'est lui qui lui
    dit de se reconnecter."""
    while True:
        event = await queue.get()
        yield event
        if event is LAGGED:
            return
```

- [ ] **Étape 4 : lancer les tests pour les voir passer**

```bash
cd backend && uv run pytest tests/test_events.py -v
```

Attendu : 7 passés.

- [ ] **Étape 5 : vérifier par mutation que les tests mordent**

C'est la leçon du plan 3, et elle n'est pas négociable ici : écrire le test
ne suffit pas, il faut le voir tomber. Copiez le fichier de côté, appliquez
chaque mutation, lancez `tests/test_events.py`, restaurez.

| Mutation | Doit faire tomber |
|---|---|
| `except asyncio.QueueFull: pass` au lieu d'appeler `_drop_lagging` | `..._falls_behind_is_dropped_with_an_error` |
| `_drop_lagging` sans le `discard` du canal | le même — l'abonné recevrait des fragments après l'avis |
| `_iterate` sans son `if event is LAGGED: return` | le même — trouvé par la relecture, c'est la mutation qui survivait |
| retirer le `del _channels[project_id]` | `..._channel_disappears_when_its_last_subscriber_leaves` |
| `_channels.get(project_id, ())` → parcourir tous les canaux | `..._subscriber_of_another_project_receives_nothing` |

Si l'une reste verte, c'est le test qu'il faut corriger, pas la mutation.
Reportez dans le compte rendu ce que chacune a donné.

- [ ] **Étape 6 : lancer la suite complète**

```bash
cd backend && uv run pytest -m "not network" -q
```

Attendu : 381 passés, 5 désélectionnés.

- [ ] **Étape 7 : commiter**

```bash
git add backend/app/runs/__init__.py backend/app/runs/events.py backend/tests/test_events.py
git commit -m "feat(runs): un bus d'événements en mémoire, une file par abonné"
```

---

### Tâche 2 : le graphe publie ce qu'il fait

**Fichiers :**
- Modifier : `backend/app/agent/nodes.py` — `write`, `critique`, `save`
- Test : `backend/tests/test_node_events.py` (nouveau fichier, pour ne pas
  gonfler `test_nodes.py` qui approche les quatre cents lignes)

**Interfaces :**
- Consomme : `RunEvent`, `publish` de la tâche 1 ; `state["project_id"]`,
  déjà présent dans `EsquisseState`.
- Produit : cinq des huit événements du §6.1. Les trois autres —
  `interaction`, `error`, `done` — naissent du pilote (tâche 3) et non des
  nœuds, parce qu'ils décrivent le run et non la rédaction.

**Le point qui décide de la tâche :** publier ne doit **rien changer** quand
personne n'écoute. Les 374 tests existants tournent sans abonné ; s'ils
changent de comportement, la publication n'est pas au bon endroit. C'est
l'objet du dernier test.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_node_events.py
from uuid import uuid4

import pytest_asyncio

from app.agent import nodes
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.llm.fake import FakeTransport
from app.projects.repository import create_project
from app.runs.events import subscribe

CATALOGUE = load_catalogue()


@pytest_asyncio.fixture
async def project(migrated_db):
    # Même motif que `tests/test_nodes.py::project` : les nœuds écrivent dans
    # `llm_usage` et `sections`, qui portent une clé étrangère vers `projects`.
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id",
                (f"events-{uuid4()}@exemple.fr",),
            )
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="consultation", profil_bp=None,
            thread_id=f"thread-{uuid4()}", templates_version="0.1",
        )
    yield str(project_id)


def _state(project_id, **overrides):
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    base = {
        "project_id": project_id,
        "documents": "cdc",
        "profil_cdc": "consultation",
        "profil_bp": None,
        "idea": "Une plateforme de coaching sportif à domicile.",
        "facts": {},
        "plan": plan,
        "cursor": 0,
        "draft": None,
        "score": None,
        "problems": [],
        "revisions": 0,
        "question_rounds": 0,
        "computations": {},
        "pending_questions": None,
        "inconsistencies": [],
    }
    base.update(overrides)
    return base


async def _collect(events, stop_after):
    """Tout ce qui arrive jusqu'à en avoir `stop_after`, sans attendre
    indéfiniment si le nœud n'en publie pas assez."""
    import asyncio

    collected = []
    try:
        while len(collected) < stop_after:
            collected.append(await asyncio.wait_for(anext(events), timeout=1))
    except asyncio.TimeoutError:
        pass
    return collected


async def test_writing_publishes_its_tokens(project):
    async with subscribe(project) as events:
        await nodes.write(_state(project), transport=FakeTransport())
        received = await _collect(events, 200)
    tokens = [e for e in received if e.name == "token"]
    assert tokens, "la rédaction n'a publié aucun fragment"
    assert all("text" in e.data for e in tokens)
    # Le texte publié est celui qui part dans le brouillon, pas un résumé.
    assert "".join(e.data["text"] for e in tokens)


async def test_the_critique_publishes_its_score(project):
    async with subscribe(project) as events:
        from app.agent.state import Paragraph

        await nodes.critique(
            _state(project, draft=[Paragraph(text="Un texte de section.")]),
            transport=FakeTransport())
        received = await _collect(events, 1)
    assert [e.name for e in received] == ["score"]
    assert "score" in received[0].data
    assert "problems" in received[0].data


async def test_saving_publishes_the_section_and_the_progress(project):
    from app.agent.state import Paragraph

    async with subscribe(project) as events:
        await nodes.save(_state(project, draft=[Paragraph(text="Un texte.")],
                                score=9))
        received = await _collect(events, 2)
    names = [e.name for e in received]
    assert names == ["section_saved", "progress"]
    saved, progress = received
    assert saved.data["document"] == "cdc"
    assert saved.data["section_id"] == CATALOGUE.plan_for(
        "cdc", "consultation", None)[0].section_id
    # Le curseur publié est celui d'APRÈS l'avancée : le front affiche une
    # progression, pas la section qu'il vient de quitter.
    assert progress.data["cursor"] == 1
    assert progress.data["total"] == len(
        CATALOGUE.plan_for("cdc", "consultation", None))


async def test_a_node_runs_identically_with_nobody_listening(project):
    """Le test qui protège les 374 autres.

    Aucun abonné : `publish` est sans effet, et le nœud doit rendre
    exactement ce qu'il rendait avant cette tâche.
    """
    maj = await nodes.write(_state(project), transport=FakeTransport())
    assert maj["draft"]
    assert maj["revisions"] == 1
```

- [ ] **Étape 2 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_node_events.py -v
```

Attendu : les trois premiers échouent (`recus` vide, donc `assert jetons` ou
la comparaison de noms), le quatrième passe déjà.

- [ ] **Étape 3 : publier depuis `write`**

Dans `backend/app/agent/nodes.py`, ajouter l'import en tête de fichier :

```python
from app.runs.events import RunEvent, publish
```

Puis, dans `write`, à l'intérieur de la boucle `async for event in stream(...)` :

```python
        if isinstance(event, TextDelta):
            pieces.append(event.text)
            # Publier ici et non après la boucle : c'est tout l'intérêt du
            # flux. Sans abonné l'appel est sans effet, ce qui est le cas
            # normal — un run tourne aussi bien sans navigateur connecté.
            publish(state["project_id"], RunEvent("token", {"text": event.text}))
        elif isinstance(event, StreamRestart):
            # Le flux est reparti entier sur le fournisseur suivant (§5.2) :
            # ce qui avait déjà été accumulé n'est plus la section, sous
            # peine de coller un faux départ devant le texte relancé.
            pieces = []
            # Le front doit vider son affichage pour la même raison, sinon il
            # montrerait le faux départ suivi du vrai texte.
            publish(state["project_id"], RunEvent("section_restart", {
                "document": ref.document, "section_id": ref.section_id,
            }))
```

- [ ] **Étape 4 : publier depuis `critique`**

`critique` rend aujourd'hui son verdict directement dans le `return`, sans
variables intermédiaires. On les nomme, plutôt que de recalculer l'expression
deux fois :

```python
    verdict = reponse.parsed
    score = verdict.score if verdict else 0
    problems = verdict.problems if verdict else []
    publish(state["project_id"], RunEvent("score", {
        "score": score, "problems": problems,
    }))
    return {"score": score, "problems": problems}
```

Le repli sur `0` et `[]` quand `verdict` est `None` existe déjà : on le
déplace, on ne le change pas. Une note de zéro est en dessous de
`REWRITE_SCORE`, donc une réponse hors schéma fait repartir la section en
réécriture — c'était déjà le comportement, et il reste.

- [ ] **Étape 5 : publier depuis `save`**

`save` n'a pas de `transport` et ne prend pas le second membre de `_current` :
sa première ligne est `ref, _ = _current(state)`, donc `ref` est disponible.
Après le bloc `async with connection()`, avant le `return` :

```python
    publish(state["project_id"], RunEvent("section_saved", {
        "document": ref.document,
        "section_id": ref.section_id,
        "score": state["score"],
    }))
    publish(state["project_id"], RunEvent("progress", {
        "cursor": state["cursor"] + 1,
        "total": len(state["plan"]),
    }))
```

`state["cursor"] + 1` et non `state["cursor"]` : le curseur publié est celui
d'après l'avancée. Le front affiche « 4 sections sur 30 », pas la section
qu'il vient de quitter.

- [ ] **Étape 6 : lancer les tests pour les voir passer**

```bash
cd backend && uv run pytest tests/test_node_events.py -v
```

Attendu : 4 passés.

- [ ] **Étape 7 : vérifier par mutation**

| Mutation | Doit faire tomber |
|---|---|
| retirer le `publish` de `write` | `test_writing_publishes_its_tokens` |
| `"cursor": state["cursor"]` au lieu de `+ 1` | `test_saving_publishes_the_section_and_the_progress` |
| publier `section_saved` **après** `progress` | le même (l'ordre est une valeur de contrat) |


- [ ] **Étape 7 bis : les quatre trous que la relecture a trouvés par mutation**

L'implémentation de `nodes.py` est juste — le relecteur a construit tous les
chemins, y compris ceux que la suite ne couvre pas, et n'a trouvé aucun
défaut de comportement. Mais **quatre mutations survivent**, c'est-à-dire que
quatre propriétés du contrat ne sont tenues par rien. La couche SSE de la
tâche 6 s'appuiera sur deux d'entre elles.

Ajouter ces tests à `backend/tests/test_node_events.py` :

```python
async def test_a_restart_is_published_between_the_false_start_and_the_real_text(project):
    """L'ordre est le contrat, autant que la charge utile.

    Publié trop tôt, le navigateur effacerait du texte valide ; trop tard, il
    laisserait le faux départ collé devant le vrai. Et sans `document` ni
    `section_id`, il ne saurait pas quelle section vider — un projet `both`
    en a soixante.

    `FakeTransport` ne rompt jamais un flux : ce chemin ne s'atteint qu'avec
    le simulé sous script de `test_nodes.py`.
    """
    from app.llm.errors import ProviderUnavailable
    from tests.test_nodes import _RestartingTransport

    stub = _RestartingTransport({
        ("gemini", "gemini-3.1-flash-lite"): [
            "Un faux départ jamais gardé.",
            ProviderUnavailable("gemini", "erreur", "flux rompu"),
        ],
        ("mistral", "ministral-8b-latest"): ["Le texte définitif de la section."],
    })
    async with subscribe(project) as events:
        await nodes.write(_state(project), transport=stub)
        received = await _collect(events, 200)

    names = [e.name for e in received]
    assert "section_restart" in names, "la reprise de flux n'a pas été publiée"
    cut = names.index("section_restart")
    before = "".join(e.data["text"] for e in received[:cut] if e.name == "token")
    after = "".join(e.data["text"] for e in received[cut + 1:] if e.name == "token")
    assert "faux départ" in before, "le faux départ n'a pas été publié avant la reprise"
    assert "définitif" in after, "le vrai texte n'a pas été publié après la reprise"

    restart = received[cut]
    ref = _state(project)["plan"][0]
    assert restart.data == {"document": ref.document, "section_id": ref.section_id}


async def test_no_empty_fragment_is_ever_published(project):
    """Un `token` vide n'est pas anodin.

    Il signifierait que la publication a quitté la branche `TextDelta` et
    s'applique aussi aux trames de service — reprise de flux, fin de flux.
    Le navigateur recevrait alors des fragments qui ne sont pas du texte, et
    rien dans la concaténation ne le dirait : coller des chaînes vides ne
    change pas le résultat, c'est pourquoi l'assertion sur le texte assemblé
    ne suffit pas à garder cette propriété.
    """
    async with subscribe(project) as events:
        await nodes.write(_state(project), transport=FakeTransport())
        received = await _collect(events, 200)

    tokens = [e for e in received if e.name == "token"]
    assert tokens
    assert all(e.data["text"] for e in tokens), "un fragment vide a été publié"


async def test_the_progress_total_follows_the_state_plan_and_not_the_catalogue(project):
    """`total` vient de `state["plan"]`, et l'écart compte.

    Les deux expressions donnent le même nombre dans le cas nominal, ce qui
    rendait ce contrat intestable : la fixture a toujours un plan qui coïncide
    avec ce qu'une relecture du catalogue produirait. On tronque donc le plan,
    et les deux sources divergent.

    Ce n'est pas une contorsion de test : le plan de l'état est ce qui reste
    juste quand il a été réduit — une reprise partielle, une section rouverte
    — alors qu'une relecture du catalogue rendrait toujours la liste entière
    et afficherait une progression fausse à l'utilisateur.
    """
    from app.agent.state import Paragraph

    state = _state(project, draft=[Paragraph(text="Un texte.")], score=9)
    state["plan"] = state["plan"][:3]

    async with subscribe(project) as events:
        await nodes.save(state)
        received = await _collect(events, 2)

    progress = next(e for e in received if e.name == "progress")
    assert progress.data["total"] == 3, (
        "`total` ne vient pas de `state[\"plan\"]` mais d'une relecture du "
        "catalogue, qui ignore un plan réduit"
    )


async def test_the_published_score_matches_the_returned_one_when_nothing_parses(project):
    """Un navigateur à qui l'on montre une note que le graphe n'a pas suivie
    est un navigateur à qui l'on ment.

    Le chemin de repli — le modèle rend quelque chose d'inexploitable — n'est
    exercé par aucun test : `FakeTransport` rend toujours un schéma valide.
    Or ce repli n'est pas théorique : une note de zéro passe sous
    `REWRITE_SCORE` et renvoie donc la section en réécriture.
    """
    from app.llm.types import Completion

    class _UnparsableTransport(FakeTransport):
        async def chat(self, provider, model, messages, *, schema=None):
            return Completion(text="{}", provider=provider.name, model=model,
                              tokens=1, parsed=None)

    async with subscribe(project) as events:
        maj = await nodes.critique(
            _state(project, draft=[Paragraph(text="Un texte.")]),
            transport=_UnparsableTransport())
        received = await _collect(events, 1)

    assert maj["score"] == 0 and maj["problems"] == []
    published = next(e for e in received if e.name == "score")
    assert published.data["score"] == maj["score"]
    assert published.data["problems"] == maj["problems"]
```

`Paragraph` s'importe depuis `app.agent.state` ; le fichier le fait déjà
dans une autre fonction, remontez l'import en tête plutôt que de le répéter.

- [ ] **Étape 7 ter : rejouer les quatre mutations qui survivaient**

| Mutation | Doit faire tomber |
|---|---|
| publier `token` hors de la branche `TextDelta`, par `getattr(event, "text", "")` | `..._no_empty_fragment_is_ever_published` |
| `section_restart` publié avec `{}` | `..._restart_is_published_between...` |
| `"total": len(_catalogue().plan_for(...))` au lieu de `len(state["plan"])` | `..._progress_total_follows_the_state_plan...` |
| `critique` publiant `verdict.score` au lieu de `score` | `..._published_score_matches_the_returned_one...` |

Les quatre laissaient les 385 tests au vert avant ces ajouts. Si l'une reste
verte après, c'est le test qu'il faut corriger, pas la mutation.
- [ ] **Étape 8 : lancer la suite complète**

```bash
cd backend && uv run pytest -m "not network" -q
```

Attendu : 389 passés, 5 désélectionnés. **Si un test antérieur change de
couleur, la publication est au mauvais endroit** — c'est le signal que la
tâche a débordé, pas une broutille à contourner.

- [ ] **Étape 9 : commiter**

```bash
git add backend/app/agent/nodes.py backend/tests/test_node_events.py
git commit -m "feat(agent): les nœuds publient la rédaction, la note et l'avancement"
```

---

### Tâche 3 : le pilote de run

**Fichiers :**
- Créer : `backend/app/runs/registry.py`
- Créer : `backend/app/runs/runner.py`
- Modifier : `backend/app/projects/repository.py` — ajouter `set_run_status`
- Test : `backend/tests/test_runner.py`

**Interfaces :**
- Consomme : `RunEvent`, `publish` (tâche 1) ; `compiled_graph`,
  `initial_state` (`app/agent/graph.py`) ; `purge_checkpoints`
  (`app/agent/checkpointer.py`) ; `project_for_user` (`app/projects/repository.py`).
- Produit :
  - `start_run(project_id: str, thread_id: str, graph_input) -> None` —
    lance la tâche de fond, rend la main immédiatement
  - `advance(project_id: str, thread_id: str, graph_input) -> None` — le
    corps de la tâche, testable sans asyncio de fond
  - `RunAlreadyRunning` — exception levée par `start_run` si une tâche vit
    déjà pour ce projet
  - `set_run_status(conn, project_id: UUID, status: str) -> None`
  - `RUN_STATUSES = ("idle", "running", "waiting", "failed", "done")`

**Ce que le pilote doit garantir, et pourquoi :**

- **Un run ne vit jamais dans une requête HTTP.** Le §8 de la spec dit que la
  connexion SSE coupée ne perd rien ; cela n'a de sens que si le run tourne
  ailleurs. `start_run` crée une tâche et rend la main.
- **`run_status` dit la vérité à l'instant près.** `running` pendant que le
  graphe avance, `waiting` dès qu'il s'arrête sur une interruption, `done`
  au bout, `failed` sur exception. C'est ce que `/state` lit, et c'est ce que
  la réconciliation du démarrage (tâche 7) corrige quand le processus est
  mort sans repasser par là.
- **La purge tourne à la fin d'un run** (§9.3). `purge_checkpoints` est écrit
  et testé depuis le plan 3 et **n'a jamais eu d'appelant** — c'est le
  constat 8 de la revue finale. Il en a un ici.
- **Une exception ne disparaît pas.** Une tâche asyncio dont personne
  n'attend le résultat avale son exception jusqu'au ramasse-miettes. Le run
  passe en `failed`, publie un `error`, et l'exception est journalisée.

- [ ] **Étape 1 : écrire `set_run_status` dans le dépôt**

Dans `backend/app/projects/repository.py`, à la suite de `project_for_user` :

```python
RUN_STATUSES = ("idle", "running", "waiting", "failed", "done")


async def set_run_status(conn, project_id: UUID, status: str) -> None:
    """Le seul chemin d'écriture de `run_status`.

    Le contrôle sur `RUN_STATUSES` est ici et non à l'appelant : la colonne
    est du texte libre côté base, et une faute de frappe y passerait sans
    bruit pour ne se voir qu'à l'affichage, des heures plus tard.

    `updated_at` suit : l'index de la liste du propriétaire trie dessus, et
    un projet qui avance sans remonter dans la liste serait déroutant.
    """
    if status not in RUN_STATUSES:
        raise ValueError(f"statut de run inconnu : {status}")
    async with conn.cursor() as cur:
        await cur.execute(
            "update projects set run_status = %s, updated_at = now() where id = %s",
            (status, project_id),
        )
```

- [ ] **Étape 2 : écrire les tests qui échouent**

```python
# backend/tests/test_runner.py
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio

from app.agent.graph import initial_state
from app.core.db import connection
from app.projects.repository import create_project, project_for_user, set_run_status
from app.runs.events import subscribe
from app.runs.runner import RunAlreadyRunning, advance, start_run


@pytest_asyncio.fixture
async def project(migrated_db, monkeypatch):
    # `ESQUISSE_FAKE_LLM` n'est pas un détail de confort : le pilote appelle
    # le graphe SANS lui passer de transport, et la passerelle lit donc le
    # réglage. Sans cette ligne, `advance` partirait vers les vrais
    # fournisseurs au milieu d'une suite qui s'annonce hors-réseau. Même
    # montage que `tests/test_graph.py::project`.
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config
    config.settings.cache_clear()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id",
                (f"runner-{uuid4()}@exemple.fr",),
            )
            user_id = (await cur.fetchone())[0]
        # Le fil est tiré AVANT l'insertion et réutilisé tel quel : le rendre
        # différent de celui écrit en base donnerait des tests qui passent
        # tout en pilotant un autre point de reprise que le projet.
        thread_id = f"thread-{uuid4()}"
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="consultation", profil_bp=None,
            thread_id=thread_id, templates_version="0.1",
        )
    yield {"project_id": project_id, "user_id": user_id,
           "thread_id": thread_id}
    # Démontage : le point de reprise ouvre un pool lié à la boucle
    # d'événements du test, et pytest-asyncio en donne une neuve à chacun.
    # Le laisser derrière soi ferait échouer un test suivant sans rapport.
    from app.agent.checkpointer import close_checkpointer

    await close_checkpointer()
    config.settings.cache_clear()


async def _status(project_id, user_id):
    async with connection() as conn:
        row = await project_for_user(conn, project_id, user_id)
    return row["run_status"]


async def test_a_run_stops_on_its_first_interruption_and_says_so(project):
    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    await advance(str(project["project_id"]), project["thread_id"], graph_input)
    assert await _status(project["project_id"], project["user_id"]) == "waiting"


async def test_the_interruption_is_published(project):
    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    async with subscribe(str(project["project_id"])) as events:
        await advance(str(project["project_id"]), project["thread_id"], graph_input)
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except asyncio.TimeoutError:
            pass
    interactions = [e for e in received if e.name == "interaction"]
    assert interactions, "l'interruption n'a pas été publiée"
    assert "id" in interactions[-1].data, (
        "sans project_id d'interaction, /answer ne peut pas être idempotent"
    )
    assert interactions[-1].data["kind"] in {"questions", "review",
                                             "inconsistencies"}


async def test_a_failing_run_is_marked_failed_and_publishes_an_error(project):
    async with subscribe(str(project["project_id"])) as events:
        # Une entrée invalide : le catalogue refuse un profil inconnu, donc
        # `initial_state` lève dès la construction du plan. On appelle
        # `advance` avec un état déjà construit mais au plan vide, ce qui
        # fait sortir le graphe des bornes de son curseur.
        await advance(str(project["project_id"]), project["thread_id"],
                      {"plan": [], "cursor": 5})
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except asyncio.TimeoutError:
            pass
    assert await _status(project["project_id"], project["user_id"]) == "failed"
    errors = [e for e in received if e.name == "error"]
    assert errors, "un run en échec doit le dire sur le flux"
    assert errors[-1].data["reprenable"] is True


async def test_a_finished_run_marks_done_then_purges_then_says_so(project, monkeypatch):
    """Le VRAI chemin de fin, pas une trappe de test.

    La première version de ce test passait par un paramètre `_force_done`
    qui sautait tout le bloc `try` : elle prouvait que la trappe purgeait,
    jamais qu'un graphe terminé purge. Mettre tout le corps de fin derrière
    ce drapeau laissait les 394 tests au vert. On remplace donc le graphe,
    pas le chemin.

    `purge_checkpoints` est écrit et testé depuis le plan 3 et n'avait aucun
    appelant — constat 8 de la revue finale. Il en a un ici.
    """
    from types import SimpleNamespace

    from app.agent import checkpointer
    from app.runs import runner

    class _FinishedGraph:
        async def ainvoke(self, graph_input, config):
            return {}

        async def aget_state(self, config):
            return SimpleNamespace(interrupts=(), values={})

    async def _finished_graph():
        return _FinishedGraph()

    calls = []

    async def _count_calls(thread_id, keep=1):
        calls.append((thread_id, keep))
        return 0

    monkeypatch.setattr(runner, "compiled_graph", _finished_graph)
    monkeypatch.setattr(checkpointer, "purge_checkpoints", _count_calls)

    async with subscribe(str(project["project_id"])) as events:
        await advance(str(project["project_id"]), project["thread_id"], None)
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass

    assert calls == [(project["thread_id"], 1)], (
        "un run terminé doit purger ses points de reprise"
    )
    assert await _status(project["project_id"], project["user_id"]) == "done"
    assert [e.name for e in received] == ["done"]


async def test_the_status_is_written_before_the_event_leaves(project, monkeypatch):
    """L'ordre, et pas seulement le contenu.

    Un client qui appelle `/state` en réaction à un événement doit trouver la
    colonne déjà à jour. On enregistre l'ordre réel des deux effets plutôt
    que de guetter une course : un test qui dépend de l'ordonnanceur passe ou
    non selon la machine, ce qui est la pire sorte.
    """
    from app.runs import runner

    order = []
    real_status, real_publish = runner._status, runner.publish

    async def _record_status(project_id, status):
        order.append(f"status:{status}")
        await real_status(project_id, status)

    def _record_publish(project_id, event):
        order.append(f"publish:{event.name}")
        real_publish(project_id, event)

    monkeypatch.setattr(runner, "_status", _record_status)
    monkeypatch.setattr(runner, "publish", _record_publish)

    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    await advance(str(project["project_id"]), project["thread_id"], graph_input)

    assert order[0] == "status:running", (
        "le run doit s'annoncer en cours avant de faire quoi que ce soit"
    )
    assert "status:waiting" in order and "publish:interaction" in order
    assert order.index("status:waiting") < order.index("publish:interaction")


async def test_the_error_event_leaves_even_if_the_database_is_unreachable(project, monkeypatch):
    """Le filet ne doit pas pouvoir être tué par ce qui l'a rendu nécessaire.

    `_status` ouvre une connexion. Si la base est la cause de l'échec, elle
    lèvera aussi en marquant l'échec — et dans l'ordre inverse cette seconde
    levée emporterait la publication, depuis une tâche que personne
    n'attend. Le run mourrait alors en silence, ce que ce bloc existe pour
    empêcher.
    """
    from app.runs import runner

    real_status = runner._status

    async def _refuse_failed(project_id, status):
        if status == "failed":
            raise RuntimeError("base injoignable")
        await real_status(project_id, status)

    monkeypatch.setattr(runner, "_status", _refuse_failed)

    async with subscribe(str(project["project_id"])) as events:
        await advance(str(project["project_id"]), project["thread_id"],
                      {"plan": [], "cursor": 5})
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass

    errors = [e for e in received if e.name == "error"]
    assert errors, (
        "l'événement d'erreur n'est pas parti : une base injoignable a "
        "emporté le filet qu'elle rendait nécessaire"
    )


async def test_an_unknown_run_status_is_refused():
    """La seule logique neuve de `repository.py`, et rien ne l'exerçait.

    La colonne est du texte libre côté base : une faute de frappe y passerait
    sans bruit pour ne se voir qu'à l'affichage, des heures plus tard.
    """
    async with connection() as conn:
        with pytest.raises(ValueError, match="statut de run inconnu"):
            await set_run_status(conn, uuid4(), "en_cours")


async def test_a_finished_task_never_unregisters_its_successor():
    """Le défaut que la relecture a reproduit.

    Le rappel de fin retirait par clé. La tâche A qui se termine effaçait
    donc l'entrée de la tâche B qui venait de la remplacer : `is_running`
    répondait « non » pour un run bien vivant, le garde de
    `RunAlreadyRunning` tombait, et `cancel_all` ne voyait plus l'orpheline.
    """
    from app.runs import registry

    async def _immediate():
        return None

    async def _long():
        await asyncio.sleep(10)

    first = asyncio.create_task(_immediate())
    registry.register("projet-course", first)
    await first

    second = asyncio.create_task(_long())
    registry.register("projet-course", second)
    try:
        # Le rappel de `first` s'exécute au tour de boucle suivant.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert registry.is_running("projet-course"), (
            "le rappel de la tâche terminée a désenregistré sa remplaçante"
        )
    finally:
        await registry.cancel_all()


async def test_two_starts_for_the_same_project_are_refused(project):
    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    start_run(str(project["project_id"]), project["thread_id"], graph_input)
    try:
        with pytest.raises(RunAlreadyRunning):
            start_run(str(project["project_id"]), project["thread_id"],
                      graph_input)
    finally:
        from app.runs.registry import cancel_all

        await cancel_all()
```

- [ ] **Étape 3 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_runner.py -v
```

Attendu : `ModuleNotFoundError: No module named 'app.runs.runner'`.

- [ ] **Étape 4 : écrire le registre**

```python
# backend/app/runs/registry.py
import asyncio
import logging

logger = logging.getLogger(__name__)

# Une tâche par projet, sur la durée de vie du processus.
#
# COMME LE BUS, CE REGISTRE EST EN MÉMOIRE (§9.2). Avec deux instances,
# chacune croirait être seule à piloter un projet et deux runs avanceraient
# le même graphe en parallèle — deux points de reprise concurrents sur le
# même `thread_id`, c'est-à-dire de la corruption silencieuse. La contrainte
# « une seule instance » n'est pas un détail d'exploitation, elle est
# structurelle tant que ce dictionnaire existe.
_tasks: dict[str, asyncio.Task] = {}


def register(project_id: str, task: asyncio.Task) -> None:
    _tasks[project_id] = task
    # Le rappel de fin vérifie l'IDENTITÉ de la tâche avant de retirer
    # l'entrée, et ce n'est pas une précaution de style.
    #
    # `is_running` passe à faux dès qu'une tâche se termine, mais le rappel
    # ne s'exécute qu'au tour de boucle suivant. Dans cet intervalle, une
    # coroutine déjà prête — une requête `/answer` qui reprend, par exemple —
    # passe le garde, `register` remplace l'entrée, puis le rappel de la
    # tâche A efface l'entrée de la tâche B. Deux tâches avancent alors le
    # même `thread_id` — exactement la corruption que ce module existe pour
    # empêcher — et `cancel_all` ne voit plus l'orpheline.
    #
    # Reproduit, pas supposé : la relecture de cette tâche en a produit une
    # démonstration autonome.
    task.add_done_callback(_forget(project_id))


def _forget(project_id: str):
    """Le rappel qui ne retire que sa propre tâche."""
    def _callback(task: asyncio.Task) -> None:
        if _tasks.get(project_id) is task:
            del _tasks[project_id]
    return _callback


def is_running(project_id: str) -> bool:
    task = _tasks.get(project_id)
    return task is not None and not task.done()


async def cancel_all() -> None:
    """Annule tout et attend que ce soit fait.

    Appelée à l'arrêt de l'application, et par les tests qui ont lancé une
    tâche de fond — sans quoi une tâche survivrait à son test et écrirait
    dans une base que le test suivant croit à lui.
    """
    pending = dict(_tasks)
    for task in pending.values():
        task.cancel()
    for project_id, task in pending.items():
        try:
            await task
        except BaseException:
            # `BaseException` et non `Exception` : l'annulation qu'on vient
            # de demander se présente en `CancelledError`, qui n'hérite plus
            # d'`Exception` depuis Python 3.8. Un vrai échec de run remonte
            # aussi par ici à l'arrêt ; on le journalise plutôt que de le
            # perdre en silence.
            logger.debug("run %s terminé à l'arrêt", project_id, exc_info=True)
        # On ne retire que ce qu'on a annulé. Un `_tasks.clear()` final
        # emporterait une tâche enregistrée pendant qu'on attendait.
        if _tasks.get(project_id) is task:
            del _tasks[project_id]
```

- [ ] **Étape 5 : écrire le pilote**

```python
# backend/app/runs/runner.py
import asyncio
import logging

from langgraph.types import Command

from app.agent import checkpointer
from app.agent.graph import compiled_graph
from app.core.db import connection
from app.projects.repository import set_run_status
from app.runs import registry
from app.runs.events import RunEvent, publish

logger = logging.getLogger(__name__)


class RunAlreadyRunning(RuntimeError):
    """Un run avance déjà pour ce projet.

    Ce n'est pas une erreur d'utilisateur mais un garde-fou : deux tâches sur
    le même `thread_id` écriraient deux points de reprise concurrents.
    """


def start_run(project_id: str, thread_id: str, graph_input) -> None:
    """Lance le run en tâche de fond et rend la main tout de suite.

    La requête HTTP qui appelle ceci ne doit pas attendre : une section prend
    des dizaines de secondes et le §8 veut que la coupure du client ne change
    rien au run.
    """
    if registry.is_running(project_id):
        raise RunAlreadyRunning(project_id)
    task = asyncio.create_task(advance(project_id, thread_id, graph_input))
    registry.register(project_id, task)


async def advance(project_id: str, thread_id: str, graph_input) -> None:
    """Avance le graphe jusqu'à l'interruption suivante ou jusqu'au bout.

    Fonction séparée de `start_run` pour être appelable directement : un test
    du pilote n'a pas à se battre avec l'ordonnanceur pour savoir quand la
    tâche a fini.
    """
    config = {"configurable": {"thread_id": thread_id}}
    await _status(project_id, "running")
    try:
        graph = await compiled_graph()
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)
    except asyncio.CancelledError:
        # L'arrêt de l'application. On ne touche pas au statut : la ligne
        # reste `running` et la réconciliation du démarrage suivant la
        # repassera en `failed` en proposant « Reprendre » (tâche 7). Tant
        # que cette réconciliation n'existe pas, la colonne ment après une
        # annulation — c'est assumé, et c'est la tâche 7 qui le referme.
        #
        # Cette clause est documentaire : depuis Python 3.8,
        # `CancelledError` hérite de `BaseException` et non d'`Exception`,
        # donc le bloc suivant ne l'aurait pas attrapée de toute façon. On
        # l'écrit pour que le lecteur sache que le cas a été pesé, pas
        # oublié.
        raise
    except Exception as error:
        await _fail(project_id, error)
        return

    # Le statut AVANT la publication, dans les deux sorties. Un client qui
    # appelle `/state` en réaction à l'événement doit trouver la colonne déjà
    # à jour ; l'ordre inverse lui montrerait l'état d'avant, une fois sur
    # on ne sait combien.
    if snapshot.interrupts:
        await _status(project_id, "waiting")
        await _publish_interrupt(project_id, snapshot.interrupts[0])
        return

    await _status(project_id, "done")
    # §9.3 : la purge tourne à la fin d'un run. L'appel passe par le module
    # et non par un nom importé, pour que le test puisse le remplacer.
    removed = await checkpointer.purge_checkpoints(thread_id)
    logger.info("run %s terminé, %d points de reprise purgés", project_id, removed)
    publish(project_id, RunEvent("done", {"project_id": project_id}))


async def _fail(project_id: str, error: Exception) -> None:
    """Marque l'échec sans jamais le perdre.

    L'événement part AVANT l'écriture en base, et l'écriture est elle-même
    gardée. `_status` ouvre une connexion : si la base est la cause de
    l'échec initial — le cas le plus probable — elle lèvera ici aussi. Dans
    l'ordre inverse, cette seconde levée emporterait la publication et
    s'échapperait d'une tâche que personne n'attend : le run mourrait en
    silence et `run_status` resterait à `running` pour toujours, c'est-à-dire
    exactement ce que ce bloc existe pour empêcher. Constaté sur une sonde,
    pas déduit.

    `logger.exception` est appelé sous une exception active, il journalise
    donc la trace complète.
    """
    logger.exception("run %s en échec", project_id)
    publish(project_id, RunEvent("error", {
        "code": "run_en_echec",
        "message": str(error) or error.__class__.__name__,
        "reprenable": True,
    }))
    try:
        await _status(project_id, "failed")
    except Exception:
        logger.exception(
            "run %s : impossible d'écrire le statut d'échec", project_id)


async def _publish_interrupt(project_id: str, interrupt) -> None:
    """Publie l'interruption avec son identifiant.

    L'identifiant vient de LangGraph et non de nous : c'est lui que
    `POST /answer` renverra, et c'est en le comparant à l'interruption
    current qu'on saura si la requête rejoue un point déjà dépassé (§6.2).
    """
    publish(project_id, RunEvent("interaction", {
        "id": interrupt.id,
        **interrupt.value,
    }))


async def _status(project_id: str, status: str) -> None:
    from uuid import UUID

    async with connection() as conn:
        await set_run_status(conn, UUID(project_id), status)
```

- [ ] **Étape 6 : lancer les tests pour les voir passer**

```bash
cd backend && uv run pytest tests/test_runner.py -v
```

Attendu : 9 passés.

**`interrupt.id` existe bien**, vérifié sur la version installée avant
d'écrire ce plan : `langgraph.types.Interrupt` est une dataclass à deux
champs, `value` et `id`, ce dernier documenté « Can be used to resume the
interrupt directly ». Les champs `ns`, `when`, `resumable` et
`interrupt_id` ont été retirés en 0.6.0 ; si vous lisez un exemple en ligne
qui les emploie, il est périmé.

- [ ] **Étape 7 : vérifier par mutation**

| Mutation | Doit faire tomber |
|---|---|
| retirer l'appel à `purge_checkpoints` | `..._finished_run_marks_done_then_purges_then_says_so` |
| `except Exception` qui relève au lieu d'appeler `_fail` | `..._failing_run_is_marked_failed...` |
| `registry.is_running` rendant toujours `False` | `..._two_starts_for_the_same_project_are_refused` |
| ne pas publier l'identifiant dans `interaction` | `..._interruption_is_published` |
| purger AVANT d'écrire `done` | `..._finished_run_marks_done_then_purges_then_says_so` |
| écrire `waiting` APRÈS avoir publié l'interruption | `..._status_is_written_before_the_event_leaves` |
| supprimer l'écriture de `running` | le même |
| `_fail` écrivant le statut AVANT de publier | `..._error_event_leaves_even_if_the_database_is_unreachable` |
| retirer le contrôle sur `RUN_STATUSES` | `..._unknown_run_status_is_refused` |
| `_forget` retirant par clé sans contrôler l'identité | `..._finished_task_never_unregisters_its_successor` |

Ces six dernières laissaient les 394 tests au vert avant cette correction.
La relecture les a trouvées par mutation, aucune par lecture.

- [ ] **Étape 8 : lancer la suite complète, puis commiter**

```bash
cd backend && uv run pytest -m "not network" -q
git add backend/app/runs/registry.py backend/app/runs/runner.py \
        backend/app/projects/repository.py backend/tests/test_runner.py
git commit -m "feat(runs): un pilote qui conduit le graphe hors de la requête HTTP"
```

Attendu : 398 passés, 5 désélectionnés.

---

### Tâche 4 : les routes de projet

**Fichiers :**
- Créer : `backend/app/projects/schemas.py`
- Créer : `backend/app/projects/routes.py`
- Modifier : `backend/app/projects/repository.py` — ajouter `projects_of_user`
- Modifier : `backend/app/main.py` — monter le routeur
- Test : `backend/tests/test_project_routes.py`

**Interfaces :**
- Consomme : `active_user` (`app/auth/dependencies.py`), `create_project`,
  `project_for_user`, `set_run_status` (`app/projects/repository.py`),
  `start_run` (`app/runs/runner.py`), `load_facts`, `load_sections`
  (`app/agent/projections.py`), `compiled_graph` (`app/agent/graph.py`).
- Produit : `router` monté sans préfixe (les chemins portent `/projects`),
  et les schémas `ProjectCreate`, `ProjectSummary`, `ProjectState`.

**Les quatre routes :**

| Route | Ce qu'elle fait |
|---|---|
| `POST /projects` | Crée la ligne, démarre le run, rend `201` et l'entête |
| `GET /projects` | La liste du propriétaire, la plus récemment modifiée d'abord |
| `GET /projects/{id}` | Entête et progression |
| `GET /projects/{id}/state` | Plan, faits, sections, interaction en attente |

**Le point de sécurité, non négociable :** un projet qui n'appartient pas à
l'appelant répond **`404`, jamais `403`**. Un `403` confirmerait que
l'identifiant existe, ce qui suffit à énumérer les projets des autres. Le
filtre sur le propriétaire vit dans `project_for_user`, dans la requête SQL
elle-même : aucune route ne le refait à la main.

- [ ] **Étape 1 : ajouter `projects_of_user` au dépôt**

```python
async def projects_of_user(conn, user_id: UUID) -> list[dict]:
    """La liste du propriétaire, la plus récemment modifiée d'abord.

    Le tri suit l'index `(user_id, updated_at desc)` posé par la migration
    0002 : sans lui, cette requête ferait un balayage complet dès que la
    table grossirait.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select id, nom, documents, profil_cdc, profil_bp,
                   run_status, created_at, updated_at
            from projects where user_id = %s order by updated_at desc
            """,
            (user_id,),
        )
        return [dict(row) for row in await cur.fetchall()]
```

**Attention au format des lignes.** `project_for_user` lit ses colonnes par
index (`row[0]`), ce qui indique que le curseur ne rend pas des dicts par
défaut. Vérifiez comment `app/core/db.py` configure `row_factory` avant
d'écrire `dict(row)`, et alignez-vous sur ce que fait déjà
`project_for_user` plutôt que d'introduire un second usage.

- [ ] **Étape 2 : écrire les schémas**

```python
# backend/app/projects/schemas.py
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    """Ce que le front envoie pour créer un projet.

    Les profils sont conditionnels : un projet `cdc` n'a pas de profil de
    business plan, et réclamer les deux obligerait le front à inventer une
    valeur. Le validateur croisé dit lequel est requis — sans lui,
    `plan_for` lèverait plus loin, avec un message qui parlerait du
    catalogue et non du formulaire.
    """

    nom: str = Field(min_length=1, max_length=200)
    documents: Literal["cdc", "bp", "both"]
    profil_cdc: Literal["consultation", "cadrage"] | None = None
    profil_bp: Literal["banque", "investisseur"] | None = None
    idee: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def _profiles_match_the_documents(self):
        if self.documents in ("cdc", "both") and self.profil_cdc is None:
            raise ValueError("profil_cdc est requis pour ce choix de documents")
        if self.documents in ("bp", "both") and self.profil_bp is None:
            raise ValueError("profil_bp est requis pour ce choix de documents")
        return self


class ProjectSummary(BaseModel):
    id: UUID
    nom: str
    documents: str
    profil_cdc: str | None
    profil_bp: str | None
    run_status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectState(BaseModel):
    """Tout ce qu'il faut pour peindre l'écran sans réhydrater le graphe.

    `interaction` est `None` quand le run avance : le front affiche alors la
    rédaction en cours, qu'il reçoit par le flux.
    """

    projet: ProjectSummary
    plan: list[dict]
    curseur: int
    faits: dict[str, dict]
    sections: list[dict]
    interaction: dict | None
```

- [ ] **Étape 3 : écrire les tests qui échouent**

```python
# backend/tests/test_project_routes.py
import pytest_asyncio

CREATION = {
    "nom": "CoachDom",
    "documents": "cdc",
    "profil_cdc": "consultation",
    "idee": "Une plateforme de coaching sportif à domicile.",
}
MOT_DE_PASSE = "motdepasse123"


async def _active_account(client, email: str) -> dict:
    """Inscrit, active en base, se connecte, rend l'en-tête d'autorisation.

    Même motif que `tests/test_login.py::_register_and_activate` : le contrat
    d'API est en français — `mot_de_passe` à l'entrée, `jeton` à la sortie.
    """
    from app.core.db import connection

    await client.post("/auth/register",
                      json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update users set is_active = true where email = %s", (email,))
    response = await client.post(
        "/auth/login", json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    return {"Authorization": f"Bearer {response.json()['jeton']}"}


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "projets@exemple.fr")


async def test_creating_a_project_returns_its_header(client, account):
    response = await client.post("/projects", json=CREATION, headers=account)
    assert response.status_code == 201
    body = response.json()
    assert body["nom"] == "CoachDom"
    assert "id" in body
    # `idle` est admis, et ce n'est pas une faiblesse du test : `start_run`
    # crée une tâche et rend la main, donc la ligne peut être relue avant
    # que le pilote ait eu son tour d'ordonnanceur. Exiger `running` ici
    # ferait un test qui passe ou non selon la charge de la machine — le
    # pire genre. C'est `/state` et le flux qui disent où en est le run.
    assert body["run_status"] in {"idle", "running", "waiting"}


async def test_a_project_without_its_profile_is_refused(client, account):
    response = await client.post(
        "/projects", json={**CREATION, "profil_cdc": None}, headers=account)
    assert response.status_code == 422


async def test_the_list_only_holds_the_owners_projects(client, account):
    await client.post("/projects", json=CREATION, headers=account)

    # Un second compte, avec son propre projet.
    other_account = await _active_account(client, "intrus@exemple.fr")
    await client.post("/projects", json={**CREATION, "nom": "PasÀToi"},
                      headers=other_account)

    names = [p["nom"] for p in (await client.get("/projects", headers=account)).json()]
    assert names == ["CoachDom"]
    assert "PasÀToi" not in names


async def test_another_users_project_is_not_found_never_forbidden(client, account):
    owner = await _active_account(client, "owner@exemple.fr")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]

    for chemin in (f"/projects/{project_id}", f"/projects/{project_id}/state"):
        response = await client.get(chemin, headers=account)
        assert response.status_code == 404, (
            f"{chemin} a répondu {response.status_code} : un 403 confirmerait "
            "que l'identifiant existe, ce qui suffit à énumérer les projets "
            "des autres"
        )


async def test_an_unauthenticated_call_is_refused(client):
    assert (await client.get("/projects")).status_code in (401, 403)


async def test_the_state_carries_the_plan_and_the_pending_interaction(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    # Le run tourne en tâche de fond : on lui laisse atteindre sa première
    # interruption avant de lire l'état.
    import asyncio

    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    assert state_body["plan"], "le plan est vide"
    assert state_body["curseur"] == 0
    assert state_body["interaction"]["kind"] in {"questions", "review",
                                           "inconsistencies"}
    assert "id" in state_body["interaction"]
```

- [ ] **Étape 4 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_project_routes.py -v
```

Attendu : `404` sur toutes les routes — le routeur n'est pas monté.

- [ ] **Étape 5 : écrire les routes**

```python
# backend/app/projects/routes.py
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.graph import compiled_graph, initial_state
from app.agent.projections import load_facts, load_sections
from app.agent.templates import load_catalogue
from app.auth.dependencies import active_user
from app.core.db import connection
from app.projects.repository import (
    ProjectNotFound,
    create_project,
    project_for_user,
    projects_of_user,
)
from app.projects.schemas import ProjectCreate, ProjectState, ProjectSummary
from app.runs.runner import RunAlreadyRunning, start_run

router = APIRouter(prefix="/projects", tags=["projets"])


async def _owned(project_id: UUID, user) -> dict:
    """Le projet, ou 404.

    `project_for_user` LÈVE `ProjectNotFound` — elle ne rend pas `None`.
    Sa docstring dit pourquoi les deux cas se confondent : « n'existe pas »
    et « appartient à quelqu'un d'other_account » se répondent pareil, sans quoi les
    identifiants deviendraient énumérables. On traduit l'exception en 404,
    on ne réinvente pas le filtre.
    """
    async with connection() as conn:
        try:
            return await project_for_user(conn, project_id, user["id"])
        except ProjectNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                {"code": "projet_introuvable"}) from None


@router.post("", status_code=status.HTTP_201_CREATED,
             response_model=ProjectSummary)
async def create(body: ProjectCreate, user=Depends(active_user)):
    """Crée le projet et démarre son run.

    Le `thread_id` est tiré ici et porté par la ligne : c'est la seule chose
    qui relie une ligne `projects` à son point de reprise LangGraph, et la
    contrainte d'unicité de la colonne empêche deux projets de partager un
    fil.
    """
    thread_id = f"projet-{uuid4()}"
    catalogue = load_catalogue()
    async with connection() as conn:
        project_id = await create_project(
            conn, user["id"], nom=body.nom, documents=body.documents,
            profil_cdc=body.profil_cdc, profil_bp=body.profil_bp,
            thread_id=thread_id,
            templates_version=str(catalogue.cdc.version),
        )
    start_run(
        str(project_id), thread_id,
        initial_state(str(project_id), body.documents, body.profil_cdc,
                      body.profil_bp, body.idee),
    )
    # On ne guette pas un statut « stable » avant de répondre : le run vient
    # de partir en tâche de fond et la ligne peut porter encore `idle`.
    # Attendre ici rendrait la création lente et le code de retour
    # dépendant de l'ordonnanceur.
    async with connection() as conn:
        row = await project_for_user(conn, project_id, user["id"])
    return ProjectSummary(**row)


@router.get("", response_model=list[ProjectSummary])
async def listing(user=Depends(active_user)):
    async with connection() as conn:
        return [ProjectSummary(**row)
                for row in await projects_of_user(conn, user["id"])]


@router.get("/{project_id}", response_model=ProjectSummary)
async def header(project_id: UUID, user=Depends(active_user)):
    return ProjectSummary(**await _owned(project_id, user))


@router.get("/{project_id}/state", response_model=ProjectState)
async def state(project_id: UUID, user=Depends(active_user)):
    """L'état complet, lu du point de reprise pour l'interaction et des
    projections pour le reste.

    Deux sources et non une seule : le point de reprise sait seul quelle
    interruption est en attente, les projections répondent sans réhydrater
    le graphe — ce qui est tout leur objet (§4.6).
    """
    row = await _owned(project_id, user)
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)

    interaction = None
    if snapshot.interrupts:
        pending = snapshot.interrupts[0]
        interaction = {"id": pending.id, **pending.value}

    values = snapshot.values or {}
    async with connection() as conn:
        facts = await load_facts(conn, project_id)
        sections = await load_sections(conn, project_id)

    return ProjectState(
        projet=ProjectSummary(**row),
        plan=[ref.model_dump() for ref in values.get("plan", [])],
        curseur=values.get("cursor", 0),
        faits={key: fact.model_dump() for key, fact in facts.items()},
        sections=sections,
        interaction=interaction,
    )
```

- [ ] **Étape 6 : monter le routeur**

Dans `backend/app/main.py`, à la suite des routeurs d'authentification :

```python
    from app.projects.routes import router as projects_router
    app.include_router(projects_router)
```

- [ ] **Étape 7 : lancer les tests, puis la suite complète**

```bash
cd backend && uv run pytest tests/test_project_routes.py -v
cd backend && uv run pytest -m "not network" -q
```

**Deux points vérifiés avant l'écriture de ce plan, pour que vous n'ayez pas
à les redécouvrir :**

`project_for_user` rend bien un `dict` — elle construit ses clés depuis
`cur.description` — mais elle **lève `ProjectNotFound`** au lieu de rendre
`None`. Le code de `_owned` ci-dessus en tient compte.

`SectionTemplate.version` est déclaré `str | float` (un différé connu de la
revue du plan 3 : des guillemets dans les YAML rendraient l'union inutile).
`templates_version` étant une colonne `text`, convertissez : `str(...)`.
Pour un projet `bp` seul, `catalogue.cdc.version` reste néanmoins la valeur
écrite — les deux gabarits sont versionnés ensemble, et c'est la version du
**jeu** de gabarits qui doit être tracée, pas celle d'un document. Si un
jour les deux divergent, cette ligne est l'endroit où le problème se pose.

- [ ] **Étape 8 : vérifier par mutation**

| Mutation | Doit faire tomber |
|---|---|
| `_owned` levant `403` au lieu de `404` | `..._not_found_never_forbidden` |
| `projects_of_user` sans le `where user_id` | `..._list_only_holds_the_owners_projects` |
| retirer le `model_validator` de `ProjectCreate` | `..._without_its_profile_is_refused` |

- [ ] **Étape 9 : commiter**

```bash
git add backend/app/projects/ backend/app/main.py backend/tests/test_project_routes.py
git commit -m "feat(projects): créer un projet, le lister, lire son état"
```

---

### Tâche 5 : répondre à une interaction, sans rejouer

**Fichiers :**
- Modifier : `backend/app/projects/routes.py` — ajouter `POST /{id}/answer`
- Modifier : `backend/app/projects/schemas.py` — ajouter `AnswerRequest`
- Modifier : `backend/app/runs/runner.py` — `advance` accepte un `Command`
- Test : `backend/tests/test_answer.py`

**Interfaces :**
- Consomme : tout ce que la tâche 4 produit, plus `Command`
  (`langgraph.types`) et `Interrupt.id`.
- Produit : `AnswerRequest` — `interaction_id: str`, `reponse: Any`.

**Le §6.2, et pourquoi il n'est pas optionnel :**

> `POST /answer` porte l'identifiant de l'interaction à laquelle il répond.
> Si le run a déjà dépassé ce point — double clic, reconnexion, onglet resté
> ouvert — la requête ne rejoue rien et renvoie l'état courant avec `200`.

Sans cela, un réseau instable fait avancer le graphe deux fois : la même
réponse est consommée par deux interruptions différentes, et l'utilisateur
voit ses réponses décalées d'un cran pour le reste du run. Le défaut est
silencieux et irrattrapable.

**La mécanique, vérifiée avant d'écrire ce plan :** `langgraph.types.Command`
accepte `resume` sous deux formes — une valeur simple, ou **un dictionnaire
d'identifiants d'interruption vers leurs valeurs**. On emploie la seconde :
elle dit explicitement à quelle interruption on répond.

Mais on ne s'en remet pas à LangGraph pour décider qu'une réponse est
périmée. On compare nous-mêmes l'identifiant reçu à celui de l'interruption
courante, **avant** de reprendre. Deux raisons : le comportement de
LangGraph sur un identifiant inconnu n'est pas un contrat qu'on contrôle, et
un test de notre idempotence doit éprouver notre code, pas le sien.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_answer.py
import asyncio

import pytest_asyncio

from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "reponses@exemple.fr")


async def _wait_for_interaction(client, project_id, headers):
    """L'interaction en attente, une fois que le run l'a atteinte.

    Le run tourne en tâche de fond : sans cette attente, le test lirait un
    état où rien n'est encore arrivé et passerait pour de mauvaises raisons.
    """
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=headers)).json()
        if state_body["interaction"] is not None:
            return state_body["interaction"]
        await asyncio.sleep(0.05)
    raise AssertionError("le run n'a jamais atteint d'interruption")


def _answer_for(interaction):
    """Une réponse plausible selon le type d'interruption."""
    if interaction["kind"] == "questions":
        return {q["fact_id"]: "une réponse" for q in interaction["questions"]}
    if interaction["kind"] == "review":
        return {"action": "accept"}
    return []


async def test_answering_advances_the_run(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)
    assert response.status_code == 200

    # Le run repart : soit il atteint une autre interruption, soit il finit.
    for _ in range(200):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        current = state_body["interaction"]
        if current is None or current["id"] != interaction["id"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a pas dépassé l'interruption répondue")


async def test_answering_twice_does_not_advance_twice(client, account):
    """Le double-clic, et le §6.2.

    La seconde requête doit répondre 200 sans rien rejouer. Si elle rejouait,
    la réponse serait consommée par l'interruption SUIVANTE et tout le reste
    du run serait décalé d'un cran — en silence.
    """
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    body = {"interaction_id": interaction["id"],
             "reponse": _answer_for(interaction)}

    first = await client.post(f"/projects/{project_id}/answer",
                                 json=body, headers=account)
    second = await client.post(f"/projects/{project_id}/answer",
                                json=body, headers=account)

    assert first.status_code == 200
    assert second.status_code == 200, (
        "une réponse déjà consommée doit renvoyer l'état courant, pas une "
        "erreur : le front ne peut pas distinguer un double-clic d'un échec"
    )
    assert second.json()["rejoue"] is False


async def test_a_stale_interaction_id_changes_nothing(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": "une-interruption-qui-n-existe-pas",
              "reponse": {}},
        headers=account)
    assert response.status_code == 200
    assert response.json()["rejoue"] is False

    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    assert state_body["interaction"]["id"] == interaction["id"], (
        "un identifiant périmé a fait avancer le graphe"
    )


async def test_answering_another_users_project_is_not_found(client, account):
    owner = await _active_account(client, "other_account-proprio@exemple.fr")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": "peu-importe", "reponse": {}},
        headers=account)
    assert response.status_code == 404
```

- [ ] **Étape 2 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_answer.py -v
```

Attendu : `404` sur `/answer`, la route n'existe pas.

- [ ] **Étape 3 : élargir `advance` pour accepter une reprise**

Dans `backend/app/runs/runner.py`, `advance` prend déjà `graph_input` et le
passe à `ainvoke` : un `Command` y passe sans changement. Rien à modifier —
**vérifiez-le plutôt que de le supposer**, en lisant la signature de
`ainvoke`. Si un ajustement est nécessaire, faites-le et dites-le dans le
compte rendu.

- [ ] **Étape 4 : écrire le schéma**

```python
class AnswerRequest(BaseModel):
    """La réponse à une interaction précise.

    `reponse` n'est pas typée : les cinq interruptions du §4.5 portent des
    charges utiles différentes — un dictionnaire de faits, une décision de
    relecture, une liste d'arbitrages. Les typer ici obligerait à une union
    discriminée qui devrait suivre chaque évolution du graphe, alors que
    c'est le graphe qui valide ce qu'il reçoit.
    """

    interaction_id: str = Field(min_length=1)
    reponse: Any = None
```

`Any` demande `from typing import Any` en tête de `schemas.py`.

- [ ] **Étape 5 : écrire la route**

```python
@router.post("/{project_id}/answer")
async def answer(project_id: UUID, body: AnswerRequest,
                 user=Depends(active_user)):
    """Répond à l'interaction current et relance le run (§6.2).

    L'idempotence se joue ici, pas dans le graphe : on compare l'identifiant
    reçu à celui de l'interruption en attente et on ne reprend que s'ils
    coïncident. Un double-clic, une reconnexion, un onglet resté ouvert sur
    un état dépassé — tous répondent 200 avec `rejoue: false`, et rien ne
    bouge.

    Répondre 409 serait défendable en théorie et désastreux en pratique : le
    front ne peut pas distinguer « tu as cliqué deux fois » d'un vrai échec,
    et afficherait une erreur à un utilisateur dont la réponse est bien
    passée.
    """
    row = await _owned(project_id, user)
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)

    pending = snapshot.interrupts[0] if snapshot.interrupts else None
    if pending is None or pending.id != body.interaction_id:
        return {"rejoue": False, "run_status": row["run_status"]}

    try:
        start_run(str(project_id), row["thread_id"],
                  Command(resume={body.interaction_id: body.reponse}))
    except RunAlreadyRunning:
        # Un run avance déjà : c'est que deux requêtes sont arrivées ensemble
        # et que la première a gagné. La seconde n'a rien à rejouer.
        return {"rejoue": False, "run_status": "running"}
    return {"rejoue": True, "run_status": "running"}
```

Imports à ajouter en tête de `routes.py`, en plus de ceux de la tâche 4 :

```python
from langgraph.types import Command

from app.projects.schemas import AnswerRequest
from app.runs.runner import RunAlreadyRunning, start_run
```

`start_run` est peut-être déjà importé par la tâche 4 ; n'en faites pas deux
lignes.

- [ ] **Étape 6 : lancer les tests, puis la suite complète**

```bash
cd backend && uv run pytest tests/test_answer.py -v
cd backend && uv run pytest -m "not network" -q
```

- [ ] **Étape 7 : vérifier par mutation**

| Mutation | Doit faire tomber |
|---|---|
| retirer la comparaison `en_attente.id != corps.interaction_id` | `..._twice_does_not_advance_twice` **et** `..._stale_interaction_id_changes_nothing` |
| `Command(resume=corps.reponse)` au lieu du dictionnaire | `..._answering_advances_the_run` |
| répondre `409` au lieu de `200` sur une réponse périmée | `..._twice_does_not_advance_twice` |

Si la première mutation ne fait tomber qu'**un seul** des deux tests,
l'autre passe pour une mauvaise raison — corrigez-le avant de continuer.

- [ ] **Étape 8 : commiter**

```bash
git add backend/app/projects/ backend/app/runs/runner.py backend/tests/test_answer.py
git commit -m "feat(projects): répondre à une interaction, sans jamais rejouer"
```

---

### Tâche 6 : le flux SSE

**Fichiers :**
- Créer : `backend/app/projects/stream.py`
- Modifier : `backend/app/projects/routes.py` — monter la route
- Test : `backend/tests/test_stream.py`

**Interfaces :**
- Consomme : `subscribe`, `RunEvent` (tâche 1) ; `_owned` (tâche 4).
- Produit : `encode(event: RunEvent) -> str`, et la route
  `GET /projects/{id}/stream`.

**Le protocole, en entier.** Server-Sent Events tient en quelques règles :

```
event: token\n
data: {"text":"Bonjour"}\n
\n
```

Un champ par ligne, une ligne vide pour terminer l'événement, tout en UTF-8.
Deux pièges, et ce sont eux qui justifient d'écrire `encode` à part plutôt
que de mettre des f-strings dans la route :

1. **Un saut de ligne dans les données casse le flux.** `data:` est une
   ligne ; un `\n` au milieu du JSON serait lu comme la fin du champ. Le JSON
   compact n'en produit pas, mais un texte rédigé en contient, donc on sérialise
   toujours par `json.dumps` — qui les échappe en `\\n` — et jamais par
   interpolation directe.
2. **Un client qui ne lit rien pendant longtemps est coupé** par les
   intermédiaires. Un commentaire SSE (`: battement\n\n`) toutes les quinze
   secondes tient la connexion sans être vu du client.

**Pourquoi pas `sse-starlette` :** une dépendance de plus à suivre, à
verrouiller et à déployer, pour vingt lignes qu'on veut de toute façon
pouvoir tester unitairement. Le jour où le protocole se complique — reprise
par `Last-Event-ID`, par exemple — la question se repose honnêtement.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_stream.py
import asyncio
import json

import pytest_asyncio

from app.runs.events import RunEvent, publish
from app.projects.stream import HEARTBEAT, encode
from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "flux@exemple.fr")


def test_an_event_is_encoded_as_two_fields_and_a_blank_line():
    rendered = encode(RunEvent("token", {"text": "Bonjour"}))
    assert rendered == 'event: token\ndata: {"text": "Bonjour"}\n\n'


def test_a_newline_in_the_payload_never_breaks_the_frame():
    """Le piège du protocole : `data:` est UNE ligne. Un saut de ligne brut
    au milieu couperait la trame et le client lirait deux événements dont
    l'un est invalide."""
    rendered = encode(RunEvent("token", {"text": "deux\nlignes"}))
    body = rendered.split("\n\n")[0]
    assert body.count("\n") == 1, "la trame porte plus d'un saut de line"
    assert "\\n" in rendered, "le saut de line n'a pas été échappé"
    assert json.loads(body.split("data: ", 1)[1])["text"] == "deux\nlignes"


def test_the_heartbeat_is_a_comment_and_not_an_event():
    # Un client qui reçoit un commentaire ne déclenche aucun gestionnaire :
    # c'est ce qui permet de tenir la connexion sans polluer l'affichage.
    assert HEARTBEAT.startswith(":")
    assert HEARTBEAT.endswith("\n\n")


async def test_the_stream_delivers_what_the_run_publishes(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    received = []
    async with client.stream("GET", f"/projects/{project_id}/stream",
                             headers=account) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        # Le run tourne déjà et publie ; on lui laisse le temps d'émettre,
        # puis on publie nous-mêmes un repère qu'on sait reconnaître.
        await asyncio.sleep(0.1)
        publish(project_id, RunEvent("progress", {"cursor": 42, "total": 99}))

        async for line in response.aiter_lines():
            received.append(line)
            if '"cursor": 42' in line:
                break

    assert any(l.startswith("event: ") for l in received)
    assert any('"cursor": 42' in l for l in received)


async def test_another_users_stream_is_not_found(client, account):
    owner = await _active_account(client, "flux-proprio@exemple.fr")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]

    async with client.stream("GET", f"/projects/{project_id}/stream",
                             headers=account) as response:
        assert response.status_code == 404
```

- [ ] **Étape 2 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_stream.py -v
```

Attendu : `ModuleNotFoundError: No module named 'app.projects.stream'`.

- [ ] **Étape 3 : écrire l'encodage et la route**

```python
# backend/app/projects/stream.py
import asyncio
import json
from collections.abc import AsyncIterator

from app.runs.events import RunEvent, subscribe

# Un commentaire SSE : le client le reçoit et ne déclenche aucun
# gestionnaire. C'est ce qui tient la connexion ouverte à travers les
# intermédiaires qui coupent au bout de trente à soixante secondes
# d'inactivité — et une section peut s'écrire sans rien publier pendant
# plusieurs secondes.
HEARTBEAT = ": battement\n\n"
HEARTBEAT_SECONDS = 15


def encode(event: RunEvent) -> str:
    """Une trame SSE : un champ par ligne, une ligne vide pour terminer.

    `json.dumps` n'est pas un détail : `data:` est UNE ligne, et un saut de
    ligne brut dans le texte rédigé couperait la trame en deux. Le client
    lirait alors un événement tronqué suivi d'un fragment invalide, sans
    erreur visible côté serveur.
    """
    return f"event: {event.name}\ndata: {json.dumps(event.data)}\n\n"


async def event_stream(project_id: str) -> AsyncIterator[str]:
    """Les événements du projet, plus un battement quand rien ne vient.

    `asyncio.wait_for` sur l'événement suivant plutôt qu'une tâche de
    battement séparée : une tâche de plus par connexion se paierait à
    l'annulation, et il faudrait l'annuler exactement quand le client part.
    """
    async with subscribe(project_id) as events:
        iterator = events.__aiter__()
        while True:
            try:
                event = await asyncio.wait_for(anext(iterator),
                                               timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield HEARTBEAT
                continue
            except StopAsyncIteration:
                # L'abonné a été abandonné pour retard : l'avis est déjà
                # parti, il n'y a plus rien à envoyer.
                return
            yield encode(event)
```

Puis dans `backend/app/projects/routes.py` :

```python
@router.get("/{project_id}/stream")
async def stream(project_id: UUID, user=Depends(active_user)):
    """Le flux du §6.1.

    Le contrôle du propriétaire passe AVANT d'ouvrir le flux : une fois la
    réponse en cours, on ne peut plus changer son code de statut, et un 404
    tardif ne serait pas lisible par le client.

    `X-Accel-Buffering: no` et `Cache-Control: no-cache` disent aux
    intermédiaires de ne pas accumuler : sans eux, un proxy peut retenir le
    flux jusqu'à remplir un tampon, et l'utilisateur verrait la section
    apparaître d'un bloc à la fin — soit exactement ce que le flux existe
    pour éviter.
    """
    await _owned(project_id, user)
    return StreamingResponse(
        event_stream(str(project_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Imports à ajouter : `from fastapi.responses import StreamingResponse` et
`from app.projects.stream import event_stream`.

- [ ] **Étape 4 : lancer les tests pour les voir passer**

```bash
cd backend && uv run pytest tests/test_stream.py -v
```

**Si `test_the_stream_delivers_what_the_run_publishes` reste bloqué**, la
cause la plus probable est que `httpx.ASGITransport` ne fait pas tourner le
flux et la tâche de fond concurremment comme un vrai serveur. Deux
vérifications, dans cet ordre : que le test ne consomme pas le flux avant
qu'un abonné existe, et que la boucle `aiter_lines` a bien une condition de
sortie. **Si le transport ASGI ne permet pas ce test, dites-le plutôt que de
le contourner** — le contrat vaut mieux d'être éprouvé par un test unitaire
sur `event_stream` que par un test d'intégration qui ment.

- [ ] **Étape 5 : vérifier par mutation**

| Mutation | Doit faire tomber |
|---|---|
| `encode` interpolant `event.data` au lieu de `json.dumps` | `..._newline_in_the_payload_never_breaks_the_frame` |
| `HEARTBEAT = "event: ping\n\n"` | `..._heartbeat_is_a_comment_and_not_an_event` |
| retirer l'appel à `_owned` avant d'ouvrir le flux | `..._another_users_stream_is_not_found` |

- [ ] **Étape 6 : lancer la suite complète, puis commiter**

```bash
cd backend && uv run pytest -m "not network" -q
git add backend/app/projects/stream.py backend/app/projects/routes.py backend/tests/test_stream.py
git commit -m "feat(projects): le flux SSE, battement compris"
```

---

### Tâche 7 : reprendre, réconcilier, rouvrir

**Fichiers :**
- Modifier : `backend/app/projects/routes.py` — `POST /{id}/resume`,
  `POST /{id}/sections/{sid}/reopen`
- Modifier : `backend/app/projects/repository.py` — `running_projects`
- Modifier : `backend/app/main.py` — réconciliation et purge au démarrage
- Test : `backend/tests/test_resume.py`

**Interfaces :**
- Consomme : `reproject`, `mark_for_reopening` (`app/agent/projections.py`),
  `purge_checkpoints` (`app/agent/checkpointer.py`), `Catalogue.depend_de`
  (`app/agent/templates.py`), tout ce que les tâches 3 à 5 produisent.
- Produit : `running_projects(conn) -> list[dict]`,
  `reconcile_orphan_runs() -> int`.

**Ce que dit le §8, et pourquoi c'est le cas courant :**

> Le service d'hébergement gratuit s'endort après quinze minutes et redémarre
> sans prévenir. Un run en cours meurt. **Ce n'est pas un cas limite, c'est le
> cas courant.**

Au redémarrage, `run_status` vaut encore `running` alors que plus rien ne
tourne — le registre des tâches est en mémoire, et la mémoire est partie.
L'application doit détecter l'incohérence au démarrage, passer ces projets en
`failed`, et proposer « Reprendre ».

**Les trois appelants manquants du plan 3 se branchent ici.** La revue finale
notait que `reproject`, `mark_for_reopening` et — pour sa seconde moitié —
`purge_checkpoints` étaient écrits, testés, et jamais invoqués. `POST
/resume` appelle `reproject`, `POST /reopen` appelle `mark_for_reopening`,
et le démarrage appelle `purge_checkpoints` en filet (§9.3).

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_resume.py
import asyncio

import pytest_asyncio

from app.core.db import connection
from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "reprise@exemple.fr")


async def _force_status(project_id, statut):
    """Simule ce que fait un redémarrage : la ligne reste `running` alors
    que plus aucune tâche ne tourne."""
    from uuid import UUID

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update projects set run_status = %s where id = %s",
                (statut, UUID(project_id)))


async def test_a_run_left_running_by_a_restart_is_marked_failed(client, account):
    from app.runs.registry import cancel_all
    from app.main import reconcile_orphan_runs

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    await cancel_all()                      # le processus est mort
    await _force_status(project_id, "running")

    reconciled = await reconcile_orphan_runs()

    assert reconciled >= 1
    state_body = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert state_body["run_status"] == "failed", (
        "un run que plus rien ne pilote doit le dire, sinon l'utilisateur "
        "attend indéfiniment devant un écran qui ne bougera plus"
    )


async def test_reconciliation_leaves_a_live_run_alone(client, account):
    from app.main import reconcile_orphan_runs

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    await _force_status(project_id, "running")
    # La tâche est toujours au registre : ce run-là n'est pas orphelin.
    await reconcile_orphan_runs()
    state_body = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert state_body["run_status"] != "failed"


async def test_resuming_restarts_the_run_from_its_checkpoint(client, account):
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    interaction_before = state_body["interaction"]

    await cancel_all()
    await _force_status(project_id, "failed")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200

    # L'interruption est retrouvée à l'identique : le point de reprise fait
    # foi, rien n'a été perdu.
    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    assert state_body["interaction"]["id"] == interaction_before["id"]


async def test_reopening_a_section_marks_it_and_its_dependents(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    section_id = state_body["plan"][0]["section_id"]

    response = await client.post(
        f"/projects/{project_id}/sections/{section_id}/reopen",
        headers=account)
    assert response.status_code == 200
    assert "sections" in response.json()


async def test_resuming_another_users_project_is_not_found(client, account):
    owner = await _active_account(client, "reprise-proprio@exemple.fr")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]
    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 404
```

- [ ] **Étape 2 : lancer les tests pour les voir échouer**

```bash
cd backend && uv run pytest tests/test_resume.py -v
```

- [ ] **Étape 3 : ajouter `running_projects` au dépôt**

```python
async def running_projects(conn) -> list[dict]:
    """Les projets que la base croit en cours, tous propriétaires confondus.

    L'exception à la règle « toujours filtrer sur le propriétaire » : cette
    requête sert la réconciliation du démarrage, qui n'agit au nom de
    personne. Elle ne rend que l'identifiant et le fil — de quoi réconcilier,
    rien de plus — pour qu'un appel de trop ne devienne pas une fuite.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, thread_id from projects where run_status = 'running'")
        rows = await cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]
```

- [ ] **Étape 4 : écrire la réconciliation et la purge de filet**

Dans `backend/app/main.py`. Ce module n'importe aujourd'hui que `pool` de
`app.core.db` et n'a pas de journal — il faut donc ajouter en tête :

```python
import logging

from app.agent.checkpointer import purge_checkpoints
from app.core.db import connection, pool

logger = logging.getLogger(__name__)
```

```python
async def reconcile_orphan_runs() -> int:
    """Passe en `failed` les runs que plus aucune tâche ne pilote (§8).

    Au redémarrage, le registre des tâches est vide — il vivait en mémoire —
    alors que des lignes portent encore `running`. Sans cette réconciliation,
    l'utilisateur attend devant un écran qui ne bougera plus jamais, et
    `/resume` refuserait de partir en croyant qu'un run tourne déjà.

    Le test du registre n'est pas superflu pour autant : cette fonction est
    aussi appelable à chaud, et un run bien vivant ne doit pas être abattu.
    """
    from app.projects.repository import running_projects, set_run_status
    from app.runs import registry

    reconciled = 0
    async with connection() as conn:
        for row in await running_projects(conn):
            if registry.is_running(str(row["id"])):
                continue
            await set_run_status(conn, row["id"], "failed")
            reconciled += 1
    return reconciled
```

Et dans `lifespan`, après l'ouverture du pool :

```python
    orphans = await reconcile_orphan_runs()
    if orphans:
        logger.warning("%d run(s) orphelin(s) repassés en échec", orphans)
    # §9.3, la purge « en filet » : celle de fin de run a pu ne jamais
    # tourner, précisément parce que le processus est mort en chemin.
    await purge_finished_projects()
```

`purge_finished_projects` parcourt les projets en `done` et appelle
`purge_checkpoints(thread_id)` sur chacun. Écrivez-la à côté de
`reconcile_orphan_runs`, avec son test.

**L'arrêt, et ce n'est pas une remarque en passant.** La relecture de la
tâche 3 a constaté que `cancel_all` n'avait aucun appelant en production —
exactement le travers que le préambule de ce plan reproche au plan 3, et
qu'il prétend refermer. Le `finally` de `lifespan` devient donc :

```python
    finally:
        # L'ordre compte : on annule d'abord les runs, ensuite seulement on
        # ferme ce dont ils se servent. L'inverse laisserait une tâche
        # vivante écrire dans un point de reprise dont la connexion vient
        # d'être fermée, et l'erreur remonterait dans une tâche que
        # personne n'attend, donc nulle part.
        await registry.cancel_all()
        try:
            await close_checkpointer()
        finally:
            try:
                await close_clients()
            finally:
                await connection_pool.close()
```

Et son test, dans `backend/tests/test_lifespan.py` :

```python
async def test_shutting_down_cancels_the_running_runs():
    """Un run qui survit à l'arrêt écrit dans une connexion fermée, et
    personne ne voit l'erreur : elle remonte dans une tâche que personne
    n'attend."""
    import asyncio

    from app.main import create_app
    from app.runs import registry

    async def _long():
        await asyncio.sleep(30)

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test") as client:
        await client.get("/health")
        task = asyncio.create_task(_long())
        registry.register("projet-a-l-arret", task)
        assert registry.is_running("projet-a-l-arret")

    assert not registry.is_running("projet-a-l-arret"), (
        "l'arrêt de l'application n'a pas annulé le run en cours"
    )
    assert task.cancelled()
```

Le client `httpx` en gestionnaire de contexte déclenche le cycle de vie de
l'application à la sortie du bloc : c'est ce qui rend l'arrêt observable
depuis un test. Vérifiez comment `tests/test_lifespan.py` procède déjà et
alignez-vous dessus plutôt que d'introduire un second motif.

- [ ] **Étape 5 : écrire les deux routes**

```python
@router.post("/{project_id}/resume")
async def resume(project_id: UUID, user=Depends(active_user)):
    """Relance un run interrompu, depuis son point de reprise (§8).

    `reproject` tourne AVANT la relance, comme le §4.6 l'impose : en cas de
    divergence entre le point de reprise et les projections, c'est le point
    de reprise qui gagne. Un run mort en plein `save` a pu écrire une
    projection que le graphe ne connaît pas.
    """
    row = await _owned(project_id, user)
    if registry.is_running(str(project_id)):
        return {"reprise": False, "run_status": "running"}

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}

    async with connection() as conn:
        await reproject(
            conn, project_id,
            values.get("facts", {}),
            _sections_from(values),
        )

    # `None` et non un état neuf : LangGraph repart du point de reprise. Lui
    # passer un état reconstruit écraserait ce qu'il a gardé.
    start_run(str(project_id), row["thread_id"], None)
    return {"reprise": True, "run_status": "running"}


@router.post("/{project_id}/sections/{section_id}/reopen")
async def reopen(project_id: UUID, section_id: str,
                 user=Depends(active_user)):
    """Rouvre une section et celles qui en dépendent.

    Rouvrir la seule section demandée laisserait le document incohérent :
    celles qui la citent dans leur `depend_de` ont été écrites en s'appuyant
    sur ce qu'elle disait.
    """
    row = await _owned(project_id, user)
    graph = await compiled_graph()
    snapshot = await graph.aget_state(
        {"configurable": {"thread_id": row["thread_id"]}})
    plan = (snapshot.values or {}).get("plan", [])

    matching = [ref for ref in plan if ref.section_id == section_id]
    if not matching:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            {"code": "section_introuvable"})
    if len(matching) > 1:
        # Possible depuis la migration 0003 : les deux documents peuvent
        # porter le même identifiant de section. On refuse plutôt que d'en
        # choisir un au hasard — le front, lui, sait de quel document il
        # parle, et pourra le préciser le jour où le cas se présente.
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            {"code": "section_ambigue"})

    qualified = load_catalogue().sections_depending_on(
        f"{matching[0].document}.{section_id}")
    async with connection() as conn:
        touched = await mark_for_reopening(conn, project_id, qualified)
    return {"sections": sorted(qualified), "touchees": touched}
```

**`sections_depending_on` n'existe pas encore — c'est à écrire.** Ne le
confondez pas avec `Catalogue.sections_to_reopen`, qui prend un ensemble
d'**identifiants de faits** et applique le troisième invariant du §4.2
(« modifier un fait rouvre les sections que `utilise_par` désigne »). Ici on
part d'une **section**, pas d'un fait : deux relations différentes, et
confondre les deux était l'erreur de la première version de ce plan.

Le champ `depend_de` est déclaré sur chaque section des gabarits depuis le
plan 3 et n'est appliqué nulle part — la revue finale l'a relevé, en notant
que le tri de `plan_for` restait du coup le seul mécanisme de dépendance du
graphe. C'est ici qu'il sert enfin.

```python
    def sections_depending_on(self, qualified_id: str) -> set[str]:
        """La section demandée et, transitivement, celles qui en dépendent.

        `depend_de` nomme des sections du MÊME document, sans préfixe : la
        fermeture ne traverse donc jamais la frontière entre le CDC et le
        business plan. C'est voulu — les deux documents se recoupent par les
        faits, pas par les sections, et c'est `sections_to_reopen` qui porte
        ce chemin-là.

        Transitive, parce qu'une dépendance l'est : si C dépend de B et B de
        A, rouvrir A sans rouvrir C laisserait C appuyée sur un B qui va
        changer. La file évite la récursion, qu'un cycle dans les gabarits
        ferait déborder ; `to_reopen` sert aussi de marquage, donc un cycle
        s'arrête de lui-même.
        """
        document, _, section_id = qualified_id.partition(".")
        template = self._document(document)
        if not any(s.id == section_id for s in template.sections):
            raise KeyError(f"section inconnue : {qualified_id}")

        to_reopen = {qualified_id}
        queue = [section_id]
        while queue:
            current = queue.pop()
            for section in template.sections:
                if current in section.depend_de:
                    qualified = f"{document}.{section.id}"
                    if qualified not in to_reopen:
                        to_reopen.add(qualified)
                        queue.append(section.id)
        return to_reopen
```

Ses tests, dans `backend/tests/test_templates.py` :

```python
def test_reopening_a_section_pulls_in_what_depends_on_it():
    catalogue = load_catalogue()
    reopened = catalogue.sections_depending_on("cdc.contexte_objectifs")

    assert "cdc.contexte_objectifs" in reopened, (
        "la section demandée doit être du lot : c'est elle qu'on rouvre"
    )
    # `cdc.yaml` déclare plusieurs dépendances directes ; sans elles, ce test
    # ne prouverait rien et passerait pour une mauvaise raison.
    direct = {f"cdc.{s.id}" for s in catalogue.cdc.sections
              if "contexte_objectifs" in s.depend_de}
    assert direct, "le gabarit ne déclare plus aucune dépendance directe"
    assert direct <= reopened

    # Et la fermeture est bien transitive, pas seulement directe.
    for qualified in direct:
        bare = qualified.split(".", 1)[1]
        indirect = {f"cdc.{s.id}" for s in catalogue.cdc.sections
                    if bare in s.depend_de}
        assert indirect <= reopened


def test_a_section_dependency_never_crosses_the_documents():
    reopened = load_catalogue().sections_depending_on("cdc.contexte_objectifs")
    assert all(q.startswith("cdc.") for q in reopened)


def test_an_unknown_section_is_refused():
    import pytest

    with pytest.raises(KeyError):
        load_catalogue().sections_depending_on("cdc.section_qui_n_existe_pas")
```

Imports à ajouter en tête de `routes.py` :

```python
from app.agent.checkpointer import purge_checkpoints
from app.agent.projections import mark_for_reopening, reproject
from app.agent.templates import load_catalogue
from app.runs import registry
```

`load_catalogue` est déjà importé par la tâche 4 pour `templates_version`.

`mark_for_reopening` attend des identifiants **qualifiés**
(`cdc.contexte_objectifs`), établi par son test du plan 3 — c'est bien ce que
`sections_depending_on` rend.

**Un seul point reste à établir en lisant le code :** la forme du quatrième
argument de `reproject`, qui est
`list[tuple[SectionRef, list[Block], str, int | None, int]]`. Le
`_sections_from` écrit plus haut est un nom, pas du code : écrivez-le en
lisant ce que l'état du graphe porte réellement, et **ne reconstruisez
jamais** ce que le point de reprise ne contient pas. Si le point de reprise
ne porte pas de quoi réécrire les sections déjà validées — il ne garde que la
section courante — alors `reproject` ne peut pas être appelée ainsi, et
c'est un constat à rapporter, pas à contourner par une valeur inventée.

- [ ] **Étape 6 : lancer les tests, puis la suite complète**

```bash
cd backend && uv run pytest tests/test_resume.py -v
cd backend && uv run pytest -m "not network" -q
```

- [ ] **Étape 7 : vérifier par mutation**

| Mutation | Doit faire tomber |
|---|---|
| `reconcile_orphan_runs` sans le test `registry.is_running` | `..._leaves_a_live_run_alone` |
| `reconcile_orphan_runs` rendant `0` sans rien faire | `..._left_running_by_a_restart_is_marked_failed` |
| `resume` passant un `initial_state` au lieu de `None` | `..._restarts_the_run_from_its_checkpoint` |
| `sections_depending_on` rendant `{qualified_id}` seul | `..._marks_it_and_its_dependents` — **si ce test ne tombe pas, il ne teste rien** : renforcez-le sur une section qui a réellement des dépendantes |

- [ ] **Étape 8 : commiter**

```bash
git add backend/app/projects/ backend/app/main.py backend/tests/test_resume.py
git commit -m "feat(projects): reprendre un run mort, rouvrir une section"
```

---
