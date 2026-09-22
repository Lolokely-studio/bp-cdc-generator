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
(tâches 3 et 7) et `mark_for_reopening` sans appelant (tâche 7).

`reproject` était du lot dans la première version de ce plan. Elle en sort :
sa prémisse est fausse, le point de reprise ne porte pas les sections déjà
validées et ne peut donc pas les réécrire. La tâche 7 dit pourquoi, et le
constat part au plan suivant plutôt que d'être refermé par un appel de
complaisance.

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
    # `order` enregistre les deux effets dans l'ordre réel. Sans lui, le test
    # constate que la purge a eu lieu et que le statut vaut `done`, mais
    # jamais lequel des deux est venu en premier — et intervertir les deux
    # laissait la suite verte.
    #
    # L'ordre compte : purger avant d'écrire `done`, c'est risquer de mourir
    # entre les deux et de laisser un projet marqué `running` dont les points
    # de reprise ont disparu. Dans l'autre sens, la mort entre les deux
    # laisse un projet `done` dont les points de reprise survivent — ce que
    # la purge de filet du démarrage ramasse sans rien perdre.
    order = []
    real_status = runner._status

    async def _record_status(project_id, status):
        order.append(f"status:{status}")
        await real_status(project_id, status)

    async def _count_calls(thread_id, keep=1):
        order.append("purge")
        calls.append((thread_id, keep))
        return 0

    monkeypatch.setattr(runner, "compiled_graph", _finished_graph)
    monkeypatch.setattr(runner, "_status", _record_status)
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
    assert order.index("status:done") < order.index("purge"), (
        "la purge a précédé l'écriture de `done` : mourir entre les deux "
        "laisserait un projet `running` sans points de reprise"
    )


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


