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
