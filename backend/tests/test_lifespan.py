import pytest

from app import main


async def test_the_database_pool_closes_even_if_a_model_client_refuses(monkeypatch):
    """Le pool de base se ferme quoi qu'il arrive. Il a toujours eu cette
    garantie ; l'ajout des clients de modèles ne doit pas la retirer."""
    closed: list[str] = []

    class _Pool:
        async def open(self, wait: bool = False) -> None:
            return None

        async def close(self) -> None:
            closed.append("pool")

    async def _refuse() -> None:
        raise RuntimeError("client récalcitrant")

    monkeypatch.setattr(main, "pool", lambda: _Pool())
    monkeypatch.setattr(main, "close_clients", _refuse)

    with pytest.raises(RuntimeError):
        async with main.lifespan(object()):
            pass

    assert closed == ["pool"]


async def test_shutting_down_cancels_the_running_runs():
    """Un run qui survit à l'arrêt écrit dans une connexion fermée, et
    personne ne voit l'erreur : elle remonte dans une tâche que personne
    n'attend.

    On déclenche `lifespan` directement, comme le test ci-dessus, et non par
    un client `httpx` en gestionnaire de contexte : `httpx.ASGITransport`
    n'exécute pas les événements de cycle de vie ASGI (même motif que
    `tests/conftest.py::_close_the_application_pool`), donc sortir de son
    bloc ne déclenche ni le démarrage ni l'arrêt de l'application. Vérifié à
    la sonde : aucun événement de cycle de vie n'était observé. Le seul
    chemin qui exerce réellement le `finally` de `lifespan` est celui déjà en
    usage juste au-dessus.
    """
    import asyncio

    from app.runs import registry

    async def _long():
        await asyncio.sleep(30)

    async with main.lifespan(object()):
        task = asyncio.create_task(_long())
        registry.register("projet-a-l-arret", task)
        assert registry.is_running("projet-a-l-arret")

    assert not registry.is_running("projet-a-l-arret"), (
        "l'arrêt de l'application n'a pas annulé le run en cours"
    )
    assert task.cancelled()


async def test_startup_succeeds_even_if_reconciliation_raises(monkeypatch):
    """Le démarrage ne doit jamais dépendre du ménage : une erreur de
    `reconcile_orphan_runs` — la base qui répond mal au réveil, le cas le
    plus probable sur un hébergement qui vient de se réveiller — ne doit pas
    empêcher `/health` de répondre. Sans la garde, cette erreur remontait
    hors du `yield` et l'application ne démarrait jamais."""
    async def _raise():
        raise RuntimeError("base indisponible au réveil")

    monkeypatch.setattr(main, "reconcile_orphan_runs", _raise)

    async with main.lifespan(object()):
        pass  # ne doit pas lever : c'est tout ce que ce test vérifie


async def test_startup_succeeds_even_if_the_purge_raises(monkeypatch):
    """Même garde, même raison, pour `purge_finished_projects`."""
    async def _raise():
        raise RuntimeError("purge en échec")

    monkeypatch.setattr(main, "purge_finished_projects", _raise)

    async with main.lifespan(object()):
        pass  # ne doit pas lever


async def test_startup_calls_the_reconciliation_and_the_purge(monkeypatch):
    """Les `try/except` ajoutés pour la garde ci-dessus ne doivent pas se
    substituer aux appels eux-mêmes : rien ne vérifiait qu'ils ont vraiment
    lieu au démarrage."""
    calls: list[str] = []

    async def _fake_reconcile():
        calls.append("reconcile")
        return 0

    async def _fake_purge():
        calls.append("purge")
        return 0

    monkeypatch.setattr(main, "reconcile_orphan_runs", _fake_reconcile)
    monkeypatch.setattr(main, "purge_finished_projects", _fake_purge)

    async with main.lifespan(object()):
        pass

    assert calls == ["reconcile", "purge"], (
        "le démarrage doit appeler les deux tâches de ménage, "
        "la réconciliation avant la purge"
    )


async def test_shutdown_cancels_runs_before_closing_the_checkpointer(monkeypatch):
    """`cancel_all` doit avoir déjà tourné quand `close_checkpointer` est
    appelé : sinon une tâche encore vivante peut écrire dans un point de
    reprise dont la connexion vient de se fermer, et l'erreur remonte dans
    une tâche que personne n'attend. On espionne `close_checkpointer` pour
    constater, AU MOMENT où il est appelé, que la tâche enregistrée est déjà
    annulée — pas seulement que les deux ont fini par se produire."""
    import asyncio

    from app.runs import registry

    async def _long():
        await asyncio.sleep(30)

    real_close_checkpointer = main.close_checkpointer
    observed: dict[str, bool] = {}

    async def _spy_close_checkpointer():
        observed["encore_vivant"] = registry.is_running("projet-ordre-arret")
        return await real_close_checkpointer()

    monkeypatch.setattr(main, "close_checkpointer", _spy_close_checkpointer)

    async with main.lifespan(object()):
        task = asyncio.create_task(_long())
        registry.register("projet-ordre-arret", task)

    assert observed.get("encore_vivant") is False, (
        "le point de reprise a été fermé avant que le run ne soit annulé"
    )