async def test_the_error_event_does_not_wait_for_the_database(project, monkeypatch):
    """Publier d'abord, écrire ensuite — et le test voisin ne suffit pas.

    La garde autour de l'écriture du statut protège d'une base qui LÈVE :
    l'exception est absorbée sur place, et l'événement part quel que soit
    l'ordre des deux. Ce test-là ne distingue donc pas les deux ordres, ce
    que la mutation a montré en restant verte.

    Une base qui TRAÎNE les distingue. Le pool peut mettre plusieurs
    secondes à rendre une connexion — c'est même le cas courant sur un
    hébergement qui sort de veille — et dans l'ordre inverse le navigateur
    attendrait tout ce temps avant d'apprendre que son run est mort.
    """
    from app.runs import runner

    real_status = runner._status

    async def _slow_failed(project_id, status):
        if status == "failed":
            await asyncio.sleep(5)
        await real_status(project_id, status)

    monkeypatch.setattr(runner, "_status", _slow_failed)

    async with subscribe(str(project["project_id"])) as events:
        running = asyncio.create_task(advance(
            str(project["project_id"]), project["thread_id"],
            {"plan": [], "cursor": 5}))
        try:
            event = await asyncio.wait_for(anext(events), timeout=1)
        finally:
            running.cancel()

    assert event.name == "error", (
        "le navigateur a attendu la base avant d'apprendre l'échec"
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
        # On déclenche le rappel de la PREMIÈRE tâche à la main, après que la
        # seconde a pris sa place. Compter sur l'ordonnanceur pour produire
        # cet entrelacement donnerait un test qui passe ou non selon la
        # machine — et, de fait, `await first` draine déjà le rappel avant
        # que la seconde existe, si bien que la fenêtre ne s'ouvre jamais.
        # C'est ce qui rendait la première version de ce test aveugle à la
        # mutation qu'elle devait attraper.
        registry._forget("projet-course")(first)
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
    courante qu'on saura si la requête rejoue un point déjà dépassé (§6.2).
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

Attendu : 10 passés.

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
| `_fail` écrivant le statut AVANT de publier | `..._error_event_does_not_wait_for_the_database` — et non le test voisin, qui ne distingue pas les deux ordres |
| retirer le contrôle sur `RUN_STATUSES` | `..._unknown_run_status_is_refused` |
| `_forget` retirant par clé sans contrôler l'identité | `..._finished_task_never_unregisters_its_successor` |
| purger AVANT d'écrire `done` (déjà listée) | vérifiée par l'ordre enregistré, pas par la seule présence des effets |

Ces six dernières laissaient les 394 tests au vert avant cette correction.
La relecture les a trouvées par mutation, aucune par lecture.

- [ ] **Étape 8 : lancer la suite complète, puis commiter**

```bash
cd backend && uv run pytest -m "not network" -q
git add backend/app/runs/registry.py backend/app/runs/runner.py \
        backend/app/projects/repository.py backend/tests/test_runner.py
git commit -m "feat(runs): un pilote qui conduit le graphe hors de la requête HTTP"
```

Attendu : 399 passés, 5 désélectionnés.

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

- [ ] **Étape 1 bis : `project_for_user` rend aussi les horodatages**

`ProjectSummary` porte `created_at` et `updated_at`, mais `project_for_user`
ne les sélectionne pas : deux des trois routes qui rendent ce schéma
répondaient donc toujours `null`, tandis que la liste les renseignait. Même
schéma, deux sens selon la route — un front qui affiche « modifié le »
d'après l'entête n'obtient rien. Ajoutez les deux colonnes au `select` :

```sql
            select id, user_id, nom, documents, profil_cdc, profil_bp,
                   thread_id, run_status, templates_version,
                   created_at, updated_at
            from projects where id = %s and user_id = %s
```

Rien d'autre à changer : la fonction construit déjà ses clés depuis
`cur.description`.

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


async def _active_account(client, label: str) -> dict:
    """Inscrit, active en base, se connecte, rend l'en-tête d'autorisation.

    Même motif que `tests/test_login.py::_register_and_activate` : le contrat
    d'API est en français — `mot_de_passe` à l'entrée, `jeton` à la sortie.

    L'adresse porte un suffixe unique, et ce n'est pas de la coquetterie :
    `migrated_db` a la portée de la SESSION, donc la base n'est pas remise à
    zéro entre deux tests d'un même fichier. Avec une adresse fixe, chaque
    test hérite des projets créés par ses prédécesseurs — constaté :
    `..._list_only_holds_the_owners_projects` voyait deux « CoachDom » et
    échouait, tout en passant lorsqu'on le lançait seul. Un test qui dépend
    de l'ordre de ses voisins est un test qu'on finit par désactiver.
    """
    from uuid import uuid4

    from app.core.db import connection

    email = f"{label}-{uuid4()}@exemple.fr"
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
    return await _active_account(client, "projets")


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
    other_account = await _active_account(client, "intrus")
    await client.post("/projects", json={**CREATION, "nom": "PasÀToi"},
                      headers=other_account)

    names = [p["nom"] for p in (await client.get("/projects", headers=account)).json()]
    assert names == ["CoachDom"]
    assert "PasÀToi" not in names


async def test_another_users_project_is_not_found_never_forbidden(client, account):
    owner = await _active_account(client, "owner")
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
from app.runs.runner import start_run

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
    # L'état de départ est construit AVANT l'insertion, et ce n'est pas un
    # détail d'ordre. `initial_state` appelle `plan_for`, qui LÈVE sur un
    # profil absent de `profils_disponibles`. Construit après, il laisserait
    # une ligne `projects` derrière lui que personne ne pourra jamais faire
    # avancer : l'appelant reçoit un 500 sans identifiant, et aucune route de
    # ce plan ne sait reprendre un projet dont on ignore l'existence.
    #
    # Le cas ne peut pas se produire aujourd'hui — les `Literal` des schémas
    # et les `profils_disponibles` des YAML coïncident — mais ce sont deux
    # listes tenues dans deux fichiers que rien ne relie. Vérifié : en
    # faisant lever `start_run`, la ligne survit bel et bien.
    graph_input = initial_state("", body.documents, body.profil_cdc,
                                body.profil_bp, body.idee)
    async with connection() as conn:
        project_id = await create_project(
            conn, user["id"], nom=body.nom, documents=body.documents,
            profil_cdc=body.profil_cdc, profil_bp=body.profil_bp,
            thread_id=thread_id,
            templates_version=str(catalogue.cdc.version),
        )
    graph_input["project_id"] = str(project_id)
    start_run(str(project_id), thread_id, graph_input)
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
    # L'ORDRE DES TROIS LECTURES EST PORTEUR, et rien ne les synchronise.
    # La ligne d'abord, le point de reprise ensuite, les projections en
    # dernier : le statut lu est donc le plus ancien des trois. Tant que les
    # statuts n'avancent que dans un sens, l'écart penche du bon côté — on
    # peut voir `running` à côté d'une interaction déjà présente, et le front
    # affiche une question sous une bannière « en cours » périmée d'un
    # sondage. Inverser les deux premières lectures donnerait `waiting` avec
    # `interaction: null` : un état qui n'a jamais existé, et qu'un front
    # rend en « répondez à la question qui n'est pas là ».
    #
    # La tâche 7 fait reculer les statuts (`failed` puis `running` à la
    # reprise) : c'est là qu'il faudra reposer la question.
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


- [ ] **Étape 9 bis : ce que la relecture a trouvé par mutation**

Seize mutations jouées, **onze non attrapées**. Les routes sont justes — le
relecteur a vérifié le 404 sur les quatre, corps et en-têtes compris, et n'a
trouvé aucun canal temporel. Ce sont les tests qui ne regardent pas.

D'abord, **renforcer les tests existants**. Dans
`test_creating_a_project_returns_its_header`, après les assertions déjà
présentes :

```python
    # Ce que la création a réellement écrit. Sans ces lignes, intervertir
    # `profil_cdc` et `profil_bp` à l'insertion laissait les 405 tests verts
    # — alors que l'étoile de `create_project` existe précisément pour
    # empêcher cette confusion au site d'appel.
    assert body["documents"] == CREATION["documents"]
    assert body["profil_cdc"] == CREATION["profil_cdc"]
    assert body["profil_bp"] is None
    # Les horodatages valent sur TOUTES les routes qui rendent ce schéma,
    # pas seulement sur la liste.
    assert body["created_at"] and body["updated_at"]
    # Le jeu de clés exact : `thread_id` et `user_id` ne sortent jamais. Ils
    # sont filtrés deux fois aujourd'hui — par `response_model` et parce que
    # pydantic ignore les clés en trop — mais deux coïncidences ne font pas
    # un contrat.
    assert set(body) == {"id", "nom", "documents", "profil_cdc", "profil_bp",
                         "run_status", "created_at", "updated_at"}
```

Dans `test_another_users_project_is_not_found_never_forbidden`, à l'intérieur
de la boucle, après le contrôle du statut :

```python
        assert response.json() == {"detail": {"code": "projet_introuvable"}}, (
            "le corps distingue « n'existe pas » de « pas à vous » : c'est "
            "un oracle d'énumération complet, exactement ce que le 404 "
            "existe pour fermer"
        )
```

Puis **quatre tests neufs** :

```python
async def test_an_unknown_project_answers_exactly_like_someone_elses(client, account):
    """Le code de statut ne suffit pas à fermer le trou d'énumération.

    Vérifié par mutation : un corps qui distingue les deux sortes d'absence
    laissait les six tests verts, alors qu'il suffit à énumérer les projets
    des autres.
    """
    from uuid import uuid4

    owner = await _active_account(client, "corps-404")
    someone_elses = (await client.post("/projects", json=CREATION,
                                       headers=owner)).json()["id"]
    unknown = str(uuid4())

    bodies = []
    for candidate in (someone_elses, unknown):
        for path in (f"/projects/{candidate}", f"/projects/{candidate}/state"):
            response = await client.get(path, headers=account)
            assert response.status_code == 404
            bodies.append(response.json())
    assert all(b == bodies[0] for b in bodies), (
        "les deux sortes d'absence ne se répondent pas à l'identique"
    )


async def test_the_header_status_agrees_with_the_state(client, account):
    """`run_status` pilote toute l'interface, et rien ne le regardait.

    Une valeur figée à `idle` dans le schéma laissait les 405 tests verts.
    """
    import asyncio

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}",
                                   headers=account)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("l'entête n'a jamais annoncé `waiting`")

    state_body = (await client.get(f"/projects/{project_id}/state",
                                   headers=account)).json()
    assert state_body["interaction"] is not None, (
        "l'entête annonce `waiting` alors que rien n'attend de réponse"
    )
    # Le jeu de clés de CETTE route-ci. Le contrôle posé sur la création ne
    # la couvre pas — elle n'appelle que `POST /projects` — et sans cette
    # ligne, retirer `response_model` de `header` rendrait la ligne brute,
    # `thread_id` et `user_id` compris, sans que rien ne bronche.
    assert set(header) == {"id", "nom", "documents", "profil_cdc", "profil_bp",
                           "run_status", "created_at", "updated_at"}


async def test_the_state_interaction_id_is_the_one_langgraph_gave(client, account):
    """Toute l'idempotence de la tâche 5 repose sur cet identifiant.

    Le test précédent ne vérifiait que sa PRÉSENCE : une constante y passait,
    et la suite entière restait verte. On le compare donc à la source.
    """
    import asyncio
    from uuid import UUID

    from app.agent.graph import compiled_graph
    from app.core.db import connection

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                       headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select thread_id from projects where id = %s",
                              (UUID(project_id),))
            thread_id = (await cur.fetchone())[0]
    graph = await compiled_graph()
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})

    assert state_body["interaction"]["id"] == snapshot.interrupts[0].id


async def test_a_both_document_project_carries_the_two_profiles(client, account):
    """`profil_bp` n'était renseigné nulle part dans toute la suite.

    La moitié du validateur de `ProjectCreate` et la moitié de `plan_for`
    n'étaient donc jamais traversées par HTTP. Un projet `both` produit aussi
    le plan le plus long, ce qui exerce le chemin où le curseur enjambe deux
    catalogues.
    """
    creation = {**CREATION, "nom": "LesDeux", "documents": "both",
                "profil_bp": "banque"}
    body = (await client.post("/projects", json=creation,
                              headers=account)).json()
    assert body["profil_cdc"] == "consultation"
    assert body["profil_bp"] == "banque"

    # Le sondage n'est pas facultatif : `start_run` rend la main avant que le
    # pilote ait eu son tour d'ordonnanceur, donc `snapshot.values` est vide
    # et `plan` vaut `[]` si on interroge tout de suite. Constaté, trois fois
    # sur trois.
    import asyncio

    for _ in range(100):
        state_body = (await client.get(f"/projects/{body['id']}/state",
                                       headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le plan est resté vide")

    documents = {ref["document"] for ref in state_body["plan"]}
    assert documents == {"cdc", "bp"}, (
        "un projet `both` doit porter les deux documents à son plan"
    )


async def test_the_list_is_ordered_most_recently_modified_first(client, account):
    """Le tri est la seule raison d'être de l'index que la docstring invoque,
    et rien ne le vérifiait.

    Les horodatages sont posés à la main : les runs de fond écrivent
    `updated_at` à leur rythme, et un test qui dépend de leur ordonnancement
    passerait selon la machine.
    """
    from uuid import UUID

    from app.core.db import connection

    # L'ordre d'insertion doit être l'INVERSE de l'ordre attendu, sinon le
    # test est aveugle : sans clause de tri, PostgreSQL rend ces deux lignes
    # fraîches dans l'ordre où elles ont été écrites, et si cet ordre est
    # déjà le bon l'assertion passe pour rien. C'est l'erreur de la première
    # version de ce test, constatée par mutation.
    #
    # On insère donc le PLUS ANCIEN d'abord, et on attend le plus récent en
    # tête.
    older = (await client.post("/projects", json={**CREATION, "nom": "Ancien"},
                               headers=account)).json()["id"]
    newer = (await client.post("/projects", json={**CREATION, "nom": "Recent"},
                               headers=account)).json()["id"]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update projects set updated_at = now() - interval '1 hour' "
                "where id = %s", (UUID(older),))
            await cur.execute(
                "update projects set updated_at = now() where id = %s",
                (UUID(newer),))

    names = [p["nom"] for p in (await client.get("/projects",
                                                 headers=account)).json()]
    assert names.index("Recent") < names.index("Ancien"), (
        "la liste n'est pas triée par date de modification décroissante"
    )
```

- [ ] **Étape 9 ter : rejouer les mutations qui survivaient**

| Mutation | Doit faire tomber |
|---|---|
| le corps du 404 distingue « pas à vous » de « n'existe pas » | `..._unknown_project_answers_exactly_like_someone_elses` |
| `ProjectSummary` fige `run_status = "idle"` | `..._header_status_agrees_with_the_state` |
| `interaction["id"]` remplacé par une constante | `..._state_interaction_id_is_the_one_langgraph_gave` |
| `create` intervertit `profil_cdc` et `profil_bp` | `..._creating_a_project_returns_its_header` |
| `header` sans `response_model`, rendant la ligne brute | `..._header_status_agrees_with_the_state` — et NON le test de création, qui n'appelle jamais cette route |
| `projects_of_user` sans `order by updated_at desc` | `..._list_is_ordered_most_recently_modified_first` |
| `project_for_user` cessant de lire les horodatages | `..._creating_a_project_returns_its_header` |
| `start_run` qui lève, après l'insertion | aucune — voir ci-dessous |

Les sept premières laissaient les 405 tests au vert. **La huitième n'a pas
de test** : éprouver qu'une levée de `start_run` ne laisse pas de ligne
derrière demanderait de faire lever une fonction qui, telle qu'elle est
écrite, ne lève plus — l'ordre du code est la garantie, et c'est le
commentaire qui la porte. C'est assumé, et c'est écrit ici pour que
personne ne croie l'avoir oublié.

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


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Bascule le graphe sur le modèle simulé.

    Obligatoire dans TOUT fichier de test qui appelle `POST /projects` :
    la route démarre un vrai run en tâche de fond, et sans cette bascule
    `advance` appellerait la passerelle avec `ESQUISSE_FAKE_LLM=false` — la
    valeur que `tests/conftest.py` fixe pour toute la suite — donc de vraies
    requêtes réseau avec des clés factices. C'est exactement ce que la suite
    `not network` interdit, et c'est passé inaperçu jusqu'à la tâche 3.

    Le nettoyage des runs et des pools n'est PAS ici : `tests/conftest.py`
    porte un démontage autouse qui annule les runs, ferme le point de
    reprise et ferme le pool applicatif, dans cet ordre. Le dupliquer ferait
    deux endroits à tenir d'accord, et c'est toujours le second qu'on
    oublie.
    """
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "reponses")


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


async def _wait_for_status(client, project_id, headers, expected):
    """Attend que l'entête annonce `expected`, et le rend.

    Le statut et le point de reprise ne deviennent pas visibles au même
    instant : le second l'est dès la fin d'`ainvoke`, le premier une
    écriture en base plus tard. Un test qui a vu l'interruption n'a donc
    aucune garantie sur le statut.
    """
    import asyncio

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}",
                                   headers=headers)).json()
        if header["run_status"] == expected:
            return header
        await asyncio.sleep(0.05)
    raise AssertionError(f"le statut n'a jamais atteint `{expected}`")


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
    # On attend que le graphe se soit ARRÊTÉ sur l'interruption suivante, et
    # non simplement qu'il ait quitté la précédente. Entre deux
    # interruptions, `/state` rend `interaction: null` de façon transitoire :
    # une boucle qui s'arrête là capture un état de passage, et la
    # comparaison finale porte alors contre `None`. C'est ce qui rendait ce
    # test instable — cinq échecs sur six en isolement, sur un `TypeError`
    # et non sur son assertion.
    # Deux conditions ensemble, et il faut les deux. Attendre `interaction:
    # null` capture un état de PASSAGE entre deux interruptions, et la
    # comparaison finale porte alors contre `None` — cinq échecs sur six, sur
    # un `TypeError`. Mais attendre le seul statut `waiting` ne suffit pas non
    # plus : `start_run` rend la main avant que la tâche de fond écrive
    # `running`, donc on retrouve le `waiting` D'AVANT la réponse et on
    # repart avec l'ancienne interruption.
    #
    # On exige donc un statut arrêté ET une interruption réellement nouvelle.
    for _ in range(200):
        header = (await client.get(f"/projects/{project_id}",
                                   headers=account)).json()
        pending = (await client.get(f"/projects/{project_id}/state",
                                    headers=account)).json()["interaction"]
        if (header["run_status"] == "waiting" and pending is not None
                and pending["id"] != interaction["id"]):
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(
            "le run ne s'est pas arrêté sur l'interruption suivante")


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
    assert first.status_code == 200

    # Le second appel n'est envoyé qu'une fois le run passé à autre chose.
    # Un aller-retour immédiat serait absorbé par le registre
    # (`RunAlreadyRunning`, tâche 3) parce que le premier run tourne
    # encore : ce test passerait alors pour CETTE raison-là, et non parce
    # que l'identifiant est reconnu comme périmé. Constaté par mutation —
    # retirer la comparaison d'identifiant ne faisait tomber que le test
    # voisin, celui-ci restait vert pour la mauvaise raison.
    for _ in range(200):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                       headers=account)).json()
        current = state_body["interaction"]
        if current is None or current["id"] != interaction["id"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a pas dépassé l'interruption répondue")

    second = await client.post(f"/projects/{project_id}/answer",
                               json=body, headers=account)
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
    owner = await _active_account(client, "autre-proprio")
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
    """Répond à l'interaction courante et relance le run (§6.2).

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
    # L'ORDRE DES TROIS LECTURES EST PORTEUR, et rien ne les synchronise.
    # La ligne d'abord, le point de reprise ensuite, les projections en
    # dernier : le statut lu est donc le plus ancien des trois. Tant que les
    # statuts n'avancent que dans un sens, l'écart penche du bon côté — on
    # peut voir `running` à côté d'une interaction déjà présente, et le front
    # affiche une question sous une bannière « en cours » périmée d'un
    # sondage. Inverser les deux premières lectures donnerait `waiting` avec
    # `interaction: null` : un état qui n'a jamais existé, et qu'un front
    # rend en « répondez à la question qui n'est pas là ».
    #
    # La tâche 7 fait reculer les statuts (`failed` puis `running` à la
    # reprise) : c'est là qu'il faudra reposer la question.
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
| `Command(resume=body.reponse)` au lieu du dictionnaire | **aucun test, et c'est normal** — voir ci-dessous |
| répondre `409` au lieu de `200` sur une réponse périmée | `..._twice_does_not_advance_twice` |

Si la première mutation ne fait tomber qu'**un seul** des deux tests,
l'autre passe pour une mauvaise raison — corrigez-le avant de continuer.
C'est arrivé : le double-clic était absorbé par le registre au lieu d'être
reconnu comme périmé, d'où l'attente ajoutée au test ci-dessus.

**La forme à dictionnaire n'est pas testable sur ce graphe, et le dire vaut
mieux que l'inventer.** Le graphe est strictement linéaire :
`ask_questions`, `review` et `arbitrate` n'interrompent jamais en parallèle,
donc `snapshot.interrupts` ne porte jamais plus d'une entrée. Or une valeur
simple vise « la prochaine interruption », qui est ici la seule qui existe :
les deux formes sont donc rigoureusement équivalentes aujourd'hui, et aucune
mutation ne peut les distinguer.

On garde le dictionnaire quand même, pour deux raisons. Il dit explicitement
à quoi l'on répond, ce qui est la seule lecture correcte de la route. Et le
jour où un nœud interrompra en parallèle — un arbitrage par incohérence,
par exemple — la forme simple deviendrait fausse en silence, sur un chemin
que personne ne rejoue.


- [ ] **Étape 7 bis : une réponse mal formée ne doit pas condamner le projet**

Le constat le plus grave du plan, trouvé par la relecture et reproduit deux
fois. `POST /answer` accepte `"reponse"` de n'importe quelle forme — le
schéma la type `Any` au motif que « c'est le graphe qui valide ». C'est faux
sur ce chemin : `ask_questions` fait `(answers or {}).items()`, donc une
liste, une chaîne ou un nombre y lèvent une `AttributeError`. La route a déjà
répondu `200 {"rejoue": true}`, le run meurt, `run_status` passe à `failed`.

Le pire vient après. L'interruption reste en attente au point de reprise, et
LangGraph **rejoue la valeur stockée** : une reprise correcte replante donc à
l'identique, trois fois sur trois. Le projet est coincé pour de bon, sans
aucun chemin de retour par l'API — et le `/resume` de la tâche 7 rejouerait
le même poison.

On corrige à deux niveaux, parce qu'ils ne font pas le même travail.

**Le nœud ne doit jamais mourir sur ce que le client envoie.** Dans
`backend/app/agent/graph.py`, ajouter en tête `import logging` et
`logger = logging.getLogger(__name__)`, puis dans `ask_questions`, juste
après l'`interrupt` :

```python
    # `answers` vient du client par `Command(resume=…)` et n'est validé par
    # personne avant d'arriver ici. Une liste, une chaîne ou un nombre y
    # produisaient une `AttributeError` qui tuait le run — et, LangGraph
    # rejouant la valeur stockée au point de reprise, une reprise correcte
    # replantait à l'identique. Le projet restait coincé pour de bon.
    #
    # `review` porte déjà ce garde (`isinstance(feedback, dict)`) ; il
    # manquait ici. On ignore ce qu'on ne sait pas lire plutôt que de mourir
    # dessus : la section reposera ses questions au tour suivant. C'est
    # aussi ce qui désempoisonne un point de reprise déjà corrompu.
    if not isinstance(answers, dict):
        if answers is not None:
            logger.warning("réponse ignorée, forme inattendue : %s",
                           type(answers).__name__)
        answers = {}
```

et remplacer `(answers or {}).items()` par `answers.items()`.

**La route refuse au seuil ce qu'elle peut voir de travers.** Ignorer
silencieusement ferait disparaître la réponse d'un utilisateur sans rien lui
dire ; un 422 est honnête, puisque rien n'a été consommé et qu'il peut
renvoyer. Dans `backend/app/projects/routes.py`, au-dessus de la route :

```python
# La forme que chaque interruption attend, telle que les nœuds la lisent.
# `ask_questions` veut une correspondance fait → valeur, `review` un
# dictionnaire d'action, `arbitrate` une liste d'arbitrages.
_EXPECTED_ANSWER = {"questions": dict, "review": dict, "inconsistencies": list}
```

et, dans `answer`, juste après la comparaison d'identifiant :

```python
    expected = _EXPECTED_ANSWER.get(pending.value.get("kind"))
    if (expected is not None and body.reponse is not None
            and not isinstance(body.reponse, expected)):
        # Refuser ici plutôt que de laisser le nœud s'en étrangler. Rien n'a
        # été consommé : l'interruption reste en attente et le client peut
        # renvoyer. `Any` sur le schéma reste le bon choix — les cinq
        # interruptions portent des charges utiles différentes — mais « le
        # graphe valide ce qu'il reçoit » n'était vrai que de `review`.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"code": "reponse_mal_formee"})
```

- [ ] **Étape 7 ter : huit mutations survivaient, dont le défaut du §6.2 lui-même**

Onze mutations jouées par la relecture, **huit survivantes**. La plus grave :
la branche « périmé » peut reprendre le run *quand même* tout en répondant
`rejoue: False`, et les quatre tests restent verts. Le test du double-clic
passe donc au vert pendant que le graphe avance deux fois — précisément ce
que sa propre docstring décrit comme le défaut à empêcher.

Deux raisons : il n'assertait que le drapeau, jamais le graphe ; et
l'assertion d'état du test voisin lisait `/state` **immédiatement** après la
requête, donc elle gagnait une course au lieu de vérifier quoi que ce soit.

Corriger les deux tests existants. Dans
`test_a_stale_interaction_id_changes_nothing`, avant l'assertion finale :

```python
    # L'attente n'est pas du confort. Sans elle, la tâche de fond n'a pas
    # bougé quand on lit, et l'assertion gagne une course au lieu de
    # vérifier quelque chose : avec l'attente elle passe sur le code livré
    # et TOMBE sur une route qui reprendrait malgré l'identifiant périmé.
    await asyncio.sleep(1)
```

Dans `test_answering_twice_does_not_advance_twice`, après le second appel :

```python
    # Le drapeau ne suffit pas : une route qui reprend quand même tout en
    # répondant `rejoue: False` le laissait au vert. On regarde donc le
    # graphe, pas la réponse.
    after = (await client.get(f"/projects/{project_id}/state",
                              headers=account)).json()["interaction"]
    assert after is not None and after["id"] == pending["id"], (
        "le second appel a fait avancer le graphe"
    )
```

Puis **cinq tests neufs** :

```python
async def test_a_malformed_answer_is_refused_and_consumes_nothing(client, account):
    """Le constat le plus grave du plan, réduit à un test.

    Une liste au lieu d'une correspondance tuait le run, et le point de
    reprise gardant la valeur, une reprise correcte replantait à
    l'identique : le projet ne revenait plus jamais.
    """
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    refused = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"], "reponse": ["a", "b"]},
        headers=account)
    assert refused.status_code == 422

    # Rien n'a été consommé : la même interruption attend toujours, et une
    # réponse correcte passe.
    state_body = (await client.get(f"/projects/{project_id}/state",
                                   headers=account)).json()
    assert state_body["interaction"]["id"] == interaction["id"]
    accepted = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)
    assert accepted.status_code == 200
    assert accepted.json()["rejoue"] is True


async def test_the_answer_reaches_the_graph_unchanged(client, account, monkeypatch):
    """Rien ne vérifiait que la réponse de l'utilisateur arrive au graphe.

    Reprendre avec une charge vide laissait les quatre tests verts. On
    intercepte donc le `Command` remis au pilote — les faits répondus ne
    sont projetés qu'au nœud `save`, bien plus tard, donc `/state` ne peut
    pas servir de témoin ici.
    """
    from app.projects import routes

    captured = []
    real_start_run = routes.start_run
    monkeypatch.setattr(routes, "start_run",
                        lambda pid, tid, gi: captured.append(gi))

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    payload = _answer_for(interaction)
    await client.post(f"/projects/{project_id}/answer",
                      json={"interaction_id": interaction["id"],
                            "reponse": payload},
                      headers=account)

    assert captured, "le pilote n'a pas été appelé"
    assert captured[-1].resume == {interaction["id"]: payload}


async def test_a_race_on_the_same_answer_is_absorbed(client, account, monkeypatch):
    """La seule branche écrite pour une vraie course, et rien ne l'exerçait.

    Supprimer son `except` laissait les 414 tests verts, alors qu'un vrai
    double-clic simultané rend alors un 500.
    """
    from app.projects import routes
    from app.runs.runner import RunAlreadyRunning

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    def _already(project_id, thread_id, graph_input):
        raise RunAlreadyRunning(project_id)

    monkeypatch.setattr(routes, "start_run", _already)
    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)

    assert response.status_code == 200
    assert response.json() == {"rejoue": False, "run_status": "running"}


async def test_every_answer_reports_the_run_status(client, account):
    """La moitié du contrat de réponse n'était assertée nulle part : retirer
    `run_status` des trois retours laissait la suite verte."""
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    # `_wait_for_interaction` sonde `/state`, qui lit le point de reprise —
    # et celui-ci devient visible À L'INTÉRIEUR d'`ainvoke`, donc AVANT que
    # le pilote écrive `waiting`. Attendre l'interruption ne garantit donc
    # pas le statut : il faut attendre le statut lui-même, sinon
    # l'assertion ci-dessous gagne une course au lieu de vérifier un fait.
    #
    # Le contrôle de la tâche 5 l'a prouvé en glissant un délai avant
    # l'écriture du statut : l'assertion rendait alors « running ». Elle ne
    # cassait jamais en pratique, seulement parce que l'écriture est rapide
    # devant l'aller-retour HTTP suivant.
    await _wait_for_status(client, project_id, account, "waiting")

    stale = (await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": "depuis-longtemps-perime", "reponse": {}},
        headers=account)).json()
    assert set(stale) == {"rejoue", "run_status"}
    assert stale["run_status"] in {"idle", "running", "waiting", "failed", "done"}

    fresh = (await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)).json()
    assert set(fresh) == {"rejoue", "run_status"}


async def test_the_request_body_and_the_token_are_both_required(client, account):
    """Ni le 401 ni le 422 n'étaient couverts."""
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    assert (await client.post(f"/projects/{project_id}/answer",
                              json={"reponse": {}})).status_code in (401, 403)
    assert (await client.post(f"/projects/{project_id}/answer",
                              json={"reponse": {}},
                              headers=account)).status_code == 422
    assert (await client.post(f"/projects/{project_id}/answer",
                              json={"interaction_id": "", "reponse": {}},
                              headers=account)).status_code == 422
```

Les mutations à rejouer, toutes survivantes avant cette correction :

| Mutation | Doit faire tomber |
|---|---|
| la branche « périmé » reprend quand même, en annonçant `rejoue: False` | `..._twice_does_not_advance_twice` **et** `..._stale_interaction_id_changes_nothing` |
| `Command(resume={id: None})` — la charge de l'utilisateur jetée | `..._answer_reaches_the_graph_unchanged` |
| `resume` indexé sur `pending.id` au lieu de `body.interaction_id` | le même |
| supprimer l'`except RunAlreadyRunning` | `..._race_on_the_same_answer_is_absorbed` |
| retirer `run_status` des trois retours | `..._every_answer_reports_the_run_status` |
| la branche « périmé » annonce `run_status: "done"` | le même |
| `interaction_id: str \| None = None` | `..._request_body_and_the_token_are_both_required` |
| retirer `Field(min_length=1)` | le même |
| `ask_questions` sans son garde de forme | `..._malformed_answer_is_refused_and_consumes_nothing` |

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

**Le blocage que vous pourriez craindre est déjà trouvé et corrigé.** La
tâche 4 a révélé que la suite PENDAIT dès qu'une requête HTTP lisait la base
pendant qu'un run avançait : `httpx.ASGITransport` n'exécute pas le cycle de
vie ASGI, donc le pool applicatif n'était jamais fermé, et l'annulation en
masse de ses tâches récursait dans psycopg jusqu'à une `RecursionError`
qu'asyncio avale dans un rappel. `tests/conftest.py` porte désormais un
démontage autouse qui annule les runs, ferme le point de reprise et ferme le
pool, dans cet ordre. Vous n'avez rien à ajouter — et surtout rien à
dupliquer.

Si malgré cela un test pend, **arrêtez-vous et dites-le** plutôt que
d'attendre : ce serait une forme neuve, et la connaître vaut mieux qu'un
contournement.

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


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Bascule le graphe sur le modèle simulé.

    Obligatoire dans TOUT fichier de test qui appelle `POST /projects` :
    la route démarre un vrai run en tâche de fond, et sans cette bascule
    `advance` appellerait la passerelle avec `ESQUISSE_FAKE_LLM=false` — la
    valeur que `tests/conftest.py` fixe pour toute la suite — donc de vraies
    requêtes réseau avec des clés factices. C'est exactement ce que la suite
    `not network` interdit, et c'est passé inaperçu jusqu'à la tâche 3.

    Le nettoyage des runs et des pools n'est PAS ici : `tests/conftest.py`
    porte un démontage autouse qui annule les runs, ferme le point de
    reprise et ferme le pool applicatif, dans cet ordre. Le dupliquer ferait
    deux endroits à tenir d'accord, et c'est toujours le second qu'on
    oublie.
    """
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "flux")


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
    owner = await _active_account(client, "flux-proprio")
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


- [ ] **Étape 5 bis : la route entière peut disparaître sans qu'un test bronche**

Douze mutations jouées par la relecture, **huit survivantes**. Deux sont
graves, et la première l'est au point de vider la tâche de son sens.

**`test_another_users_stream_is_not_found` passe avec la route supprimée.**
Il n'assertait que `status_code == 404` — or FastAPI répond 404 sur un chemin
qui n'existe pas. Vérifié : en retirant tout le bloc `@router.get(".../stream")`,
la suite complète reste à 425 passés. C'est l'unique test HTTP de la tâche,
donc rien ne tient l'existence de la route, ni sa méthode, ni son chemin, ni
son câblage.

**Le correctif qui a justifié cette tâche n'a pas de test de non-régression.**
Remettre le `asyncio.wait_for` du brief — le défaut même que le passage à
`asyncio.wait` corrige, celui qui tue le flux après le premier battement —
laisse la suite à 425 passés.

Ajouter à `backend/tests/test_stream.py` :

```python
def test_the_heartbeat_is_frequent_enough_to_hold_a_connection():
    # Le commentaire du module invoque la fenêtre d'inactivité de trente à
    # soixante secondes des intermédiaires. Le test voisin ne regarde que la
    # FORME du battement ; porter le délai à cent mille secondes laissait la
    # suite verte.
    from app.projects.stream import HEARTBEAT_SECONDS

    assert HEARTBEAT_SECONDS <= 30


async def test_the_stream_survives_its_own_heartbeats(monkeypatch):
    """Le défaut qui a justifié cette tâche, réduit à un test.

    `asyncio.wait_for(anext(it), …)` ANNULE l'`anext` à l'expiration, ce qui
    ferme le générateur asynchrone : le flux mourait après le premier
    battement, en silence, au bout de quinze secondes. Sans ce test, rien
    n'empêche quiconque de réintroduire la forme d'origine.
    """
    from app.projects import stream as st

    monkeypatch.setattr(st, "HEARTBEAT_SECONDS", 0.02)
    project_id = f"battements-{uuid4()}"
    frames = st.event_stream(project_id)

    beats = [await asyncio.wait_for(anext(frames), timeout=1) for _ in range(3)]
    assert beats == [st.HEARTBEAT] * 3

    # Et après trois battements, un vrai événement passe encore.
    publish(project_id, RunEvent("token", {"text": "vivant"}))
    frame = await asyncio.wait_for(anext(frames), timeout=1)
    assert frame.startswith("event: token")
    await frames.aclose()


async def test_the_lag_notice_reaches_the_client():
    """Le bus coupe l'abonné en retard ; encore faut-il que l'avis sorte.

    `tests/test_events.py` couvre le bus. Rien ne couvrait la traversée :
    faire avaler l'avis par `event_stream` laissait la suite verte, et le
    navigateur perdait le signal de reconnexion sur lequel repose le §8.
    """
    from app.runs.events import SUBSCRIBER_QUEUE_SIZE

    project_id = f"retard-{uuid4()}"
    frames = event_stream(project_id)
    # On amorce l'abonnement : le générateur ne s'abonne qu'à la première
    # itération, et publier avant ne toucherait personne.
    first = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    for index in range(SUBSCRIBER_QUEUE_SIZE + 50):
        publish(project_id, RunEvent("token", {"text": str(index)}))

    received = [await asyncio.wait_for(first, timeout=1)]
    with contextlib.suppress(StopAsyncIteration, asyncio.TimeoutError):
        while True:
            received.append(await asyncio.wait_for(anext(frames), timeout=1))

    assert received[-1].startswith("event: error"), (
        "l'avis de retard n'est pas parvenu au client"
    )
    assert "flux_en_retard" in received[-1]


async def test_the_response_carries_the_sse_contract(client, account):
    """La route rend-elle ce qu'un `EventSource` accepte, et écoute-t-elle le
    bon projet ?

    Trois mutations survivaient : un `media_type` en `text/plain`, la perte
    des en-têtes anti-tampon, et un abonnement à un autre projet — ce
    dernier rendant un flux silencieux pour toujours. On appelle la fonction
    de route directement : le transport de test ne sait pas conduire une
    réponse en flux, mais l'objet qu'elle construit s'inspecte.
    """
    from uuid import UUID

    from app.core.db import connection
    from app.projects.routes import stream as stream_route

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select user_id from projects where id = %s",
                              (UUID(project_id),))
            user_id = (await cur.fetchone())[0]

    response = await stream_route(UUID(project_id), {"id": user_id})
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    body = response.body_iterator
    pending = asyncio.ensure_future(anext(body))
    await asyncio.sleep(0)
    publish(project_id, RunEvent("progress", {"cursor": 7, "total": 9}))
    frame = await asyncio.wait_for(pending, timeout=1)
    assert frame.startswith("event: progress")
    assert '"cursor": 7' in frame, (
        "le flux n'écoute pas le projet demandé"
    )
    await body.aclose()


async def test_the_stream_releases_its_subscription(client, account):
    """Une tâche laissée par navigateur déconnecté est une fuite qui ne se
    voit qu'en production. Remplacer le `finally` par `pass` laissait la
    suite verte."""
    from app.runs import events as ev

    project_id = f"fuite-{uuid4()}"
    frames = event_stream(project_id)
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    publish(project_id, RunEvent("token", {"text": "un"}))
    await asyncio.wait_for(pending, timeout=1)

    await frames.aclose()
    await asyncio.sleep(0)
    assert project_id not in ev._channels, "le canal n'a pas été libéré"
    leaked = [t for t in asyncio.all_tasks()
              if "asend" in repr(t) and not t.done()]
    assert not leaked, f"tâche laissée derrière : {leaked}"
```

Et dans `test_another_users_stream_is_not_found`, une ligne qui change tout :

```python
        assert response.json() == {"detail": {"code": "projet_introuvable"}}, (
            "un 404 de chemin inexistant se lit pareil qu'un 404 de "
            "propriété : sans le corps, ce test passe même si la route a "
            "disparu — vérifié"
        )
```

- [ ] **Étape 5 ter : rejouer les huit mutations survivantes**

| Mutation | Doit faire tomber |
|---|---|
| supprimer tout le bloc `@router.get(".../stream")` | `..._another_users_stream_is_not_found` |
| revenir au `asyncio.wait_for` du brief dans `event_stream` | `..._stream_survives_its_own_heartbeats` |
| `event_stream` avale `LAGGED` et sort au lieu de le rendre | `..._lag_notice_reaches_the_client` |
| `media_type="text/plain"` | `..._response_carries_the_sse_contract` |
| retirer `Cache-Control` et `X-Accel-Buffering` | le même |
| `event_stream("un-autre-projet")` au lieu du projet demandé | le même |
| remplacer le `finally` qui annule l'`anext` par `pass` | `..._stream_releases_its_subscription` |
| `HEARTBEAT_SECONDS = 100000` | `..._heartbeat_is_frequent_enough_to_hold_a_connection` |

Les huit laissaient les 425 tests au vert. J'ai vérifié la première
moi-même : route entière supprimée, suite complète verte.

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
- Consomme : `save_facts`, `mark_for_reopening` (`app/agent/projections.py`),
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

**Ce que la tâche 5 vous lègue, et qu'il faut trancher ici.** Sa relecture a
mesuré la fenêtre de `RunAlreadyRunning` avec un nœud délibérément ralenti :
dès qu'une reprise démarre, le point de reprise cesse d'exposer
l'interruption, si bien qu'une requête tardive est refusée par la branche
« périmé » et non par le registre. La conflation de `/answer` — « un run
tourne déjà » répondu `{"rejoue": False, "run_status": "running"}` — est
donc vraie aujourd'hui.

Elle cesse de l'être ici. Un run planté laisse son interruption **en
attente** : un `/answer` envoyé pendant qu'un `/resume` avance reconnaîtra
donc l'identifiant comme courant, tombera sur le registre, et s'entendra
répondre `rejoue: False` **pendant que sa charge utile est jetée** et que
l'ancienne valeur est rejouée. L'utilisateur croit avoir répondu ; il n'a
rien répondu.

Deux issues défendables, à choisir en écrivant la tâche : répondre `409` sur
cette branche-là seulement, ce qui rompt la promesse « toujours 200 » du
§6.2 mais ne ment pas ; ou faire attendre la requête que la reprise ait
atteint son interruption suivante, ce qui tient la promesse au prix d'une
latence. **Décidez et écrivez pourquoi** — ne laissez pas le commentaire de
`routes.py` affirmer « deux requêtes sont arrivées ensemble », qui sera faux
dès que cette tâche existera.

**Les trois appelants manquants du plan 3 se branchent ici.** La revue finale
notait que `reproject`, `mark_for_reopening` et — pour sa seconde moitié —
`purge_checkpoints` étaient écrits, testés, et jamais invoqués. Deux sur
trois trouvent le leur ici : `POST /reopen` appelle `mark_for_reopening`, et
le démarrage appelle `purge_checkpoints` en filet (§9.3).

`reproject` n'en trouvera pas, et c'est un constat et non un oubli : voir
l'étape 5.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_resume.py
import asyncio

import pytest_asyncio

from app.core.db import connection
from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Bascule le graphe sur le modèle simulé.

    Obligatoire dans TOUT fichier de test qui appelle `POST /projects` :
    la route démarre un vrai run en tâche de fond, et sans cette bascule
    `advance` appellerait la passerelle avec `ESQUISSE_FAKE_LLM=false` — la
    valeur que `tests/conftest.py` fixe pour toute la suite — donc de vraies
    requêtes réseau avec des clés factices. C'est exactement ce que la suite
    `not network` interdit, et c'est passé inaperçu jusqu'à la tâche 3.

    Le nettoyage des runs et des pools n'est PAS ici : `tests/conftest.py`
    porte un démontage autouse qui annule les runs, ferme le point de
    reprise et ferme le pool applicatif, dans cet ordre. Le dupliquer ferait
    deux endroits à tenir d'accord, et c'est toujours le second qu'on
    oublie.
    """
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "reprise")


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
    owner = await _active_account(client, "reprise-proprio")
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

    Les faits sont réécrits AVANT la relance, dans l'esprit du §4.6 : en cas
    de divergence, c'est le point de reprise qui gagne. Les sections, elles,
    ne s'y trouvent pas — il ne porte que la section en cours — et elles se
    réparent d'elles-mêmes, `save` écrivant la projection avant d'avancer le
    curseur. Un run mort entre les deux refait simplement sa section.
    """
    row = await _owned(project_id, user)
    if registry.is_running(str(project_id)):
        return {"reprise": False, "run_status": "running"}

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}

    # `save_facts` et non `reproject` : le point de reprise porte les faits,
    # jamais les sections déjà validées. Voir la note ci-dessous — ce n'est
    # pas un raccourci, c'est la seule projection qu'il puisse reconstruire.
    async with connection() as conn:
        await save_facts(conn, project_id, values.get("facts", {}))

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
from app.agent.projections import mark_for_reopening, save_facts
from app.agent.templates import load_catalogue
from app.runs import registry
```

`load_catalogue` est déjà importé par la tâche 4 pour `templates_version`.

`mark_for_reopening` attend des identifiants **qualifiés**
(`cdc.contexte_objectifs`), établi par son test du plan 3 — c'est bien ce que
`sections_depending_on` rend.

**Le point que j'avais laissé ouvert est tranché, et la réponse change cette
tâche.** J'ai lu ce que l'état du graphe porte : `facts`, `plan`, `cursor`,
`computations`, et `draft` — **la section en cours, et elle seule**. Les
sections déjà validées ne sont nulle part dans le point de reprise ; elles
n'existent que dans la table `sections`.

Donc `reproject(conn, project_id, facts, sections)` **ne peut pas être
alimentée depuis le point de reprise**. Son quatrième argument n'a pas de
source. Lui passer une liste vide effacerait tout le document au lieu de le
réparer — l'inverse exact de ce qu'elle prétend faire.

Et en y regardant, elle n'a pas lieu d'être appelée. Le nœud `save` écrit la
projection **puis** avance le curseur : les sections situées avant le curseur
sont donc correctes par construction. Une mort entre l'écriture en base et
celle du point de reprise laisse une projection en avance d'une section ; à
la reprise, le graphe refait cette section et `save` réécrit la projection
par-dessus. La divergence est bornée et se répare d'elle-même.

**Ce que `/resume` fait donc à la place :** il réécrit les faits depuis le
point de reprise, par `save_facts`, qui est la seule projection que le
point de reprise puisse réellement reconstruire. C'est peu, et c'est
honnête.

**Et `reproject` reste sans appelant.** Le préambule de ce plan reproche
précisément cela au plan 3 ; je ne peux pas le refermer ici sans inventer
une source qui n'existe pas. Le constat est donc : cette fonction a été
écrite sur une prémisse fausse — que le point de reprise porte le document —
et c'est elle qu'il faut retirer ou repenser, dans le plan qui touchera à
l'export. **Écrivez-le dans le compte rendu** plutôt que de la faire appeler
pour la forme.

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

- [ ] **Étape 9 : ce que la relecture de la tâche 7 a trouvé**

Vingt-trois mutations, onze survivantes, et deux comportements faux.

1. **Le démarrage ne doit jamais dépendre des tâches de ménage.**
   `reconcile_orphan_runs` et `purge_finished_projects` tournent avant le
   `yield` du cycle de vie. Une erreur de l'une ou l'autre, par exemple la base
   qui répond mal au réveil, empêche l'application de démarrer : pas de
   `/health`, et l'hébergeur peut la relancer en boucle. Chacune s'entoure
   d'un `try/except` qui journalise et continue.
2. **`/resume` ne reprend que ce qui est à reprendre.** Il n'agit que sur
   `failed`, ou sur un `running` orphelin (plus aucune tâche vivante). Sur
   `waiting`, `done` ou `idle`, il répond `{"reprise": false, "run_status": …}`
   sans rien lancer. Sinon, sur un projet en attente, il rejouait
   l'interruption et faisait refuser par un 409 la vraie réponse de
   l'utilisateur, et sur un projet sans point de reprise il repartait d'un
   plan vide vers un `failed` présenté comme reprenable.
3. **Le commentaire de `/state` était faux.** L'état `waiting` avec
   `interaction: null` existe déjà, sans que les lectures soient inversées.
   Pendant un `/answer`, la ligne lue est encore `waiting` alors que le point
   de reprise a déjà consommé la réponse. La relecture l'a reproduit en
   élargissant la fenêtre. Le commentaire dit maintenant la vérité : c'est un
   état de passage, et le front doit relire `/state` quand il le rencontre.
   Le même texte copié dans `/answer`, qui ne lit aucune projection, est
   corrigé aussi.
4. **La réconciliation n'écrase pas un statut plus récent.** Elle ne passe à
   `failed` que ce qui est encore `running`, via une mise à jour conditionnelle
   (`where run_status = 'running'`).
5. **Tests manquants :**
   - la purge compte les points de reprise avant et après, et laisse intact un
     projet qui n'est pas `done` ;
   - le démarrage appelle bien la réconciliation et la purge ;
   - l'arrêt annule les runs AVANT de fermer le point de reprise ;
   - `/reopen` sur un projet `bp` et sur un projet `both` ;
   - `/reopen` sur une section inconnue répond 404 ;
   - le contenu exact de la réponse de `/reopen` ;
   - `/resume` transmet à `save_facts` les faits du point de reprise, et non
     un dictionnaire vide ;
   - un cycle dans `depend_de` se termine (catalogue modifié en test) ;
   - chaque correction ci-dessus a son test.

**Reporté au plan suivant, avec la raison :**
- la purge au démarrage refait tout le travail à chaque réveil, ce qui est un
  coût, pas un défaut de correction ;
- le statut `reopened` est écrit mais relu par personne, donc rouvrir une
  section ne la fait pas réécrire : c'est au plan qui câblera la réécriture ;
- deux `pool.open(wait=True)` concurrents dans `purge_checkpoints` lèvent, et
  deux runs qui se terminent ensemble peuvent le déclencher : même défaut que
  celui corrigé dans `saver()`, à traiter de la même façon.

---

### Tâche 8 : ce que la revue finale a trouvé entre les tâches

**Fichiers :**
- Créer : `backend/migrations/versions/0004_projects_idee.py`
- Modifier : `backend/Dockerfile`, `backend/app/runs/runner.py`,
  `backend/app/projects/routes.py`, `backend/app/projects/repository.py`
- Test : `backend/tests/test_runner.py`, `backend/tests/test_resume.py`,
  `backend/tests/test_migrations.py` si elle vérifie la liste des révisions

La revue finale a regardé les sept tâches ensemble, ce qu'aucun relecteur de
tâche ne pouvait faire. Elle déconseille la fusion en l'état. Les trois
premiers constats ci-dessous ont été vérifiés par sondes. Le quatrième repose
sur le code et sur la documentation de Render.

**1. Un run qui échoue avant son premier point de reprise ne peut jamais être
relancé, alors qu'on le présente comme reprenable.** Si `compiled_graph` lève
au premier `advance` (par exemple sur un délai d'attente du pool du point de
reprise), la ligne passe à `failed` sans aucun point de reprise. `/resume`
appelle alors `advance(..., None)`, LangGraph répond « Received no input for
__start__ », et la ligne repasse à `failed` avec `reprenable: true`. Cela se
répète à chaque tentative. Il en va de même d'un processus tué entre
l'insertion et le démarrage de la tâche : la ligne reste `idle` pour
toujours.

   Correctif : quand `snapshot.values` est vide, `/resume` reconstruit
   `initial_state` depuis la ligne (`documents`, profils, idée) au lieu de
   passer `None`. L'idée n'est pas stockée aujourd'hui. D'où :
   - une migration `0004` qui ajoute `idee text` à `projects` (nullable, pour
     les lignes existantes) ;
   - `create_project` qui l'écrit ;
   - `project_for_user` qui la lit.

   `/resume` accepte alors `idle` s'il n'y a **pas** de point de reprise, car
   c'est exactement le projet mort-né. Il continue de refuser `idle` s'il y en
   a un. Sur une ligne ancienne dont `idee` est nulle, on refuse avec
   `{"reprise": false, ...}` plutôt que de relancer sur une idée vide.

**2. Ce qui échoue après le `try` d'`advance` perd l'événement final.** Si
`purge_checkpoints` lève, la ligne est `done` mais aucun événement `done`
n'est publié, et l'exception sort d'une tâche que personne n'attend. Le client
SSE ne reçoit plus que des battements, ne se reconnecte jamais, et l'écran
reste sur « rédaction en cours ». Si c'est `_status("waiting")` qui lève, la
ligne reste `running` pour toujours.

   Correctif : la purge passe dans un `try/except` qui journalise, et `done` est
   publié dans tous les cas. Une purge ratée n'est qu'un coût de stockage, la
   purge de filet du démarrage la rattrapera. Les écritures de statut situées
   après le `try` passent par `_fail` en cas d'échec, comme celles qui sont
   dedans.

**3. Un double clic sur « Reprendre » rend un 500.** Deux `/resume`
concurrents passent tous deux le garde `is_running`, puis attendent
`aget_state` et `save_facts` avant d'appeler `start_run`. Le second lève
`RunAlreadyRunning`, qui n'est pas rattrapé. Correctif : on le rattrape et on
répond `{"reprise": false, "run_status": "running"}`. Ici c'est vrai : rien
n'est perdu, puisqu'une reprise ne porte aucune charge utile.

**4. Deux processus peuvent piloter le même fil.** `--workers` prend par
défaut la valeur de `$WEB_CONCURRENCY`, que Render fixe d'après le nombre de
processeurs. La commande de démarrage ne le fige pas, donc passer à un plan
plus grand démarrerait deux workers sans que rien ne le dise. Correctif :
`--workers 1` dans le `CMD` du `Dockerfile`, avec un commentaire qui renvoie
au §9.2.

   Le chevauchement des déploiements sans interruption relève du même défaut,
   mais n'est **pas** corrigé ici. Render démarre la nouvelle instance à côté
   de l'ancienne, et la réconciliation de la nouvelle passerait à `failed` les
   runs vivants de l'ancienne. Un seuil d'âge ne suffirait pas : un run vivant
   peut passer plusieurs minutes sans changer de statut. La décision est
   laissée au propriétaire (voir le compte rendu).

**Tests** (chacun doit échouer si on retire son correctif) :
- un run dont le premier `advance` lève, puis `/resume` : la ligne atteint
  `waiting` ;
- un projet `idle` sans point de reprise : `/resume` le démarre ;
- un projet ancien sans `idee` : `/resume` refuse ;
- une purge qui lève en fin de run : l'événement `done` est quand même publié
  et la ligne est `done` ;
- `_status("waiting")` qui lève : la ligne n'est pas laissée à `running`, et un
  événement `error` part ;
- deux `/resume` concurrents : ni l'un ni l'autre ne rend 500 ;
- la migration `0004` monte et descend proprement.

Commit : `fix(runs): un run mort-né se relance, et la fin d'un run publie toujours son événement`.
