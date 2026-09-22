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


async def test_a_failing_purge_still_marks_done_and_publishes_it(project, monkeypatch):
    """Constat 2 de la revue finale : une purge ratée n'est qu'un coût de
    stockage — la purge de filet du démarrage la rattrape — mais elle ne
    doit jamais faire perdre l'événement `done`. Avant le correctif,
    l'exception sortait d'une tâche que personne n'attend : le client SSE ne
    recevait plus que des battements et l'écran restait sur « rédaction en
    cours » alors que la ligne était bel et bien `done`."""
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

    async def _failing_purge(thread_id, keep=1):
        raise RuntimeError("purge ratée")

    monkeypatch.setattr(runner, "compiled_graph", _finished_graph)
    monkeypatch.setattr(checkpointer, "purge_checkpoints", _failing_purge)

    async with subscribe(str(project["project_id"])) as events:
        await advance(str(project["project_id"]), project["thread_id"], None)
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass

    assert await _status(project["project_id"], project["user_id"]) == "done", (
        "une purge ratée ne doit pas empêcher la ligne de passer `done`"
    )
    assert [e.name for e in received] == ["done"], (
        "l'événement `done` doit partir même si la purge qui le précède a levé"
    )


async def test_a_failing_status_write_on_waiting_does_not_leave_the_row_running(
        project, monkeypatch):
    """Constat 2 de la revue finale : si `_status("waiting")` lève, la ligne
    ne doit pas rester `running` pour toujours. L'écriture est maintenant
    dans le `try` d'`advance`, donc son échec passe par `_fail` comme
    n'importe quel autre — et publie son événement `error`."""
    from app.runs import runner

    real_status = runner._status

    async def _refuse_waiting(project_id, status):
        if status == "waiting":
            raise RuntimeError("base injoignable")
        await real_status(project_id, status)

    monkeypatch.setattr(runner, "_status", _refuse_waiting)

    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    async with subscribe(str(project["project_id"])) as events:
        await advance(str(project["project_id"]), project["thread_id"], graph_input)
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except (StopAsyncIteration, asyncio.TimeoutError):
            pass

    assert await _status(project["project_id"], project["user_id"]) == "failed", (
        "l'échec de l'écriture de `waiting` a laissé la ligne à `running` pour toujours"
    )
    errors = [e for e in received if e.name == "error"]
    assert errors, "l'échec de l'écriture de `waiting` doit publier une erreur"


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
