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
